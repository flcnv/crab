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

CONFIDENT = 0.8
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
    if n == 0:
        return None
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


LARGE_OWNER_FRACTION = 0.01


@dataclass(frozen=True, slots=True)
class ViewFacts:
    main_type: UtilityType
    owner_visible: bool
    other_visible: bool
    owner_fraction: float

    @property
    def lines_judgeable(self) -> bool:
        return not self.other_visible


def judge(line_type: UtilityType, facts: ViewFacts) -> Judgement:
    if line_type is UtilityType.UNKNOWN:
        return "abstain"
    if not facts.lines_judgeable:
        return "unjudged"
    if line_type is facts.main_type and facts.owner_visible:
        return "correct"
    return "wrong"


@dataclass(frozen=True, slots=True)
class JudgedLine:
    case_id: str
    view: str
    utility_type: UtilityType
    confidence: float
    judgement: Judgement
    flagged: bool


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
    if not facts.owner_visible:
        return None
    return any(o.utility_type is facts.main_type for o in observations)


def main_type_invented(facts: ViewFacts, observations: Sequence[LineObservation]) -> bool | None:
    if facts.owner_visible:
        return None
    return any(o.utility_type is facts.main_type for o in observations)


@dataclass(frozen=True, slots=True)
class ViewOutcome:
    facts: ViewFacts
    failed: bool
    main_found: bool | None
    main_invented: bool | None
    trench_reported: bool | None


def view_outcome(facts: ViewFacts, raw: FrameAnalysis | None) -> ViewOutcome:
    if raw is None:
        return ViewOutcome(
            facts=facts,
            failed=True,
            main_found=False if facts.owner_visible else None,
            main_invented=None,
            trench_reported=None,
        )
    return ViewOutcome(
        facts=facts,
        failed=False,
        main_found=main_type_found(facts, raw.lines),
        main_invented=main_type_invented(facts, raw.lines),
        trench_reported=raw.is_trench_visible,
    )


def _rate(flags: Sequence[bool | None]) -> Rate:
    known = [f for f in flags if f is not None]
    return Rate(sum(known), len(known))


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
    failed_views: int
    judgeable_views: int
    lines: int
    main_found: Rate
    main_found_large: Rate
    main_found_small: Rate
    main_invented: Rate
    correct: Rate
    wrong_when_confident: Rate
    abstain: Rate
    unjudged: int
    review_recall: Rate
    review_precision: Rate
    review_rate: Rate
    calibration: list[CalibrationBin]
    ece: float | None
    brier: float | None
    no_trench_reported: Rate


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


def summarise(lines: Sequence[JudgedLine], views: Sequence[ViewOutcome]) -> Summary:
    judged = [ln for ln in lines if ln.judgement in ("correct", "wrong")]
    wrong = [ln for ln in judged if ln.judgement == "wrong"]
    flagged_judged = [ln for ln in judged if ln.flagged]
    confident = [ln for ln in judged if ln.confidence >= CONFIDENT]
    table = calibration(lines)
    large = [v for v in views if v.facts.owner_fraction >= LARGE_OWNER_FRACTION]
    small = [v for v in views if v.facts.owner_fraction < LARGE_OWNER_FRACTION]
    return Summary(
        views=len(views),
        failed_views=sum(v.failed for v in views),
        judgeable_views=sum(v.facts.lines_judgeable and not v.failed for v in views),
        lines=len(lines),
        main_found=_rate([v.main_found for v in views]),
        main_found_large=_rate([v.main_found for v in large]),
        main_found_small=_rate([v.main_found for v in small]),
        main_invented=_rate([v.main_invented for v in views]),
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
        no_trench_reported=_rate(
            [None if v.trench_reported is None else not v.trench_reported for v in views]
        ),
    )


def hallucinated_sizes(raw: Sequence[FrameAnalysis]) -> int:
    return sum(
        (o.approx_outer_diameter_mm is not None) + (o.approx_depth_of_cover_m is not None)
        for a in raw
        if not a.scale_reference_visible
        for o in a.lines
    )
