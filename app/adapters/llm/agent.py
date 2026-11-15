"""Consolidation agent: a hand-written tool-use loop over the per-frame findings.

Tools: get_frame_findings, get_frame_image, submit_report. The loop is append-only (assistant
turns are sent back unchanged), and it ends when submit_report passes the domain checks.
"""

import base64
import json
import logging
from typing import Any
from uuid import UUID

import anthropic
from anthropic.types.beta import (
    BetaMessageParam,
    BetaToolParam,
    BetaToolResultBlockParam,
    BetaToolUseBlock,
)
from pydantic import BaseModel, ValidationError

from app.adapters.llm.claude import ClaudeClient, Effort, validation_summary
from app.adapters.llm.prompts import load_prompt
from app.adapters.llm.schemas import (
    GetFrameFindingsInput,
    GetFrameImageInput,
    SubmitReportInput,
)
from app.domain.errors import ConsolidationError
from app.domain.models import Consolidation, FrameAnalysis, LLMUsage, ReportLine
from app.domain.ports.llm import ImageLoader
from app.domain.services import check_report_lines

logger = logging.getLogger(__name__)


def _tool(name: str, description: str, schema: type[BaseModel]) -> BetaToolParam:
    return {
        "name": name,
        "description": description,
        "input_schema": anthropic.transform_schema(schema.model_json_schema()),
        "strict": True,
    }


TOOLS: list[BetaToolParam] = [
    _tool(
        "get_frame_findings",
        "Full findings of the given frames: lines with evidence, confidence and position, "
        "warning tapes, scale reference, image quality.",
        GetFrameFindingsInput,
    ),
    _tool(
        "get_frame_image",
        "The image of one frame, to settle a conflict between frames. Limited number of calls.",
        GetFrameImageInput,
    ),
    _tool(
        "submit_report",
        "Submit the consolidated lines, each citing the frame observations it merges. "
        "Rejected with a list of problems if inconsistent with the frames; fix them and "
        "submit again.",
        SubmitReportInput,
    ),
]

NUDGE = "Finish by calling submit_report with the consolidated lines."


def overview(analyses: list[FrameAnalysis]) -> str:
    """Compact first message: enough to plan, details come from get_frame_findings."""
    rows = []
    for a in analyses:
        lines = "; ".join(
            f"[{i}] {ln.utility_type}/{ln.material} {ln.color or '?'} @ {ln.position or '?'}"
            for i, ln in enumerate(a.lines)
        )
        rows.append(
            f"- {a.frame_id}: trench {'yes' if a.is_trench_visible else 'no'}, "
            f"scale ref {'yes' if a.scale_reference_visible else 'no'}, "
            f"tapes {a.warning_tapes or 'none'}, {len(a.lines)} lines [{lines}]"
            + (f", issues {a.image_quality_issues}" if a.image_quality_issues else "")
        )
    return (
        f"{len(analyses)} analyzed frames, ids in time order:\n" + "\n".join(rows) + "\n\n"
        "Consolidate them into distinct physical lines and call submit_report."
    )


class ClaudeReportAgent(ClaudeClient):
    error_type = ConsolidationError

    def __init__(
        self,
        client: anthropic.AsyncAnthropic,
        model: str,
        *,
        prompt_version: str = "v1",
        effort: Effort = "high",
        max_turns: int = 10,
        max_image_views: int = 6,
        refusal_fallback: bool = True,
    ) -> None:
        super().__init__(
            client, model, prompt_version=prompt_version, refusal_fallback=refusal_fallback
        )
        self.max_turns = max_turns
        self.max_image_views = max_image_views
        self._system = self.cached_system(load_prompt("consolidate", prompt_version))
        self._effort = effort

    async def consolidate(
        self, job_id: UUID, analyses: list[FrameAnalysis], load_image: ImageLoader
    ) -> tuple[Consolidation, list[LLMUsage]]:
        session = _Session(analyses, load_image, self.max_image_views)
        messages: list[BetaMessageParam] = [{"role": "user", "content": overview(analyses)}]
        usage: list[LLMUsage] = []

        for turn in range(1, self.max_turns + 1):
            response = await self._create(
                messages,
                usage,
                system=self._system,
                output_config={"effort": self._effort},
                tools=TOOLS,
            )
            messages.append({"role": "assistant", "content": response.content})
            calls = [b for b in response.content if b.type == "tool_use"]
            if not calls:
                messages.append({"role": "user", "content": NUDGE})
                continue

            results = [await session.run(call) for call in calls]
            if session.result is not None:
                logger.info("job %s consolidated in %d turns", job_id, turn)
                return session.result, usage
            # All results of one turn go back in a single user message.
            messages.append({"role": "user", "content": results})

        raise ConsolidationError(f"no valid report after {self.max_turns} turns", usage)


class _Session:
    """Tool state for one consolidation run."""

    def __init__(
        self, analyses: list[FrameAnalysis], load_image: ImageLoader, max_image_views: int
    ) -> None:
        self.analyses = {a.frame_id: a for a in analyses}
        self.load_image = load_image
        self.image_views_left = max_image_views
        self.result: Consolidation | None = None

    async def run(self, call: BetaToolUseBlock) -> BetaToolResultBlockParam:
        try:
            match call.name:
                case "get_frame_findings":
                    content: Any = self._findings(GetFrameFindingsInput.model_validate(call.input))
                case "get_frame_image":
                    content = await self._image(GetFrameImageInput.model_validate(call.input))
                case "submit_report":
                    content = self._submit(SubmitReportInput.model_validate(call.input))
                case _:
                    raise _ToolError(f"unknown tool {call.name}")
        except ValidationError as e:
            return _error(call, f"invalid input:\n{validation_summary(e)}")
        except _ToolError as e:
            return _error(call, str(e))
        return {"type": "tool_result", "tool_use_id": call.id, "content": content}

    def _findings(self, args: GetFrameFindingsInput) -> str:
        ids = args.frame_ids or list(self.analyses)
        if unknown := [i for i in ids if i not in self.analyses]:
            raise _ToolError(f"unknown frame ids {unknown}; known: {list(self.analyses)}")
        return json.dumps([_with_line_indices(self.analyses[i]) for i in ids], ensure_ascii=False)

    async def _image(self, args: GetFrameImageInput) -> list[dict[str, Any]]:
        if args.frame_id not in self.analyses:
            raise _ToolError(f"unknown frame id {args.frame_id}")
        if self.image_views_left <= 0:
            raise _ToolError("image budget used up; decide from the findings")
        self.image_views_left -= 1
        jpeg = await self.load_image(args.frame_id)
        return [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/jpeg",
                    "data": base64.standard_b64encode(jpeg).decode("ascii"),
                },
            },
            {"type": "text", "text": f"Frame {args.frame_id}"},
        ]

    def _submit(self, args: SubmitReportInput) -> str:
        lines = [
            ReportLine(id=f"L{i}", **draft.model_dump())
            for i, draft in enumerate(args.lines, start=1)
        ]
        if problems := check_report_lines(lines, list(self.analyses.values())):
            raise _ToolError("report rejected:\n" + "\n".join(f"- {p}" for p in problems))
        self.result = Consolidation(lines=lines, remarks=args.remarks, method="agent")
        return "accepted"


def _with_line_indices(analysis: FrameAnalysis) -> dict[str, Any]:
    """Findings as JSON, each line prefixed with the `line_index` the agent cites it by."""
    data = analysis.model_dump(mode="json", exclude_none=True)
    data["lines"] = [{"line_index": i, **line} for i, line in enumerate(data["lines"])]
    return data


class _ToolError(Exception):
    pass


def _error(call: BetaToolUseBlock, message: str) -> BetaToolResultBlockParam:
    return {"type": "tool_result", "tool_use_id": call.id, "content": message, "is_error": True}
