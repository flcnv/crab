import asyncio
import re
from datetime import datetime
from pathlib import Path
from typing import Any

lazy from PIL import ExifTags, Image

from app.adapters.media import ffmpeg
from app.domain.errors import MediaProcessingError
from app.domain.models import GeoPoint, MediaKind, MediaMetadata

_ISO6709 = re.compile(r"([+-]\d+(?:\.\d+)?)([+-]\d+(?:\.\d+)?)")

_GPS_LAT_REF, _GPS_LAT, _GPS_LON_REF, _GPS_LON, _GPS_ACCURACY = 1, 2, 3, 4, 31
_DATETIME, _DATETIME_ORIGINAL, _OFFSET_TIME_ORIGINAL = 306, 36867, 36881


class MediaMetadataReader:
    async def read(self, path: Path, kind: MediaKind) -> MediaMetadata:
        if kind == "video":
            return _video_metadata(await ffmpeg.probe(path))
        return await asyncio.to_thread(_image_metadata, path)


def _video_metadata(probe: dict[str, Any]) -> MediaMetadata:
    fmt = probe.get("format", {})
    video = next((s for s in probe.get("streams", []) if s.get("codec_type") == "video"), None)
    if video is None:
        raise MediaProcessingError("file has no video stream")

    width, height = video.get("width"), video.get("height")
    if _rotation(video) in (90, 270):
        width, height = height, width

    tags = {k.lower(): v for k, v in {**video.get("tags", {}), **fmt.get("tags", {})}.items()}
    duration = fmt.get("duration") or video.get("duration")
    return MediaMetadata(
        kind="video",
        duration_s=round(float(duration), 3) if duration else None,
        width=width,
        height=height,
        location=parse_iso6709(
            tags.get("com.apple.quicktime.location.iso6709") or tags.get("location")
        ),
        captured_at=_parse_iso_datetime(
            tags.get("com.apple.quicktime.creationdate") or tags.get("creation_time")
        ),
    )


def _rotation(stream: dict[str, Any]) -> int:
    for side in stream.get("side_data_list", []):
        if "rotation" in side:
            return abs(int(side["rotation"])) % 360
    return abs(int(stream.get("tags", {}).get("rotate", 0))) % 360


def parse_iso6709(value: str | None) -> GeoPoint | None:
    if not value or not (m := _ISO6709.match(value.strip())):
        return None
    lat, lon = float(m[1]), float(m[2])
    if (lat, lon) == (0.0, 0.0) or abs(lat) > 90 or abs(lon) > 180:
        return None
    return GeoPoint(lat=lat, lon=lon)


def _parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _image_metadata(path: Path) -> MediaMetadata:
    try:
        with Image.open(path) as img:
            exif = img.getexif()
            width, height = img.size
    except Exception as e:
        raise MediaProcessingError(f"cannot read image {path.name}: {e}") from e

    if exif.get(0x0112) in (5, 6, 7, 8):
        width, height = height, width

    exif_ifd = exif.get_ifd(ExifTags.IFD.Exif)
    return MediaMetadata(
        kind="image",
        width=width,
        height=height,
        location=gps_from_exif(exif.get_ifd(ExifTags.IFD.GPSInfo)),
        captured_at=parse_exif_datetime(
            exif_ifd.get(_DATETIME_ORIGINAL) or exif.get(_DATETIME),
            exif_ifd.get(_OFFSET_TIME_ORIGINAL),
        ),
    )


def gps_from_exif(gps: dict[int, Any]) -> GeoPoint | None:
    try:
        lat = _dms_to_degrees(gps[_GPS_LAT], gps.get(_GPS_LAT_REF, "N"), "S")
        lon = _dms_to_degrees(gps[_GPS_LON], gps.get(_GPS_LON_REF, "E"), "W")
    except KeyError, TypeError, ValueError, ZeroDivisionError:
        return None
    if abs(lat) > 90 or abs(lon) > 180:
        return None
    accuracy = gps.get(_GPS_ACCURACY)
    return GeoPoint(
        lat=round(lat, 7),
        lon=round(lon, 7),
        accuracy_m=float(accuracy) if accuracy is not None else None,
    )


def _dms_to_degrees(dms: Any, ref: str, negative_ref: str) -> float:
    d, m, s = (float(x) for x in dms)
    value = d + m / 60 + s / 3600
    return -value if str(ref).upper().startswith(negative_ref) else value


def parse_exif_datetime(value: str | None, offset: str | None = None) -> datetime | None:
    if not value or len(value) < 19:
        return None
    iso = f"{value[:10].replace(':', '-')}T{value[11:19]}{offset or ''}"
    try:
        return datetime.fromisoformat(iso)
    except ValueError:
        return None
