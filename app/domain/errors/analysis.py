from app.domain.models import LLMUsage


class ModelCallError(RuntimeError):
    """A model-backed step failed. Carries the usage of calls already made, so cost is recorded."""

    def __init__(self, message: str, usage: list[LLMUsage] | None = None) -> None:
        super().__init__(message)
        self.usage = usage or []


class FrameAnalysisError(ModelCallError):
    """A frame could not be analyzed (refusal, invalid output after retry, API failure)."""


class ConsolidationError(ModelCallError):
    """The consolidation agent produced no valid report (turn limit, refusal, API failure)."""
