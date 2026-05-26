from __future__ import annotations

from typing import TYPE_CHECKING, Iterator

if TYPE_CHECKING:
    from PIL.Image import Image

import numpy as np

QR_DECODE_DEPENDENCY_HINT = "pip install opencv-python-headless pyzbar"

# Upscale small screen captures until the longer side reaches this (capped by MAX_SCALE).
_MIN_DECODE_SIDE = 1200
_MAX_SCALE = 12.0
_MAX_UPSCALED_SIDE = 2400
_QUIET_ZONE_RATIO = 0.12


def decode_qr_codes(image: Image) -> list[str]:
    """Decode QR codes from a screen-capture image. Returns unique non-empty texts."""
    try:
        import cv2
    except ImportError as error:
        raise ImportError(
            f"缺少二维码识别库。请先运行：{QR_DECODE_DEPENDENCY_HINT}"
        ) from error

    rgb = np.asarray(image.convert("RGB"))
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    detector = cv2.QRCodeDetector()

    found: list[str] = []
    _extend_unique(found, _decode_with_opencv(detector, bgr))
    if found:
        return found

    _extend_unique(found, _decode_with_pyzbar(bgr))
    if found:
        return found

    padded = _add_quiet_zone(bgr, _QUIET_ZONE_RATIO)
    _extend_unique(found, _decode_with_opencv(detector, padded))
    if found:
        return found

    _extend_unique(found, _decode_with_pyzbar(padded))
    if found:
        return found

    for scaled in _scaled_bgr_frames(bgr):
        _extend_unique(found, _decode_with_opencv(detector, scaled))
        if found:
            return found
        for variant in _bgr_variants(scaled):
            _extend_unique(found, _decode_with_opencv(detector, variant))
            if found:
                return found
            _extend_unique(found, _decode_with_pyzbar(variant))
            if found:
                return found

    return found


def _extend_unique(target: list[str], texts: list[str]) -> None:
    seen = set(target)
    for text in texts:
        if text and text not in seen:
            seen.add(text)
            target.append(text)


def _scaled_bgr_frames(bgr: np.ndarray) -> Iterator[np.ndarray]:
    import cv2

    height, width = bgr.shape[:2]
    longest = max(height, width)
    if longest < 1:
        return

    scales: list[float] = []
    if longest < _MIN_DECODE_SIDE:
        needed = _MIN_DECODE_SIDE / longest
        scale = 2.0
        while scale <= min(_MAX_SCALE, needed * 1.25):
            scales.append(scale)
            scale *= 1.5
        if not scales or scales[-1] < needed:
            scales.append(min(_MAX_SCALE, max(2.0, needed)))

    seen_sizes: set[tuple[int, int]] = {(width, height)}
    for scale in scales:
        new_w = int(width * scale)
        new_h = int(height * scale)
        if new_w < 32 or new_h < 32:
            continue
        longest_scaled = max(new_w, new_h)
        if longest_scaled > _MAX_UPSCALED_SIDE:
            fit = _MAX_UPSCALED_SIDE / longest_scaled
            new_w = max(32, int(new_w * fit))
            new_h = max(32, int(new_h * fit))
        size_key = (new_w, new_h)
        if size_key in seen_sizes:
            continue
        seen_sizes.add(size_key)
        yield cv2.resize(bgr, (new_w, new_h), interpolation=cv2.INTER_CUBIC)


def _add_quiet_zone(bgr: np.ndarray, ratio: float) -> np.ndarray:
    import cv2

    height, width = bgr.shape[:2]
    margin_x = max(8, int(width * ratio))
    margin_y = max(8, int(height * ratio))
    padded = cv2.copyMakeBorder(
        bgr,
        margin_y,
        margin_y,
        margin_x,
        margin_x,
        cv2.BORDER_CONSTANT,
        value=(255, 255, 255),
    )
    return padded


def _bgr_variants(bgr: np.ndarray) -> Iterator[np.ndarray]:
    import cv2

    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    yield gray

    clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
    enhanced = clahe.apply(gray)
    yield enhanced

    blurred = cv2.GaussianBlur(gray, (0, 0), sigmaX=0.8)
    sharp = cv2.addWeighted(gray, 1.6, blurred, -0.6, 0)
    yield sharp

    yield cv2.adaptiveThreshold(
        enhanced,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        31,
        5,
    )

    _, otsu = cv2.threshold(enhanced, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    yield otsu
    yield cv2.bitwise_not(otsu)


def _decode_with_opencv(detector: object, frame: np.ndarray) -> list[str]:
    import cv2

    texts: list[str] = []

    if frame.ndim == 2:
        decode_input = frame
    else:
        decode_input = frame

    try:
        ok, decoded, _points, _ = detector.detectAndDecodeMulti(decode_input)  # type: ignore[attr-defined]
        if ok and decoded is not None:
            if isinstance(decoded, str):
                decoded = (decoded,)
            for item in decoded:
                if item:
                    texts.append(item)
    except Exception:
        pass

    if not texts:
        try:
            data, _points, _ = detector.detectAndDecode(decode_input)  # type: ignore[attr-defined]
            if data:
                texts.append(data)
        except Exception:
            pass

    decode_curved = getattr(detector, "decodeCurved", None)
    if not texts and decode_curved is not None and frame.ndim == 3:
        try:
            ok, points = detector.detect(frame)  # type: ignore[attr-defined]
            if ok and points is not None:
                data, _ = decode_curved(frame, points)  # type: ignore[attr-defined]
                if data:
                    texts.append(data)
        except Exception:
            pass

    return texts


def _decode_with_pyzbar(frame: np.ndarray) -> list[str]:
    try:
        from pyzbar.pyzbar import ZBarSymbol, decode
    except ImportError:
        return []

    symbols = [ZBarSymbol.QRCODE]
    texts: list[str] = []
    try:
        for item in decode(frame, symbols=symbols):
            payload = item.data.decode("utf-8", errors="replace").strip()
            if payload:
                texts.append(payload)
    except Exception:
        return []
    return texts
