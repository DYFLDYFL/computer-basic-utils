from __future__ import annotations

import base64
import html
import io
import re
import tempfile
import urllib.request
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal
from tkinter import (
    BOTH,
    LEFT,
    RIGHT,
    VERTICAL,
    WORD,
    Canvas,
    Frame,
    PhotoImage,
    Text,
    Toplevel,
    ttk,
)

from PIL import Image, ImageTk

_CODE_BLOCK_PATTERN = re.compile(r"```([^\n`]*)\n(.*?)```", re.DOTALL)
_IMAGE_PATTERN = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
_DISPLAY_MATH_PATTERN = re.compile(r"\$\$(.+?)\$\$", re.DOTALL)
_INLINE_MATH_PATTERN = re.compile(r"(?<!\$)\$(?!\$)(.+?)(?<!\$)\$(?!\$)")
_INLINE_CODE_PATTERN = re.compile(r"`([^`\n]+)`")
_BOLD_PATTERN = re.compile(r"\*\*([^*]+)\*\*")


@dataclass
class ContentBlock:
    kind: Literal["text", "code", "image", "math"]
    content: str
    language: str = ""
    display_math: bool = False


def parse_ai_result(content: str) -> list[ContentBlock]:
    blocks: list[ContentBlock] = []
    position = 0
    for match in _CODE_BLOCK_PATTERN.finditer(content):
        if match.start() > position:
            blocks.extend(_parse_text_segment(content[position : match.start()]))
        language = match.group(1).strip()
        code = match.group(2).rstrip("\n")
        blocks.append(ContentBlock(kind="code", content=code, language=language))
        position = match.end()
    if position < len(content):
        blocks.extend(_parse_text_segment(content[position:]))
    return blocks if blocks else [ContentBlock(kind="text", content=content)]


def _parse_text_segment(segment: str) -> list[ContentBlock]:
    if not segment:
        return []

    blocks: list[ContentBlock] = []
    position = 0
    combined_pattern = re.compile(
        r"!\[([^\]]*)\]\(([^)]+)\)|\$\$(.+?)\$\$|(?<!\$)\$(?!\$)(.+?)(?<!\$)\$(?!\$)",
        re.DOTALL,
    )
    for match in combined_pattern.finditer(segment):
        if match.start() > position:
            blocks.append(ContentBlock(kind="text", content=segment[position : match.start()]))
        if match.group(0).startswith("!["):
            url = (match.group(2) or "").strip()
            if url:
                blocks.append(ContentBlock(kind="image", content=url))
        elif match.group(3) is not None:
            blocks.append(
                ContentBlock(
                    kind="math",
                    content=match.group(3).strip(),
                    display_math=True,
                )
            )
        elif match.group(4) is not None:
            blocks.append(
                ContentBlock(
                    kind="math",
                    content=match.group(4).strip(),
                    display_math=False,
                )
            )
        position = match.end()
    if position < len(segment):
        blocks.append(ContentBlock(kind="text", content=segment[position:]))
    return blocks


def build_ai_result_html(content: str) -> str:
    blocks = parse_ai_result(content)
    body_parts: list[str] = []
    for block in blocks:
        if block.kind == "code":
            language = html.escape(block.language) if block.language else "text"
            code = html.escape(block.content)
            body_parts.append(
                f'<pre class="code-block"><code class="language-{language}">{code}</code></pre>'
            )
        elif block.kind == "image":
            url = html.escape(block.content, quote=True)
            body_parts.append(f'<figure class="image-block"><img src="{url}" alt="image"/></figure>')
        elif block.kind == "math":
            tex = _escape_tex(block.content)
            if block.display_math:
                body_parts.append(f'<div class="math-display">$${tex}$$</div>')
            else:
                body_parts.append(f'<span class="math-inline">${tex}$</span>')
        else:
            body_parts.append(_format_text_html(block.content))

    body = "\n".join(body_parts)
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <script>
    window.MathJax = {{
      tex: {{
        inlineMath: [['$', '$'], ['\\\\(', '\\\\)']],
        displayMath: [['$$', '$$'], ['\\\\[', '\\\\]']]
      }}
    }};
  </script>
  <script defer src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-chtml.js"></script>
  <style>
    body {{
      font-family: "Segoe UI", "Microsoft YaHei", sans-serif;
      line-height: 1.6;
      margin: 16px;
      color: #1a1a1a;
      background: #ffffff;
    }}
    p {{ margin: 0.5em 0; }}
    .code-block {{
      background: #f5f5f5;
      border: 1px solid #e0e0e0;
      border-radius: 6px;
      padding: 12px;
      overflow-x: auto;
      font-family: Consolas, "Courier New", monospace;
      font-size: 13px;
      white-space: pre-wrap;
      word-break: break-word;
    }}
    .image-block img {{
      max-width: 100%;
      height: auto;
      border-radius: 4px;
      border: 1px solid #ddd;
      margin: 8px 0;
    }}
    code.inline-code {{
      background: #f0f0f0;
      padding: 0.1em 0.35em;
      border-radius: 3px;
      font-family: Consolas, monospace;
      font-size: 0.95em;
    }}
    .math-display {{
      display: block;
      margin: 12px 0;
      overflow-x: auto;
    }}
    .math-inline {{ white-space: normal; }}
  </style>
</head>
<body>
{body}
</body>
</html>"""


def _escape_tex(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _format_text_html(text: str) -> str:
    paragraphs = text.split("\n\n")
    rendered: list[str] = []
    for paragraph in paragraphs:
        if not paragraph.strip():
            continue
        lines = [html.escape(line) for line in paragraph.split("\n")]
        paragraph_html = "<br/>".join(_apply_inline_markdown(line) for line in lines)
        rendered.append(f"<p>{paragraph_html}</p>")
    return "\n".join(rendered) if rendered else ""


def _apply_inline_markdown(line: str) -> str:
    placeholders: dict[str, str] = {}

    def stash(match: re.Match[str], prefix: str) -> str:
        key = f"@@{prefix}{len(placeholders)}@@"
        placeholders[key] = f'<code class="inline-code">{match.group(1)}</code>'
        return key

    line = _INLINE_CODE_PATTERN.sub(lambda match: stash(match, "c"), line)
    line = _BOLD_PATTERN.sub(r"<strong>\1</strong>", line)
    for key, value in placeholders.items():
        line = line.replace(key, value)
    return line


def _load_photo_image(url: str, master: object, *, max_width: int = 560) -> PhotoImage | None:
    try:
        if url.startswith("data:"):
            _, encoded = url.split(",", 1)
            payload = base64.b64decode(encoded)
        else:
            request = urllib.request.Request(
                url,
                headers={"User-Agent": "FolderOrganizer/1.0"},
            )
            payload = urllib.request.urlopen(request, timeout=20).read()
        image = Image.open(io.BytesIO(payload))
        if image.width > max_width:
            ratio = max_width / image.width
            image = image.resize(
                (max_width, max(1, int(image.height * ratio))),
                Image.Resampling.LANCZOS,
            )
        return ImageTk.PhotoImage(image, master=master)
    except Exception:
        return None


class ScrollableRichResultFrame(ttk.Frame):
    def __init__(self, master: object, content: str) -> None:
        super().__init__(master)
        self._image_refs: list[PhotoImage] = []

        container = ttk.Frame(self)
        container.pack(fill=BOTH, expand=True)

        canvas = Canvas(container, highlightthickness=0)
        scrollbar = ttk.Scrollbar(container, orient=VERTICAL, command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side=LEFT, fill=BOTH, expand=True)
        scrollbar.pack(side=RIGHT, fill=Y)

        self._inner = ttk.Frame(canvas)
        window_id = canvas.create_window((0, 0), window=self._inner, anchor="nw")

        def on_configure(_event: object) -> None:
            canvas.configure(scrollregion=canvas.bbox("all"))
            canvas.itemconfigure(window_id, width=canvas.winfo_width())

        self._inner.bind("<Configure>", on_configure)
        canvas.bind("<Configure>", on_configure)

        def on_mousewheel(event: object) -> None:
            if hasattr(event, "delta") and event.delta:
                canvas.yview_scroll(int(-event.delta / 120), "units")
            elif hasattr(event, "num"):
                if event.num == 4:
                    canvas.yview_scroll(-3, "units")
                elif event.num == 5:
                    canvas.yview_scroll(3, "units")

        for widget in (canvas, self._inner):
            widget.bind("<MouseWheel>", on_mousewheel)
            widget.bind("<Button-4>", on_mousewheel)
            widget.bind("<Button-5>", on_mousewheel)

        self._render_blocks(parse_ai_result(content))

    def _render_blocks(self, blocks: list[ContentBlock]) -> None:
        for block in blocks:
            if block.kind == "code":
                self._add_code_block(block.content, block.language)
            elif block.kind == "image":
                self._add_image_block(block.content)
            elif block.kind == "math":
                self._add_math_block(block.content, block.display_math)
            else:
                self._add_text_block(block.content)

    def _add_text_block(self, text: str) -> None:
        if not text.strip():
            return
        label = ttk.Label(self._inner, text=text.strip(), wraplength=560, justify=LEFT)
        label.pack(anchor="w", fill=X, pady=(0, 8))

    def _add_code_block(self, code: str, language: str) -> None:
        frame = ttk.LabelFrame(
            self._inner,
            text=f"代码{(' · ' + language) if language else ''}",
            padding=4,
        )
        frame.pack(fill=X, pady=(0, 8))
        widget = Text(
            frame,
            wrap=WORD,
            font=("Consolas", 10),
            background="#f5f5f5",
            relief="flat",
            padx=8,
            pady=8,
        )
        widget.insert("1.0", code)
        widget.configure(state="disabled")
        line_count = int(widget.index("end-1c").split(".")[0])
        widget.configure(height=min(max(line_count, 3), 24))
        widget.pack(fill=X)

    def _add_image_block(self, url: str) -> None:
        frame = ttk.LabelFrame(self._inner, text="图片", padding=4)
        frame.pack(fill=X, pady=(0, 8))
        photo = _load_photo_image(url, self)
        if photo is not None:
            self._image_refs.append(photo)
            label = ttk.Label(frame, image=photo)
            label.image = photo
            label.pack(anchor="w")
            return
        ttk.Label(frame, text=url, wraplength=560).pack(anchor="w")

    def _add_math_block(self, latex: str, display_math: bool) -> None:
        title = "公式" if display_math else "行内公式"
        frame = ttk.LabelFrame(self._inner, text=title, padding=8)
        frame.pack(fill=X, pady=(0, 8))
        ttk.Label(
            frame,
            text=latex,
            wraplength=560,
            font=("Cambria Math", 11) if display_math else ("Consolas", 10),
        ).pack(anchor="w")


class AiResultDialog:
    def __init__(
        self,
        parent: object,
        *,
        image_path: Path,
        result: str,
        on_saved: Callable[[], None] | None = None,
    ) -> None:
        self.image_path = image_path
        self.result = result
        self.on_saved = on_saved

        self.dialog = Toplevel(parent)
        self.dialog.title("AI 识图结果")
        self.dialog.transient(parent)
        self.dialog.geometry("720x520")
        self.dialog.minsize(520, 320)

        header = ttk.Label(
            self.dialog,
            text=f"截图：{image_path.name}",
            padding=(12, 8, 12, 0),
        )
        header.pack(anchor="w")

        viewer_frame = ttk.Frame(self.dialog, padding=(12, 8, 12, 0))
        viewer_frame.pack(fill=BOTH, expand=True)
        self._html = build_ai_result_html(result)
        self._use_html_viewer(viewer_frame)

        actions = ttk.Frame(self.dialog, padding=12)
        actions.pack(fill=X)
        ttk.Button(actions, text="关闭", command=self.dialog.destroy).pack(side=RIGHT)
        ttk.Button(actions, text="浏览器查看", command=self._open_in_browser).pack(
            side=RIGHT, padx=(0, 8)
        )
        ttk.Button(actions, text="保存 HTML", command=self._save_html).pack(side=RIGHT, padx=(0, 8))
        ttk.Button(actions, text="保存文本", command=self._save_text).pack(side=RIGHT, padx=(0, 8))

    def _use_html_viewer(self, parent: object) -> None:
        try:
            from tkinterweb import HtmlFrame

            viewer = HtmlFrame(parent, messages_enabled=False)
            viewer.load_html(self._html)
            viewer.pack(fill=BOTH, expand=True)
            return
        except Exception:
            pass

        notebook = ttk.Notebook(parent)
        notebook.pack(fill=BOTH, expand=True)

        rendered_tab = ttk.Frame(notebook, padding=4)
        source_tab = ttk.Frame(notebook, padding=4)
        notebook.add(rendered_tab, text="渲染")
        notebook.add(source_tab, text="源码")

        rich = ScrollableRichResultFrame(rendered_tab, self.result)
        rich.pack(fill=BOTH, expand=True)

        source = Text(source_tab, wrap=WORD, font=("Consolas", 10))
        source_scroll = ttk.Scrollbar(source_tab, orient=VERTICAL, command=source.yview)
        source.configure(yscrollcommand=source_scroll.set)
        source.pack(side=LEFT, fill=BOTH, expand=True)
        source_scroll.pack(side=RIGHT, fill=Y)
        source.insert("1.0", self.result)
        source.configure(state="disabled")

        hint = ttk.Label(
            parent,
            text="安装 tkinterweb 可获得更佳公式/排版效果；也可点「浏览器查看」。",
            wraplength=640,
        )
        hint.pack(anchor="w", pady=(4, 0))

    def _open_in_browser(self) -> None:
        temp_file = Path(tempfile.gettempdir()) / f"folder_organizer_ai_{self.image_path.stem}.html"
        temp_file.write_text(self._html, encoding="utf-8")
        webbrowser.open(temp_file.as_uri())

    def _save_text(self) -> None:
        destination = self.image_path.with_suffix(".txt")
        try:
            destination.write_text(self.result, encoding="utf-8")
        except OSError as error:
            from tkinter import messagebox

            messagebox.showerror("保存失败", str(error), parent=self.dialog)
            return
        from tkinter import messagebox

        messagebox.showinfo("已保存", f"结果已保存到：\n{destination}", parent=self.dialog)
        if self.on_saved:
            self.on_saved()

    def _save_html(self) -> None:
        destination = self.image_path.with_suffix(".html")
        try:
            destination.write_text(self._html, encoding="utf-8")
        except OSError as error:
            from tkinter import messagebox

            messagebox.showerror("保存失败", str(error), parent=self.dialog)
            return
        from tkinter import messagebox

        messagebox.showinfo("已保存", f"结果已保存到：\n{destination}", parent=self.dialog)
        if self.on_saved:
            self.on_saved()
