import pytest

from app.domain.models import Evidence, FrameAnalysis, LineObservation, Material, UtilityType
from eval.metrics import (
    JudgedLine,
    Rate,
    ViewFacts,
    brier,
    calibration,
    expected_calibration_error,
    hallucinated_sizes,
    judge,
    main_type_found,
    summarise,
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


@pytest.mark.parametrize(
    ("line", "facts", "expected"),
    [
        (W, ViewFacts(W, owner_visible=True, other_visible=False), "correct"),
        (W, ViewFacts(W, owner_visible=False, other_visible=False), "wrong"),
        (DH, ViewFacts(W, owner_visible=True, other_visible=False), "wrong"),
        (GAS, ViewFacts(W, owner_visible=True, other_visible=False), "wrong"),
        (GAS, ViewFacts(W, owner_visible=True, other_visible=True), "unjudged"),
        (W, ViewFacts(W, owner_visible=False, other_visible=True), "unjudged"),
        (UNK, ViewFacts(W, owner_visible=True, other_visible=False), "abstain"),
    ],
)
def test_judge(line: UtilityType, facts: ViewFacts, expected: str) -> None:
    assert judge(line, facts) == expected


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


def test_main_type_found() -> None:
    visible = ViewFacts(W, owner_visible=True, other_visible=False)
    assert main_type_found(visible, [obs(GAS), obs(W)]) is True
    assert main_type_found(visible, [obs(GAS)]) is False
    assert main_type_found(ViewFacts(W, False, False), [obs(W)]) is None


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


def test_summary_counts() -> None:
    s = summarise(
        LINES, main_found=[True, True, False, None], trench_visible_reported=[True, False]
    )
    assert (s.views, s.lines, s.unjudged) == (4, 7, 1)
    assert (s.main_found.k, s.main_found.n) == (2, 3)
    assert (s.correct.k, s.correct.n) == (3, 5)
    assert (s.wrong_when_confident.k, s.wrong_when_confident.n) == (1, 2)
    assert (s.abstain.k, s.abstain.n) == (1, 7)
    assert (s.review_recall.k, s.review_recall.n) == (1, 2)
    assert (s.review_precision.k, s.review_precision.n) == (1, 2)
    assert (s.review_rate.k, s.review_rate.n) == (3, 7)
    assert (s.no_trench_reported.k, s.no_trench_reported.n) == (1, 2)


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
