from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from statistics import median

from app.domain.models import (
    FrameAnalysis,
    LineObservation,
    Material,
    MediaKind,
    ObservationRef,
    ReportLine,
    ReviewFinding,
    ReviewReason,
    TrenchReport,
    UtilityType,
    VerificationConfig,
)
from app.domain.services.conventions import COLOR_CONVENTIONS_SOURCE, expected_types


@dataclass(frozen=True, slots=True)
class LineEvidence:
    line: ReportLine
    observations: tuple[tuple[ObservationRef, LineObservation], ...]
    scaled_frames: frozenset[str]


def frames_of(line: ReportLine) -> list[str]:
    if line.observations:
        return sorted({ref.frame_id for ref in line.observations})
    return list(line.seen_in_frames)


def line_evidence(line: ReportLine, frames: Mapping[str, FrameAnalysis]) -> LineEvidence:
    resolved = tuple(
        (ref, frames[ref.frame_id].lines[ref.line_index])
        for ref in line.observations
        if ref.frame_id in frames and ref.line_index < len(frames[ref.frame_id].lines)
    )
    scaled = frozenset(
        f for f in frames_of(line) if f in frames and frames[f].scale_reference_visible
    )
    return LineEvidence(line=line, observations=resolved, scaled_frames=scaled)


def low_confidence(line: ReportLine, config: VerificationConfig) -> ReviewFinding | None:
    if line.confidence > config.min_confidence:
        return None
    return ReviewFinding(
        reason=ReviewReason.LOW_CONFIDENCE,
        detail=f"confidence {line.confidence:.2f} <= {config.min_confidence:.2f}",
    )


def unknown_type(line: ReportLine) -> ReviewFinding | None:
    if line.utility_type is not UtilityType.UNKNOWN:
        return None
    return ReviewFinding(reason=ReviewReason.UNKNOWN_TYPE, detail="utility type is unknown")


def unknown_material(line: ReportLine) -> ReviewFinding | None:
    if line.material is not Material.UNKNOWN:
        return None
    return ReviewFinding(reason=ReviewReason.UNKNOWN_MATERIAL, detail="material is unknown")


def conflicting_types(evidence: LineEvidence) -> ReviewFinding | None:
    known = [
        (ref, o.utility_type)
        for ref, o in evidence.observations
        if o.utility_type is not UtilityType.UNKNOWN
    ]
    if len({t for _, t in known}) < 2:
        return None
    return ReviewFinding(
        reason=ReviewReason.CONFLICTING_TYPES,
        detail="observations disagree: " + ", ".join(f"{ref} {t}" for ref, t in known),
    )


def size_inconsistent(evidence: LineEvidence, config: VerificationConfig) -> ReviewFinding | None:
    scaled = [o for ref, o in evidence.observations if ref.frame_id in evidence.scaled_frames]
    problems = []
    for name, unit, values in (
        ("diameter", "mm", [o.approx_outer_diameter_mm for o in scaled]),
        ("depth of cover", "m", [o.approx_depth_of_cover_m for o in scaled]),
    ):
        known = [float(v) for v in values if v is not None]
        if len(known) < 2:
            continue
        mid = median(known)
        if mid <= 0:
            continue
        spread = (max(known) - min(known)) / mid
        if spread > config.size_tolerance:
            problems.append(
                f"{name} {min(known):g}-{max(known):g} {unit} across frames "
                f"(spread {spread:.0%} > {config.size_tolerance:.0%})"
            )
    if not problems:
        return None
    return ReviewFinding(reason=ReviewReason.SIZE_INCONSISTENT, detail="; ".join(problems))


def size_without_scale(evidence: LineEvidence) -> ReviewFinding | None:
    line = evidence.line
    sized = line.approx_outer_diameter_mm is not None or line.approx_depth_of_cover_m is not None
    if not sized or evidence.scaled_frames:
        return None
    return ReviewFinding(
        reason=ReviewReason.SIZE_WITHOUT_SCALE,
        detail="size given, but none of its frames shows a scale reference",
    )


def color_contradicts_type(evidence: LineEvidence) -> ReviewFinding | None:
    line_type = evidence.line.utility_type
    if line_type is UtilityType.UNKNOWN:
        return None
    contradictions = []
    for ref, obs in evidence.observations:
        expected = expected_types(obs.color)
        if expected is not None and line_type not in expected:
            names = " or ".join(sorted(expected))
            contradictions.append(f"{ref} {obs.color!r} usually means {names}")
    if not contradictions:
        return None
    return ReviewFinding(
        reason=ReviewReason.COLOR_CONTRADICTS_TYPE,
        detail=f"{line_type}, but "
        + "; ".join(contradictions)
        + f" (colour table: {COLOR_CONVENTIONS_SOURCE})",
    )


def single_frame_only(line: ReportLine, media_kind: MediaKind) -> ReviewFinding | None:
    cited = frames_of(line)
    if media_kind != "video" or len(cited) != 1:
        return None
    return ReviewFinding(
        reason=ReviewReason.SINGLE_FRAME_ONLY,
        detail=f"seen in one keyframe only ({cited[0]})",
    )


type _Rule = Callable[[LineEvidence, VerificationConfig, MediaKind], ReviewFinding | None]

RULES: tuple[_Rule, ...] = (
    lambda e, c, _: low_confidence(e.line, c),
    lambda e, _c, _m: unknown_type(e.line),
    lambda e, _c, _m: unknown_material(e.line),
    lambda e, _c, _m: conflicting_types(e),
    lambda e, c, _: size_inconsistent(e, c),
    lambda e, _c, _m: size_without_scale(e),
    lambda e, _c, _m: color_contradicts_type(e),
    lambda e, _c, m: single_frame_only(e.line, m),
)

_ORDER = {reason: i for i, reason in enumerate(ReviewReason)}


def review_line(
    line: ReportLine,
    frames: Mapping[str, FrameAnalysis],
    config: VerificationConfig,
    media_kind: MediaKind,
) -> ReportLine:
    evidence = line_evidence(line, frames)
    findings = [f for rule in RULES if (f := rule(evidence, config, media_kind)) is not None]
    findings.sort(key=lambda f: _ORDER[f.reason])
    return line.model_copy(update={"needs_review": bool(findings), "review": findings})


def verify_report(
    report: TrenchReport,
    analyses: Sequence[FrameAnalysis],
    config: VerificationConfig,
    *,
    media_kind: MediaKind,
) -> TrenchReport:
    frames = {a.frame_id: a for a in analyses}
    lines = [review_line(line, frames, config, media_kind) for line in report.lines]
    flagged = sum(line.needs_review for line in lines)
    flags = [f"{flagged} of {len(lines)} lines need review"] if flagged else []
    return report.model_copy(update={"lines": lines, "verification_flags": flags})
