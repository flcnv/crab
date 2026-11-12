"""Ports: interfaces the domain needs. Adapters implement them."""

from pathlib import Path
from typing import Protocol
from uuid import UUID

from app.domain.models import (
    Frame,
    FrameAnalysis,
    JobStatus,
    LLMUsage,
    MediaMetadata,
    TrenchReport,
)


class Storage(Protocol):
    async def put(self, key: str, data: bytes) -> str: ...
    async def get(self, key: str) -> bytes: ...
    def local_path(self, key: str) -> Path: ...


class MetadataReader(Protocol):
    def read(self, path: Path) -> MediaMetadata: ...


class FrameExtractor(Protocol):
    """Video -> sampled, de-blurred, de-duplicated keyframes."""

    async def extract(self, video: Path, out_dir: Path, max_frames: int) -> list[Frame]: ...


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


class JobRepository(Protocol):
    async def create(self, upload_key: str, media_kind: str) -> UUID: ...
    async def set_status(
        self, job_id: UUID, status: JobStatus, error: str | None = None
    ) -> None: ...
    async def save_frames(self, job_id: UUID, frames: list[Frame]) -> None: ...
    async def save_analysis(
        self, job_id: UUID, analysis: FrameAnalysis, usage: LLMUsage
    ) -> None: ...
    async def save_report(self, job_id: UUID, report: TrenchReport) -> None: ...
    async def get_report(self, job_id: UUID) -> TrenchReport | None: ...
