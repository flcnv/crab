from app.domain.models import LLMUsage


class FrameAnalysisError(RuntimeError):
    """A frame could not be analyzed (refusal, invalid output after retry, API failure).

    Carries the usage of the calls already made, so their cost is still recorded.
    """

    def __init__(self, message: str, usage: list[LLMUsage] | None = None) -> None:
        super().__init__(message)
        self.usage = usage or []
