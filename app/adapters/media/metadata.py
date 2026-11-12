"""MetadataReader: duration/resolution via ffprobe, GPS from EXIF or video metadata."""

from pathlib import Path

from app.domain.models import MediaMetadata


class FfprobeMetadataReader:
    def read(self, path: Path) -> MediaMetadata:
        raise NotImplementedError
