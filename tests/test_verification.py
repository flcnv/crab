"""Verification rules: one positive, one negative and the threshold edge per rule."""

import uuid

from app.domain.models import (
    Evidence,
    FrameAnalysis,
    LineObservation,
    Material,
    ObservationRef,
    ReportLine,
    ReviewFinding,
    ReviewReason,
    TrenchReport,
    UtilityType,
    VerificationConfig,
)
from app.domain.services.verification import (
    color_contradicts_type,
    conflicting_types,
    line_evidence,
    low_confidence,
    single_frame_only,
    size_inconsistent,
    size_without_scale,
    unknown_material,
    unknown_type,
    verify_report,
)

CONFIG = VerificationConfig()  # min_confidence 0.6, size_tolerance 0.15


def obs(
    utility: UtilityType = UtilityType.GAS,
    color: str | None = "yellow",
    *,
    diameter: int | None = None,
    depth: float | None = None,
) -> LineObservation:
    return LineObservation(
        utility_type=utility,
        material=Material.PE,
        color=color,
        approx_outer_diameter_mm=diameter,
        approx_depth_of_cover_m=depth,
        is_house_connection=None,
        evidence=[Evidence(cue="color", detail=color or "-")],
        confidence=0.9,
    )


def frame(frame_id: str, *lines: LineObservation, scale: bool = False) -> FrameAnalysis:
    return FrameAnalysis(
        frame_id=frame_id,
        is_trench_visible=True,
        scale_reference_visible=scale,
        warning_tapes=[],
        lines=list(lines),
        image_quality_issues=[],
    )


def refs(*labels: str) -> list[ObservationRef]:
    return [
        ObservationRef(frame_id=f, line_index=int(i)) for f, i in (x.split("#") for x in labels)
    ]


def line(
    *labels: str,
    utility: UtilityType = UtilityType.GAS,
    material: Material = Material.PE,
    confidence: float = 0.9,
    diameter: int | None = None,
    depth: float | None = None,
    line_id: str = "L1",
) -> ReportLine:
    return ReportLine(
        id=line_id,
        utility_type=utility,
        material=material,
        approx_outer_diameter_mm=diameter,
        approx_depth_of_cover_m=depth,
        observations=refs(*labels),
        confidence=confidence,
        notes=None,
    )


def frames(*analyses: FrameAnalysis) -> dict[str, FrameAnalysis]:
    return {a.frame_id: a for a in analyses}


# --- low_confidence ------------------------------------------------------------------------


def test_low_confidence() -> None:
    finding = low_confidence(line("f001#0", confidence=0.4), CONFIG)
    assert finding == ReviewFinding(
        reason=ReviewReason.LOW_CONFIDENCE, detail="confidence 0.40 <= 0.60"
    )
    assert low_confidence(line("f001#0", confidence=0.61), CONFIG) is None


def test_low_confidence_threshold_is_inclusive() -> None:
    assert low_confidence(line("f001#0", confidence=0.6), CONFIG) is not None


# --- unknown_type / unknown_material -------------------------------------------------------


def test_unknown_type() -> None:
    assert unknown_type(line("f001#0", utility=UtilityType.UNKNOWN)) is not None
    assert unknown_type(line("f001#0")) is None


def test_unknown_material() -> None:
    assert unknown_material(line("f001#0", material=Material.UNKNOWN)) is not None
    assert unknown_material(line("f001#0")) is None


# --- conflicting_types ---------------------------------------------------------------------


def test_conflicting_types() -> None:
    fs = frames(frame("f001", obs(UtilityType.GAS)), frame("f002", obs(UtilityType.WATER)))
    finding = conflicting_types(line_evidence(line("f001#0", "f002#0"), fs))
    assert finding is not None
    assert finding.detail == "observations disagree: f001#0 gas, f002#0 water"


def test_agreeing_types_do_not_conflict() -> None:
    fs = frames(frame("f001", obs()), frame("f002", obs()))
    assert conflicting_types(line_evidence(line("f001#0", "f002#0"), fs)) is None


def test_unknown_observation_is_not_a_conflict() -> None:
    fs = frames(frame("f001", obs()), frame("f002", obs(UtilityType.UNKNOWN, None)))
    assert conflicting_types(line_evidence(line("f001#0", "f002#0"), fs)) is None


# --- size_inconsistent ---------------------------------------------------------------------


def test_size_inconsistent_diameter() -> None:
    fs = frames(
        frame("f001", obs(diameter=100), scale=True),
        frame("f002", obs(diameter=140), scale=True),
    )
    finding = size_inconsistent(line_evidence(line("f001#0", "f002#0"), fs), CONFIG)
    assert finding is not None
    assert finding.detail == "diameter 100-140 mm across frames (spread 33% > 15%)"


def test_size_inconsistent_depth_is_checked_separately() -> None:
    fs = frames(
        frame("f001", obs(diameter=110, depth=0.8), scale=True),
        frame("f002", obs(diameter=110, depth=1.2), scale=True),
    )
    finding = size_inconsistent(line_evidence(line("f001#0", "f002#0"), fs), CONFIG)
    assert finding is not None
    assert finding.detail.startswith("depth of cover 0.8-1.2 m")


def test_size_spread_exactly_at_tolerance_is_consistent() -> None:
    # 100, 100, 115: median 100, spread (115 - 100) / 100 = exactly 15 % -> not over
    fs = frames(
        frame("f001", obs(diameter=100), scale=True),
        frame("f002", obs(diameter=100), scale=True),
        frame("f003", obs(diameter=115), scale=True),
    )
    evidence = line_evidence(line("f001#0", "f002#0", "f003#0"), fs)
    assert size_inconsistent(evidence, CONFIG) is None
    assert size_inconsistent(evidence, VerificationConfig(size_tolerance=0.149)) is not None


def test_size_inconsistent_ignores_unscaled_frames_and_single_values() -> None:
    fs = frames(
        frame("f001", obs(diameter=100), scale=True),
        frame("f002", obs(diameter=300)),  # no scale reference: not comparable
    )
    assert size_inconsistent(line_evidence(line("f001#0", "f002#0"), fs), CONFIG) is None


# --- size_without_scale --------------------------------------------------------------------


def test_size_without_scale() -> None:
    fs = frames(frame("f001", obs()))
    finding = size_without_scale(line_evidence(line("f001#0", diameter=110), fs))
    assert finding is not None


def test_size_with_scale_or_no_size_is_fine() -> None:
    scaled = frames(frame("f001", obs(), scale=True))
    assert size_without_scale(line_evidence(line("f001#0", diameter=110), scaled)) is None
    unscaled = frames(frame("f001", obs()))
    assert size_without_scale(line_evidence(line("f001#0"), unscaled)) is None


# --- color_contradicts_type ----------------------------------------------------------------


def test_color_contradicts_type() -> None:
    fs = frames(frame("f001", obs(color="blue")))
    finding = color_contradicts_type(line_evidence(line("f001#0"), fs))  # gas line
    assert finding is not None
    assert finding.detail == (
        "gas, but f001#0 'blue' usually means water (colour table: heuristic)"
    )


def test_matching_or_ambiguous_colour_is_fine() -> None:
    fs = frames(frame("f001", obs(color="yellow"), obs(color="black")))
    assert color_contradicts_type(line_evidence(line("f001#0", "f001#1"), fs)) is None


def test_unknown_type_line_is_not_checked_against_colour() -> None:
    fs = frames(frame("f001", obs(color="blue")))
    evidence = line_evidence(line("f001#0", utility=UtilityType.UNKNOWN), fs)
    assert color_contradicts_type(evidence) is None


# --- single_frame_only ---------------------------------------------------------------------


def test_single_frame_only_in_video() -> None:
    finding = single_frame_only(line("f004#0"), "video")
    assert finding is not None
    assert finding.detail == "seen in one keyframe only (f004)"


def test_single_frame_is_normal_for_photos_and_two_frames_are_enough() -> None:
    assert single_frame_only(line("f004#0"), "image") is None
    assert single_frame_only(line("f004#0", "f005#1"), "video") is None


# --- verify_report -------------------------------------------------------------------------


ANALYSES = [
    frame("f001", obs(), obs(UtilityType.WATER, "blue")),
    frame("f002", obs(), obs(UtilityType.GAS, "blue")),
]


def report(*lines: ReportLine) -> TrenchReport:
    return TrenchReport(
        job_id=uuid.uuid4(),
        lines=list(lines),
        verification_flags=[],
        limitations=["l"],
        location=None,
        consolidation_method="agent",
    )


def test_verify_report_flags_lines_in_enum_order() -> None:
    clean = line("f001#0", "f002#0")
    doubtful = line(
        "f001#1",
        "f002#1",
        utility=UtilityType.WATER,
        material=Material.UNKNOWN,
        confidence=0.5,
        line_id="L2",
    )

    result = verify_report(report(clean, doubtful), ANALYSES, CONFIG, media_kind="video")

    ok, flagged = result.lines
    assert (ok.needs_review, ok.review) == (False, [])
    assert flagged.needs_review is True
    assert [f.reason for f in flagged.review] == [
        ReviewReason.LOW_CONFIDENCE,
        ReviewReason.UNKNOWN_MATERIAL,
        ReviewReason.CONFLICTING_TYPES,  # f002#1 says gas
    ]
    assert result.verification_flags == ["1 of 2 lines need review"]


def test_verify_report_without_findings_has_no_flags() -> None:
    result = verify_report(report(line("f001#0", "f002#0")), ANALYSES, CONFIG, media_kind="video")
    assert result.verification_flags == []


def test_verify_report_is_idempotent_and_recomputes_from_scratch() -> None:
    stale = line("f001#0", "f002#0").model_copy(
        update={
            "needs_review": True,
            "review": [ReviewFinding(reason=ReviewReason.UNKNOWN_TYPE, detail="old")],
        }
    )
    original = report(stale, line("f001#1", confidence=0.3, line_id="L2"))

    once = verify_report(original, ANALYSES, CONFIG, media_kind="video")
    twice = verify_report(once, ANALYSES, CONFIG, media_kind="video")

    assert once == twice
    assert once.lines[0].review == []  # stale finding is gone, not kept
    assert once.verification_flags == ["1 of 2 lines need review"]


def test_verify_report_only_writes_review_fields() -> None:
    original = report(line("f001#1", utility=UtilityType.WATER, confidence=0.3))
    result = verify_report(original, ANALYSES, CONFIG, media_kind="video")

    untouched = {"needs_review", "review"}
    before = original.lines[0].model_dump(exclude=untouched)
    assert result.lines[0].model_dump(exclude=untouched) == before
    assert result.model_dump(exclude={"lines", "verification_flags"}) == original.model_dump(
        exclude={"lines", "verification_flags"}
    )


def test_verify_report_handles_reports_stored_before_refs() -> None:
    old = ReportLine(
        id="L1",
        utility_type=UtilityType.GAS,
        material=Material.PE,
        approx_outer_diameter_mm=None,
        approx_depth_of_cover_m=None,
        seen_in_frames=["f001"],
        confidence=0.9,
        notes=None,
    )
    result = verify_report(report(old), ANALYSES, CONFIG, media_kind="video")
    assert [f.reason for f in result.lines[0].review] == [ReviewReason.SINGLE_FRAME_ONLY]


def test_unresolvable_refs_are_skipped_not_fatal() -> None:
    dangling = line("f009#0", "f001#7", confidence=0.9)
    result = verify_report(report(dangling), ANALYSES, CONFIG, media_kind="video")
    assert result.lines[0].review == []  # nothing resolvable to judge, and no crash
