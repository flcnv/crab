import asyncio
import tempfile
from pathlib import Path

from app.adapters.media import ffmpeg, images
from app.domain.errors import MediaProcessingError
from app.domain.models import ExtractedFrame
from app.domain.services import FrameCandidate, select_keyframes


class FfmpegFrameExtractor:
    def __init__(
        self,
        *,
        sample_fps: float = 1.0,
        max_edge_px: int = 1500,
        min_sharpness: float = 60.0,
        min_hash_distance: int = 6,
    ) -> None:
        self.sample_fps = sample_fps
        self.max_edge_px = max_edge_px
        self.min_sharpness = min_sharpness
        self.min_hash_distance = min_hash_distance

    async def from_video(self, video: Path, max_frames: int) -> list[ExtractedFrame]:
        with tempfile.TemporaryDirectory(prefix="frames-") as tmp:
            paths = await ffmpeg.sample_frames(
                video, Path(tmp), fps=self.sample_fps, max_edge_px=self.max_edge_px
            )
            if not paths:
                raise MediaProcessingError("video contains no decodable frames")
            candidates = await asyncio.to_thread(self._measure, paths)
            picked = select_keyframes(
                candidates,
                max_frames=max_frames,
                min_sharpness=self.min_sharpness,
                min_hash_distance=self.min_hash_distance,
            )
            jpegs = await asyncio.to_thread(lambda: [paths[c.index].read_bytes() for c in picked])
        return [
            ExtractedFrame(
                jpeg=jpeg,
                timestamp_s=round(c.index / self.sample_fps, 3),
                sharpness=round(c.sharpness, 2),
            )
            for c, jpeg in zip(picked, jpegs, strict=True)
        ]

    async def from_images(self, image_paths: list[Path]) -> list[ExtractedFrame]:
        return await asyncio.to_thread(self._prepare_images, image_paths)

    @staticmethod
    def _measure(paths: list[Path]) -> list[FrameCandidate]:
        candidates = []
        for i, path in enumerate(paths):
            jpeg = path.read_bytes()
            candidates.append(
                FrameCandidate(index=i, sharpness=images.sharpness(jpeg), phash=images.dhash(jpeg))
            )
        return candidates

    def _prepare_images(self, image_paths: list[Path]) -> list[ExtractedFrame]:
        frames = []
        for path in image_paths:
            jpeg = images.prepare_image(path.read_bytes(), self.max_edge_px)
            frames.append(ExtractedFrame(jpeg=jpeg, sharpness=round(images.sharpness(jpeg), 2)))
        return frames
