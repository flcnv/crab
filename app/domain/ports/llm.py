from collections.abc import Awaitable, Callable
from typing import Protocol
from uuid import UUID

from app.domain.models import Consolidation, FrameAnalysis, LLMUsage

type ImageLoader = Callable[[str], Awaitable[bytes]]  # frame_id -> JPEG bytes


class VisionModel(Protocol):
    """One image -> structured findings.

    Returns the usage of every model call made (a retry adds one). Raises
    `FrameAnalysisError` (which also carries the usage) when the frame cannot be analyzed.
    """

    async def analyze(
        self, image: bytes, frame_id: str
    ) -> tuple[FrameAnalysis, list[LLMUsage]]: ...


class ReportAgent(Protocol):
    """Per-frame findings -> distinct physical lines (tool-use agent loop).

    May look at frame images through `load_image`. Raises `ConsolidationError` (with usage)
    when it cannot produce a valid result.
    """

    async def consolidate(
        self, job_id: UUID, analyses: list[FrameAnalysis], load_image: ImageLoader
    ) -> tuple[Consolidation, list[LLMUsage]]: ...
