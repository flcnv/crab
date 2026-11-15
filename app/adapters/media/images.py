import io
from typing import Any

lazy import cv2
lazy import imagehash
lazy import numpy as np
lazy from PIL import Image, ImageOps

from app.domain.errors import MediaProcessingError

SHARPNESS_WIDTH_PX = 640


def _open(data: bytes) -> Any:
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception as e:
        raise MediaProcessingError(f"cannot decode image: {e}") from e
    return img


def prepare_image(data: bytes, max_edge_px: int) -> bytes:
    img = ImageOps.exif_transpose(_open(data)).convert("RGB")
    img.thumbnail((max_edge_px, max_edge_px), Image.Resampling.LANCZOS)
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=90, optimize=True)
    return out.getvalue()


def sharpness(jpeg: bytes) -> float:
    gray = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
    if gray is None:
        raise MediaProcessingError("cannot decode frame")
    h, w = gray.shape
    if w > SHARPNESS_WIDTH_PX:
        gray = cv2.resize(gray, (SHARPNESS_WIDTH_PX, round(h * SHARPNESS_WIDTH_PX / w)))
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def dhash(jpeg: bytes) -> int:
    return int(str(imagehash.dhash(_open(jpeg), hash_size=8)), 16)
