"""Thin async wrappers around the ffmpeg / ffprobe CLIs."""

import asyncio
import json
from pathlib import Path
from typing import Any

from app.domain.errors import MediaProcessingError


async def _run(*cmd: str) -> bytes:
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as e:
        raise MediaProcessingError(f"{cmd[0]} is not installed") from e
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        detail = stderr.decode(errors="replace").strip().splitlines()[-1:] or ["no output"]
        raise MediaProcessingError(f"{cmd[0]} failed: {detail[0]}")
    return stdout


async def probe(path: Path) -> dict[str, Any]:
    out = await _run(
        "ffprobe",
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
    )
    data: dict[str, Any] = json.loads(out)
    return data


async def sample_frames(video: Path, out_dir: Path, *, fps: float, max_edge_px: int) -> list[Path]:
    """Decode `fps` frames per second as JPEGs, long edge <= max_edge_px.

    ffmpeg applies the rotation from the video's display matrix automatically.
    """
    m = max_edge_px
    scale = f"scale='if(gte(iw,ih),min(iw,{m}),-2)':'if(gte(iw,ih),-2,min(ih,{m}))'"
    await _run(
        "ffmpeg", "-nostdin", "-v", "error", "-i", str(video),
        "-vf", f"fps={fps},{scale}", "-q:v", "2",
        str(out_dir / "%05d.jpg"),
    )  # fmt: skip
    return await asyncio.to_thread(lambda: sorted(out_dir.glob("*.jpg")))
