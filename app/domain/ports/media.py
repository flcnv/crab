from pathlib import Path
from typing import Protocol

from app.domain.models import Frame, MediaMetadata


class MetadataReader(Protocol):
    def read(self, path: Path) -> MediaMetadata: ...


class FrameExtractor(Protocol):
    """Video -> sampled, de-blurred, de-duplicated keyframes."""

    async def extract(self, video: Path, out_dir: Path, max_frames: int) -> list[Frame]: ...
