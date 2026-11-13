"""Composition root: the only place that picks concrete adapters for the domain ports.

Both entrypoints (FastAPI in `app/api`, arq worker in `app/worker`) call `build_deps()`.
Tests can build their own `Deps` with fakes instead.
"""

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncEngine

from app.adapters.db.repositories import SqlJobRepository
from app.adapters.db.session import create_engine, create_sessionmaker
from app.adapters.llm.claude import ClaudeReportAgent, ClaudeVerifier, ClaudeVisionModel
from app.adapters.media.frames import FfmpegFrameExtractor
from app.adapters.media.metadata import FfprobeMetadataReader
from app.adapters.storage.local import LocalStorage
from app.domain.ports import (
    FrameExtractor,
    JobRepository,
    MetadataReader,
    ReportAgent,
    Storage,
    Verifier,
    VisionModel,
)
from app.settings import Settings, get_settings


@dataclass(frozen=True, slots=True)
class Deps:
    settings: Settings
    engine: AsyncEngine
    jobs: JobRepository
    storage: Storage
    metadata_reader: MetadataReader
    frame_extractor: FrameExtractor
    vision_model: VisionModel
    report_agent: ReportAgent
    verifier: Verifier

    async def aclose(self) -> None:
        await self.engine.dispose()


def build_deps(settings: Settings | None = None) -> Deps:
    settings = settings or get_settings()
    engine = create_engine(settings.database_url)
    return Deps(
        settings=settings,
        engine=engine,
        jobs=SqlJobRepository(create_sessionmaker(engine)),
        storage=LocalStorage(settings.storage_dir),
        metadata_reader=FfprobeMetadataReader(),
        frame_extractor=FfmpegFrameExtractor(sample_fps=settings.sample_fps),
        vision_model=ClaudeVisionModel(settings.claude_model, settings.prompt_version),
        report_agent=ClaudeReportAgent(settings.claude_model, settings.prompt_version),
        verifier=ClaudeVerifier(settings.claude_model, settings.prompt_version),
    )
