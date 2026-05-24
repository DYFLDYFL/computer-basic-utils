from __future__ import annotations

import threading
import time
from pathlib import Path


class RegionScreenRecorder:
    def __init__(
        self,
        bbox: tuple[int, int, int, int],
        output_path: Path,
        *,
        fps: int = 20,
        output_size: tuple[int, int] | None = None,
    ) -> None:
        self.bbox = bbox
        self.output_path = output_path
        self.fps = fps
        self.output_size = output_size
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._error: Exception | None = None

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.is_running:
            return
        self._stop_event.clear()
        self._error = None
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=30)
        self._thread = None

    def error(self) -> Exception | None:
        return self._error

    def _run(self) -> None:
        try:
            import mss
            import numpy as np
            import imageio.v2 as imageio
        except ImportError as error:
            message = (
                "录屏需要 mss 与 imageio。\n"
                "开发运行：在项目目录执行 .\\run.ps1（会自动安装依赖）。\n"
                "或手动：.venv\\Scripts\\pip install -r requirements.txt\n"
                "打包版：重新执行 .\\build_exe.ps1 后再运行 FolderOrganizer.exe"
            )
            self._error = ImportError(f"{message}\n详情：{error}")
            self._error.__cause__ = error
            return

        left, top, right, bottom = self.bbox
        width = right - left
        height = bottom - top
        if width < 2 or height < 2:
            self._error = ValueError("录屏区域太小。")
            return

        monitor = {"left": left, "top": top, "width": width, "height": height}
        target_width, target_height = self._resolve_output_size(width, height)
        interval = 1.0 / self.fps
        self.output_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            writer = imageio.get_writer(
                str(self.output_path),
                fps=self.fps,
                macro_block_size=1,
            )
        except Exception as error:
            self._error = RuntimeError(f"无法创建视频文件：{error}")
            self._error.__cause__ = error
            return

        resize_frames = (target_width, target_height) != (width, height)

        try:
            with mss.mss() as capture:
                while not self._stop_event.is_set():
                    started = time.perf_counter()
                    frame = np.array(capture.grab(monitor))
                    rgb = frame[:, :, [2, 1, 0]]
                    if resize_frames:
                        rgb = self._resize_frame(rgb, target_width, target_height)
                    writer.append_data(rgb)
                    elapsed = time.perf_counter() - started
                    sleep_seconds = interval - elapsed
                    if sleep_seconds > 0:
                        time.sleep(sleep_seconds)
        except Exception as error:
            self._error = error
        finally:
            writer.close()

    def _resolve_output_size(self, source_width: int, source_height: int) -> tuple[int, int]:
        if self.output_size is None:
            return source_width, source_height
        width, height = self.output_size
        return max(2, width), max(2, height)

    @staticmethod
    def _resize_frame(frame, target_width: int, target_height: int):
        from PIL import Image

        image = Image.fromarray(frame)
        if image.size != (target_width, target_height):
            image = image.resize(
                (target_width, target_height),
                Image.Resampling.LANCZOS,
            )
        import numpy as np

        return np.asarray(image)
