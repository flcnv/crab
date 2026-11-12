"""Pure domain logic: consolidation helpers, matching, confidence rules."""

from app.domain.models import FrameAnalysis, ReportLine, TrenchReport

DEFAULT_LIMITATIONS: tuple[str, ...] = (
    "Semantic extraction from 2D images only; no 3D reconstruction or metric survey.",
    "Diameter and depth are only estimated when a scale reference is visible.",
    "Utility type from color is weak evidence; conventions differ by operator.",
)


def strip_unscaled_measurements(analysis: FrameAnalysis) -> FrameAnalysis:
    """Null out diameter/depth when no scale reference is visible (guard against hallucination)."""
    raise NotImplementedError


def apply_verification_flags(report: TrenchReport, flags: list[str]) -> TrenchReport:
    """Attach flags and lower confidence of flagged lines."""
    raise NotImplementedError


def merge_lines(analyses: list[FrameAnalysis]) -> list[ReportLine]:
    """Deterministic fallback consolidation (no LLM), also used as a baseline in eval."""
    raise NotImplementedError
