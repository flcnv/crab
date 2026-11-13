from pathlib import Path
from typing import Protocol

from app.domain.models import ExtractedFrame, MediaKind, MediaMetadata


class MetadataReader(Protocol):
    """Duration, resolution, capture time and GPS of one uploaded file."""

    async def read(self, path: Path, kind: MediaKind) -> MediaMetadata: ...


class FrameExtractor(Protocol):
    async def from_video(self, video: Path, max_frames: int) -> list[ExtractedFrame]:
        """Sample, drop blurry and near-duplicate frames, keep at most `max_frames`."""
        ...

    async def from_images(self, images: list[Path]) -> list[ExtractedFrame]:
        """Photos skip selection: each one is normalized (rotation, size) and kept."""
        ...
