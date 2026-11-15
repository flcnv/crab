from pathlib import Path
from typing import Protocol

from app.domain.models import ExtractedFrame, MediaKind, MediaMetadata


class MetadataReader(Protocol):
    async def read(self, path: Path, kind: MediaKind) -> MediaMetadata: ...


class FrameExtractor(Protocol):
    async def from_video(self, video: Path, max_frames: int) -> list[ExtractedFrame]: ...

    async def from_images(self, images: list[Path]) -> list[ExtractedFrame]: ...
