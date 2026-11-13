from typing import Protocol
from uuid import UUID

from app.domain.models import FrameAnalysis, LLMUsage, TrenchReport


class VisionModel(Protocol):
    """One image -> structured findings."""

    async def analyze(self, image: bytes, frame_id: str) -> tuple[FrameAnalysis, LLMUsage]: ...


class ReportAgent(Protocol):
    """Per-frame findings -> one consolidated report (tool-use agent loop)."""

    async def consolidate(
        self, job_id: UUID, analyses: list[FrameAnalysis]
    ) -> tuple[TrenchReport, list[LLMUsage]]: ...


class Verifier(Protocol):
    """Independent pass: flags report claims not supported by frame findings."""

    async def verify(
        self, report: TrenchReport, analyses: list[FrameAnalysis]
    ) -> tuple[list[str], LLMUsage]: ...
