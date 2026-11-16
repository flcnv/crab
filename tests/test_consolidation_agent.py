import json
import uuid

import pytest

from app.adapters.llm.agent import NUDGE, TOOLS, ClaudeReportAgent
from app.domain.errors import ConsolidationError
from app.domain.models import Evidence, FrameAnalysis, LineObservation, Material, UtilityType
from tests.anthropic_fakes import FakeClient, FakeMessages, message, tool_use


def _frame(frame_id: str) -> FrameAnalysis:
    line = LineObservation(
        utility_type=UtilityType.GAS,
        material=Material.PE,
        color="yellow",
        approx_outer_diameter_mm=None,
        approx_depth_of_cover_m=None,
        is_house_connection=None,
        evidence=[Evidence(cue="warning_tape_text", detail="Achtung Gasleitung")],
        confidence=0.9,
        position="bottom",
    )
    return FrameAnalysis(
        frame_id=frame_id,
        is_trench_visible=True,
        scale_reference_visible=False,
        warning_tapes=["yellow: Achtung Gasleitung"],
        lines=[line],
        image_quality_issues=[],
    )


ANALYSES = [_frame("f001"), _frame("f002")]
GAS_LINE = {
    "utility_type": "gas",
    "material": "pe",
    "approx_outer_diameter_mm": None,
    "approx_depth_of_cover_m": None,
    "observations": [
        {"frame_id": "f001", "line_index": 0},
        {"frame_id": "f002", "line_index": 0},
    ],
    "confidence": 0.9,
    "notes": "tape text in both frames",
}
SUBMIT_OK = {"lines": [GAS_LINE], "remarks": ["only 2 frames"]}


async def load_image(frame_id: str) -> bytes:
    return f"jpeg-{frame_id}".encode()


def agent(replies: list, **kwargs: int) -> tuple[ClaudeReportAgent, FakeMessages]:  # type: ignore[type-arg]
    client = FakeClient(replies)
    return ClaudeReportAgent(client, "claude-sonnet-5-5", **kwargs), client.messages  # type: ignore[arg-type]


def results_of(request: dict) -> list[dict]:  # type: ignore[type-arg]
    content = request["messages"][-1]["content"]
    assert isinstance(content, list)
    return content


async def test_findings_then_submit() -> None:
    a, api = agent(
        [
            message(tool_use("get_frame_findings", {"frame_ids": None})),
            message(tool_use("submit_report", SUBMIT_OK, id="toolu_2")),
        ]
    )

    consolidation, usage = await a.consolidate(uuid.uuid4(), ANALYSES, load_image)

    assert consolidation.method == "agent"
    assert consolidation.remarks == ["only 2 frames"]
    [line] = consolidation.lines
    assert (line.id, line.utility_type, line.seen_in_frames) == (
        "L1",
        UtilityType.GAS,
        ["f001", "f002"],
    )
    assert len(usage) == 2

    first, second = api.requests
    assert "f001: trench yes" in first["messages"][0]["content"]
    assert "[0] gas/pe yellow @ bottom" in first["messages"][0]["content"]
    assert first["tools"] == TOOLS
    assert all(t["strict"] for t in TOOLS)
    assert first["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert first["output_config"] == {"effort": "high"}
    assert all(r["cache_control"] == {"type": "ephemeral"} for r in api.requests)
    [result] = results_of(second)
    assert result["tool_use_id"] == "toolu_1"
    findings = json.loads(result["content"])
    assert [f["frame_id"] for f in findings] == ["f001", "f002"]
    assert findings[0]["lines"][0]["line_index"] == 0
    assert second["messages"][1]["role"] == "assistant"


async def test_rejected_report_is_fixed_and_resubmitted() -> None:
    bad = {
        "lines": [{**GAS_LINE, "observations": [{"frame_id": "f009", "line_index": 0}]}],
        "remarks": [],
    }
    sized = {"lines": [{**GAS_LINE, "approx_outer_diameter_mm": 110}], "remarks": []}
    a, api = agent(
        [
            message(tool_use("submit_report", bad)),
            message(tool_use("submit_report", sized, id="toolu_2")),
            message(tool_use("submit_report", SUBMIT_OK, id="toolu_3")),
        ]
    )

    consolidation, usage = await a.consolidate(uuid.uuid4(), ANALYSES, load_image)

    assert len(consolidation.lines) == 1
    assert len(usage) == 3
    [r1] = results_of(api.requests[1])
    assert r1["is_error"] is True
    assert "unknown frame ids ['f009']" in r1["content"]
    [r2] = results_of(api.requests[2])
    assert "scale reference" in r2["content"]


async def test_image_tool_and_budget() -> None:
    a, api = agent(
        [
            message(
                tool_use("get_frame_image", {"frame_id": "f002"}),
                tool_use("get_frame_image", {"frame_id": "f001"}, id="toolu_2"),
            ),
            message(tool_use("submit_report", SUBMIT_OK, id="toolu_3")),
        ],
        max_image_views=1,
    )

    await a.consolidate(uuid.uuid4(), ANALYSES, load_image)

    image, budget = results_of(api.requests[1])
    assert image["content"][0]["type"] == "image"
    assert image["content"][1]["text"] == "Frame f002"
    assert budget["is_error"] is True
    assert "budget" in budget["content"]


async def test_invalid_tool_input_and_unknown_frame_are_errors() -> None:
    a, api = agent(
        [
            message(
                tool_use("get_frame_findings", {"frame_ids": ["f404"]}),
                tool_use(
                    "submit_report",
                    {"lines": [{**GAS_LINE, "confidence": 3}], "remarks": []},
                    id="toolu_2",
                ),
            ),
            message(tool_use("submit_report", SUBMIT_OK, id="toolu_3")),
        ]
    )
    await a.consolidate(uuid.uuid4(), ANALYSES, load_image)

    unknown, invalid = results_of(api.requests[1])
    assert "unknown frame ids ['f404']" in unknown["content"]
    assert "lines.0.confidence" in invalid["content"]


async def test_text_only_answer_gets_a_nudge() -> None:
    a, api = agent(
        [message(text="Here is my summary..."), message(tool_use("submit_report", SUBMIT_OK))]
    )
    await a.consolidate(uuid.uuid4(), ANALYSES, load_image)
    assert api.requests[1]["messages"][-1] == {"role": "user", "content": NUDGE}


async def test_turn_limit() -> None:
    a, _ = agent([message(text="thinking...")] * 3, max_turns=3)
    with pytest.raises(ConsolidationError, match="no valid report after 3 turns") as exc:
        await a.consolidate(uuid.uuid4(), ANALYSES, load_image)
    assert len(exc.value.usage) == 3


async def test_refusal() -> None:
    refusal = message(
        stop_reason="refusal",
        stop_details={"type": "refusal", "category": None, "explanation": None},
    )
    a, _ = agent([refusal])
    with pytest.raises(ConsolidationError, match="refused"):
        await a.consolidate(uuid.uuid4(), ANALYSES, load_image)


async def test_observation_claimed_twice_is_rejected() -> None:
    twice = {"lines": [GAS_LINE, {**GAS_LINE, "notes": "same pipe again"}], "remarks": []}
    missing = {
        "lines": [{**GAS_LINE, "observations": [{"frame_id": "f001", "line_index": 5}]}],
        "remarks": [],
    }
    a, api = agent(
        [
            message(tool_use("submit_report", twice)),
            message(tool_use("submit_report", missing, id="toolu_2")),
            message(tool_use("submit_report", SUBMIT_OK, id="toolu_3")),
        ]
    )

    consolidation, _ = await a.consolidate(uuid.uuid4(), ANALYSES, load_image)

    [line] = consolidation.lines
    assert [str(r) for r in line.observations] == ["f001#0", "f002#0"]
    [r1] = results_of(api.requests[1])
    assert "L2: observation f001#0 is already used by L1" in r1["content"]
    [r2] = results_of(api.requests[2])
    assert "f001#5 does not exist" in r2["content"]


def test_submit_tool_requires_observations() -> None:
    [submit] = [t for t in TOOLS if t["name"] == "submit_report"]
    line_schema = json.dumps(submit["input_schema"])
    assert "observations" in line_schema
    assert "seen_in_frames" not in line_schema
