from __future__ import annotations

import sys
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PIL.Image import Image


def enable_windows_dpi_awareness() -> None:
    """Match Tk selection coordinates with ImageGrab physical pixels on Windows."""
    if sys.platform != "win32":
        return

    import ctypes

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    except (AttributeError, OSError):
        pass

    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except (AttributeError, OSError):
        pass


def get_virtual_screen_bounds() -> tuple[int, int, int, int]:
    """Return (left, top, width, height) for the virtual desktop in physical pixels."""
    if sys.platform != "win32":
        return 0, 0, 0, 0

    import ctypes

    user32 = ctypes.windll.user32
    left = int(user32.GetSystemMetrics(76))
    top = int(user32.GetSystemMetrics(77))
    width = int(user32.GetSystemMetrics(78))
    height = int(user32.GetSystemMetrics(79))
    return left, top, width, height


def grab_screen_region(left: int, top: int, right: int, bottom: int) -> Image:
    from PIL import ImageGrab

    left = int(left)
    top = int(top)
    right = int(right)
    bottom = int(bottom)
    if right <= left or bottom <= top:
        raise ValueError("选区无效。")

    return ImageGrab.grab(bbox=(left, top, right, bottom), all_screens=True)


def hide_toplevel_window(window) -> None:  # type: ignore[no-untyped-def]
    """Hide a Tk window so it is excluded from screen capture on Windows."""
    window.withdraw()
    window.update_idletasks()
    if sys.platform != "win32":
        return

    import ctypes

    ctypes.windll.user32.ShowWindow(int(window.winfo_id()), 0)


def show_toplevel_window(window) -> None:  # type: ignore[no-untyped-def]
    window.deiconify()
    if sys.platform != "win32":
        return

    import ctypes

    ctypes.windll.user32.ShowWindow(int(window.winfo_id()), 5)
    window.update_idletasks()


def wait_for_capture_compositor(*, delay_ms: int) -> None:
    if delay_ms <= 0:
        return
    time.sleep(delay_ms / 1000.0)
