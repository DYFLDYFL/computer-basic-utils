from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PIL.Image import Image

QR_DECODE_DEPENDENCY_HINT = "pip install opencv-python-headless"


def decode_qr_codes(image: Image) -> list[str]:
    """Decode QR codes from a screen-capture image. Returns unique non-empty texts."""
    try:
        import cv2
        import numpy as np
    except ImportError as error:
        raise ImportError(
            f"缺少二维码识别库。请先运行：{QR_DECODE_DEPENDENCY_HINT}"
        ) from error

    rgb = np.asarray(image.convert("RGB"))
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    detector = cv2.QRCodeDetector()
    texts: list[str] = []

    try:
        ok, decoded, _points, _ = detector.detectAndDecodeMulti(bgr)
        if ok and decoded is not None:
            if isinstance(decoded, str):
                decoded = (decoded,)
            for item in decoded:
                if item:
                    texts.append(item)
    except Exception:
        pass

    if not texts:
        data, _points, _ = detector.detectAndDecode(bgr)
        if data:
            texts.append(data)

    seen: set[str] = set()
    unique: list[str] = []
    for text in texts:
        if text not in seen:
            seen.add(text)
            unique.append(text)
    return unique
