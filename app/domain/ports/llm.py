from collections.abc import Awaitable, Callable
from typing import Protocol
from uuid import UUID

from app.domain.models import Consolidation, FrameAnalysis, LLMUsage

type ImageLoader = Callable[[str], Awaitable[bytes]]


class VisionModel(Protocol):
    async def analyze(
        self, image: bytes, frame_id: str
    ) -> tuple[FrameAnalysis, list[LLMUsage]]: ...


class ReportAgent(Protocol):
    async def consolidate(
        self, job_id: UUID, analyses: list[FrameAnalysis], load_image: ImageLoader
    ) -> tuple[Consolidation, list[LLMUsage]]: ...
