import sys

from file_organizer.screen_capture import enable_windows_dpi_awareness

enable_windows_dpi_awareness()


def _preload_recording_dependencies() -> None:
    if not getattr(sys, "frozen", False):
        return
    import imageio.v2  # noqa: F401
    import imageio_ffmpeg  # noqa: F401
    import cv2  # noqa: F401
    import mss  # noqa: F401
    import pyzbar.pyzbar  # noqa: F401
    import numpy  # noqa: F401


_preload_recording_dependencies()

from file_organizer.app import main


if __name__ == "__main__":
    main()
