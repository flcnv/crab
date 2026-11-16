from dataclasses import dataclass
from uuid import UUID

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
from app.domain.models import Consolidation, FrameAnalysis, LLMUsage, VerificationConfig
from app.domain.ports import (
    FrameExtractor,
    JobQueue,
    JobRepository,
    MetadataReader,
    ReportAgent,
    Storage,
    VisionModel,
)
from app.domain.ports.llm import ImageLoader
from app.settings import Settings, get_settings


@dataclass(frozen=True, slots=True)
class Deps:
    settings: Settings
    engine: AsyncEngine
    anthropic: anthropic.AsyncAnthropic | None
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
        if self.anthropic is not None:
            await self.anthropic.close()
        await self.engine.dispose()


class LLMNotWired:
    async def analyze(self, image: bytes, frame_id: str) -> tuple[FrameAnalysis, list[LLMUsage]]:
        raise RuntimeError("LLM adapters are only wired in the worker (build_deps(with_llm=True))")

    async def consolidate(
        self, job_id: UUID, analyses: list[FrameAnalysis], load_image: ImageLoader
    ) -> tuple[Consolidation, list[LLMUsage]]:
        raise RuntimeError("LLM adapters are only wired in the worker (build_deps(with_llm=True))")


def _llm_adapters(
    settings: Settings,
) -> tuple[anthropic.AsyncAnthropic, VisionModel, ReportAgent]:
    key = settings.anthropic_api_key
    claude = anthropic.AsyncAnthropic(
        api_key=key.get_secret_value() if key else None,
        max_retries=settings.claude_max_retries,
        timeout=settings.claude_timeout_s,
    )
    vision = ClaudeVisionModel(
        claude,
        settings.claude_model,
        prompt_version=settings.prompt_version,
        effort=settings.claude_effort,
        refusal_fallback=settings.claude_refusal_fallback,
    )
    agent = ClaudeReportAgent(
        claude,
        settings.claude_model,
        prompt_version=settings.prompt_version,
        effort=settings.agent_effort,
        max_turns=settings.agent_max_turns,
        max_image_views=settings.agent_max_image_views,
        refusal_fallback=settings.claude_refusal_fallback,
    )
    return claude, vision, agent


def build_deps(settings: Settings | None = None, *, with_llm: bool = True) -> Deps:
    settings = settings or get_settings()
    engine = create_engine(settings.database_url)
    claude: anthropic.AsyncAnthropic | None = None
    vision_model: VisionModel = LLMNotWired()
    report_agent: ReportAgent = LLMNotWired()
    if with_llm:
        claude, vision_model, report_agent = _llm_adapters(settings)
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
        vision_model=vision_model,
        report_agent=report_agent,
        verification=VerificationConfig(
            min_confidence=settings.verify_min_confidence,
            size_tolerance=settings.verify_size_tolerance,
        ),
    )
