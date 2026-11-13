import uuid
from datetime import UTC, datetime

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


def test_merge_lines_counts_by_max_per_frame() -> None:
    analyses = [
        frame("f001", obs(*GAS, conf=0.4), obs(*HEAT, paired=True), obs(*HEAT, paired=True)),
        frame("f002", obs(*GAS, conf=0.8)),
        frame("f003", obs(*HEAT, paired=True), obs(*HEAT, paired=True)),
    ]

    lines = merge_lines(analyses)

    heat = [ln for ln in lines if ln.utility_type is UtilityType.DISTRICT_HEATING]
    gas = [ln for ln in lines if ln.utility_type is UtilityType.GAS]
    assert len(heat) == 2  # a pair, not four pipes
    assert heat[0].seen_in_frames == ["f001", "f003"]
    assert len(gas) == 1
    assert gas[0].seen_in_frames == ["f001", "f002"]
    assert gas[0].confidence == 0.6
    assert [ln.id for ln in lines] == ["L1", "L2", "L3"]


def test_merge_lines_color_is_case_insensitive() -> None:
    lines = merge_lines(
        [frame("f001", obs(UtilityType.GAS, Material.PE, "Yellow")), frame("f002", obs(*GAS))]
    )
    assert len(lines) == 1


def _line(seen: list[str], diameter: int | None = None) -> ReportLine:
    return ReportLine(
        id="L1",
        utility_type=UtilityType.GAS,
        material=Material.PE,
        approx_outer_diameter_mm=diameter,
        approx_depth_of_cover_m=None,
        seen_in_frames=seen,
        confidence=0.7,
        notes=None,
    )


def test_check_report_lines() -> None:
    analyses = [frame("f001"), frame("f002", scale=True)]
    assert check_report_lines([_line(["f001"])], analyses) == []
    assert check_report_lines([_line(["f002"], diameter=110)], analyses) == []
    assert "unknown frame ids ['f009']" in check_report_lines([_line(["f009"])], analyses)[0]
    assert "seen_in_frames is empty" in check_report_lines([_line([])], analyses)[0]
    assert "scale reference" in check_report_lines([_line(["f001"], diameter=110)], analyses)[0]


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
        lines=[_line(["f001"])], remarks=["east end not filmed"], method="agent"
    )

    report = build_report(job, consolidation, extra_limitations=["1 of 3 frames failed"])

    assert report.job_id == job.id
    assert report.location == GeoPoint(lat=47.0, lon=8.0)
    assert report.limitations == [
        *DEFAULT_LIMITATIONS,
        "1 of 3 frames failed",
        "east end not filmed",
    ]
