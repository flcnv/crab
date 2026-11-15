from app.domain.models import LLMUsage


class ModelCallError(RuntimeError):
    def __init__(self, message: str, usage: list[LLMUsage] | None = None) -> None:
        super().__init__(message)
        self.usage = usage or []


class FrameAnalysisError(ModelCallError): ...


class ConsolidationError(ModelCallError): ...
