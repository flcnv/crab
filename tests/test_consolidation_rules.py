import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.domain.models import (
    Consolidation,
    Evidence,
    FrameAnalysis,
    GeoPoint,
    Job,
    JobStatus,
    LineObservation,
    Material,
    MediaMetadata,
    ObservationRef,
    ReportLine,
    UtilityType,
)
from app.domain.services import DEFAULT_LIMITATIONS, build_report, check_report_lines, merge_lines


def obs(
    utility: UtilityType, material: Material, color: str, *, paired: bool = False, conf: float = 0.6
) -> LineObservation:
    return LineObservation(
        utility_type=utility,
        material=material,
        color=color,
        approx_outer_diameter_mm=None,
        approx_depth_of_cover_m=None,
        is_house_connection=None,
        evidence=[Evidence(cue="color", detail=color)],
        confidence=conf,
        is_paired=paired,
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


GAS = (UtilityType.GAS, Material.PE, "yellow")
HEAT = (UtilityType.DISTRICT_HEATING, Material.PRE_INSULATED, "black")


def refs(*labels: str) -> list[ObservationRef]:
    out = []
    for label in labels:
        frame_id, index = label.split("#")
        out.append(ObservationRef(frame_id=frame_id, line_index=int(index)))
    return out


def test_merge_lines_counts_by_max_per_frame() -> None:
    analyses = [
        frame("f001", obs(*GAS, conf=0.4), obs(*HEAT, paired=True), obs(*HEAT, paired=True)),
        frame("f002", obs(*GAS, conf=0.8)),
        frame("f003", obs(*HEAT, paired=True), obs(*HEAT, paired=True)),
    ]

    lines = merge_lines(analyses)

    heat = [ln for ln in lines if ln.utility_type is UtilityType.DISTRICT_HEATING]
    gas = [ln for ln in lines if ln.utility_type is UtilityType.GAS]
    assert len(heat) == 2
    assert heat[0].seen_in_frames == ["f001", "f003"]
    assert len(gas) == 1
    assert gas[0].seen_in_frames == ["f001", "f002"]
    assert gas[0].confidence == 0.6
    assert [ln.id for ln in lines] == ["L1", "L2", "L3"]


def test_merge_lines_assigns_kth_observation_to_kth_line() -> None:
    analyses = [
        frame("f001", obs(*GAS, conf=0.4), obs(*HEAT, paired=True), obs(*HEAT, paired=True)),
        frame("f002", obs(*GAS, conf=0.8)),
        frame("f003", obs(*HEAT, paired=True), obs(*HEAT, paired=True)),
    ]

    l1, l2, l3 = merge_lines(analyses)

    assert l1.observations == refs("f001#1", "f003#0")
    assert l2.observations == refs("f001#2", "f003#1")
    assert l3.observations == refs("f001#0", "f002#0")
    assert check_report_lines([l1, l2, l3], analyses) == []


def test_merge_lines_extra_copy_only_has_its_own_observations() -> None:
    analyses = [
        frame("f001", obs(*GAS, conf=0.4), obs(*GAS, conf=0.9)),
        frame("f002", obs(*GAS, conf=0.6)),
    ]

    first, second = merge_lines(analyses)

    assert first.observations == refs("f001#0", "f002#0")
    assert first.confidence == 0.5
    assert second.observations == refs("f001#1")
    assert second.seen_in_frames == ["f001"]
    assert second.confidence == 0.9


def test_merge_lines_color_is_case_insensitive() -> None:
    lines = merge_lines(
        [frame("f001", obs(UtilityType.GAS, Material.PE, "Yellow")), frame("f002", obs(*GAS))]
    )
    assert len(lines) == 1


def _line(
    observations: list[ObservationRef], diameter: int | None = None, line_id: str = "L1"
) -> ReportLine:
    return ReportLine(
        id=line_id,
        utility_type=UtilityType.GAS,
        material=Material.PE,
        approx_outer_diameter_mm=diameter,
        approx_depth_of_cover_m=None,
        observations=observations,
        confidence=0.7,
        notes=None,
    )


def test_seen_in_frames_is_derived_from_observations() -> None:
    line = _line(refs("f002#0", "f001#1", "f002#1"))
    assert line.seen_in_frames == ["f001", "f002"]


def test_seen_in_frames_contradicting_observations_is_rejected() -> None:
    with pytest.raises(ValidationError, match="does not match observations"):
        ReportLine.model_validate(
            {**_line(refs("f001#0")).model_dump(), "seen_in_frames": ["f009"]}
        )


def test_report_line_stored_before_refs_still_loads() -> None:
    old = {
        "id": "L1",
        "utility_type": "gas",
        "material": "pe",
        "approx_outer_diameter_mm": None,
        "approx_depth_of_cover_m": None,
        "seen_in_frames": ["f001", "f002"],
        "confidence": 0.7,
        "notes": None,
    }
    line = ReportLine.model_validate(old)
    assert line.observations == []
    assert line.seen_in_frames == ["f001", "f002"]


def test_check_report_lines_accepts_consistent_lines() -> None:
    analyses = [frame("f001", obs(*GAS)), frame("f002", obs(*GAS), scale=True)]
    assert check_report_lines([_line(refs("f001#0", "f002#0"))], analyses) == []
    assert check_report_lines([_line(refs("f002#0"), diameter=110)], analyses) == []


def test_check_report_lines_rejects_bad_refs() -> None:
    analyses = [frame("f001", obs(*GAS)), frame("f002", obs(*GAS), scale=True)]

    def problems(*lines: ReportLine) -> list[str]:
        return check_report_lines(lines, analyses)

    assert problems(_line([])) == ["L1: no observations referenced"]
    assert problems(_line(refs("f001#0", "f009#0"))) == ["L1: unknown frame ids ['f009']"]
    assert problems(_line(refs("f001#1"))) == ["L1: f001#1 does not exist (frame f001 has 1 lines)"]
    assert problems(_line(refs("f001#0")), _line(refs("f001#0", "f002#0"), line_id="L2")) == [
        "L2: observation f001#0 is already used by L1"
    ]
    assert problems(_line(refs("f001#0", "f001#0", "f002#0"))) == [
        "L1: observation f001#0 is listed twice"
    ]
    assert "scale reference" in problems(_line(refs("f001#0"), diameter=110))[0]


def test_build_report() -> None:
    now = datetime.now(UTC)
    job = Job(
        id=uuid.uuid4(),
        status=JobStatus.CONSOLIDATING,
        media_kind="video",
        upload_keys=["a.mp4"],
        metadata=MediaMetadata(kind="video", location=GeoPoint(lat=47.0, lon=8.0)),
        created_at=now,
        updated_at=now,
    )
    consolidation = Consolidation(
        lines=[_line(refs("f001#0"))], remarks=["east end not filmed"], method="agent"
    )

    report = build_report(job, consolidation, extra_limitations=["1 of 3 frames failed"])

    assert report.job_id == job.id
    assert report.location == GeoPoint(lat=47.0, lon=8.0)
    assert report.consolidation_method == "agent"
    assert report.verification_flags == []
    assert report.limitations == [
        *DEFAULT_LIMITATIONS,
        "1 of 3 frames failed",
        "east end not filmed",
    ]
