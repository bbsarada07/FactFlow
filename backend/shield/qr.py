"""QR codes in images (quishing): decode them so the hidden link gets the same checks as any other.

Images come from attachments and inline `data:` images. Each image is size-checked before it is
decoded (to refuse decompression bombs), and only the decoded text is used; images are never
rendered or opened by anything else. Decoding uses OpenCV's QRCodeDetector.
"""
from __future__ import annotations

import base64
import binascii
import io

MAX_IMAGES = 10
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_PIXELS = 4096 * 4096


def _dimensions_ok(data: bytes) -> bool:
    try:
        from PIL import Image

        with Image.open(io.BytesIO(data)) as img:
            w, h = img.size
        return 0 < w * h <= MAX_PIXELS
    except Exception:  # noqa: BLE001 - not an image Pillow can read
        return False


def decode(data: bytes) -> list[str]:
    """Texts of the QR codes found in an image ([] if none, unreadable, or too large)."""
    if not data or len(data) > MAX_IMAGE_BYTES or not _dimensions_ok(data):
        return []
    import cv2
    import numpy as np

    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_GRAYSCALE)
    if img is None:
        return []
    detector = cv2.QRCodeDetector()
    found: list[str] = []
    try:
        ok, texts, _points, _ = detector.detectAndDecodeMulti(img)
        if ok:
            found = [t for t in texts if t]
    except cv2.error:
        pass
    if not found:
        try:
            text, _points, _ = detector.detectAndDecode(img)
            if text:
                found = [text]
        except cv2.error:
            pass
    return list(dict.fromkeys(found))


def data_uri_bytes(src: str) -> bytes | None:
    """Bytes of a base64 `data:image/...` URI, or None."""
    if not src.lower().startswith("data:image/") or ";base64," not in src[:100].lower():
        return None
    payload = src.split(",", 1)[1]
    if len(payload) * 3 / 4 > MAX_IMAGE_BYTES:
        return None
    try:
        return base64.b64decode(payload, validate=False)
    except (binascii.Error, ValueError):
        return None


def scan_images(images: list[tuple[str, bytes]]) -> list[tuple[str, str]]:
    """(image name, decoded text) for every QR code found in up to MAX_IMAGES images."""
    out = []
    for name, data in images[:MAX_IMAGES]:
        for text in decode(data):
            out.append((name, text))
    return out
