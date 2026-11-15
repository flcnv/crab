import io
import shutil
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from app.adapters.media.frames import FfmpegFrameExtractor
from app.adapters.media.metadata import MediaMetadataReader
from app.domain.errors import MediaProcessingError

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


@pytest.fixture(scope="module")
def video(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("video") / "clip.mp4"
    subprocess.run(
        [
            "ffmpeg", "-nostdin", "-v", "error",
            "-f", "lavfi", "-i", "testsrc2=size=1920x1080:rate=10:duration=3",
            "-f", "lavfi", "-i", "color=c=gray:size=1920x1080:rate=10:duration=3",
            "-filter_complex", "[0:v][1:v]concat=n=2:v=1[v]", "-map", "[v]",
            "-metadata", "location=+47.3769+008.5417/",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )  # fmt: skip
    return path


async def test_video_metadata(video: Path) -> None:
    md = await MediaMetadataReader().read(video, "video")
    assert md.duration_s == pytest.approx(6.0, abs=0.2)
    assert (md.width, md.height) == (1920, 1080)
    assert md.location is not None
    assert md.location.lat == pytest.approx(47.3769)


async def test_from_video_selects_sharp_distinct_frames(video: Path) -> None:
    extractor = FfmpegFrameExtractor(sample_fps=2, max_edge_px=800, min_sharpness=60)

    frames = await extractor.from_video(video, max_frames=12)

    assert 1 <= len(frames) < 12
    timestamps = [f.timestamp_s or 0.0 for f in frames]
    assert timestamps == sorted(timestamps)
    assert all(f.timestamp_s is not None and f.timestamp_s < 3.0 for f in frames)
    assert Image.open(io.BytesIO(frames[0].jpeg)).size == (800, 450)


async def test_from_video_respects_max_frames(video: Path) -> None:
    extractor = FfmpegFrameExtractor(sample_fps=4, min_hash_distance=0)
    frames = await extractor.from_video(video, max_frames=2)
    assert len(frames) == 2


async def test_broken_video_raises(tmp_path: Path) -> None:
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(b"not a video")
    with pytest.raises(MediaProcessingError):
        await FfmpegFrameExtractor().from_video(bad, max_frames=3)
