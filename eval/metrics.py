"""Eval metrics: pure functions over ground truth + predictions (no I/O, no model calls).

OpenTrench3D views (frame mode). The truth of a view is what its visible pixels show
(`eval.opentrench.ViewTruth`): the area's utility type (water or district heating) if the main
or an inactive utility of the owner is visible, plus "other utilities" of unknown type.

A predicted line is **judged** only when the data decides it:
- correct: type == the area's type, and the main or inactive utility is visible;
- wrong: a concrete type other than the area's (or the area's type although neither the main
  nor an inactive utility is visible), and **no** other utility is visible — so nothing in the
  view could be that type;
- not judged: `unknown` type (an abstention, counted separately), or a concrete other type while
  other utilities are visible (they are untyped in the dataset).

Rates come with counts and 95 % Wilson intervals; with a few dozen views they are wide.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from app.domain.models import (
    FrameAnalysis,
    LineObservation,
    ReportLine,
    UtilityType,
)

type Judgement = Literal["correct", "wrong", "abstain", "unjudged"]

CONFIDENT = 0.8  # "wrong when confident" threshold (CLAUDE.md §11.4)
CALIBRATION_BINS = 5


@dataclass(frozen=True, slots=True)
class Rate:
    k: int
    n: int

    @property
    def value(self) -> float | None:
        return self.k / self.n if self.n else None

    @property
    def interval(self) -> tuple[float, float] | None:
        return wilson(self.k, self.n)

    def __str__(self) -> str:
        if not self.n:
            return "n/a (0)"
        lo, hi = wilson(self.k, self.n) or (0.0, 0.0)
        return f"{self.k}/{self.n} = {self.k / self.n:.0%} [{lo:.0%}-{hi:.0%}]"


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    """95 % Wilson score interval for k successes out of n (None for n = 0)."""
    if n == 0:
        return None
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


@dataclass(frozen=True, slots=True)
class ViewFacts:
    """What the data says about one rendered view (from eval.opentrench.ViewTruth)."""

    main_type: UtilityType
    owner_visible: bool  # main or inactive utility of the area's type is visible
    other_visible: bool  # utilities of other owners (type unknown) are visible


def judge(line_type: UtilityType, facts: ViewFacts) -> Judgement:
    if line_type is UtilityType.UNKNOWN:
        return "abstain"
    if line_type is facts.main_type and facts.owner_visible:
        return "correct"
    if facts.other_visible:
        return "unjudged"
    return "wrong"


@dataclass(frozen=True, slots=True)
class JudgedLine:
    case_id: str
    view: str
    utility_type: UtilityType
    confidence: float
    judgement: Judgement
    flagged: bool  # needs_review after verification


def judge_lines(
    case_id: str, view: str, facts: ViewFacts, lines: Sequence[ReportLine]
) -> list[JudgedLine]:
    return [
        JudgedLine(
            case_id=case_id,
            view=view,
            utility_type=line.utility_type,
            confidence=line.confidence,
            judgement=judge(line.utility_type, facts),
            flagged=line.needs_review,
        )
        for line in lines
    ]


def main_type_found(facts: ViewFacts, observations: Sequence[LineObservation]) -> bool | None:
    """Did the model report a line of the area's type where one is visible? None if the
    owner's utility is not visible in this view (nothing to find)."""
    if not facts.owner_visible:
        return None
    return any(o.utility_type is facts.main_type for o in observations)


@dataclass(frozen=True, slots=True)
class CalibrationBin:
    lower: float
    upper: float
    n: int
    mean_confidence: float | None
    accuracy: float | None


@dataclass(frozen=True, slots=True)
class Summary:
    views: int
    lines: int
    main_found: Rate  # views where the owner's utility is visible
    correct: Rate  # of judged lines
    wrong_when_confident: Rate  # of judged lines with confidence >= CONFIDENT
    abstain: Rate  # unknown type, of all lines
    unjudged: int
    review_recall: Rate  # wrong lines that were flagged / wrong lines
    review_precision: Rate  # flagged judged lines that are wrong / flagged judged lines
    review_rate: Rate  # flagged / all lines
    calibration: list[CalibrationBin]
    ece: float | None
    brier: float | None
    no_trench_reported: Rate  # views with a visible trench where the model said "no trench"


def calibration(lines: Sequence[JudgedLine], bins: int = CALIBRATION_BINS) -> list[CalibrationBin]:
    judged = [ln for ln in lines if ln.judgement in ("correct", "wrong")]
    out = []
    for i in range(bins):
        lower, upper = i / bins, (i + 1) / bins
        inside = [
            ln
            for ln in judged
            if lower <= ln.confidence < upper or (i == bins - 1 and ln.confidence == 1.0)
        ]
        out.append(
            CalibrationBin(
                lower=lower,
                upper=upper,
                n=len(inside),
                mean_confidence=(
                    sum(ln.confidence for ln in inside) / len(inside) if inside else None
                ),
                accuracy=(
                    sum(ln.judgement == "correct" for ln in inside) / len(inside)
                    if inside
                    else None
                ),
            )
        )
    return out


def expected_calibration_error(table: Sequence[CalibrationBin]) -> float | None:
    total = sum(b.n for b in table)
    if not total:
        return None
    return sum(
        b.n / total * abs((b.accuracy or 0.0) - (b.mean_confidence or 0.0)) for b in table if b.n
    )


def brier(lines: Sequence[JudgedLine]) -> float | None:
    judged = [ln for ln in lines if ln.judgement in ("correct", "wrong")]
    if not judged:
        return None
    return sum(
        (ln.confidence - (1.0 if ln.judgement == "correct" else 0.0)) ** 2 for ln in judged
    ) / len(judged)


def summarise(
    lines: Sequence[JudgedLine],
    main_found: Sequence[bool | None],
    trench_visible_reported: Sequence[bool],
) -> Summary:
    judged = [ln for ln in lines if ln.judgement in ("correct", "wrong")]
    wrong = [ln for ln in judged if ln.judgement == "wrong"]
    flagged_judged = [ln for ln in judged if ln.flagged]
    confident = [ln for ln in judged if ln.confidence >= CONFIDENT]
    found = [f for f in main_found if f is not None]
    table = calibration(lines)
    return Summary(
        views=len(main_found),
        lines=len(lines),
        main_found=Rate(sum(found), len(found)),
        correct=Rate(len(judged) - len(wrong), len(judged)),
        wrong_when_confident=Rate(sum(ln.judgement == "wrong" for ln in confident), len(confident)),
        abstain=Rate(sum(ln.judgement == "abstain" for ln in lines), len(lines)),
        unjudged=sum(ln.judgement == "unjudged" for ln in lines),
        review_recall=Rate(sum(ln.flagged for ln in wrong), len(wrong)),
        review_precision=Rate(
            sum(ln.judgement == "wrong" for ln in flagged_judged), len(flagged_judged)
        ),
        review_rate=Rate(sum(ln.flagged for ln in lines), len(lines)),
        calibration=table,
        ece=expected_calibration_error(table),
        brier=brier(lines),
        no_trench_reported=Rate(
            sum(not seen for seen in trench_visible_reported), len(trench_visible_reported)
        ),
    )


def hallucinated_sizes(raw: Sequence[FrameAnalysis]) -> int:
    """Sizes the model returned without a visible scale reference (raw output, before the
    pipeline strips them)."""
    return sum(
        (o.approx_outer_diameter_mm is not None) + (o.approx_depth_of_cover_m is not None)
        for a in raw
        if not a.scale_reference_visible
        for o in a.lines
    )
