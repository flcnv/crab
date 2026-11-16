from collections import defaultdict
from collections.abc import Sequence
from statistics import median

from app.domain.models import (
    Consolidation,
    FrameAnalysis,
    Job,
    LineObservation,
    Material,
    ObservationRef,
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
    by_id = {a.frame_id: a for a in analyses}
    claimed_by: dict[ObservationRef, str] = {}
    problems: list[str] = []
    for line in lines:
        if not line.observations:
            problems.append(f"{line.id}: no observations referenced")
            continue
        unknown = sorted({r.frame_id for r in line.observations if r.frame_id not in by_id})
        if unknown:
            problems.append(f"{line.id}: unknown frame ids {unknown}")
            continue
        out_of_range = [
            r for r in line.observations if r.line_index >= len(by_id[r.frame_id].lines)
        ]
        if out_of_range:
            problems.extend(
                f"{line.id}: {r} does not exist "
                f"(frame {r.frame_id} has {len(by_id[r.frame_id].lines)} lines)"
                for r in out_of_range
            )
            continue
        problems.extend(
            f"{line.id}: observation {ref} is listed twice"
            for ref in sorted(set(line.observations), key=str)
            if line.observations.count(ref) > 1
        )
        problems.extend(
            f"{line.id}: observation {ref} is already used by {claimed_by[ref]}"
            for ref in line.observations
            if claimed_by.setdefault(ref, line.id) != line.id
        )
        has_scale = any(by_id[f].scale_reference_visible for f in line.seen_in_frames)
        sized = (
            line.approx_outer_diameter_mm is not None or line.approx_depth_of_cover_m is not None
        )
        if sized and not has_scale:
            problems.append(
                f"{line.id}: diameter/depth given, but none of its frames has a scale reference"
            )
    return problems


type _Key = tuple[UtilityType, Material, str | None, bool | None]


def _key(obs: LineObservation) -> _Key:
    color = obs.color.strip().lower() if obs.color else None
    return (obs.utility_type, obs.material, color, obs.is_paired)


def merge_lines(analyses: Sequence[FrameAnalysis]) -> list[ReportLine]:
    refs: dict[_Key, dict[str, list[int]]] = defaultdict(dict)
    found: dict[tuple[str, int], LineObservation] = {}
    for analysis in analyses:
        for index, obs in enumerate(analysis.lines):
            refs[_key(obs)].setdefault(analysis.frame_id, []).append(index)
            found[analysis.frame_id, index] = obs

    def total(key: _Key) -> int:
        return sum(len(indices) for indices in refs[key].values())

    lines: list[ReportLine] = []
    for key in sorted(refs, key=lambda k: (-total(k), str(k))):
        per_frame = refs[key]
        utility, material, color, _ = key
        for k in range(max(len(indices) for indices in per_frame.values())):
            own = [
                ObservationRef(frame_id=frame_id, line_index=indices[k])
                for frame_id, indices in sorted(per_frame.items())
                if k < len(indices)
            ]
            group = [found[r.frame_id, r.line_index] for r in own]
            diameters = [o.approx_outer_diameter_mm for o in group if o.approx_outer_diameter_mm]
            depths = [o.approx_depth_of_cover_m for o in group if o.approx_depth_of_cover_m]
            lines.append(
                ReportLine(
                    id=f"L{len(lines) + 1}",
                    utility_type=utility,
                    material=material,
                    approx_outer_diameter_mm=round(median(diameters)) if diameters else None,
                    approx_depth_of_cover_m=round(median(depths), 2) if depths else None,
                    observations=own,
                    confidence=round(sum(o.confidence for o in group) / len(group), 2),
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
        consolidation_method=consolidation.method,
    )
