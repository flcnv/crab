from pathlib import Path

import cv2
import numpy as np
import pytest

from app.domain.errors import FrameAnalysisError
from app.domain.models import (
    Evidence,
    FrameAnalysis,
    LineObservation,
    LLMUsage,
    Material,
    UtilityType,
    VerificationConfig,
)
from eval.opentrench import OpenTrenchCase, ViewTruth
from eval.run_eval import estimate_cost, plan, run_views, score, to_markdown

USAGE = LLMUsage(
    model="fake", prompt_version="v1", input_tokens=1, output_tokens=1, cost_usd=0.01, latency_s=0
)


def view(file: str, name: str, *, main: bool = True, other: bool = False) -> ViewTruth:
    return ViewTruth(
        file=file,
        view=name,
        main_visible=main,
        other_visible=other,
        inactive_visible=False,
        fractions={0: 0.1, 1: 0.01 if other else 0.0},
    )


def case(case_id: str, split: str, *views: ViewTruth) -> OpenTrenchCase:
    return OpenTrenchCase(
        case_id=case_id,
        source=f"x/{case_id}.ply",
        area="Water_Area_1",
        main_type=UtilityType.WATER,
        split=split,
        views=list(views),
    )


def line(
    t: UtilityType, color: str, confidence: float, diameter: int | None = None
) -> LineObservation:
    return LineObservation(
        utility_type=t,
        material=Material.PE,
        color=color,
        approx_outer_diameter_mm=diameter,
        approx_depth_of_cover_m=None,
        is_house_connection=None,
        evidence=[Evidence(cue="color", detail=color)],
        confidence=confidence,
    )


class FakeVision:
    async def analyze(self, image: bytes, frame_id: str) -> tuple[FrameAnalysis, list[LLMUsage]]:
        if frame_id.endswith(":left"):
            raise FrameAnalysisError("model refused", [USAGE])
        analysis = FrameAnalysis(
            frame_id=frame_id,
            is_trench_visible=True,
            scale_reference_visible=False,
            warning_tapes=[],
            lines=[
                line(UtilityType.WATER, "blue", 0.9, diameter=110),
                line(UtilityType.GAS, "black", 0.85),
            ],
            image_quality_issues=[],
        )
        return analysis, [USAGE]


@pytest.fixture
def renders(tmp_path: Path) -> Path:
    for name in ("c1_top.jpg", "c1_left.jpg", "c2_top.jpg"):
        cv2.imwrite(str(tmp_path / name), np.full((300, 600, 3), 120, np.uint8))
    return tmp_path


CASES = [
    case("c1", "dev", view("c1_top.jpg", "top"), view("c1_left.jpg", "left")),
    case("c2", "test", view("c2_top.jpg", "top")),
]


def test_plan_filters_split_and_limit() -> None:
    assert [(v.case.case_id, v.view) for v in plan(CASES, "dev")] == [("c1", "top"), ("c1", "left")]
    assert len(plan(CASES, "dev", limit=1)) == 1
    assert [v.view for v in plan(CASES, "test")] == ["top"]


def test_estimate_cost_is_positive_for_a_priced_model(renders: Path) -> None:
    calls, usd = estimate_cost(plan(CASES, "dev"), "claude-sonnet-5-5", "v1", 1500, renders)
    assert calls == 2
    assert 0 < usd < 0.1


async def test_run_and_score(renders: Path) -> None:
    results = await run_views(
        plan(CASES, "dev"), FakeVision(), VerificationConfig(), max_edge=1500, render_dir=renders
    )
    top, left = results
    assert left.error == "model refused"
    assert left.usage == [USAGE]
    assert top.raw is not None
    assert top.raw.lines[0].approx_outer_diameter_mm == 110
    assert all(ln.approx_outer_diameter_mm is None for ln in top.lines)

    summary, judged = score(results)
    assert (summary.correct.k, summary.correct.n) == (1, 2)
    assert (summary.wrong_when_confident.k, summary.wrong_when_confident.n) == (1, 2)
    assert (summary.review_recall.k, summary.review_recall.n) == (0, 1)
    assert (summary.main_found.k, summary.main_found.n) == (1, 2)

    md = to_markdown({"split": "dev", "model": "fake"}, summary, judged, results)
    assert "2 views (1 failed)" in md
    assert "| c1 / top | gas | 0.85 | **not flagged** |" in md
    assert "Not measurable" not in md


async def test_views_with_other_utilities_are_not_judged_line_by_line(renders: Path) -> None:
    cases = [case("c3", "test", view("c2_top.jpg", "top", other=True))]
    results = await run_views(
        plan(cases, "test"), FakeVision(), VerificationConfig(), max_edge=1500, render_dir=renders
    )
    summary, judged = score(results)
    assert results[0].owner_fraction == 0.1
    assert summary.judgeable_views == 0
    assert (summary.correct.k, summary.correct.n) == (0, 0)
    assert summary.unjudged == 2
    assert (summary.main_found.k, summary.main_found.n) == (1, 1)
    assert (summary.main_found_large.k, summary.main_found_large.n) == (1, 1)

    md = to_markdown({"split": "test", "model": "fake"}, summary, judged, results)
    assert "Not measurable on this split" in md
    assert "ECE" not in md
