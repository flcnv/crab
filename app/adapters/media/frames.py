"""FrameExtractor: ffmpeg sampling -> blur filter (variance of Laplacian) -> dHash dedup -> top N.

Heavy modules (numpy/cv2) are imported lazily (Python 3.15 `lazy import`)
so the API starts fast.
"""

from pathlib import Path

from app.domain.models import Frame


class FfmpegFrameExtractor:
    def __init__(self, sample_fps: float = 1.0, blur_threshold: float = 100.0) -> None:
        self.sample_fps = sample_fps
        self.blur_threshold = blur_threshold

    async def extract(self, video: Path, out_dir: Path, max_frames: int) -> list[Frame]:
        raise NotImplementedError


def prepare_image(data: bytes, max_edge_px: int = 1500) -> bytes:
    """exif_transpose + downscale to max_edge_px on the long edge, re-encode as JPEG."""
    raise NotImplementedError
