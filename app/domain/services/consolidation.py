"""Consolidation rules: checking an agent's report and a deterministic fallback merge."""

from collections import Counter, defaultdict
from collections.abc import Sequence
from statistics import median

from app.domain.models import (
    Consolidation,
    FrameAnalysis,
    Job,
    LineObservation,
    Material,
    ReportLine,
    TrenchReport,
    UtilityType,
)

DEFAULT_LIMITATIONS: tuple[str, ...] = (
    "Semantic extraction from 2D images only; no 3D reconstruction or metric survey.",
    "Diameter and depth are only estimated when a scale reference is visible.",
    "Utility type from color is weak evidence; conventions differ by operator.",
)


def check_report_lines(lines: Sequence[ReportLine], analyses: Sequence[FrameAnalysis]) -> list[str]:
    """Problems with a proposed set of lines; empty list means it is consistent with the frames."""
    by_id = {a.frame_id: a for a in analyses}
    problems: list[str] = []
    for line in lines:
        if not line.seen_in_frames:
            problems.append(f"{line.id}: seen_in_frames is empty")
            continue
        unknown = [f for f in line.seen_in_frames if f not in by_id]
        if unknown:
            problems.append(f"{line.id}: unknown frame ids {unknown}")
            continue
        has_scale = any(by_id[f].scale_reference_visible for f in line.seen_in_frames)
        sized = (
            line.approx_outer_diameter_mm is not None or line.approx_depth_of_cover_m is not None
        )
        if sized and not has_scale:
            problems.append(
                f"{line.id}: diameter/depth given, but none of its frames has a scale reference"
            )
    return problems


# --- deterministic fallback --------------------------------------------------------------

type _Key = tuple[UtilityType, Material, str | None, bool | None]


def _key(obs: LineObservation) -> _Key:
    color = obs.color.strip().lower() if obs.color else None
    return (obs.utility_type, obs.material, color, obs.is_paired)


def merge_lines(analyses: Sequence[FrameAnalysis]) -> list[ReportLine]:
    """Merge without an LLM: observations with the same type, material, color and pairing are
    the same kind of line. The number of physical lines of a kind is the most seen in one frame.

    Crude by design: it cannot tell two identical pipes in different places apart. Used when
    the agent fails, and as a baseline in the eval.
    """
    per_frame: dict[_Key, Counter[str]] = defaultdict(Counter)
    observations: dict[_Key, list[LineObservation]] = defaultdict(list)
    for analysis in analyses:
        for obs in analysis.lines:
            per_frame[_key(obs)][analysis.frame_id] += 1
            observations[_key(obs)].append(obs)

    lines: list[ReportLine] = []
    for key in sorted(per_frame, key=lambda k: (-per_frame[k].total(), str(k))):
        frames = sorted(per_frame[key])
        group = observations[key]
        diameters = [o.approx_outer_diameter_mm for o in group if o.approx_outer_diameter_mm]
        depths = [o.approx_depth_of_cover_m for o in group if o.approx_depth_of_cover_m]
        confidence = round(sum(o.confidence for o in group) / len(group), 2)
        utility, material, color, _ = key
        for _ in range(max(per_frame[key].values())):
            lines.append(
                ReportLine(
                    id=f"L{len(lines) + 1}",
                    utility_type=utility,
                    material=material,
                    approx_outer_diameter_mm=round(median(diameters)) if diameters else None,
                    approx_depth_of_cover_m=round(median(depths), 2) if depths else None,
                    seen_in_frames=frames,
                    confidence=confidence,
                    notes=f"merged by rule (color: {color or 'unknown'})",
                )
            )
    return lines


def build_report(
    job: Job,
    consolidation: Consolidation,
    *,
    extra_limitations: Sequence[str] = (),
) -> TrenchReport:
    limitations = [*DEFAULT_LIMITATIONS, *extra_limitations, *consolidation.remarks]
    return TrenchReport(
        job_id=job.id,
        lines=consolidation.lines,
        verification_flags=[],
        limitations=limitations,
        location=job.metadata.location if job.metadata else None,
    )
