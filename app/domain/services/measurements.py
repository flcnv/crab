"""Guard against invented sizes: a single image has no absolute scale without a reference."""

from app.domain.models import FrameAnalysis


def count_unscaled_measurements(analysis: FrameAnalysis) -> int:
    """Non-null diameters/depths reported although no scale reference is visible."""
    if analysis.scale_reference_visible:
        return 0
    return sum(
        (line.approx_outer_diameter_mm is not None) + (line.approx_depth_of_cover_m is not None)
        for line in analysis.lines
    )


def strip_unscaled_measurements(analysis: FrameAnalysis) -> FrameAnalysis:
    """Null out diameter and depth when no scale reference is visible.

    The prompt already asks for this; the guard makes it a hard rule, whatever the model says.
    The eval counts violations on the raw model output, before this guard.
    """
    if count_unscaled_measurements(analysis) == 0:
        return analysis
    return analysis.model_copy(
        update={
            "lines": [
                line.model_copy(
                    update={"approx_outer_diameter_mm": None, "approx_depth_of_cover_m": None}
                )
                for line in analysis.lines
            ]
        }
    )
