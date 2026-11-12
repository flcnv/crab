"""Claude adapter: VisionModel, ReportAgent and Verifier via the official anthropic SDK."""

from uuid import UUID

from app.domain.models import FrameAnalysis, LLMUsage, TrenchReport


class ClaudeVisionModel:
    """Structured per-frame extraction. One retry with the validation error, then fail the frame."""

    def __init__(self, model: str, prompt_version: str = "v1") -> None:
        self.model = model
        self.prompt_version = prompt_version

    async def analyze(self, image: bytes, frame_id: str) -> tuple[FrameAnalysis, LLMUsage]:
        raise NotImplementedError


class ClaudeReportAgent:
    """Hand-written tool-use loop. Tools: get_frame_findings, get_frame_image, submit_report."""

    def __init__(self, model: str, prompt_version: str = "v1", max_turns: int = 10) -> None:
        self.model = model
        self.prompt_version = prompt_version
        self.max_turns = max_turns

    async def consolidate(
        self, job_id: UUID, analyses: list[FrameAnalysis]
    ) -> tuple[TrenchReport, list[LLMUsage]]:
        raise NotImplementedError


class ClaudeVerifier:
    def __init__(self, model: str, prompt_version: str = "v1") -> None:
        self.model = model
        self.prompt_version = prompt_version

    async def verify(
        self, report: TrenchReport, analyses: list[FrameAnalysis]
    ) -> tuple[list[str], LLMUsage]:
        raise NotImplementedError
