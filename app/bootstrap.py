from dataclasses import dataclass

import anthropic
from arq.connections import RedisSettings
from sqlalchemy.ext.asyncio import AsyncEngine

from app.adapters.db.repositories import SqlJobRepository
from app.adapters.db.session import create_engine, create_sessionmaker
from app.adapters.llm.agent import ClaudeReportAgent
from app.adapters.llm.claude import ClaudeVisionModel
from app.adapters.media.frames import FfmpegFrameExtractor
from app.adapters.media.metadata import MediaMetadataReader
from app.adapters.queue.arq import ArqJobQueue
from app.adapters.storage.local import LocalStorage
from app.domain.models import VerificationConfig
from app.domain.ports import (
    FrameExtractor,
    JobQueue,
    JobRepository,
    MetadataReader,
    ReportAgent,
    Storage,
    VisionModel,
)
from app.settings import Settings, get_settings


@dataclass(frozen=True, slots=True)
class Deps:
    settings: Settings
    engine: AsyncEngine
    anthropic: anthropic.AsyncAnthropic
    jobs: JobRepository
    queue: JobQueue
    storage: Storage
    metadata_reader: MetadataReader
    frame_extractor: FrameExtractor
    vision_model: VisionModel
    report_agent: ReportAgent
    verification: VerificationConfig

    async def aclose(self) -> None:
        await self.queue.aclose()
        await self.anthropic.close()
        await self.engine.dispose()


def build_deps(settings: Settings | None = None) -> Deps:
    settings = settings or get_settings()
    engine = create_engine(settings.database_url)
    key = settings.anthropic_api_key
    claude = anthropic.AsyncAnthropic(
        api_key=key.get_secret_value() if key else None,
        max_retries=settings.claude_max_retries,
        timeout=settings.claude_timeout_s,
    )
    return Deps(
        settings=settings,
        engine=engine,
        anthropic=claude,
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
        vision_model=ClaudeVisionModel(
            claude,
            settings.claude_model,
            prompt_version=settings.prompt_version,
            effort=settings.claude_effort,
            refusal_fallback=settings.claude_refusal_fallback,
        ),
        report_agent=ClaudeReportAgent(
            claude,
            settings.claude_model,
            prompt_version=settings.prompt_version,
            effort=settings.agent_effort,
            max_turns=settings.agent_max_turns,
            max_image_views=settings.agent_max_image_views,
            refusal_fallback=settings.claude_refusal_fallback,
        ),
        verification=VerificationConfig(
            min_confidence=settings.verify_min_confidence,
            size_tolerance=settings.verify_size_tolerance,
        ),
    )
