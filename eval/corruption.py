"""Safety-net eval without labels: inject known errors, measure what verification catches.

A clean report (consistent frames, confident types that match the colours, sizes only with a
scale reference) is corrupted in one specific way at a time — the kind of mistake the vision
model or the consolidation agent can make — and `verify_report` runs on the result. Because
the injected error is known, no human labels are needed.

Some corruptions are expected to slip through (e.g. a wrong type whose colour is ambiguous):
they are listed as blind spots on purpose; the report must show them, not hide them.

    uv run python -m eval.corruption        # -> eval/results/<date>_safety_net.{json,md}

Pure code: no model calls, no cost, deterministic.
"""

import argparse
import json
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from pydantic import BaseModel

from app.domain.models import (
    Evidence,
    FrameAnalysis,
    LineObservation,
    Material,
    MediaKind,
    ObservationRef,
    ReportLine,
    ReviewReason,
    TrenchReport,
    UtilityType,
    VerificationConfig,
)
from app.domain.services import verify_report

RESULTS_DIR = Path("eval/results")
JOB_ID = UUID(int=0)

# One clean line per utility kind: (type, material, colour seen by the model).
_KINDS: tuple[tuple[UtilityType, Material, str], ...] = (
    (UtilityType.GAS, Material.PE, "yellow"),
    (UtilityType.WATER, Material.PE, "blue"),
    (UtilityType.WASTEWATER, Material.PVC_PP, "orange-brown"),
    (UtilityType.DISTRICT_HEATING, Material.PRE_INSULATED, "black"),
    (UtilityType.TELECOM, Material.CABLE, "green"),
    (UtilityType.POWER, Material.CABLE, "red"),
)
FRAMES = ("f001", "f002", "f003")


@dataclass(frozen=True, slots=True)
class Scenario:
    """A report with its frame analyses, as the pipeline would hand them to verify."""

    report: TrenchReport
    analyses: list[FrameAnalysis]
    media_kind: MediaKind = "video"


def _observation(
    utility: UtilityType,
    material: Material,
    color: str,
    *,
    diameter: int | None = None,
    confidence: float = 0.9,
) -> LineObservation:
    return LineObservation(
        utility_type=utility,
        material=material,
        color=color,
        approx_outer_diameter_mm=diameter,
        approx_depth_of_cover_m=None,
        is_house_connection=None,
        evidence=[Evidence(cue="warning_tape_text", detail="tape text read")],
        confidence=confidence,
    )


def clean_scenario() -> Scenario:
    """Every kind of line seen in all three video frames, line i at index i of each frame.

    Clean means: verification must flag nothing here (checked by `run`)."""
    analyses = [
        FrameAnalysis(
            frame_id=frame_id,
            is_trench_visible=True,
            scale_reference_visible=False,
            warning_tapes=[],
            lines=[_observation(u, m, c) for u, m, c in _KINDS],
            image_quality_issues=[],
        )
        for frame_id in FRAMES
    ]
    lines = [
        ReportLine(
            id=f"L{i + 1}",
            utility_type=u,
            material=m,
            approx_outer_diameter_mm=None,
            approx_depth_of_cover_m=None,
            observations=[ObservationRef(frame_id=f, line_index=i) for f in FRAMES],
            confidence=0.9,
            notes=None,
        )
        for i, (u, m, _) in enumerate(_KINDS)
    ]
    report = TrenchReport(
        job_id=JOB_ID,
        lines=lines,
        verification_flags=[],
        limitations=[],
        location=None,
        consolidation_method="agent",
    )
    return Scenario(report=report, analyses=analyses)


# --- corruptions --------------------------------------------------------------------------
# Each takes a clean scenario and returns (corrupted scenario, id of the corrupted line).


def _replace_line(s: Scenario, index: int, **changes: object) -> Scenario:
    lines = list(s.report.lines)
    lines[index] = lines[index].model_copy(update=changes)
    return Scenario(s.report.model_copy(update={"lines": lines}), s.analyses, s.media_kind)


def _replace_observation(s: Scenario, frame: int, index: int, **changes: object) -> Scenario:
    analyses = [a.model_copy(deep=True) for a in s.analyses]
    obs = analyses[frame].lines[index]
    analyses[frame].lines[index] = obs.model_copy(update=changes)
    return Scenario(s.report, analyses, s.media_kind)


@dataclass(frozen=True, slots=True)
class Corruption:
    name: str
    description: str
    expected: ReviewReason | None  # None = a known blind spot: nothing is expected to fire
    apply: Callable[[Scenario], tuple[Scenario, str]]


def _wrong_type_vs_colour(s: Scenario) -> tuple[Scenario, str]:
    return _replace_line(s, 0, utility_type=UtilityType.WATER), "L1"  # yellow line -> water


def _wrong_type_ambiguous_colour(s: Scenario) -> tuple[Scenario, str]:
    return _replace_line(s, 3, utility_type=UtilityType.POWER), "L4"  # black heating -> power


def _wrong_type_everywhere(s: Scenario) -> tuple[Scenario, str]:
    """The model saw blue and called it water in every frame, but the pipe is gas."""
    for frame in range(len(FRAMES)):
        s = _replace_observation(s, frame, 0, utility_type=UtilityType.WATER, color="blue")
    return _replace_line(s, 0, utility_type=UtilityType.WATER), "L1"


def _one_frame_disagrees(s: Scenario) -> tuple[Scenario, str]:
    return _replace_observation(s, 1, 1, utility_type=UtilityType.WASTEWATER), "L2"


def _overconfident_guess(s: Scenario) -> tuple[Scenario, str]:
    return _replace_line(s, 4, confidence=0.55), "L5"


def _unknown_type(s: Scenario) -> tuple[Scenario, str]:
    return _replace_line(s, 5, utility_type=UtilityType.UNKNOWN), "L6"


def _unknown_material(s: Scenario) -> tuple[Scenario, str]:
    return _replace_line(s, 1, material=Material.UNKNOWN), "L2"


def _invented_size(s: Scenario) -> tuple[Scenario, str]:
    return _replace_line(s, 2, approx_outer_diameter_mm=160), "L3"


def _sizes_disagree(s: Scenario) -> tuple[Scenario, str]:
    analyses = [
        a.model_copy(update={"scale_reference_visible": True}, deep=True) for a in s.analyses
    ]
    s = Scenario(s.report, analyses, s.media_kind)
    for frame, diameter in enumerate((110, 110, 160)):
        s = _replace_observation(s, frame, 1, approx_outer_diameter_mm=diameter)
    return _replace_line(s, 1, approx_outer_diameter_mm=110), "L2"


def _phantom_line(s: Scenario) -> tuple[Scenario, str]:
    """A line the agent invented from a single frame of a video."""
    return _replace_line(s, 4, observations=[ObservationRef(frame_id="f002", line_index=4)]), "L5"


CORRUPTIONS: tuple[Corruption, ...] = (
    Corruption(
        "wrong_type_vs_colour",
        "type changed so that it contradicts the observed colour (yellow pipe called water)",
        ReviewReason.COLOR_CONTRADICTS_TYPE,
        _wrong_type_vs_colour,
    ),
    Corruption(
        "one_frame_disagrees",
        "one of three frames names a different type for the same line",
        ReviewReason.CONFLICTING_TYPES,
        _one_frame_disagrees,
    ),
    Corruption(
        "overconfident_guess",
        "confidence lowered to 0.55 (a colour-only guess)",
        ReviewReason.LOW_CONFIDENCE,
        _overconfident_guess,
    ),
    Corruption("unknown_type", "type left unknown", ReviewReason.UNKNOWN_TYPE, _unknown_type),
    Corruption(
        "unknown_material",
        "material left unknown",
        ReviewReason.UNKNOWN_MATERIAL,
        _unknown_material,
    ),
    Corruption(
        "invented_size",
        "diameter reported although no frame has a scale reference",
        ReviewReason.SIZE_WITHOUT_SCALE,
        _invented_size,
    ),
    Corruption(
        "sizes_disagree",
        "scaled frames give 110 / 110 / 160 mm for the same pipe",
        ReviewReason.SIZE_INCONSISTENT,
        _sizes_disagree,
    ),
    Corruption(
        "phantom_line",
        "a line backed by a single frame of a video",
        ReviewReason.SINGLE_FRAME_ONLY,
        _phantom_line,
    ),
    Corruption(
        "wrong_type_ambiguous_colour",
        "black pre-insulated heating pipe called power, confidently (black means nothing)",
        None,
        _wrong_type_ambiguous_colour,
    ),
    Corruption(
        "wrong_type_everywhere",
        "every frame consistently sees blue and says water, but the pipe is gas",
        None,
        _wrong_type_everywhere,
    ),
)


# --- run ----------------------------------------------------------------------------------


class CorruptionResult(BaseModel):
    name: str
    description: str
    expected: ReviewReason | None
    fired: list[ReviewReason]  # reasons on the corrupted line
    caught: bool  # any reason fired on the corrupted line
    caught_as_expected: bool
    false_alarms: int  # findings on the untouched lines


class SafetyNetReport(BaseModel):
    date: str
    commit: str
    config: VerificationConfig
    clean_false_alarms: int
    results: list[CorruptionResult]

    @property
    def detectable(self) -> list[CorruptionResult]:
        return [r for r in self.results if r.expected is not None]


def run(config: VerificationConfig | None = None) -> SafetyNetReport:
    config = config or VerificationConfig()
    clean = clean_scenario()
    verified_clean = verify_report(
        clean.report, clean.analyses, config, media_kind=clean.media_kind
    )
    results = []
    for corruption in CORRUPTIONS:
        scenario, line_id = corruption.apply(clean_scenario())
        verified = verify_report(
            scenario.report, scenario.analyses, config, media_kind=scenario.media_kind
        )
        target = next(line for line in verified.lines if line.id == line_id)
        fired = [f.reason for f in target.review]
        results.append(
            CorruptionResult(
                name=corruption.name,
                description=corruption.description,
                expected=corruption.expected,
                fired=fired,
                caught=bool(fired),
                caught_as_expected=corruption.expected in fired,
                false_alarms=sum(len(line.review) for line in verified.lines if line.id != line_id),
            )
        )
    return SafetyNetReport(
        date=datetime.now(UTC).date().isoformat(),
        commit=_commit(),
        config=config,
        clean_false_alarms=sum(len(line.review) for line in verified_clean.lines),
        results=results,
    )


def _commit() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],  # noqa: S607 (fixed command)
            capture_output=True,
            text=True,
            check=True,
        )
    except OSError, subprocess.CalledProcessError:
        return "unknown"
    return out.stdout.strip()


def to_markdown(report: SafetyNetReport) -> str:
    detectable = report.detectable
    caught = sum(r.caught_as_expected for r in detectable)
    rows = [
        f"| `{r.name}` | {r.description} | {r.expected or '— (blind spot)'} | "
        f"{', '.join(r.fired) or '—'} | "
        + (
            "✅"
            if r.caught_as_expected
            else "❌"
            if r.expected
            else "⚠️ not caught"
            if not r.caught
            else "caught"
        )
        + f" | {r.false_alarms} |"
        for r in report.results
    ]
    return "\n".join(
        [
            "# Safety net: injected errors",
            "",
            f"Date {report.date} · commit `{report.commit}` · "
            f"min_confidence {report.config.min_confidence} · "
            f"size_tolerance {report.config.size_tolerance}",
            "",
            "Each row corrupts one line of a clean, consistent report in one specific way and "
            "runs the deterministic verification (`verify_report`). No model calls, no labels: "
            "the injected error is the ground truth. This measures the **rules**, not the "
            "vision model; how often the model makes each kind of mistake is measured "
            "separately (OpenTrench3D eval).",
            "",
            f"- Detectable corruptions caught by the intended rule: **{caught} / {len(detectable)}**",
            f"- Findings on the clean report (false alarms): **{report.clean_false_alarms}**",
            f"- Known blind spots (expected to pass unflagged): "
            f"**{len(report.results) - len(detectable)}**",
            "",
            "| corruption | what was changed | expected rule | rules that fired | result | false alarms on other lines |",
            "|---|---|---|---|---|---|",
            *rows,
            "",
            "**Blind spots.** A wrong type is only caught when something contradicts it: a "
            "colour with a known convention, another frame, a low confidence. A confident "
            "wrong type on a black/grey pipe, or the same wrong reading repeated in every "
            "frame, passes every rule. Closing these needs a second, independent signal "
            "(warning tape text, an operator's network plan, or a second model run), not "
            "more rules over the same observations.",
            "",
        ]
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Safety-net eval with injected errors")
    parser.add_argument("--out", type=Path, default=RESULTS_DIR)
    args = parser.parse_args(argv)
    report = run()
    args.out.mkdir(parents=True, exist_ok=True)
    stem = args.out / f"{report.date}_safety_net"
    stem.with_suffix(".json").write_text(
        json.dumps(report.model_dump(mode="json"), indent=2) + "\n", encoding="utf-8"
    )
    stem.with_suffix(".md").write_text(to_markdown(report), encoding="utf-8")
    detectable = report.detectable
    print(
        f"caught {sum(r.caught_as_expected for r in detectable)}/{len(detectable)} detectable, "
        f"{report.clean_false_alarms} false alarms on clean -> {stem}.md"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
