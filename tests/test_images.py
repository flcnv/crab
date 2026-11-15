import io

import pytest
from PIL import Image, ImageDraw, ImageFilter

from app.adapters.media.images import dhash, prepare_image, sharpness
from app.domain.errors import MediaProcessingError
from app.domain.services import hamming


def _jpeg(img: Image.Image, **kwargs: object) -> bytes:
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=95, **kwargs)
    return out.getvalue()


def _pattern(seed: int = 0) -> Image.Image:
    img = Image.new("RGB", (800, 600), "white")
    draw = ImageDraw.Draw(img)
    for i in range(0, 800, 20):
        draw.line([(i + seed * 7, 0), (i, 600)], fill="black", width=3)
    draw.ellipse([200 + seed * 40, 150, 500, 450], fill="blue")
    return img


def test_prepare_image_rotates_and_downscales() -> None:
    exif = Image.Exif()
    exif[0x0112] = 6
    data = _jpeg(Image.new("RGB", (4000, 3000), "gray"), exif=exif)

    out = Image.open(io.BytesIO(prepare_image(data, max_edge_px=1500)))

    assert out.size == (1125, 1500)
    assert out.format == "JPEG"
    assert out.getexif().get(0x0112) is None


def test_prepare_image_rejects_garbage() -> None:
    with pytest.raises(MediaProcessingError):
        prepare_image(b"definitely not a jpeg", max_edge_px=1500)


def test_sharpness_detects_blur() -> None:
    sharp = _pattern()
    blurred = sharp.filter(ImageFilter.GaussianBlur(radius=6))
    assert sharpness(_jpeg(sharp)) > 10 * sharpness(_jpeg(blurred))


def test_dhash_near_duplicates_vs_different() -> None:
    a = _jpeg(_pattern())
    a_recompressed = _jpeg(Image.open(io.BytesIO(a)).resize((780, 585)))
    b = _jpeg(_pattern(seed=5).transpose(Image.Transpose.FLIP_LEFT_RIGHT))

    assert hamming(dhash(a), dhash(a_recompressed)) <= 4
    assert hamming(dhash(a), dhash(b)) > 10
