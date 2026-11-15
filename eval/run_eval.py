"""Run the vision model on the OpenTrench3D views and score it (frame mode).

    uv run python -m eval.run_eval --split dev                    # dry run: calls + cost estimate
    uv run python -m eval.run_eval --split dev --yes              # real run (costs money)

Per view: the rendered image goes through the production vision adapter (same prompt, schema,
image preparation); the raw findings are kept (hallucinated sizes are counted on them), then
the production measurement guard and verification run on a one-frame report. Scores per
`eval.metrics`. Output: eval/results/<date>_<model>_<prompt>_<split>_opentrench.{json,md}.

A real run needs `--yes`; without it nothing is sent to the API (CLAUDE.md §11.3).
"""

import argparse
import asyncio
import json
import subprocess
import sys
import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID

from PIL import Image
from pydantic import BaseModel

from app.adapters.llm.pricing import PRICES, cost_usd
from app.adapters.llm.prompts import load_prompt
from app.adapters.media.images import prepare_image
from app.domain.errors import FrameAnalysisError
from app.domain.models import (
    Consolidation,
    FrameAnalysis,
    LLMUsage,
    ReportLine,
    TrenchReport,
    UtilityType,
    VerificationConfig,
)
from app.domain.services import merge_lines, strip_unscaled_measurements, verify_report
from app.settings import get_settings
from eval.metrics import (
    JudgedLine,
    Summary,
    ViewFacts,
    judge_lines,
    main_type_found,
    summarise,
)
from eval.opentrench import CASES_PATH, LICENCE, RENDER_DIR, OpenTrenchCase, read_cases

RESULTS_DIR = Path("eval/results")
# Rough per-call token budget for the estimate (image tokens are computed from the size).
SYSTEM_PROMPT_CHARS_PER_TOKEN = 4
EXPECTED_OUTPUT_TOKENS = 900
IMAGE_PIXELS_PER_TOKEN = 750


class Vision(Protocol):
    async def analyze(
        self, image: bytes, frame_id: str
    ) -> tuple[FrameAnalysis, list[LLMUsage]]: ...


@dataclass(frozen=True, slots=True)
class PlannedView:
    case: OpenTrenchCase
    view: str
    file: str
    facts: ViewFacts


class ViewResult(BaseModel):
    case_id: str
    view: str
    file: str
    main_type: UtilityType
    owner_visible: bool
    other_visible: bool
    error: str | None
    raw: FrameAnalysis | None  # before the measurement guard
    lines: list[ReportLine]  # after guard + verification
    usage: list[LLMUsage]


def plan(
    cases: Sequence[OpenTrenchCase], split: str, limit: int | None = None
) -> list[PlannedView]:
    views = [
        PlannedView(
            case=case,
            view=v.view,
            file=v.file,
            facts=ViewFacts(
                main_type=case.main_type,
                owner_visible=v.main_visible or v.inactive_visible,
                other_visible=v.other_visible,
            ),
        )
        for case in cases
        if case.split == split
        for v in case.views
    ]
    return views[:limit] if limit else views


def estimate_cost(
    views: Sequence[PlannedView],
    model: str,
    prompt: str,
    max_edge: int,
    render_dir: Path = RENDER_DIR,
) -> tuple[int, float]:
    """(calls, USD) for one attempt per view; retries and fallbacks are not included."""
    system = len(load_prompt("analyze_frame", prompt)) // SYSTEM_PROMPT_CHARS_PER_TOKEN
    total = 0.0
    for v in views:
        with Image.open(render_dir / v.file) as img:  # reads the header only
            w, h = img.size
        s = min(1.0, max_edge / max(h, w))
        image_tokens = int(h * s * w * s / IMAGE_PIXELS_PER_TOKEN)
        total += cost_usd(
            model, input_tokens=system + image_tokens + 30, output_tokens=EXPECTED_OUTPUT_TOKENS
        )
    return len(views), total


def one_frame_report(analysis: FrameAnalysis, config: VerificationConfig) -> list[ReportLine]:
    """The production rules on a single image: rule-based merge, then verification."""
    report = TrenchReport(
        job_id=UUID(int=0),
        lines=Consolidation(lines=merge_lines([analysis]), method="rules").lines,
        verification_flags=[],
        limitations=[],
        location=None,
        consolidation_method="rules",
    )
    return verify_report(report, [analysis], config, media_kind="image").lines


async def run_views(
    views: Sequence[PlannedView],
    vision: Vision,
    config: VerificationConfig,
    *,
    max_edge: int,
    concurrency: int = 4,
    render_dir: Path = RENDER_DIR,
) -> list[ViewResult]:
    semaphore = asyncio.Semaphore(concurrency)

    async def one(v: PlannedView) -> ViewResult:
        async with semaphore:
            image = prepare_image((render_dir / v.file).read_bytes(), max_edge)
            base: dict[str, Any] = {
                "case_id": v.case.case_id,
                "view": v.view,
                "file": v.file,
                "main_type": v.case.main_type,
                "owner_visible": v.facts.owner_visible,
                "other_visible": v.facts.other_visible,
            }
            try:
                raw, usage = await vision.analyze(image, f"{v.case.case_id}:{v.view}")
            except FrameAnalysisError as e:
                return ViewResult(**base, error=str(e), raw=None, lines=[], usage=e.usage)
            lines = one_frame_report(strip_unscaled_measurements(raw), config)
            return ViewResult(**base, error=None, raw=raw, lines=lines, usage=usage)

    return list(await asyncio.gather(*(one(v) for v in views)))


def score(results: Sequence[ViewResult]) -> tuple[Summary, list[JudgedLine]]:
    judged: list[JudgedLine] = []
    found: list[bool | None] = []
    trench: list[bool] = []
    for r in results:
        facts = ViewFacts(r.main_type, r.owner_visible, r.other_visible)
        if r.raw is None:
            found.append(False if facts.owner_visible else None)
            continue
        judged += judge_lines(r.case_id, r.view, facts, r.lines)
        found.append(main_type_found(facts, r.raw.lines))
        trench.append(r.raw.is_trench_visible)
    return summarise(judged, found, trench), judged


# --- report -------------------------------------------------------------------------------


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


def to_markdown(
    meta: dict[str, Any],
    summary: Summary,
    judged: Sequence[JudgedLine],
    results: Sequence[ViewResult],
) -> str:
    rows = [
        (
            "Views where the area's utility is visible and the model named its type",
            summary.main_found,
        ),
        ("Judged lines with the right type", summary.correct),
        ("Wrong when confident (conf >= 0.8)", summary.wrong_when_confident),
        ("Lines left `unknown` (abstentions)", summary.abstain),
        ("Review recall: wrong lines flagged", summary.review_recall),
        ("Review precision: flagged judged lines that are wrong", summary.review_precision),
        ("Review rate: lines flagged", summary.review_rate),
        ("Views where the model said 'no trench'", summary.no_trench_reported),
    ]
    calib = [
        f"| {b.lower:.1f}-{b.upper:.1f} | {b.n} | "
        f"{'-' if b.mean_confidence is None else f'{b.mean_confidence:.2f}'} | "
        f"{'-' if b.accuracy is None else f'{b.accuracy:.2f}'} |"
        for b in summary.calibration
    ]
    wrong = [j for j in judged if j.judgement == "wrong"]
    failures = [
        f"| {j.case_id} / {j.view} | {j.utility_type} | {j.confidence:.2f} | "
        f"{'flagged' if j.flagged else '**not flagged**'} |"
        for j in sorted(wrong, key=lambda j: (j.flagged, -j.confidence))[:15]
    ]
    errors = [r for r in results if r.error]
    return "\n".join(
        [
            f"# Eval: OpenTrench3D views, frame mode ({meta['split']})",
            "",
            " · ".join(f"{k} {v}" for k, v in meta.items()),
            "",
            f"{summary.views} views, {summary.lines} predicted lines, {summary.unjudged} not "
            "judgeable (concrete type while untyped 'other utilities' are visible). "
            f"{len(errors)} views failed.",
            "",
            "| metric | result [95 % Wilson CI] |",
            "|---|---|",
            *[f"| {name} | {rate} |" for name, rate in rows],
            "",
            f"ECE {summary.ece if summary.ece is None else f'{summary.ece:.3f}'} · "
            f"Brier {summary.brier if summary.brier is None else f'{summary.brier:.3f}'} "
            "(confidence = P(type correct), judged lines only)",
            "",
            "| confidence | n | mean conf. | accuracy |",
            "|---|---|---|---|",
            *calib,
            "",
            "## Wrong lines (most dangerous first: not flagged, confident)",
            "",
            "| view | predicted | conf. | verification |",
            "|---|---|---|---|",
            *(failures or ["| - | - | - | - |"]),
            "",
            "## Limits of this eval",
            "",
            "- Views are renders of photogrammetric point clouds (black background, holes), not phone photos.",
            "- Truth knows two utility types (water, district heating) plus untyped 'other utilities'; "
            "lines of a concrete type next to visible other utilities are not judged.",
            "- No line count in the truth (per-point classes, not instances).",
            f"- Data: {LICENCE}. Denmark, not Switzerland.",
            "",
        ]
    )


def main(argv: list[str] | None = None) -> int:
    settings = get_settings()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--split", choices=("dev", "test"), default="dev")
    parser.add_argument("--model", default=settings.claude_model)
    parser.add_argument("--prompt", default=settings.prompt_version)
    parser.add_argument("--limit", type=int, default=None, help="only the first N views")
    parser.add_argument("--yes", action="store_true", help="really call the API (costs money)")
    args = parser.parse_args(argv)

    if args.model not in PRICES:
        print(f"no price for {args.model}; add it to pricing.py first", file=sys.stderr)
        return 1
    views = plan(read_cases(CASES_PATH), args.split, args.limit)
    calls, usd = estimate_cost(views, args.model, args.prompt, settings.max_image_edge_px)
    print(
        f"{len(views)} views ({args.split}), {calls} calls to {args.model}, prompt "
        f"{args.prompt}: estimated ${usd:.2f} (one attempt each; retries extra)"
    )
    if not args.yes:
        print("dry run: nothing sent. Re-run with --yes to call the API.")
        return 0

    import anthropic

    from app.adapters.llm.claude import ClaudeVisionModel

    key = settings.anthropic_api_key
    client = anthropic.AsyncAnthropic(api_key=key.get_secret_value() if key else None)
    vision = ClaudeVisionModel(
        client, args.model, prompt_version=args.prompt, effort=settings.claude_effort
    )
    started = time.perf_counter()
    results = asyncio.run(
        run_views(
            views,
            vision,
            VerificationConfig(
                min_confidence=settings.verify_min_confidence,
                size_tolerance=settings.verify_size_tolerance,
            ),
            max_edge=settings.max_image_edge_px,
        )
    )
    summary, judged = score(results)
    usage = [u for r in results for u in r.usage]
    meta = {
        "date": datetime.now(UTC).date().isoformat(),
        "commit": _commit(),
        "model": args.model,
        "prompt": args.prompt,
        "split": args.split,
        "cases": len({v.case.case_id for v in views}),
        "views": len(views),
        "cost_usd": round(sum(u.cost_usd for u in usage), 4),
        "wall_s": round(time.perf_counter() - started, 1),
        "pricing_as_of": "2026-11 (unverified, see pricing.py)",
    }
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stem = RESULTS_DIR / f"{meta['date']}_{args.model}_{args.prompt}_{args.split}_opentrench"
    stem.with_suffix(".json").write_text(
        json.dumps(
            {
                "meta": meta,
                "summary": asdict(summary),
                "results": [r.model_dump(mode="json") for r in results],
            },
            indent=1,
            default=str,
        ),
        encoding="utf-8",
    )
    stem.with_suffix(".md").write_text(
        to_markdown(meta, summary, judged, results), encoding="utf-8"
    )
    print(f"-> {stem}.md (cost ${meta['cost_usd']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
