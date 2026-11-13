"""Image measurements and normalization. Heavy libs are imported lazily (Python 3.15)."""

import io
from typing import Any

lazy import cv2
lazy import imagehash
lazy import numpy as np
lazy from PIL import Image, ImageOps

from app.domain.errors import MediaProcessingError

# Sharpness is measured on a fixed-width grayscale copy, so the threshold does not depend
# on the input resolution.
SHARPNESS_WIDTH_PX = 640


def _open(data: bytes) -> Any:
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception as e:  # Pillow raises many different types for broken input
        raise MediaProcessingError(f"cannot decode image: {e}") from e
    return img


def prepare_image(data: bytes, max_edge_px: int) -> bytes:
    """Apply EXIF rotation, downscale to `max_edge_px` on the long edge, re-encode as JPEG.

    EXIF is dropped on purpose: it is read separately, and stripping it avoids leaking
    device details to the model.
    """
    img = ImageOps.exif_transpose(_open(data)).convert("RGB")
    img.thumbnail((max_edge_px, max_edge_px), Image.Resampling.LANCZOS)
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=90, optimize=True)
    return out.getvalue()


def sharpness(jpeg: bytes) -> float:
    """Variance of the Laplacian: low values mean motion blur or out-of-focus frames."""
    gray = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
    if gray is None:
        raise MediaProcessingError("cannot decode frame")
    h, w = gray.shape
    if w > SHARPNESS_WIDTH_PX:
        gray = cv2.resize(gray, (SHARPNESS_WIDTH_PX, round(h * SHARPNESS_WIDTH_PX / w)))
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def dhash(jpeg: bytes) -> int:
    """64-bit difference hash; near-duplicate frames differ in only a few bits."""
    return int(str(imagehash.dhash(_open(jpeg), hash_size=8)), 16)
