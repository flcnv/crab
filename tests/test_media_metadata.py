import io
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest
from PIL import Image

from app.adapters.media.metadata import (
    MediaMetadataReader,
    _video_metadata,
    gps_from_exif,
    parse_exif_datetime,
    parse_iso6709,
)
from app.domain.errors import MediaProcessingError
from app.domain.models import GeoPoint, MediaMetadata
from app.domain.services import merge_image_metadata


def test_parse_iso6709() -> None:
    assert parse_iso6709("+47.3769+008.5417+408.000/") == GeoPoint(lat=47.3769, lon=8.5417)
    assert parse_iso6709("-33.86-151.21/") == GeoPoint(lat=-33.86, lon=-151.21)
    assert parse_iso6709("+00.0000+000.0000/") is None
    assert parse_iso6709("garbage") is None
    assert parse_iso6709(None) is None


def test_gps_from_exif_dms() -> None:
    gps = {1: "N", 2: (47.0, 22.0, 36.0), 3: "W", 4: (8.0, 30.0, 0.0), 31: 5.0}
    point = gps_from_exif(gps)
    assert point is not None
    assert point.lat == pytest.approx(47.376667)
    assert (point.lon, point.accuracy_m) == (-8.5, 5.0)
    assert gps_from_exif({}) is None


def test_parse_exif_datetime() -> None:
    assert parse_exif_datetime("2026:05:01 10:20:30", "+02:00") == datetime(
        2026, 5, 1, 10, 20, 30, tzinfo=timezone(timedelta(hours=2))
    )
    naive = parse_exif_datetime("2026:05:01 10:20:30")
    assert naive is not None
    assert naive.tzinfo is None
    assert parse_exif_datetime("0000:00:00 00:00:00") is None
    assert parse_exif_datetime(None) is None


def test_video_metadata_from_probe() -> None:
    probe = {
        "format": {
            "duration": "12.345678",
            "tags": {
                "creation_time": "2026-05-01T10:20:30.000000Z",
                "com.apple.quicktime.location.ISO6709": "+47.3769+008.5417+408.000/",
            },
        },
        "streams": [
            {"codec_type": "audio"},
            {
                "codec_type": "video",
                "width": 1920,
                "height": 1080,
                "side_data_list": [{"rotation": -90}],
            },
        ],
    }
    md = _video_metadata(probe)
    assert md.kind == "video"
    assert md.duration_s == 12.346
    assert (md.width, md.height) == (1080, 1920)  # portrait phone video
    assert md.location == GeoPoint(lat=47.3769, lon=8.5417)
    assert md.captured_at == datetime(2026, 5, 1, 10, 20, 30, tzinfo=UTC)


def test_video_without_video_stream_fails() -> None:
    with pytest.raises(MediaProcessingError):
        _video_metadata({"format": {}, "streams": [{"codec_type": "audio"}]})


def _jpeg_with_exif(path: Path, *, orientation: int = 1) -> None:
    img = Image.new("RGB", (400, 300), "orange")
    exif = Image.Exif()
    exif[0x0112] = orientation
    exif.get_ifd(0x8825).update({1: "N", 2: (47.0, 30.0, 0.0), 3: "E", 4: (8.0, 15.0, 0.0)})
    exif.get_ifd(0x8769).update({36867: "2026:05:01 10:20:30", 36881: "+02:00"})
    img.save(path, format="JPEG", exif=exif)


async def test_image_metadata_reads_exif(tmp_path: Path) -> None:
    path = tmp_path / "p.jpg"
    _jpeg_with_exif(path, orientation=6)  # rotated 90 degrees

    md = await MediaMetadataReader().read(path, "image")

    assert (md.width, md.height) == (300, 400)
    assert md.location == GeoPoint(lat=47.5, lon=8.25)
    assert md.captured_at == datetime(2026, 5, 1, 8, 20, 30, tzinfo=UTC)


async def test_broken_image_raises(tmp_path: Path) -> None:
    path = tmp_path / "broken.jpg"
    path.write_bytes(io.BytesIO(b"not an image").getvalue())
    with pytest.raises(MediaProcessingError):
        await MediaMetadataReader().read(path, "image")


def test_merge_image_metadata() -> None:
    early = datetime(2026, 5, 1, 8, 0, tzinfo=UTC)
    merged = merge_image_metadata(
        [
            MediaMetadata(kind="image", width=10, height=20),
            MediaMetadata(kind="image", location=GeoPoint(lat=1, lon=2), captured_at=early),
            MediaMetadata(kind="image", captured_at=early + timedelta(hours=1)),
        ]
    )
    assert (merged.width, merged.height) == (10, 20)
    assert merged.location == GeoPoint(lat=1, lon=2)
    assert merged.captured_at == early
