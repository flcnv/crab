import uuid
from datetime import UTC, datetime

from app.adapters.render.report import render_geojson, render_markdown
from app.domain.models import (
    GeoPoint,
    Job,
    JobStatus,
    Material,
    MediaMetadata,
    ReportLine,
    ReviewFinding,
    ReviewReason,
    TrenchReport,
    UtilityType,
)

NOW = datetime(2026, 5, 1, 10, 20, tzinfo=UTC)


def _job(**metadata: object) -> Job:
    return Job(
        id=uuid.uuid4(),
        status=JobStatus.VERIFYING,
        media_kind="video",
        upload_keys=["uploads/x/000.mp4"],
        metadata=MediaMetadata(kind="video", **metadata),
        created_at=NOW,
        updated_at=NOW,
    )


def _report(job: Job, *, location: GeoPoint | None = None) -> TrenchReport:
    lines = [
        ReportLine(
            id="L1",
            utility_type=UtilityType.DISTRICT_HEATING,
            material=Material.PRE_INSULATED,
            approx_outer_diameter_mm=None,
            approx_depth_of_cover_m=None,
            seen_in_frames=["f001", "f002"],
            confidence=0.72,
            notes="pair of dark pipes | supply\nand return",
            needs_review=True,
            review=[
                ReviewFinding(reason=ReviewReason.LOW_CONFIDENCE, detail="confidence 0.72 <= 0.80"),
                ReviewFinding(
                    reason=ReviewReason.COLOR_CONTRADICTS_TYPE,
                    detail="district_heating, but f001#0 'blue' usually means water",
                ),
            ],
        ),
        ReportLine(
            id="L2",
            utility_type=UtilityType.GAS,
            material=Material.PE,
            approx_outer_diameter_mm=63,
            approx_depth_of_cover_m=0.9,
            seen_in_frames=["f003"],
            confidence=0.95,
            notes=None,
        ),
    ]
    return TrenchReport(
        job_id=job.id,
        lines=lines,
        verification_flags=["1 of 2 lines need review"],
        limitations=["No 3D reconstruction."],
        location=location,
        consolidation_method="rules",
    )


def test_markdown_report() -> None:
    job = _job(captured_at=NOW)
    md = render_markdown(
        _report(job, location=GeoPoint(lat=47.3769, lon=8.5417, accuracy_m=4.6)), job
    )

    assert md.startswith("# Trench documentation report\n")
    assert f"| Job | `{job.id}` |" in md
    assert "| Source | 1 video |" in md
    assert "| Captured | 2026-05-01 10:20 |" in md
    assert "| Location | 47.376900, 8.541700 (± 5 m) |" in md
    assert "| Consolidation | rule-based fallback (agent failed) |" in md
    assert (
        "| L1 | District heating | Pre-insulated | - | - | 72 % | "
        "⚠ low confidence, colour contradicts type | f001, f002 | "
        "pair of dark pipes \\| supply and return |" in md
    )
    assert "| L2 | Gas | PE | 63 | 0.9 | 95 % | ok | f003 | - |" in md
    assert "## Verification flags\n\n- 1 of 2 lines need review\n" in md
    assert (
        "## Needs review\n\n"
        "- **L1** (District heating)\n"
        "  - low confidence: confidence 0.72 <= 0.80\n"
        "  - colour contradicts type: district_heating, but f001#0 'blue' usually means water\n"
    ) in md
    assert "L2**" not in md  # lines without findings are not listed
    assert "## Limitations\n\n- No 3D reconstruction.\n" in md


def test_markdown_without_location_and_lines() -> None:
    job = _job()
    report = _report(job).model_copy(update={"lines": [], "verification_flags": []})
    md = render_markdown(report, job)

    assert "| Location | not available (no GPS in the upload) |" in md
    assert "No utility lines were identified." in md
    assert "Verification flags" not in md
    assert "Needs review" not in md
    assert "Captured" not in md


def test_markdown_of_report_stored_before_verification() -> None:
    job = _job()
    old = _report(job).model_copy(update={"consolidation_method": None})
    md = render_markdown(old, job)
    assert "Consolidation" not in md


def test_geojson() -> None:
    job = _job()
    assert render_geojson(_report(job)) is None

    geo = render_geojson(_report(job, location=GeoPoint(lat=47.3769, lon=8.5417)))
    assert geo is not None
    [feature] = geo["features"]
    assert feature["geometry"] == {"type": "Point", "coordinates": [8.5417, 47.3769]}
    l1, l2 = feature["properties"]["lines"]
    assert (l1["utility_type"], l2["utility_type"]) == ("district_heating", "gas")
    assert l1["needs_review"] is True
    assert [f["reason"] for f in l1["review"]] == ["low_confidence", "color_contradicts_type"]
    assert (l2["needs_review"], l2["review"]) == (False, [])
