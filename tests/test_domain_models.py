import uuid

import pytest
from pydantic import ValidationError

from app.domain.models import (
    Consolidation,
    LineObservation,
    Material,
    ReportLine,
    ReviewFinding,
    ReviewReason,
    TrenchReport,
    UtilityType,
    VerificationConfig,
)


def test_line_requires_evidence() -> None:
    with pytest.raises(ValidationError):
        LineObservation(
            utility_type=UtilityType.GAS,
            material=Material.PE,
            color="yellow",
            approx_outer_diameter_mm=None,
            approx_depth_of_cover_m=None,
            is_house_connection=None,
            evidence=[],
            confidence=0.5,
        )


LINE = {
    "id": "L1",
    "utility_type": "gas",
    "material": "pe",
    "approx_outer_diameter_mm": None,
    "approx_depth_of_cover_m": None,
    "seen_in_frames": ["f001"],
    "confidence": 0.5,
    "notes": None,
}
LOW = ReviewFinding(reason=ReviewReason.LOW_CONFIDENCE, detail="confidence 0.50 <= 0.60")


def test_review_reasons_are_listed_in_the_agreed_order() -> None:
    assert list(ReviewReason) == [
        "low_confidence",
        "unknown_type",
        "unknown_material",
        "conflicting_types",
        "size_inconsistent",
        "size_without_scale",
        "color_contradicts_type",
        "single_frame_only",
    ]


def test_line_with_findings_needs_review() -> None:
    line = ReportLine.model_validate({**LINE, "needs_review": True, "review": [LOW]})
    assert line.review == [LOW]


@pytest.mark.parametrize(("needs_review", "review"), [(True, []), (False, [LOW.model_dump()])])
def test_needs_review_must_match_findings(needs_review: bool, review: list[object]) -> None:
    with pytest.raises(ValidationError, match="needs_review must be true exactly when"):
        ReportLine.model_validate({**LINE, "needs_review": needs_review, "review": review})


def test_report_stored_before_reviews_still_loads() -> None:
    old = {
        "job_id": str(uuid.uuid4()),
        "lines": [LINE],
        "verification_flags": [],
        "limitations": [],
        "location": None,
    }
    report = TrenchReport.model_validate(old)
    assert report.consolidation_method is None
    assert (report.lines[0].needs_review, report.lines[0].review) == (False, [])


def test_consolidation_method_is_agent_or_rules() -> None:
    with pytest.raises(ValidationError):
        Consolidation.model_validate({"lines": [], "method": "magic"})


def test_verification_config_defaults_and_bounds() -> None:
    assert VerificationConfig() == VerificationConfig(min_confidence=0.6, size_tolerance=0.15)
    with pytest.raises(ValidationError):
        VerificationConfig(min_confidence=1.5)
    with pytest.raises(ValidationError):
        VerificationConfig(size_tolerance=-0.1)
