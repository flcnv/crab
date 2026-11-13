from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.domain.models.geo import GeoPoint

type MediaKind = Literal["video", "image"]


class MediaMetadata(BaseModel):
    kind: MediaKind
    duration_s: float | None = None
    width: int | None = None
    height: int | None = None
    location: GeoPoint | None = None
    captured_at: datetime | None = None


class Frame(BaseModel):
    """A keyframe selected for analysis (reference to stored image, not bytes)."""

    frame_id: str
    storage_key: str
    timestamp_s: float | None = None
    sharpness: float | None = None


class ExtractedFrame(BaseModel):
    """A keyframe produced by a FrameExtractor, before it is stored (holds the JPEG bytes)."""

    jpeg: bytes
    timestamp_s: float | None = None
    sharpness: float | None = None
