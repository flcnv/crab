from app.domain.models import FrameAnalysis, ReportLine

DEFAULT_LIMITATIONS: tuple[str, ...] = (
    "Semantic extraction from 2D images only; no 3D reconstruction or metric survey.",
    "Diameter and depth are only estimated when a scale reference is visible.",
    "Utility type from color is weak evidence; conventions differ by operator.",
)


def merge_lines(analyses: list[FrameAnalysis]) -> list[ReportLine]:
    """Deterministic fallback consolidation (no LLM), also used as a baseline in eval."""
    raise NotImplementedError
