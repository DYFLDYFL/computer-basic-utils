from __future__ import annotations

import json
import os
import shutil
import sys
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable
from tkinter import (
    BOTH,
    END,
    HORIZONTAL,
    LEFT,
    RIGHT,
    VERTICAL,
    BooleanVar,
    Canvas,
    IntVar,
    Listbox,
    Menu,
    Spinbox,
    StringVar,
    Text,
    Tk,
    Toplevel,
    messagebox,
    simpledialog,
    ttk,
)

from .ai_vision import (
    AI_PROVIDER_PRESETS,
    DEFAULT_AI_PROMPT,
    DEFAULT_AI_PROVIDER,
    ai_provider_id_from_label,
    ai_provider_label,
    ai_provider_preset,
    VISION_UNSUPPORTED_MESSAGE,
    ai_provider_supports_vision,
    call_vision_api,
    detect_ai_provider,
)
from .file_rules import (
    categorize_path,
    get_app_base_folder,
    get_managed_folder,
    get_trash_folder,
    is_internal_path,
    is_running_app_path,
    unique_destination,
)
from .help_text import build_help_text
from .hotkey_binder import AppHotkeyBinder
from .hotkey_support import (
    DEFAULT_RECORD_HOTKEY,
    DEFAULT_SCREENSHOT_HOTKEY,
    validate_hotkey,
)
from .screen_capture import (
    get_virtual_screen_bounds,
    grab_screen_region,
    hide_toplevel_window,
    show_toplevel_window,
    wait_for_capture_compositor,
)
from .qr_decode import QR_DECODE_DEPENDENCY_HINT, decode_qr_codes
from .screen_recorder import RegionScreenRecorder


TYPE_ICONS = {
    "Folders": "📁",
    "Documents": "📄",
    "Images": "🖼️",
    "Videos": "🎬",
    "Audio": "🎵",
    "Archives": "📦",
    "Applications": "⚙️",
    "Code": "💻",
    "Other": "📌",
}

DEFAULT_MAX_UNDO_STEPS = 20
DEFAULT_MAX_RECENT_APPS = 10
DEFAULT_SIDEBAR_WIDTH = 240
MIN_MAIN_PANE_WIDTH = 320
MIN_SIDEBAR_PANE_WIDTH = 140
DEFAULT_RECORD_FPS = 20
DEFAULT_RECORD_OUTPUT_WIDTH = 0
DEFAULT_RECORD_OUTPUT_HEIGHT = 0
RECORD_OUTPUT_AUTO = "自动"
SETTINGS_FILE_NAME = ".folder_organizer_settings.json"
PHOTOCUT_FOLDER_NAME = "photocut"
SCREENSHOT_HIDE_DELAY_MS = 350
SCREENSHOT_CAPTURE_WAIT_MS = 200
RECORD_HIDE_DELAY_MS = 350


@dataclass
class UndoAction:
    label: str
    undo: Callable[[], None]


class FileOrganizerApp:
    def __init__(self, root: Tk, managed_folder: Path | None = None) -> None:
        self.root = root
        self.managed_folder = (managed_folder or get_managed_folder()).resolve()
        self.back_history: list[Path] = []
        self.forward_history: list[Path] = []
        self.undo_stack: list[UndoAction] = []
        self.settings_path = self._resolve_settings_path()
        self.settings = self._load_settings()
        self.max_undo_steps = self._load_max_undo_steps()
        self.max_recent_apps = self._load_max_recent_apps()
        self.sidebar_width = self._load_sidebar_width()
        self.favorite_folders = self._load_favorite_folders()
        self.favorite_files = self._load_favorite_files()
        self.recent_apps = self._load_recent_apps()
        self.screenshot_hotkey = self._load_screenshot_hotkey()
        self.screenshot_hotkey_global = self._load_screenshot_hotkey_global()
        self.record_hotkey = self._load_record_hotkey()
        self.record_hotkey_global = self._load_record_hotkey_global()
        self.record_fps = self._load_record_fps()
        self.record_output_width = self._load_record_output_width()
        self.record_output_height = self._load_record_output_height()
        self.record_show_indicator = self._load_record_show_indicator()
        self.screenshot_hide_window = self._load_screenshot_hide_window()
        self.record_hide_window = self._load_record_hide_window()
        self.screenshot_fullscreen = self._load_screenshot_fullscreen()
        self.ai_enabled = self._load_ai_enabled()
        self.screenshot_ai_ask = self._load_screenshot_ai_ask()
        self.ai_api_provider = self._load_ai_api_provider()
        self.ai_api_base_url = self._load_ai_api_base_url()
        self.ai_api_key = self._load_ai_api_key()
        self.ai_model = self._load_ai_model()
        self.ai_prompt = self._load_ai_prompt()
        self.hotkey_binder = AppHotkeyBinder(self.root)
        self._region_recorder: RegionScreenRecorder | None = None
        self._recording_indicator: Toplevel | None = None
        self._capture_menu_hide_job: str | None = None
        self._capture_popup: Toplevel | None = None
        self._main_window_hide_depth = 0
        self._restore_focus_after_hide = False

        self.root.title("文件整理器")
        self.root.geometry("1100x560")
        self.root.minsize(900, 420)
        self.root.bind("<Control-z>", lambda _event: self.undo_last_action())
        self.root.bind_all("<Alt-Left>", lambda _event: self.go_back())
        self.root.bind_all("<Alt-Right>", lambda _event: self.go_forward())
        self._bind_mouse_side_buttons()

        self._build_layout()
        self.refresh()
        self._register_capture_hotkeys()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _bind_mouse_side_buttons(self) -> None:
        self._safe_bind_all("<Button-4>", lambda _event: self.go_back())
        self._safe_bind_all("<Button-5>", lambda _event: self.go_forward())

    def _safe_bind_all(self, sequence: str, callback) -> None:  # type: ignore[no-untyped-def]
        try:
            self.root.bind_all(sequence, callback)
        except Exception:
            # Some Windows Tk builds reject extended mouse button numbers.
            return

    def _build_capture_toolbar(self, toolbar: ttk.Frame) -> None:
        import tkinter as tk

        self.capture_container = tk.Frame(toolbar)
        self.capture_container.pack(side=LEFT, padx=(0, 6))

        self.capture_button = ttk.Button(
            self.capture_container,
            text="截图 ▾",
            command=self.start_region_screenshot,
        )
        self.capture_button.pack()

        for widget in (self.capture_container, self.capture_button):
            widget.bind("<Enter>", self._show_capture_menu, add="+")
            widget.bind("<Leave>", self._schedule_hide_capture_menu, add="+")

    def _capture_pointer_inside(self) -> bool:
        import tkinter as tk

        widgets: list[tk.Misc] = [self.capture_container, self.capture_button]
        if self._capture_popup is not None and self._capture_popup.winfo_exists():
            widgets.append(self._capture_popup)
            widgets.extend(self._capture_popup.winfo_children())

        pointer_x = self.root.winfo_pointerx()
        pointer_y = self.root.winfo_pointery()
        for widget in widgets:
            if not widget.winfo_exists():
                continue
            left = widget.winfo_rootx()
            top = widget.winfo_rooty()
            right = left + widget.winfo_width()
            bottom = top + widget.winfo_height()
            if left <= pointer_x <= right and top <= pointer_y <= bottom:
                return True
        return False

    def _show_capture_menu(self, _event=None) -> None:  # type: ignore[no-untyped-def]
        import tkinter as tk

        if self._capture_menu_hide_job is not None:
            self.root.after_cancel(self._capture_menu_hide_job)
            self._capture_menu_hide_job = None

        if self._capture_popup is not None and self._capture_popup.winfo_exists():
            return

        self.capture_button.update_idletasks()
        popup_x = self.capture_button.winfo_rootx()
        popup_y = self.capture_button.winfo_rooty() + self.capture_button.winfo_height()

        popup = Toplevel(self.root)
        popup.overrideredirect(True)
        popup.attributes("-topmost", True)
        frame = tk.Frame(popup, relief="solid", borderwidth=1)
        frame.pack()

        def run_and_close(action: Callable[[], None]) -> None:
            self._hide_capture_menu()
            action()

        for label, action in (
            ("区域截图", self.start_region_screenshot),
            ("二维码", self.start_region_qr_scan),
            ("全屏录屏", self.toggle_fullscreen_recording),
        ):
            item = tk.Button(
                frame,
                text=label,
                anchor="w",
                width=12,
                relief="flat",
                command=lambda bound_action=action: run_and_close(bound_action),
            )
            item.pack(fill="x", padx=2, pady=1)

        popup.geometry(f"+{popup_x}+{popup_y}")
        self._capture_popup = popup

        for widget in (popup, frame, *frame.winfo_children()):
            widget.bind("<Enter>", self._show_capture_menu, add="+")
            widget.bind("<Leave>", self._schedule_hide_capture_menu, add="+")

    def _schedule_hide_capture_menu(self, _event=None) -> None:  # type: ignore[no-untyped-def]
        if self._capture_menu_hide_job is not None:
            self.root.after_cancel(self._capture_menu_hide_job)
        self._capture_menu_hide_job = self.root.after(200, self._check_hide_capture_menu)

    def _check_hide_capture_menu(self) -> None:
        self._capture_menu_hide_job = None
        if self._capture_pointer_inside():
            self._capture_menu_hide_job = self.root.after(150, self._check_hide_capture_menu)
            return
        self._hide_capture_menu()

    def _hide_capture_menu(self) -> None:
        if self._capture_menu_hide_job is not None:
            self.root.after_cancel(self._capture_menu_hide_job)
            self._capture_menu_hide_job = None
        if self._capture_popup is not None and self._capture_popup.winfo_exists():
            self._capture_popup.destroy()
        self._capture_popup = None

    def _build_layout(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)

        toolbar = ttk.Frame(self.root, padding=8)
        toolbar.grid(row=0, column=0, sticky="ew")

        body = ttk.Frame(self.root)
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)

        ttk.Button(toolbar, text="返回上级", command=self.go_to_parent).pack(side=LEFT, padx=(0, 6))
        self._build_capture_toolbar(toolbar)
        for label, command in (
            ("收藏夹", self.show_favorites_menu),
            ("设置", self.open_settings),
            ("帮助", self.open_help),
        ):
            ttk.Button(toolbar, text=label, command=command).pack(side=LEFT, padx=(0, 6))

        paned = ttk.Panedwindow(body, orient=HORIZONTAL)
        paned.grid(row=0, column=0, sticky="nsew")
        self._main_paned = paned

        content = ttk.Frame(paned, padding=(8, 0, 0, 8))
        content.columnconfigure(0, weight=1)
        content.rowconfigure(0, weight=1)

        columns = ("name", "type", "size", "modified")
        self.tree_frame = ttk.Frame(content)
        self.tree_frame.grid(row=0, column=0, sticky="nsew")
        self.tree_frame.rowconfigure(0, weight=1)
        self.tree_frame.columnconfigure(0, weight=1)

        self.tree = ttk.Treeview(self.tree_frame, columns=columns, show="headings", selectmode="extended")
        self.tree.heading("name", text="名称")
        self.tree.heading("type", text="类型")
        self.tree.heading("size", text="大小")
        self.tree.heading("modified", text="修改时间")
        self.tree.column("name", minwidth=240, width=360)
        self.tree.column("type", minwidth=100, width=120)
        self.tree.column("size", minwidth=90, width=110, anchor="e")
        self.tree.column("modified", minwidth=140, width=180)
        self.tree.grid(row=0, column=0, sticky="nsew")
        self.tree.bind("<Double-1>", self._on_tree_double_click)
        self.tree.bind("<Delete>", lambda _event: self.trash_selected())
        self.tree.bind("<Button-1>", self._on_tree_button_press)
        self.tree.bind("<ButtonRelease-1>", self._on_tree_button_release, add="+")

        self._marquee_toplevel: Toplevel | None = None
        self._marquee_canvas: Canvas | None = None
        self._marquee_start: tuple[int, int] | None = None
        self._marquee_rect_id: int | None = None
        self._marquee_additive = False
        self._marquee_base_selection: tuple[str, ...] = ()
        self._marquee_tree_motion_bound = False

        scrollbar = ttk.Scrollbar(content, orient=VERTICAL, command=self.tree.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scrollbar.set)

        sidebar = ttk.LabelFrame(paned, text="最近打开", padding=8)
        paned.add(content, weight=4)
        paned.add(sidebar, weight=1)
        paned.bind("<<PanedwindowSashMoved>>", self._on_main_paned_sash_moved)

        self.recent_apps_list = Listbox(sidebar, activestyle="none", exportselection=False)
        self.recent_apps_list.pack(side=LEFT, fill="both", expand=True)
        self.recent_apps_list.bind("<Double-1>", self._open_recent_application)
        self.recent_apps_list.bind("<Button-3>", self._show_recent_apps_menu)

        recent_scrollbar = ttk.Scrollbar(sidebar, orient=VERTICAL, command=self.recent_apps_list.yview)
        recent_scrollbar.pack(side=RIGHT, fill="y")
        self.recent_apps_list.configure(yscrollcommand=recent_scrollbar.set)

        self.recent_apps_menu = Menu(self.root, tearoff=False)
        self.recent_apps_menu.add_command(label="打开", command=self._open_selected_recent_application)
        self.recent_apps_menu.add_command(label="从列表移除", command=self._remove_selected_recent_application)

        self.path_bar = ttk.Frame(self.root, padding=(8, 4))
        self.path_bar.grid(row=2, column=0, sticky="ew")

        self._render_recent_apps()
        self.root.after_idle(self._apply_initial_paned_position)

        self.file_menu = Menu(self.root, tearoff=False)
        self.file_menu.add_command(label="打开/进入", command=self.open_selected)
        self.file_menu.add_command(label="加入收藏", command=self.add_selected_to_favorites)
        self.file_menu.add_command(label="重命名", command=self.rename_selected)
        self.file_menu.add_command(label="移到回收区", command=self.trash_selected)

        self.blank_menu = Menu(self.root, tearoff=False)
        self.blank_menu.add_command(label="刷新", command=self.refresh)
        self.blank_menu.add_command(label="新建文件夹", command=self.create_folder)
        self.blank_menu.add_command(label="收藏当前目录", command=self.add_current_folder_to_favorites)
        self.blank_menu.add_command(label="撤销上一步", command=self.undo_last_action)
        self.favorites_popup: Toplevel | None = None
        self.tree.bind("<Button-3>", self._show_context_menu)

    def _clamp_main_paned_sash(self, paned: ttk.Panedwindow) -> None:
        total_width = paned.winfo_width()
        if total_width <= 1:
            return
        min_sash = MIN_MAIN_PANE_WIDTH
        max_sash = total_width - MIN_SIDEBAR_PANE_WIDTH
        if min_sash > max_sash:
            return
        sash = paned.sashpos(0)
        if sash < min_sash:
            paned.sashpos(0, min_sash)
        elif sash > max_sash:
            paned.sashpos(0, max_sash)

    def _apply_initial_paned_position(self) -> None:
        paned = getattr(self, "_main_paned", None)
        if paned is None:
            return
        total_width = paned.winfo_width()
        if total_width <= 1:
            self.root.after(50, self._apply_initial_paned_position)
            return
        sidebar_width = max(
            MIN_SIDEBAR_PANE_WIDTH,
            min(self.sidebar_width, total_width - MIN_MAIN_PANE_WIDTH),
        )
        paned.sashpos(0, total_width - sidebar_width)
        self._clamp_main_paned_sash(paned)

    def _on_main_paned_sash_moved(self, _event: object | None = None) -> None:
        paned = getattr(self, "_main_paned", None)
        if paned is None:
            return
        self._clamp_main_paned_sash(paned)
        self.sidebar_width = max(
            MIN_SIDEBAR_PANE_WIDTH,
            min(paned.winfo_width() - paned.sashpos(0), 800),
        )
        try:
            self._save_settings()
        except OSError:
            pass

    def _show_context_menu(self, event) -> None:  # type: ignore[no-untyped-def]
        row_id = self.tree.identify_row(event.y)
        if row_id:
            if row_id not in self.tree.selection():
                self.tree.selection_set(row_id)
            self._update_file_menu_labels()
            self.file_menu.tk_popup(event.x_root, event.y_root)
        else:
            self.tree.selection_remove(self.tree.selection())
            self.blank_menu.tk_popup(event.x_root, event.y_root)

    def _update_file_menu_labels(self) -> None:
        count = len(self.tree.selection())
        single = count == 1
        self.file_menu.entryconfig(0, label="打开/进入", state="normal" if single else "disabled")
        self.file_menu.entryconfig(1, label="加入收藏", state="normal" if single else "disabled")
        self.file_menu.entryconfig(2, label="重命名", state="normal" if single else "disabled")
        trash_label = "移到回收区" if count <= 1 else f"移到回收区（{count} 项）"
        self.file_menu.entryconfig(3, label=trash_label, state="normal")

    @staticmethod
    def _control_pressed(event) -> bool:  # type: ignore[no-untyped-def]
        return bool(event.state & 0x0004)

    def _on_tree_button_press(self, event) -> str | None:  # type: ignore[no-untyped-def]
        region = self.tree.identify_region(event.x, event.y)
        row_id = self.tree.identify_row(event.y)
        if region == "heading":
            return None
        if row_id:
            return None
        self._marquee_additive = self._control_pressed(event)
        if not self._marquee_additive:
            self.tree.selection_remove(self.tree.selection())
        self._begin_marquee(event.x, event.y)
        return "break"

    def _on_tree_button_release(self, event) -> None:  # type: ignore[no-untyped-def]
        if self._marquee_start is None:
            return
        self._finish_marquee(event.x, event.y)

    def _on_tree_marquee_drag(self, event) -> None:  # type: ignore[no-untyped-def]
        if self._marquee_start is None:
            return
        self._update_marquee(event.x, event.y)

    def _begin_marquee(self, x: int, y: int) -> None:
        self._marquee_start = (x, y)
        self._marquee_base_selection = tuple(self.tree.selection()) if self._marquee_additive else ()
        if not self._marquee_additive:
            self.tree.selection_remove(self.tree.selection())
        self._create_marquee_overlay()
        self._update_marquee(x, y)

    def _create_marquee_overlay(self) -> None:
        self._destroy_marquee_overlay()
        self.tree.update_idletasks()
        overlay_x = self.tree.winfo_rootx()
        overlay_y = self.tree.winfo_rooty()
        overlay_width = max(self.tree.winfo_width(), 1)
        overlay_height = max(self.tree.winfo_height(), 1)

        self._marquee_toplevel = Toplevel(self.root)
        self._marquee_toplevel.overrideredirect(True)
        self._marquee_toplevel.attributes("-topmost", True)
        transparent_bg = "magenta"
        try:
            self._marquee_toplevel.attributes("-transparentcolor", transparent_bg)
        except Exception:
            self._marquee_toplevel.attributes("-alpha", 0.01)

        self._marquee_toplevel.geometry(
            f"{overlay_width}x{overlay_height}+{overlay_x}+{overlay_y}"
        )
        self._marquee_canvas = Canvas(
            self._marquee_toplevel,
            bg=transparent_bg,
            highlightthickness=0,
            cursor="crosshair",
        )
        self._marquee_canvas.pack(fill="both", expand=True)
        self._marquee_canvas.bind("<B1-Motion>", self._on_marquee_drag)
        self._marquee_canvas.bind("<ButtonRelease-1>", self._on_marquee_release)
        self.tree.bind("<B1-Motion>", self._on_tree_marquee_drag, add="+")
        self._marquee_tree_motion_bound = True
        self._marquee_rect_id = None

    def _destroy_marquee_overlay(self) -> None:
        if self._marquee_tree_motion_bound:
            self.tree.unbind("<B1-Motion>")
            self._marquee_tree_motion_bound = False
        if self._marquee_toplevel is not None and self._marquee_toplevel.winfo_exists():
            self._marquee_toplevel.destroy()
        self._marquee_toplevel = None
        self._marquee_canvas = None
        self._marquee_rect_id = None

    def _on_marquee_drag(self, event) -> None:  # type: ignore[no-untyped-def]
        if self._marquee_start is None:
            return
        self._update_marquee(event.x, event.y)

    def _on_marquee_release(self, event) -> None:  # type: ignore[no-untyped-def]
        if self._marquee_start is None:
            return
        self._finish_marquee(event.x, event.y)

    def _update_marquee(self, x: int, y: int) -> None:
        if self._marquee_start is None:
            return

        x0, y0 = self._marquee_start
        if self._marquee_canvas is not None:
            if self._marquee_rect_id is None:
                self._marquee_rect_id = self._marquee_canvas.create_rectangle(
                    x0,
                    y0,
                    x,
                    y,
                    outline="#ff4d4f",
                    width=2,
                    dash=(4, 2),
                )
            else:
                self._marquee_canvas.coords(self._marquee_rect_id, x0, y0, x, y)

        selected_items = self._tree_items_in_rect(x0, y0, x, y)
        if self._marquee_additive:
            combined = tuple(dict.fromkeys(self._marquee_base_selection + selected_items))
            self.tree.selection_set(combined)
        else:
            self.tree.selection_set(selected_items)

    def _finish_marquee(self, x: int, y: int) -> None:
        if self._marquee_start is None:
            return
        self._update_marquee(x, y)
        self._destroy_marquee_overlay()
        self._marquee_start = None

    def _tree_items_in_rect(self, x0: int, y0: int, x1: int, y1: int) -> tuple[str, ...]:
        left = min(x0, x1)
        right = max(x0, x1)
        top = min(y0, y1)
        bottom = max(y0, y1)
        if right - left < 4 and bottom - top < 4:
            return ()

        selected: list[str] = []
        for item_id in self.tree.get_children():
            bbox = self.tree.bbox(item_id)
            if not bbox:
                continue
            item_left, item_top, item_width, item_height = bbox
            item_right = item_left + item_width
            item_bottom = item_top + item_height
            if item_right >= left and item_left <= right and item_bottom >= top and item_top <= bottom:
                selected.append(item_id)
        return tuple(selected)

    def _on_tree_double_click(self, event) -> None:  # type: ignore[no-untyped-def]
        row_id = self.tree.identify_row(event.y)
        if not row_id:
            return
        self._open_path(Path(row_id))

    def refresh(self) -> None:
        for row in self.tree.get_children():
            self.tree.delete(row)

        for path in sorted(self.managed_folder.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())):
            if is_internal_path(path, self.managed_folder):
                continue
            self.tree.insert("", END, iid=str(path), values=self._row_values(path))

        self._render_path_bar()

    def _row_values(self, path: Path) -> tuple[str, str, str, str]:
        file_type = "文件夹" if path.is_dir() else path.suffix.lower() or "文件"
        size = "-" if path.is_dir() else self._format_size(path.stat().st_size)
        modified = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
        return self._display_name(path), file_type, size, modified

    def _display_name(self, path: Path) -> str:
        icon = TYPE_ICONS.get(categorize_path(path), TYPE_ICONS["Other"])
        return f"{icon} {path.name}"

    def selected_paths(self) -> list[Path]:
        return [Path(item_id) for item_id in self.tree.selection()]

    def selected_path(self, *, require_exactly_one: bool = True) -> Path | None:
        paths = self.selected_paths()
        if not paths:
            messagebox.showinfo("未选择", "请先选择一个文件或文件夹。")
            return None
        if require_exactly_one and len(paths) > 1:
            messagebox.showinfo("无法操作", "请只选择一个文件或文件夹。")
            return None
        return paths[0]

    def open_selected(self) -> None:
        path = self.selected_path()
        if path is None:
            return
        self._open_path(path)

    def _open_path(self, path: Path) -> None:
        if path.is_dir():
            self.go_to_folder(path)
            return
        self._open_application(path)

    def go_to_parent(self) -> None:
        parent = self.managed_folder.parent
        if parent == self.managed_folder:
            messagebox.showinfo("无法返回", "已经是最上级目录。")
            return

        self.go_to_folder(parent)

    def go_to_folder(self, folder: Path, add_history: bool = True) -> None:
        folder = folder.resolve()
        if not folder.exists() or not folder.is_dir():
            messagebox.showerror("无法跳转", "目标目录不存在。")
            return

        if folder == self.managed_folder:
            return

        if add_history:
            self.back_history.append(self.managed_folder)
            self.forward_history.clear()

        self.managed_folder = folder
        self.refresh()

    def go_back(self) -> str:
        if not self.back_history:
            return "break"

        previous_folder = self.back_history.pop()
        self.forward_history.append(self.managed_folder)
        self.go_to_folder(previous_folder, add_history=False)
        return "break"

    def go_forward(self) -> str:
        if not self.forward_history:
            return "break"

        next_folder = self.forward_history.pop()
        self.back_history.append(self.managed_folder)
        self.go_to_folder(next_folder, add_history=False)
        return "break"

    def _register_capture_hotkeys(self) -> None:
        self.hotkey_binder.unregister_all()
        try:
            self.hotkey_binder.register(
                "screenshot",
                self.screenshot_hotkey,
                self.start_region_screenshot,
                global_enabled=self.screenshot_hotkey_global,
            )
        except ValueError as error:
            messagebox.showwarning("截图快捷键未生效", f"{error}\n已改用默认快捷键。")
            self.screenshot_hotkey = DEFAULT_SCREENSHOT_HOTKEY
            self.screenshot_hotkey_global = True
            try:
                self.hotkey_binder.register(
                    "screenshot",
                    self.screenshot_hotkey,
                    self.start_region_screenshot,
                    global_enabled=True,
                )
            except ValueError:
                pass

        try:
            self.hotkey_binder.register(
                "record",
                self.record_hotkey,
                self.toggle_fullscreen_recording,
                global_enabled=self.record_hotkey_global,
            )
        except ValueError as error:
            messagebox.showwarning("录屏快捷键未生效", f"{error}\n已改用默认快捷键。")
            self.record_hotkey = DEFAULT_RECORD_HOTKEY
            self.record_hotkey_global = True
            try:
                self.hotkey_binder.register(
                    "record",
                    self.record_hotkey,
                    self.toggle_fullscreen_recording,
                    global_enabled=True,
                )
            except ValueError:
                pass

    def _on_close(self) -> None:
        self._hide_capture_menu()
        if self._region_recorder is not None and self._region_recorder.is_running:
            self._stop_fullscreen_recording(silent=True)
        self.hotkey_binder.unregister_all()
        self.root.destroy()

    @staticmethod
    def _virtual_screen_bbox() -> tuple[int, int, int, int]:
        left, top, width, height = get_virtual_screen_bounds()
        return left, top, left + width, top + height

    def _hide_main_window_for_capture(self, *, restore_focus: bool) -> None:
        if self._main_window_hide_depth == 0:
            self._hide_capture_menu()
            hide_toplevel_window(self.root)
            self._restore_focus_after_hide = restore_focus
        else:
            self._restore_focus_after_hide = (
                self._restore_focus_after_hide or restore_focus
            )
        self._main_window_hide_depth += 1

    def _restore_main_window_after_capture(self) -> None:
        if self._main_window_hide_depth <= 0:
            return
        self._main_window_hide_depth -= 1
        if self._main_window_hide_depth > 0:
            return
        show_toplevel_window(self.root)
        if self._restore_focus_after_hide:
            self.root.lift()
            self.root.focus_force()
        self._restore_focus_after_hide = False

    def _begin_screenshot_capture(self, capture_action: Callable[[], None]) -> None:
        if not self.screenshot_hide_window:
            capture_action()
            return
        self._hide_main_window_for_capture(
            restore_focus=not self.screenshot_hotkey_global
        )
        self.root.after(SCREENSHOT_HIDE_DELAY_MS, capture_action)

    def start_region_screenshot(self) -> None:
        if self._region_recorder is not None and self._region_recorder.is_running:
            messagebox.showinfo("正在录屏", "请先停止录屏，再进行截图。")
            return
        try:
            from PIL import ImageGrab  # noqa: F401
        except ImportError:
            messagebox.showerror("无法截图", "缺少 Pillow 库。请先运行：pip install pillow")
            return

        if self.screenshot_fullscreen:
            self._begin_screenshot_capture(
                lambda: self._complete_region_screenshot(*self._virtual_screen_bbox())
            )
            return

        self._begin_screenshot_capture(
            lambda: self._open_region_selector(self._complete_region_screenshot)
        )

    def start_region_qr_scan(self) -> None:
        if self._region_recorder is not None and self._region_recorder.is_running:
            messagebox.showinfo("正在录屏", "请先停止录屏，再进行二维码识别。")
            return
        try:
            from PIL import ImageGrab  # noqa: F401
        except ImportError:
            messagebox.showerror("无法识别", "缺少 Pillow 库。请先运行：pip install pillow")
            return

        self._begin_screenshot_capture(
            lambda: self._open_region_selector(self._complete_region_qr_scan)
        )

    def _complete_region_qr_scan(self, left: int, top: int, right: int, bottom: int) -> None:
        capture_error: Exception | None = None
        texts: list[str] = []
        try:
            if self.screenshot_hide_window:
                wait_for_capture_compositor(delay_ms=SCREENSHOT_CAPTURE_WAIT_MS)
            image = grab_screen_region(left, top, right, bottom)
            texts = decode_qr_codes(image)
        except ImportError as error:
            capture_error = error
        except Exception as error:
            capture_error = error
        finally:
            if self.screenshot_hide_window:
                self._restore_main_window_after_capture()

        if capture_error is not None:
            title = "无法识别" if isinstance(capture_error, ImportError) else "二维码识别失败"
            messagebox.showerror(title, str(capture_error))
            return

        if not texts:
            messagebox.showinfo("二维码", "未在选区中识别到二维码。")
            return

        self._show_qr_scan_results(texts)

    def _show_qr_scan_results(self, texts: list[str]) -> None:
        popup = Toplevel(self.root)
        popup.title("二维码")
        popup.transient(self.root)

        frame = ttk.Frame(popup, padding=8)
        frame.pack(fill=BOTH, expand=True)

        if len(texts) == 1:
            ttk.Label(frame, text="识别结果：").pack(anchor="w")
        else:
            ttk.Label(frame, text=f"识别到 {len(texts)} 个二维码：").pack(anchor="w")

        if len(texts) == 1:
            body = texts[0]
        else:
            body = "\n\n".join(f"[{index}] {text}" for index, text in enumerate(texts, start=1))

        line_count = body.count("\n") + 1
        text_widget = Text(frame, width=64, height=min(16, max(6, line_count + 2)), wrap="word")
        text_widget.pack(fill=BOTH, expand=True, pady=(4, 8))
        text_widget.insert("1.0", body)
        text_widget.configure(state="disabled")

        def copy_all() -> None:
            copy_text = "\n".join(texts) if len(texts) > 1 else texts[0]
            self.root.clipboard_clear()
            self.root.clipboard_append(copy_text)
            messagebox.showinfo("已复制", "内容已复制到剪贴板。", parent=popup)

        button_row = ttk.Frame(frame)
        button_row.pack(fill="x")
        ttk.Button(button_row, text="复制", command=copy_all).pack(side=LEFT, padx=(0, 6))
        ttk.Button(button_row, text="关闭", command=popup.destroy).pack(side=LEFT)

    def toggle_fullscreen_recording(self) -> None:
        if self._region_recorder is not None and self._region_recorder.is_running:
            self._stop_fullscreen_recording()
            return
        self.start_fullscreen_recording()

    def start_fullscreen_recording(self) -> None:
        if self._region_recorder is not None and self._region_recorder.is_running:
            self._stop_fullscreen_recording()
            return

        if self.record_hide_window:
            self._hide_main_window_for_capture(restore_focus=not self.record_hotkey_global)
            self.root.after(RECORD_HIDE_DELAY_MS, self._start_fullscreen_recording_core)
            return

        self._start_fullscreen_recording_core()

    def _start_fullscreen_recording_core(self) -> None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        destination = self._recordings_folder() / f"recording_{timestamp}.mp4"
        bbox = self._virtual_screen_bbox()
        output_size = self._recording_output_size(bbox)
        self._region_recorder = RegionScreenRecorder(
            bbox,
            destination,
            fps=self.record_fps,
            output_size=output_size,
        )
        self._region_recorder.start()
        if self.record_show_indicator:
            self._show_recording_indicator()

    def _photocut_folder(self) -> Path:
        folder = get_managed_folder() / PHOTOCUT_FOLDER_NAME
        folder.mkdir(exist_ok=True)
        return folder

    def _open_region_selector(self, on_selected: Callable[[int, int, int, int], None]) -> None:
        selector = Toplevel(self.root)
        selector.attributes("-topmost", True)
        selector.attributes("-alpha", 0.25)
        selector.configure(background="black", cursor="crosshair")

        if sys.platform == "win32":
            screen_left, screen_top, screen_width, screen_height = get_virtual_screen_bounds()
            selector.overrideredirect(True)
            selector.geometry(f"{screen_width}x{screen_height}+{screen_left}+{screen_top}")
        else:
            selector.attributes("-fullscreen", True)

        canvas = Canvas(selector, highlightthickness=0, bg="black")
        canvas.pack(fill="both", expand=True)
        selector.update_idletasks()

        state: dict[str, object] = {"start": None, "rect_id": None}

        def root_to_canvas(x_root: int, y_root: int) -> tuple[int, int]:
            return x_root - selector.winfo_rootx(), y_root - selector.winfo_rooty()

        def cancel() -> None:
            if selector.winfo_exists():
                selector.destroy()
            if self.screenshot_hide_window:
                self._restore_main_window_after_capture()

        def on_press(event) -> None:  # type: ignore[no-untyped-def]
            state["start"] = (event.x_root, event.y_root)
            if state["rect_id"] is not None:
                canvas.delete(state["rect_id"])
            cx, cy = root_to_canvas(event.x_root, event.y_root)
            state["rect_id"] = canvas.create_rectangle(
                cx,
                cy,
                cx,
                cy,
                outline="#ff4d4f",
                width=2,
            )

        def on_drag(event) -> None:  # type: ignore[no-untyped-def]
            if state["start"] is None or state["rect_id"] is None:
                return
            x0, y0 = state["start"]  # type: ignore[misc]
            cx0, cy0 = root_to_canvas(x0, y0)
            cx1, cy1 = root_to_canvas(event.x_root, event.y_root)
            canvas.coords(state["rect_id"], cx0, cy0, cx1, cy1)

        def on_release(event) -> None:  # type: ignore[no-untyped-def]
            if state["start"] is None:
                cancel()
                return

            x0, y0 = state["start"]  # type: ignore[misc]
            left = min(x0, event.x_root)
            top = min(y0, event.y_root)
            right = max(x0, event.x_root)
            bottom = max(y0, event.y_root)
            selector.destroy()

            if right - left < 5 or bottom - top < 5:
                messagebox.showinfo("已取消", "选区太小。")
                if self.screenshot_hide_window:
                    self._restore_main_window_after_capture()
                return

            on_selected(left, top, right, bottom)

        selector.bind("<Escape>", lambda _event: cancel())
        canvas.bind("<Button-1>", on_press)
        canvas.bind("<B1-Motion>", on_drag)
        canvas.bind("<ButtonRelease-1>", on_release)
        selector.protocol("WM_DELETE_WINDOW", cancel)
        selector.focus_force()

    def _complete_region_screenshot(self, left: int, top: int, right: int, bottom: int) -> None:
        destination: Path | None = None
        capture_error: Exception | None = None
        try:
            if self.screenshot_hide_window:
                wait_for_capture_compositor(delay_ms=SCREENSHOT_CAPTURE_WAIT_MS)
            image = grab_screen_region(left, top, right, bottom)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            destination = self._photocut_folder() / f"screenshot_{timestamp}.png"
            image.save(destination)
        except Exception as error:
            capture_error = error
        finally:
            if self.screenshot_hide_window:
                self._restore_main_window_after_capture()

        if capture_error is not None:
            messagebox.showerror("截图失败", str(capture_error))
            return

        self.refresh()
        self._offer_screenshot_ai(destination)

    def _recordings_folder(self) -> Path:
        folder = self._photocut_folder() / "recordings"
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def _recording_output_size(
        self, bbox: tuple[int, int, int, int]
    ) -> tuple[int, int] | None:
        left, top, right, bottom = bbox
        source_width = right - left
        source_height = bottom - top
        width = self.record_output_width
        height = self.record_output_height
        if width <= 0 and height <= 0:
            return None
        if width <= 0:
            width = max(2, round(source_width * height / source_height))
        elif height <= 0:
            height = max(2, round(source_height * width / source_width))
        return max(2, width), max(2, height)

    def _show_recording_indicator(self) -> None:
        if self._recording_indicator is not None and self._recording_indicator.winfo_exists():
            self._recording_indicator.destroy()

        indicator = Toplevel(self.root)
        indicator.overrideredirect(True)
        indicator.attributes("-topmost", True)
        indicator.resizable(False, False)

        ttk.Button(
            indicator,
            text="停止",
            width=5,
            command=self._stop_fullscreen_recording,
        ).pack(padx=4, pady=4)

        indicator.update_idletasks()
        screen_left, screen_top, screen_width, _screen_height = get_virtual_screen_bounds()
        indicator_width = indicator.winfo_reqwidth()
        indicator_height = indicator.winfo_reqheight()
        indicator.geometry(
            f"{indicator_width}x{indicator_height}+"
            f"{screen_left + screen_width - indicator_width - 12}+{screen_top + 12}"
        )
        self._recording_indicator = indicator

    def _stop_fullscreen_recording(self, *, silent: bool = False) -> None:
        if self._region_recorder is None:
            return

        destination = self._region_recorder.output_path
        try:
            self._region_recorder.stop()
            error = self._region_recorder.error()
            self._region_recorder = None

            if self._recording_indicator is not None and self._recording_indicator.winfo_exists():
                self._recording_indicator.destroy()
            self._recording_indicator = None

            self.refresh()
            if error is not None:
                messagebox.showerror("录屏失败", str(error))
                if destination.exists():
                    destination.unlink(missing_ok=True)
                return

            if silent:
                return

            if destination.exists() and destination.stat().st_size == 0:
                destination.unlink(missing_ok=True)
        finally:
            if self.record_hide_window:
                self._restore_main_window_after_capture()

    def _render_path_bar(self) -> None:
        for child in self.path_bar.winfo_children():
            child.destroy()

        path_text = Text(
            self.path_bar,
            height=1,
            wrap="none",
            borderwidth=0,
            relief="flat",
            highlightthickness=0,
            padx=0,
            pady=0,
        )
        path_text.configure(background=self.root.cget("background"), cursor="xterm")
        path_text.pack(fill="x", expand=True)
        path_text.insert("end", "位置：")

        current_path: Path | None = None
        for index, part in enumerate(self.managed_folder.parts):
            current_path = Path(part) if current_path is None else current_path / part
            if index > 0:
                path_text.insert("end", "\\")

            label_text = part.rstrip("\\/") or part
            tag_name = f"path_{index}"
            start = path_text.index("end-1c")
            path_text.insert("end", label_text)
            end = path_text.index("end-1c")
            path_text.tag_add(tag_name, start, end)
            path_text.tag_bind(tag_name, "<Enter>", lambda event: event.widget.configure(cursor="hand2"))
            path_text.tag_bind(tag_name, "<Leave>", lambda event: event.widget.configure(cursor="xterm"))
            path_text.tag_bind(tag_name, "<ButtonRelease-1>", self._make_path_click_handler(current_path))

        path_text.configure(state="disabled")

    def _make_path_click_handler(self, target: Path):  # type: ignore[no-untyped-def]
        def handle_click(event) -> str | None:  # type: ignore[no-untyped-def]
            if event.widget.tag_ranges("sel"):
                return None

            self.go_to_folder(target)
            return "break"

        return handle_click

    def _resolve_settings_path(self) -> Path:
        settings_path = get_app_base_folder() / SETTINGS_FILE_NAME
        legacy_path = get_managed_folder() / SETTINGS_FILE_NAME
        if not settings_path.exists() and legacy_path.exists():
            shutil.copy2(legacy_path, settings_path)
            try:
                legacy_path.unlink()
            except OSError:
                pass
        return settings_path

    def _load_settings(self) -> dict[str, object]:
        if not self.settings_path.exists():
            return {}

        try:
            loaded_settings = json.loads(self.settings_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

        return loaded_settings if isinstance(loaded_settings, dict) else {}

    def _load_max_undo_steps(self) -> int:
        value = self.settings.get("max_undo_steps", DEFAULT_MAX_UNDO_STEPS)
        return self._normalize_max_undo_steps(value)

    def _load_max_recent_apps(self) -> int:
        value = self.settings.get("max_recent_apps", DEFAULT_MAX_RECENT_APPS)
        return self._normalize_max_recent_apps(value)

    def _load_sidebar_width(self) -> int:
        value = self.settings.get("sidebar_width", DEFAULT_SIDEBAR_WIDTH)
        try:
            width = int(value)
        except (TypeError, ValueError):
            return DEFAULT_SIDEBAR_WIDTH
        return max(MIN_SIDEBAR_PANE_WIDTH, min(width, 800))

    def _load_screenshot_hotkey(self) -> str:
        return self._load_hotkey_setting("screenshot_hotkey", DEFAULT_SCREENSHOT_HOTKEY)

    def _load_record_hotkey(self) -> str:
        return self._load_hotkey_setting("record_hotkey", DEFAULT_RECORD_HOTKEY)

    def _load_hotkey_setting(self, key: str, default: str) -> str:
        value = self.settings.get(key, default)
        if not isinstance(value, str):
            return default
        try:
            return validate_hotkey(value, require_keyboard=False)
        except ValueError:
            return default

    @staticmethod
    def _load_bool_setting(settings: dict, key: str, default: bool) -> bool:
        if key not in settings:
            return default
        return bool(settings.get(key))

    def _load_screenshot_hotkey_global(self) -> bool:
        return self._load_bool_setting(self.settings, "screenshot_hotkey_global", True)

    def _load_record_hotkey_global(self) -> bool:
        return self._load_bool_setting(self.settings, "record_hotkey_global", True)

    def _load_record_show_indicator(self) -> bool:
        return self._load_bool_setting(self.settings, "record_show_indicator", False)

    def _load_record_fps(self) -> int:
        return self._normalize_record_fps(self.settings.get("record_fps", DEFAULT_RECORD_FPS))

    def _load_record_output_width(self) -> int:
        return self._normalize_record_output_dimension(
            self.settings.get("record_output_width", DEFAULT_RECORD_OUTPUT_WIDTH)
        )

    def _load_record_output_height(self) -> int:
        return self._normalize_record_output_dimension(
            self.settings.get("record_output_height", DEFAULT_RECORD_OUTPUT_HEIGHT)
        )

    def _load_screenshot_fullscreen(self) -> bool:
        return self._load_bool_setting(self.settings, "screenshot_fullscreen", False)

    def _load_screenshot_hide_window(self) -> bool:
        return self._load_bool_setting(self.settings, "screenshot_hide_window", True)

    def _load_record_hide_window(self) -> bool:
        return self._load_bool_setting(self.settings, "record_hide_window", True)

    def _load_ai_enabled(self) -> bool:
        if "ai_enabled" in self.settings:
            return bool(self.settings.get("ai_enabled"))
        return bool(self.settings.get("screenshot_ai_ask", False))

    def _load_screenshot_ai_ask(self) -> bool:
        return bool(self.settings.get("screenshot_ai_ask", False))

    def _load_ai_api_provider(self) -> str:
        value = self.settings.get("ai_api_provider", "")
        if isinstance(value, str) and value.strip() in AI_PROVIDER_PRESETS:
            return value.strip()
        raw_url = self.settings.get("ai_api_base_url", "")
        if isinstance(raw_url, str) and raw_url.strip():
            return detect_ai_provider(raw_url.strip())
        return DEFAULT_AI_PROVIDER

    def _load_ai_api_base_url(self) -> str:
        value = self.settings.get("ai_api_base_url", "")
        if isinstance(value, str) and value.strip():
            return value.strip()
        return ai_provider_preset(self._load_ai_api_provider())["api_base_url"]

    def _load_ai_api_key(self) -> str:
        value = self.settings.get("ai_api_key", "")
        return value.strip() if isinstance(value, str) else ""

    def _load_ai_model(self) -> str:
        value = self.settings.get("ai_model", "")
        if isinstance(value, str) and value.strip():
            return value.strip()
        return ai_provider_preset(self._load_ai_api_provider())["model"]

    def _load_ai_prompt(self) -> str:
        value = self.settings.get("ai_prompt", DEFAULT_AI_PROMPT)
        if not isinstance(value, str) or not value.strip():
            return DEFAULT_AI_PROMPT
        return value.strip()

    def _ai_settings_configured(self) -> bool:
        return bool(self.ai_api_base_url and self.ai_api_key and self.ai_model)

    def _load_favorite_paths(self, settings_key: str) -> list[Path]:
        raw_favorites = self.settings.get(settings_key, [])
        if not isinstance(raw_favorites, list):
            return []

        favorites: list[Path] = []
        for raw_path in raw_favorites:
            if not isinstance(raw_path, str):
                continue
            path = Path(raw_path).resolve()
            if path not in favorites:
                favorites.append(path)
        return favorites

    def _load_favorite_folders(self) -> list[Path]:
        return self._load_favorite_paths("favorite_folders")

    def _load_favorite_files(self) -> list[Path]:
        return self._load_favorite_paths("favorite_files")

    def _load_recent_apps(self) -> list[Path]:
        raw_recent_apps = self.settings.get("recent_apps", [])
        if not isinstance(raw_recent_apps, list):
            return []

        recent_apps: list[Path] = []
        for raw_path in raw_recent_apps:
            if not isinstance(raw_path, str):
                continue
            path = Path(raw_path).resolve()
            if not path.exists() or not path.is_file():
                continue
            if path not in recent_apps:
                recent_apps.append(path)
            if len(recent_apps) >= self.max_recent_apps:
                break
        return recent_apps

    def _save_settings(self) -> None:
        settings = {
            "max_undo_steps": self.max_undo_steps,
            "max_recent_apps": self.max_recent_apps,
            "sidebar_width": self.sidebar_width,
            "screenshot_hotkey": self.screenshot_hotkey,
            "screenshot_hotkey_global": self.screenshot_hotkey_global,
            "record_hotkey": self.record_hotkey,
            "record_hotkey_global": self.record_hotkey_global,
            "record_fps": self.record_fps,
            "record_output_width": self.record_output_width,
            "record_output_height": self.record_output_height,
            "record_show_indicator": self.record_show_indicator,
            "screenshot_hide_window": self.screenshot_hide_window,
            "record_hide_window": self.record_hide_window,
            "screenshot_fullscreen": self.screenshot_fullscreen,
            "ai_enabled": self.ai_enabled,
            "screenshot_ai_ask": self.screenshot_ai_ask,
            "ai_api_provider": self.ai_api_provider,
            "ai_api_base_url": self.ai_api_base_url,
            "ai_api_key": self.ai_api_key,
            "ai_model": self.ai_model,
            "ai_prompt": self.ai_prompt,
            "favorite_folders": [str(path) for path in self.favorite_folders],
            "favorite_files": [str(path) for path in self.favorite_files],
            "recent_apps": [str(path) for path in self.recent_apps[: self.max_recent_apps]],
        }
        self.settings_path.write_text(json.dumps(settings, indent=2), encoding="utf-8")

    @staticmethod
    def _normalize_max_undo_steps(value: object) -> int:
        try:
            steps = int(value)
        except (TypeError, ValueError):
            return DEFAULT_MAX_UNDO_STEPS

        return max(1, min(steps, 100))

    @staticmethod
    def _normalize_record_fps(value: object) -> int:
        try:
            fps = int(value)
        except (TypeError, ValueError):
            return DEFAULT_RECORD_FPS
        return max(5, min(fps, 60))

    @staticmethod
    def _format_record_output_dimension(pixels: int) -> str:
        return RECORD_OUTPUT_AUTO if pixels <= 0 else str(pixels)

    @staticmethod
    def _normalize_record_output_dimension(value: object) -> int:
        try:
            return FileOrganizerApp._parse_record_output_dimension(value)
        except ValueError:
            return 0

    @staticmethod
    def _parse_record_output_dimension(value: object) -> int:
        text = str(value).strip()
        if not text or text == RECORD_OUTPUT_AUTO or text.lower() in ("auto", "automatic"):
            return 0
        try:
            pixels = int(text)
        except (TypeError, ValueError) as error:
            raise ValueError("输出宽高请填写「自动」或正整数像素。") from error
        if pixels <= 0:
            return 0
        return min(pixels, 7680)

    @staticmethod
    def _normalize_max_recent_apps(value: object) -> int:
        try:
            count = int(value)
        except (TypeError, ValueError):
            return DEFAULT_MAX_RECENT_APPS

        return max(1, min(count, 50))

    def _open_application(self, path: Path) -> None:
        path = path.resolve()
        if not path.exists():
            messagebox.showerror("无法打开", "文件不存在。")
            self._remove_recent_application(path, save=True)
            return

        os.startfile(path)  # type: ignore[attr-defined]
        if path.is_file():
            self._record_recent_application(path)

    def _record_recent_application(self, path: Path) -> None:
        path = path.resolve()
        self.recent_apps = [item for item in self.recent_apps if item != path]
        self.recent_apps.insert(0, path)
        self.recent_apps = self.recent_apps[: self.max_recent_apps]
        try:
            self._save_settings()
        except OSError:
            pass
        self._render_recent_apps()

    def _remove_recent_application(self, path: Path, *, save: bool) -> None:
        path = path.resolve()
        self.recent_apps = [item for item in self.recent_apps if item != path]
        if save:
            try:
                self._save_settings()
            except OSError:
                pass
        self._render_recent_apps()

    def _render_recent_apps(self) -> None:
        self.recent_apps_list.delete(0, END)
        existing_apps = [path for path in self.recent_apps if path.exists() and path.is_file()]
        if len(existing_apps) != len(self.recent_apps):
            self.recent_apps = existing_apps
            try:
                self._save_settings()
            except OSError:
                pass

        for path in self.recent_apps:
            self.recent_apps_list.insert(END, path.name)

    def _selected_recent_application(self) -> Path | None:
        selection = self.recent_apps_list.curselection()
        if not selection:
            return None
        index = selection[0]
        if index >= len(self.recent_apps):
            return None
        return self.recent_apps[index]

    def _open_recent_application(self, _event=None) -> None:  # type: ignore[no-untyped-def]
        path = self._selected_recent_application()
        if path is None:
            return
        self._open_application(path)

    def _open_selected_recent_application(self) -> None:
        path = self._selected_recent_application()
        if path is None:
            return
        self._open_application(path)

    def _remove_selected_recent_application(self) -> None:
        path = self._selected_recent_application()
        if path is None:
            return
        self._remove_recent_application(path, save=True)

    def _show_recent_apps_menu(self, event) -> None:  # type: ignore[no-untyped-def]
        index = self.recent_apps_list.nearest(event.y)
        if index < 0 or index >= len(self.recent_apps):
            return
        self.recent_apps_list.selection_clear(0, END)
        self.recent_apps_list.selection_set(index)
        self.recent_apps_list.activate(index)
        self.recent_apps_menu.tk_popup(event.x_root, event.y_root)

    def _push_undo(self, label: str, undo: Callable[[], None]) -> None:
        self.undo_stack.append(UndoAction(label=label, undo=undo))
        del self.undo_stack[: max(0, len(self.undo_stack) - self.max_undo_steps)]

    def add_current_folder_to_favorites(self) -> None:
        self._add_favorite_folder(self.managed_folder.resolve())

    def add_selected_to_favorites(self) -> None:
        path = self.selected_path()
        if path is None:
            return
        path = path.resolve()
        if path.is_dir():
            self._add_favorite_folder(path)
            return
        if path.is_file():
            self._add_favorite_file(path)
            return
        messagebox.showinfo("无法收藏", "只能收藏文件夹或可打开的文件。")

    def _add_favorite_folder(self, folder: Path) -> None:
        folder = folder.resolve()
        if folder in self.favorite_folders:
            messagebox.showinfo("已收藏", "该目录已在收藏夹中。")
            return
        self.favorite_folders.append(folder)
        try:
            self._save_settings()
        except OSError as error:
            self.favorite_folders.remove(folder)
            messagebox.showerror("收藏失败", str(error))
            return
        messagebox.showinfo("收藏成功", f"已收藏目录：\n{folder}")

    def _add_favorite_file(self, file_path: Path) -> None:
        file_path = file_path.resolve()
        if file_path in self.favorite_files:
            messagebox.showinfo("已收藏", "该文件已在收藏夹中。")
            return
        self.favorite_files.append(file_path)
        try:
            self._save_settings()
        except OSError as error:
            self.favorite_files.remove(file_path)
            messagebox.showerror("收藏失败", str(error))
            return
        messagebox.showinfo("收藏成功", f"已收藏文件：\n{file_path}")

    def show_favorites_menu(self) -> None:
        if self.favorites_popup is not None and self.favorites_popup.winfo_exists():
            self.favorites_popup.destroy()

        self._cleanup_favorites()

        popup = Toplevel(self.root)
        popup.title("收藏夹")
        popup.transient(self.root)
        popup.resizable(True, True)
        popup.geometry("760x380")
        popup.minsize(520, 260)
        self.favorites_popup = popup

        outer = ttk.Frame(popup, padding=8)
        outer.pack(fill=BOTH, expand=True)
        outer.rowconfigure(0, weight=1)
        outer.columnconfigure(0, weight=1)

        paned = ttk.Panedwindow(outer, orient=HORIZONTAL)
        paned.grid(row=0, column=0, sticky="nsew")

        folders_frame = ttk.LabelFrame(paned, text="目录", padding=4)
        files_frame = ttk.LabelFrame(paned, text="文件", padding=4)
        paned.add(folders_frame, weight=1)
        paned.add(files_frame, weight=1)

        folders_list = Listbox(folders_frame, activestyle="none", exportselection=False)
        folders_scroll = ttk.Scrollbar(folders_frame, orient=VERTICAL, command=folders_list.yview)
        folders_list.configure(yscrollcommand=folders_scroll.set)
        folders_list.pack(side=LEFT, fill=BOTH, expand=True)
        folders_scroll.pack(side=RIGHT, fill="y")

        files_list = Listbox(files_frame, activestyle="none", exportselection=False)
        files_scroll = ttk.Scrollbar(files_frame, orient=VERTICAL, command=files_list.yview)
        files_list.configure(yscrollcommand=files_scroll.set)
        files_list.pack(side=LEFT, fill=BOTH, expand=True)
        files_scroll.pack(side=RIGHT, fill="y")

        for folder in self.favorite_folders:
            folders_list.insert(END, str(folder))
        for file_path in self.favorite_files:
            files_list.insert(END, str(file_path))

        if not self.favorite_folders:
            folders_list.insert(END, "（暂无收藏目录）")
            folders_list.configure(state="disabled")
        if not self.favorite_files:
            files_list.insert(END, "（暂无收藏文件）")
            files_list.configure(state="disabled")

        self._bind_favorite_listbox(
            folders_list,
            self.favorite_folders,
            kind="folder",
        )
        self._bind_favorite_listbox(
            files_list,
            self.favorite_files,
            kind="file",
        )

        actions = ttk.Frame(outer)
        actions.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(
            actions,
            text="清空目录",
            command=lambda: self._clear_favorite_folders_from_popup(popup),
        ).pack(side=RIGHT, padx=(8, 0))
        ttk.Button(
            actions,
            text="清空文件",
            command=lambda: self._clear_favorite_files_from_popup(popup),
        ).pack(side=RIGHT, padx=(8, 0))
        ttk.Button(actions, text="关闭", command=popup.destroy).pack(side=RIGHT)

    def _bind_favorite_listbox(
        self,
        listbox: Listbox,
        items: list[Path],
        *,
        kind: str,
    ) -> None:
        menu = Menu(self.root, tearoff=False)
        menu.add_command(
            label="打开",
            command=lambda: self._open_favorite_list_selection(listbox, items, kind),
        )
        menu.add_command(
            label="删除收藏",
            command=lambda: self._remove_favorite_list_selection(listbox, items, kind),
        )

        def on_double_click(_event: object) -> None:
            self._open_favorite_list_selection(listbox, items, kind)

        def on_right_click(event: object) -> None:
            index = listbox.nearest(event.y)  # type: ignore[union-attr]
            if index < 0 or index >= len(items):
                return
            listbox.selection_clear(0, END)
            listbox.selection_set(index)
            listbox.activate(index)
            menu.tk_popup(event.x_root, event.y)  # type: ignore[union-attr]

        listbox.bind("<Double-1>", on_double_click)
        listbox.bind("<Button-3>", on_right_click)

    def _favorite_list_selection(self, listbox: Listbox, items: list[Path]) -> Path | None:
        selection = listbox.curselection()
        if not selection:
            return None
        index = selection[0]
        if index >= len(items):
            return None
        return items[index]

    def _open_favorite_list_selection(
        self, listbox: Listbox, items: list[Path], kind: str
    ) -> None:
        path = self._favorite_list_selection(listbox, items)
        if path is None:
            return
        if self.favorites_popup is not None and self.favorites_popup.winfo_exists():
            self.favorites_popup.destroy()
            self.favorites_popup = None
        if kind == "folder":
            self.go_to_folder(path)
            return
        self._open_application(path)

    def _remove_favorite_list_selection(
        self, listbox: Listbox, items: list[Path], kind: str
    ) -> None:
        path = self._favorite_list_selection(listbox, items)
        if path is None:
            return
        label = "目录" if kind == "folder" else "文件"
        if not messagebox.askyesno("删除收藏", f"确定删除这条收藏{label}吗？\n{path}"):
            return
        if kind == "folder":
            if path in self.favorite_folders:
                self.favorite_folders.remove(path)
        elif path in self.favorite_files:
            self.favorite_files.remove(path)
        try:
            self._save_settings()
        except OSError as error:
            messagebox.showerror("保存失败", str(error))
            return
        if self.favorites_popup is not None and self.favorites_popup.winfo_exists():
            self.show_favorites_menu()

    def _cleanup_favorites(self) -> None:
        existing_folders = [
            path for path in self.favorite_folders if path.exists() and path.is_dir()
        ]
        existing_files = [
            path for path in self.favorite_files if path.exists() and path.is_file()
        ]
        if (
            len(existing_folders) == len(self.favorite_folders)
            and len(existing_files) == len(self.favorite_files)
        ):
            return
        self.favorite_folders = existing_folders
        self.favorite_files = existing_files
        try:
            self._save_settings()
        except OSError:
            pass

    def _clear_favorite_folders_from_popup(self, popup: Toplevel) -> None:
        if not self.favorite_folders:
            return
        if not messagebox.askyesno("清空收藏", "确定清空全部收藏目录吗？"):
            return
        self.favorite_folders.clear()
        try:
            self._save_settings()
        except OSError as error:
            messagebox.showerror("保存失败", str(error))
            return
        popup.destroy()
        self.favorites_popup = None

    def _clear_favorite_files_from_popup(self, popup: Toplevel) -> None:
        if not self.favorite_files:
            return
        if not messagebox.askyesno("清空收藏", "确定清空全部收藏文件吗？"):
            return
        self.favorite_files.clear()
        try:
            self._save_settings()
        except OSError as error:
            messagebox.showerror("保存失败", str(error))
            return
        popup.destroy()
        self.favorites_popup = None

    def undo_last_action(self) -> None:
        if not self.undo_stack:
            messagebox.showinfo("无法撤销", "没有可以撤销的操作。")
            return

        action = self.undo_stack.pop()
        try:
            action.undo()
        except OSError as error:
            messagebox.showerror("撤销失败", f"{action.label} 无法撤销：{error}")
            return

        self.refresh()
        messagebox.showinfo("撤销完成", f"已撤销：{action.label}")

    def _offer_screenshot_ai(self, image_path: Path) -> None:
        if not self.ai_enabled:
            return
        if not self._ai_settings_configured():
            messagebox.showinfo(
                "截图 AI 未配置",
                "已启用 AI，但尚未填写 API 地址、API Key 或模型/接入点 ID。\n"
                "请打开「设置」完成配置。",
            )
            return
        if not ai_provider_supports_vision(self.ai_api_provider, api_base_url=self.ai_api_base_url):
            messagebox.showinfo("截图 AI", VISION_UNSUPPORTED_MESSAGE)
            return
        if self.screenshot_ai_ask and not messagebox.askyesno("截图 AI", "是否使用 AI 识图翻译？"):
            return
        self._run_screenshot_ai(image_path)

    def _run_screenshot_ai(self, image_path: Path) -> None:
        progress = Toplevel(self.root)
        progress.title("AI 识图")
        progress.transient(self.root)
        progress.resizable(False, False)
        ttk.Label(progress, text="正在识别，请稍候…", padding=12).pack()
        progress.update_idletasks()

        def worker() -> None:
            error: Exception | None = None
            result = ""
            try:
                result = call_vision_api(
                    image_path=image_path,
                    api_base_url=self.ai_api_base_url,
                    api_key=self.ai_api_key,
                    model=self.ai_model,
                    prompt=self.ai_prompt,
                    provider_id=self.ai_api_provider,
                )
            except Exception as exc:
                error = exc

            self.root.after(0, lambda: self._finish_screenshot_ai(progress, image_path, result, error))

        threading.Thread(target=worker, daemon=True).start()

    def _finish_screenshot_ai(
        self,
        progress: Toplevel,
        image_path: Path,
        result: str,
        error: Exception | None,
    ) -> None:
        if progress.winfo_exists():
            progress.destroy()

        if error is not None:
            messagebox.showerror("AI 识图失败", str(error))
            return

        self._delete_screenshot_image(image_path)
        self._show_ai_result(image_path, result)

    def _delete_screenshot_image(self, image_path: Path) -> None:
        if not image_path.is_file():
            return
        try:
            image_path.unlink()
        except OSError as error:
            messagebox.showwarning("删除截图失败", f"识图已完成，但无法删除原图：\n{error}")
            return
        self.refresh()

    def _show_ai_result(self, image_path: Path, result: str) -> None:
        from .ai_result_view import AiResultDialog

        AiResultDialog(
            self.root,
            image_path=image_path,
            result=result,
            on_saved=self.refresh,
        )

    def open_help(self) -> None:
        dialog = Toplevel(self.root)
        dialog.title("帮助")
        dialog.transient(self.root)
        dialog.geometry("580x520")
        dialog.minsize(440, 360)
        dialog.columnconfigure(0, weight=1)
        dialog.rowconfigure(0, weight=1)

        content = ttk.Frame(dialog, padding=8)
        content.grid(row=0, column=0, sticky="nsew")
        content.columnconfigure(0, weight=1)
        content.rowconfigure(0, weight=1)

        text_widget = Text(content, wrap="word", padx=4, pady=4)
        scrollbar = ttk.Scrollbar(content, orient=VERTICAL, command=text_widget.yview)
        text_widget.configure(yscrollcommand=scrollbar.set)
        text_widget.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")

        text_widget.insert(
            "1.0",
            build_help_text(
                screenshot_hotkey=self.screenshot_hotkey,
                screenshot_hotkey_global=self.screenshot_hotkey_global,
                record_hotkey=self.record_hotkey,
                record_hotkey_global=self.record_hotkey_global,
                screenshot_fullscreen=self.screenshot_fullscreen,
                screenshot_hide_window=self.screenshot_hide_window,
                record_hide_window=self.record_hide_window,
            ),
        )
        text_widget.configure(state="disabled")

        actions = ttk.Frame(dialog, padding=(0, 8, 8, 8))
        actions.grid(row=1, column=0, sticky="e")
        ttk.Button(actions, text="关闭", command=dialog.destroy).pack(side=RIGHT)

    def open_settings(self) -> None:
        dialog = Toplevel(self.root)
        dialog.title("设置")
        dialog.transient(self.root)
        dialog.resizable(False, False)

        notebook = ttk.Notebook(dialog, padding=8)
        notebook.pack(fill="both", expand=True)

        general_tab = ttk.Frame(notebook, padding=12)
        capture_tab = ttk.Frame(notebook, padding=12)
        ai_tab = ttk.Frame(notebook, padding=12)
        notebook.add(general_tab, text="常规")
        notebook.add(capture_tab, text="截图 / 录屏")
        notebook.add(ai_tab, text="截图 AI")

        undo_var = IntVar(value=self.max_undo_steps)
        recent_var = IntVar(value=self.max_recent_apps)
        hotkey_var = StringVar(value=self.screenshot_hotkey)
        screenshot_global_var = BooleanVar(value=self.screenshot_hotkey_global)
        screenshot_fullscreen_var = BooleanVar(value=self.screenshot_fullscreen)
        screenshot_hide_window_var = BooleanVar(value=self.screenshot_hide_window)
        record_hotkey_var = StringVar(value=self.record_hotkey)
        record_global_var = BooleanVar(value=self.record_hotkey_global)
        record_fps_var = IntVar(value=self.record_fps)
        record_width_var = StringVar(
            value=self._format_record_output_dimension(self.record_output_width)
        )
        record_height_var = StringVar(
            value=self._format_record_output_dimension(self.record_output_height)
        )
        record_show_indicator_var = BooleanVar(value=self.record_show_indicator)
        record_hide_window_var = BooleanVar(value=self.record_hide_window)
        ai_enabled_var = BooleanVar(value=self.ai_enabled)
        screenshot_ai_ask_var = BooleanVar(value=self.screenshot_ai_ask)
        ai_provider_var = StringVar(value=ai_provider_label(self.ai_api_provider))
        ai_base_url_var = StringVar(value=self.ai_api_base_url)
        ai_key_var = StringVar(value=self.ai_api_key)
        ai_model_var = StringVar(value=self.ai_model)
        ai_prompt_var = StringVar(value=self.ai_prompt)

        ttk.Label(general_tab, text="最多可撤销步数（1-100）：").grid(row=0, column=0, sticky="w")
        ttk.Spinbox(general_tab, from_=1, to=100, width=8, textvariable=undo_var).grid(
            row=0, column=1, sticky="w", padx=(8, 0)
        )

        ttk.Label(general_tab, text="最近打开最多记录数（1-50）：").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Spinbox(general_tab, from_=1, to=50, width=8, textvariable=recent_var).grid(
            row=1, column=1, sticky="w", padx=(8, 0), pady=(8, 0)
        )

        screenshot_group = ttk.LabelFrame(capture_tab, text="截图", padding=8)
        screenshot_group.grid(row=0, column=0, sticky="ew")
        screenshot_group.columnconfigure(1, weight=1)

        ttk.Label(screenshot_group, text="快捷键：").grid(row=0, column=0, sticky="w")
        ttk.Entry(screenshot_group, textvariable=hotkey_var, width=32).grid(
            row=0, column=1, sticky="w", padx=(8, 0)
        )
        ttk.Checkbutton(
            screenshot_group,
            text="注册为全局快捷键",
            variable=screenshot_global_var,
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 0))
        ttk.Checkbutton(
            screenshot_group,
            text="默认全屏截图（跳过区域选择）",
            variable=screenshot_fullscreen_var,
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(4, 0))
        ttk.Checkbutton(
            screenshot_group,
            text="截图时隐藏本程序窗口（结束后自动恢复）",
            variable=screenshot_hide_window_var,
        ).grid(row=3, column=0, columnspan=2, sticky="w", pady=(4, 0))
        record_group = ttk.LabelFrame(capture_tab, text="全屏录屏", padding=8)
        record_group.grid(row=1, column=0, sticky="ew", pady=(12, 0))
        record_group.columnconfigure(1, weight=1)

        ttk.Label(record_group, text="快捷键：").grid(row=0, column=0, sticky="w")
        ttk.Entry(record_group, textvariable=record_hotkey_var, width=32).grid(
            row=0, column=1, sticky="w", padx=(8, 0)
        )
        ttk.Checkbutton(
            record_group,
            text="注册为全局快捷键",
            variable=record_global_var,
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 0))
        ttk.Checkbutton(
            record_group,
            text="录屏时显示右上角停止按钮",
            variable=record_show_indicator_var,
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(4, 0))
        ttk.Checkbutton(
            record_group,
            text="录屏时隐藏本程序窗口（结束后自动恢复）",
            variable=record_hide_window_var,
        ).grid(row=3, column=0, columnspan=2, sticky="w", pady=(4, 0))

        ttk.Label(record_group, text="帧率 (FPS)：").grid(row=4, column=0, sticky="w", pady=(8, 0))
        Spinbox(
            record_group,
            from_=5,
            to=60,
            width=8,
            textvariable=record_fps_var,
        ).grid(row=4, column=1, sticky="w", padx=(8, 0), pady=(8, 0))

        ttk.Label(record_group, text="输出宽度：").grid(row=5, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(record_group, textvariable=record_width_var, width=12).grid(
            row=5, column=1, sticky="w", padx=(8, 0), pady=(8, 0)
        )

        ttk.Label(record_group, text="输出高度：").grid(row=6, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(record_group, textvariable=record_height_var, width=12).grid(
            row=6, column=1, sticky="w", padx=(8, 0), pady=(8, 0)
        )

        ttk.Label(
            record_group,
            text="宽高填「自动」表示不限制该项；两项均为自动时使用屏幕原始分辨率。",
            wraplength=420,
        ).grid(row=7, column=0, columnspan=2, sticky="w", pady=(4, 0))

        ttk.Label(
            record_group,
            text="默认不显示停止按钮，仅通过录屏快捷键开始/结束。",
            wraplength=420,
        ).grid(row=8, column=0, columnspan=2, sticky="w", pady=(8, 0))

        ttk.Label(
            capture_tab,
            text="未勾选全局时，录屏快捷键仅在本程序窗口聚焦时生效。",
            wraplength=420,
        ).grid(row=2, column=0, sticky="w", pady=(12, 0))

        ttk.Checkbutton(
            ai_tab,
            text="是否启用 AI",
            variable=ai_enabled_var,
        ).grid(row=0, column=0, columnspan=2, sticky="w")

        ttk.Checkbutton(
            ai_tab,
            text="截图后是否询问",
            variable=screenshot_ai_ask_var,
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 0))

        ttk.Label(ai_tab, text="API 平台：").grid(row=2, column=0, sticky="w", pady=(8, 0))
        ai_provider_box = ttk.Combobox(
            ai_tab,
            textvariable=ai_provider_var,
            values=[preset["label"] for preset in AI_PROVIDER_PRESETS.values()],
            state="readonly",
            width=20,
        )
        ai_provider_box.grid(row=2, column=1, sticky="w", padx=(8, 0), pady=(8, 0))

        def apply_ai_provider_preset(_event: object | None = None) -> None:
            provider_id = ai_provider_id_from_label(ai_provider_var.get())
            preset = ai_provider_preset(provider_id)
            ai_base_url_var.set(preset["api_base_url"])
            ai_model_var.set(preset["model"])

        ai_provider_box.bind("<<ComboboxSelected>>", apply_ai_provider_preset)

        ttk.Label(ai_tab, text="API 地址：").grid(row=3, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(ai_tab, textvariable=ai_base_url_var, width=48).grid(
            row=3, column=1, sticky="w", padx=(8, 0), pady=(8, 0)
        )

        ttk.Label(ai_tab, text="API Key：").grid(row=4, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(ai_tab, textvariable=ai_key_var, width=48, show="*").grid(
            row=4, column=1, sticky="w", padx=(8, 0), pady=(8, 0)
        )

        ttk.Label(ai_tab, text="模型/接入点 ID：").grid(row=5, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(ai_tab, textvariable=ai_model_var, width=48).grid(
            row=5, column=1, sticky="w", padx=(8, 0), pady=(8, 0)
        )

        ttk.Label(ai_tab, text="识图提示词：").grid(row=6, column=0, sticky="nw", pady=(8, 0))
        ttk.Entry(ai_tab, textvariable=ai_prompt_var, width=48).grid(
            row=6, column=1, sticky="w", padx=(8, 0), pady=(8, 0)
        )

        ttk.Label(
            ai_tab,
            text="截图识图请选 Poe（支持传图）。DeepSeek 官方 API 仅支持文本，不能用于识图。"
            "切换平台会填入默认地址与模型；Key 请在对应平台官网申请。",
            wraplength=420,
        ).grid(row=7, column=0, columnspan=2, sticky="w", pady=(4, 0))

        def save_settings() -> None:
            self.max_undo_steps = self._normalize_max_undo_steps(undo_var.get())
            self.max_recent_apps = self._normalize_max_recent_apps(recent_var.get())
            self.screenshot_hotkey_global = bool(screenshot_global_var.get())
            self.record_hotkey_global = bool(record_global_var.get())
            self.record_show_indicator = bool(record_show_indicator_var.get())
            self.screenshot_hide_window = bool(screenshot_hide_window_var.get())
            self.record_hide_window = bool(record_hide_window_var.get())
            self.record_fps = self._normalize_record_fps(record_fps_var.get())
            try:
                self.record_output_width = self._parse_record_output_dimension(
                    record_width_var.get()
                )
                self.record_output_height = self._parse_record_output_dimension(
                    record_height_var.get()
                )
            except ValueError as error:
                messagebox.showerror("录屏设置无效", str(error), parent=dialog)
                return
            self.screenshot_fullscreen = bool(screenshot_fullscreen_var.get())
            try:
                self.screenshot_hotkey = validate_hotkey(
                    hotkey_var.get(),
                    require_keyboard=self.screenshot_hotkey_global,
                )
                self.record_hotkey = validate_hotkey(
                    record_hotkey_var.get(),
                    require_keyboard=self.record_hotkey_global,
                )
            except ValueError as error:
                messagebox.showerror("快捷键无效", str(error), parent=dialog)
                return

            self.ai_enabled = bool(ai_enabled_var.get())
            self.screenshot_ai_ask = bool(screenshot_ai_ask_var.get())
            self.ai_api_provider = ai_provider_id_from_label(ai_provider_var.get())
            self.ai_api_base_url = ai_base_url_var.get().strip() or ai_provider_preset(
                self.ai_api_provider
            )["api_base_url"]
            self.ai_api_key = ai_key_var.get().strip()
            self.ai_model = ai_model_var.get().strip() or ai_provider_preset(self.ai_api_provider)[
                "model"
            ]
            self.ai_prompt = ai_prompt_var.get().strip() or DEFAULT_AI_PROMPT

            del self.undo_stack[: max(0, len(self.undo_stack) - self.max_undo_steps)]
            self.recent_apps = self.recent_apps[: self.max_recent_apps]
            try:
                self._save_settings()
            except OSError as error:
                messagebox.showerror("保存设置失败", str(error), parent=dialog)
                return

            try:
                self._register_capture_hotkeys()
            except ValueError as error:
                messagebox.showerror("快捷键注册失败", str(error), parent=dialog)
                return

            self._render_recent_apps()
            dialog.destroy()
            if not self.ai_enabled:
                ai_status = "未启用"
            elif self.screenshot_ai_ask:
                ai_status = "已启用，截图后询问"
            else:
                ai_status = "已启用，截图后自动识图"
            screenshot_scope = "全局" if self.screenshot_hotkey_global else "仅窗口内"
            record_scope = "全局" if self.record_hotkey_global else "仅窗口内"
            screenshot_mode = "全屏" if self.screenshot_fullscreen else "区域"
            screenshot_hide = "隐藏窗口" if self.screenshot_hide_window else "不隐藏窗口"
            record_hide = "隐藏窗口" if self.record_hide_window else "不隐藏窗口"
            if self.record_output_width <= 0 and self.record_output_height <= 0:
                record_resolution = "宽自动 × 高自动"
            elif self.record_output_width > 0 and self.record_output_height > 0:
                record_resolution = f"{self.record_output_width}×{self.record_output_height} px"
            elif self.record_output_width > 0:
                record_resolution = f"宽 {self.record_output_width} px，高自动"
            else:
                record_resolution = f"高 {self.record_output_height} px，宽自动"
            record_indicator = "显示停止按钮" if self.record_show_indicator else "仅快捷键"
            messagebox.showinfo(
                "设置已保存",
                f"最多可撤销步数：{self.max_undo_steps}\n"
                f"最近打开最多记录数：{self.max_recent_apps}\n"
                f"截图：{self.screenshot_hotkey}（{screenshot_scope}，{screenshot_mode}，{screenshot_hide}）\n"
                f"全屏录屏：{self.record_hotkey}（{record_scope}，{record_indicator}，{record_hide}，"
                f"{self.record_fps} FPS，{record_resolution}）\n"
                f"截图 AI：{ai_status}",
            )

        actions = ttk.Frame(dialog, padding=(0, 8, 8, 8))
        actions.pack(fill="x")
        ttk.Button(actions, text="取消", command=dialog.destroy).pack(side=RIGHT)
        ttk.Button(actions, text="保存", command=save_settings).pack(side=RIGHT, padx=(0, 8))

    def rename_selected(self) -> None:
        path = self.selected_path()
        if path is None:
            return

        new_name = simpledialog.askstring("重命名", "请输入新名称：", initialvalue=path.name)
        if not new_name or new_name == path.name:
            return

        destination = path.with_name(new_name)
        if destination.exists():
            messagebox.showerror("重命名失败", "已存在同名文件或文件夹。")
            return

        original_path = path
        path.rename(destination)
        self._push_undo("重命名", lambda source=destination, target=original_path: self._restore_path(source, target))
        self.refresh()

    def create_folder(self) -> None:
        folder_name = simpledialog.askstring("新建文件夹", "请输入文件夹名称：")
        if not folder_name:
            return

        destination = self.managed_folder / folder_name
        if destination.exists():
            messagebox.showerror("新建失败", "已存在同名文件或文件夹。")
            return

        destination.mkdir()
        self._push_undo("新建文件夹", lambda target=destination: self._remove_created_folder(target))
        self.refresh()

    def trash_selected(self) -> None:
        paths = self.selected_paths()
        if not paths:
            messagebox.showinfo("未选择", "请先选择一个或多个文件/文件夹。")
            return

        running_paths = [path for path in paths if is_running_app_path(path)]
        if running_paths:
            names = "、".join(path.name for path in running_paths[:3])
            suffix = " 等" if len(running_paths) > 3 else ""
            messagebox.showinfo("无法移动", f"正在运行的程序不能移到回收区：{names}{suffix}")
            return

        if len(paths) == 1:
            confirm_message = f"确定把“{paths[0].name}”移到回收区（myfile/trash）吗？"
        else:
            confirm_message = f"确定把选中的 {len(paths)} 项移到回收区（myfile/trash）吗？"
        if not messagebox.askyesno("移到回收区", confirm_message):
            return

        trash_folder = get_trash_folder()
        moved: list[tuple[Path, Path]] = []
        for path in paths:
            destination = unique_destination(trash_folder / path.name)
            shutil.move(str(path), str(destination))
            moved.append((destination, path))

        undo_label = "移到回收区" if len(moved) == 1 else f"移到回收区（{len(moved)} 项）"

        def undo_moves(moves: list[tuple[Path, Path]] = moved) -> None:
            for source, target in reversed(moves):
                self._restore_path(source, target)

        self._push_undo(undo_label, undo_moves)
        self.refresh()

    def _restore_path(self, source: Path, target: Path) -> None:
        if not source.exists():
            raise FileNotFoundError(f"找不到 {source}")

        destination = target if not target.exists() else unique_destination(target)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(destination))

    def _remove_created_folder(self, target: Path) -> None:
        if not target.exists():
            return
        if not target.is_dir():
            raise OSError(f"{target} 不是文件夹")

        target.rmdir()

    @staticmethod
    def _format_size(size: int) -> str:
        units = ("B", "KB", "MB", "GB", "TB")
        value = float(size)
        for unit in units:
            if value < 1024 or unit == units[-1]:
                return f"{value:.1f} {unit}" if unit != "B" else f"{size} B"
            value /= 1024
        return f"{size} B"


def main() -> None:
    from .screen_capture import enable_windows_dpi_awareness

    enable_windows_dpi_awareness()
    root = Tk()
    FileOrganizerApp(root)
    root.mainloop()
