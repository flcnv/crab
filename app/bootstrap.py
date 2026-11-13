"""Composition root: the only place that picks concrete adapters for the domain ports.

Both entrypoints (FastAPI in `app/api`, arq worker in `app/worker`) call `build_deps()`.
Tests can build their own `Deps` with fakes instead.
"""

from dataclasses import dataclass

from arq.connections import RedisSettings
from sqlalchemy.ext.asyncio import AsyncEngine

from app.adapters.db.repositories import SqlJobRepository
from app.adapters.db.session import create_engine, create_sessionmaker
from app.adapters.llm.claude import ClaudeReportAgent, ClaudeVerifier, ClaudeVisionModel
from app.adapters.media.frames import FfmpegFrameExtractor
from app.adapters.media.metadata import MediaMetadataReader
from app.adapters.queue.arq import ArqJobQueue
from app.adapters.storage.local import LocalStorage
from app.domain.ports import (
    FrameExtractor,
    JobQueue,
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
    queue: JobQueue
    storage: Storage
    metadata_reader: MetadataReader
    frame_extractor: FrameExtractor
    vision_model: VisionModel
    report_agent: ReportAgent
    verifier: Verifier

    async def aclose(self) -> None:
        await self.queue.aclose()
        await self.engine.dispose()


def build_deps(settings: Settings | None = None) -> Deps:
    settings = settings or get_settings()
    engine = create_engine(settings.database_url)
    return Deps(
        settings=settings,
        engine=engine,
        jobs=SqlJobRepository(create_sessionmaker(engine)),
        queue=ArqJobQueue(RedisSettings.from_dsn(settings.redis_url)),
        storage=LocalStorage(settings.storage_dir),
        metadata_reader=MediaMetadataReader(),
        frame_extractor=FfmpegFrameExtractor(
            sample_fps=settings.sample_fps,
            max_edge_px=settings.max_image_edge_px,
            min_sharpness=settings.min_frame_sharpness,
            min_hash_distance=settings.min_frame_hash_distance,
        ),
        vision_model=ClaudeVisionModel(settings.claude_model, settings.prompt_version),
        report_agent=ClaudeReportAgent(settings.claude_model, settings.prompt_version),
        verifier=ClaudeVerifier(settings.claude_model, settings.prompt_version),
    )
