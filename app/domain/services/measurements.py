from app.domain.models import FrameAnalysis


def strip_unscaled_measurements(analysis: FrameAnalysis) -> FrameAnalysis:
    """Null out diameter/depth when no scale reference is visible (guard against hallucination)."""
    raise NotImplementedError
