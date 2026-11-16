import pytest

from app.domain.models import Evidence, FrameAnalysis, LineObservation, Material, UtilityType
from eval.metrics import (
    JudgedLine,
    Rate,
    ViewFacts,
    ViewOutcome,
    brier,
    calibration,
    expected_calibration_error,
    hallucinated_sizes,
    judge,
    main_type_found,
    main_type_invented,
    summarise,
    view_outcome,
    wilson,
)

W, DH, GAS, UNK = (
    UtilityType.WATER,
    UtilityType.DISTRICT_HEATING,
    UtilityType.GAS,
    UtilityType.UNKNOWN,
)


def test_wilson_matches_known_values() -> None:
    lo, hi = wilson(7, 10) or (0, 0)
    assert (round(lo, 2), round(hi, 2)) == (0.40, 0.89)
    assert wilson(0, 0) is None
    zero = wilson(0, 5)
    assert zero is not None
    assert zero[0] == 0.0
    assert zero[1] == pytest.approx(0.435, abs=0.001)
    assert str(Rate(7, 10)) == "7/10 = 70% [40%-89%]"
    assert str(Rate(0, 0)) == "n/a (0)"


def facts(owner: bool, other: bool, fraction: float = 0.05) -> ViewFacts:
    return ViewFacts(W, owner_visible=owner, other_visible=other, owner_fraction=fraction)


@pytest.mark.parametrize(
    ("line", "view", "expected"),
    [
        (W, facts(owner=True, other=False), "correct"),
        (W, facts(owner=False, other=False), "wrong"),
        (DH, facts(owner=True, other=False), "wrong"),
        (GAS, facts(owner=True, other=False), "wrong"),
        (GAS, facts(owner=True, other=True), "unjudged"),
        (W, facts(owner=True, other=True), "unjudged"),
        (W, facts(owner=False, other=True), "unjudged"),
        (UNK, facts(owner=True, other=False), "abstain"),
        (UNK, facts(owner=True, other=True), "abstain"),
    ],
)
def test_judge(line: UtilityType, view: ViewFacts, expected: str) -> None:
    assert judge(line, view) == expected


def obs(t: UtilityType, *, diameter: int | None = None) -> LineObservation:
    return LineObservation(
        utility_type=t,
        material=Material.UNKNOWN,
        color=None,
        approx_outer_diameter_mm=diameter,
        approx_depth_of_cover_m=None,
        is_house_connection=None,
        evidence=[Evidence(cue="shape", detail="x")],
        confidence=0.5,
    )


def test_main_type_found_and_invented() -> None:
    visible, hidden = facts(owner=True, other=True), facts(owner=False, other=True)
    assert main_type_found(visible, [obs(GAS), obs(W)]) is True
    assert main_type_found(visible, [obs(GAS)]) is False
    assert main_type_found(hidden, [obs(W)]) is None
    assert main_type_invented(hidden, [obs(GAS), obs(W)]) is True
    assert main_type_invented(hidden, [obs(GAS)]) is False
    assert main_type_invented(visible, [obs(W)]) is None


def test_failed_view_counts_as_not_found_and_not_invented() -> None:
    assert view_outcome(facts(owner=True, other=False), None) == ViewOutcome(
        facts=facts(owner=True, other=False),
        failed=True,
        main_found=False,
        main_invented=None,
        trench_reported=None,
    )
    hidden = view_outcome(facts(owner=False, other=False), None)
    assert (hidden.main_found, hidden.main_invented) == (None, None)


def jl(judgement: str, confidence: float, *, flagged: bool = False) -> JudgedLine:
    return JudgedLine("c", "top", W, confidence, judgement, flagged)  # type: ignore[arg-type]


LINES = [
    jl("correct", 0.9),
    jl("correct", 0.7),
    jl("wrong", 0.85),
    jl("wrong", 0.5, flagged=True),
    jl("correct", 0.55, flagged=True),
    jl("abstain", 0.3, flagged=True),
    jl("unjudged", 0.8),
]


def outcome(
    view: ViewFacts,
    *,
    found: bool | None = None,
    invented: bool | None = None,
    trench: bool | None = True,
    failed: bool = False,
) -> ViewOutcome:
    return ViewOutcome(view, failed, found, invented, trench)


VIEWS = [
    outcome(facts(True, False, 0.2), found=True),
    outcome(facts(True, True, 0.005), found=True),
    outcome(facts(True, True, 0.005), found=False, trench=False),
    outcome(facts(False, True, 0.0), invented=True),
    outcome(facts(True, False, 0.2), found=False, trench=None, failed=True),
]


def test_summary_counts() -> None:
    s = summarise(LINES, VIEWS)
    assert (s.views, s.failed_views, s.judgeable_views, s.lines, s.unjudged) == (5, 1, 1, 7, 1)
    assert (s.main_found.k, s.main_found.n) == (2, 4)
    assert (s.main_found_large.k, s.main_found_large.n) == (1, 2)
    assert (s.main_found_small.k, s.main_found_small.n) == (1, 2)
    assert (s.main_invented.k, s.main_invented.n) == (1, 1)
    assert (s.correct.k, s.correct.n) == (3, 5)
    assert (s.wrong_when_confident.k, s.wrong_when_confident.n) == (1, 2)
    assert (s.abstain.k, s.abstain.n) == (1, 7)
    assert (s.review_recall.k, s.review_recall.n) == (1, 2)
    assert (s.review_precision.k, s.review_precision.n) == (1, 2)
    assert (s.review_rate.k, s.review_rate.n) == (3, 7)
    assert (s.no_trench_reported.k, s.no_trench_reported.n) == (1, 4)


def test_calibration_and_scores() -> None:
    table = calibration(LINES)
    assert [b.n for b in table] == [0, 0, 2, 1, 2]
    assert table[2].accuracy == 0.5
    assert table[4].mean_confidence == pytest.approx(0.875)
    assert table[4].accuracy == 0.5
    perfect = [jl("correct", 1.0), jl("wrong", 0.0)]
    assert expected_calibration_error(calibration(perfect)) == 0
    assert brier(perfect) == 0
    assert brier([jl("wrong", 1.0)]) == 1
    assert expected_calibration_error(calibration([])) is None


def test_hallucinated_sizes_only_count_unscaled_frames() -> None:
    def frame(scale: bool) -> FrameAnalysis:
        return FrameAnalysis(
            frame_id="f",
            is_trench_visible=True,
            scale_reference_visible=scale,
            warning_tapes=[],
            lines=[obs(W, diameter=110), obs(W)],
            image_quality_issues=[],
        )

    assert hallucinated_sizes([frame(False), frame(True)]) == 1
