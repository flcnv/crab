from app.domain.models import Evidence, FrameAnalysis, LineObservation, Material, UtilityType
from app.domain.services import count_unscaled_measurements, strip_unscaled_measurements


def _analysis(
    *, scale: bool, diameter: int | None = 110, depth: float | None = 1.2
) -> FrameAnalysis:
    line = LineObservation(
        utility_type=UtilityType.WATER,
        material=Material.PE,
        color="blue",
        approx_outer_diameter_mm=diameter,
        approx_depth_of_cover_m=depth,
        is_house_connection=None,
        evidence=[Evidence(cue="color", detail="blue jacket")],
        confidence=0.5,
    )
    return FrameAnalysis(
        frame_id="f001",
        is_trench_visible=True,
        scale_reference_visible=scale,
        warning_tapes=[],
        lines=[line, line],
        image_quality_issues=[],
    )


def test_strips_sizes_without_scale_reference() -> None:
    raw = _analysis(scale=False)
    assert count_unscaled_measurements(raw) == 4

    guarded = strip_unscaled_measurements(raw)

    assert count_unscaled_measurements(guarded) == 0
    assert all(
        (line.approx_outer_diameter_mm, line.approx_depth_of_cover_m) == (None, None)
        for line in guarded.lines
    )
    assert guarded.lines[0].color == "blue"  # everything else untouched
    assert raw.lines[0].approx_outer_diameter_mm == 110  # input not mutated


def test_keeps_sizes_with_scale_reference() -> None:
    raw = _analysis(scale=True)
    assert count_unscaled_measurements(raw) == 0
    assert strip_unscaled_measurements(raw) is raw


def test_counts_only_non_null_values() -> None:
    assert count_unscaled_measurements(_analysis(scale=False, diameter=None)) == 2
