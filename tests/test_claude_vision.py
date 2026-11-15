import base64
import json

import anthropic
import httpx2
import pytest
from anthropic.types.beta import BetaMessage

from app.adapters.llm.claude import FALLBACK_BETA, ClaudeVisionModel
from app.adapters.llm.pricing import cost_usd
from app.domain.errors import FrameAnalysisError
from app.domain.models import Material, UtilityType
from tests.anthropic_fakes import FakeClient, FakeMessages, message

GAS_LINE = {
    "position": "bottom center",
    "color": "yellow",
    "has_stripes": False,
    "is_paired": False,
    "evidence": [{"cue": "warning_tape_text", "detail": "yellow tape 'Achtung Gasleitung'"}],
    "utility_type": "gas",
    "material": "pe",
    "is_house_connection": None,
    "approx_outer_diameter_mm": None,
    "approx_depth_of_cover_m": None,
    "confidence": 0.9,
}
FINDINGS = {
    "is_trench_visible": True,
    "scale_reference_visible": False,
    "scale_reference": None,
    "warning_tapes": ["yellow: Achtung Gasleitung"],
    "image_quality_issues": ["water"],
    "lines": [GAS_LINE],
}


def vision(
    replies: list[BetaMessage | Exception], model: str = "claude-sonnet-5-5"
) -> tuple[ClaudeVisionModel, FakeMessages]:
    client = FakeClient(replies)
    return ClaudeVisionModel(client, model), client.messages  # type: ignore[arg-type]


async def test_valid_output_becomes_frame_analysis() -> None:
    model, _ = vision([message(text=json.dumps(FINDINGS))])

    analysis, usage = await model.analyze(b"\xff\xd8jpeg", "f003")

    assert analysis.frame_id == "f003"
    assert analysis.warning_tapes == ["yellow: Achtung Gasleitung"]
    [line] = analysis.lines
    assert (line.utility_type, line.material) == (UtilityType.GAS, Material.PE)
    assert line.position == "bottom center"

    [u] = usage
    assert (u.model, u.prompt_version) == ("claude-sonnet-5-5", "v1")
    assert u.input_tokens == 3000
    assert u.cost_usd == cost_usd(
        "claude-sonnet-5-5", input_tokens=1000, output_tokens=300, cache_read_tokens=2000
    )


async def test_request_shape() -> None:
    model, api = vision([message(text=json.dumps(FINDINGS))])
    await model.analyze(b"jpeg-bytes", "f001")

    [req] = api.requests
    image, instruction = req["messages"][0]["content"]
    assert image["source"] == {
        "type": "base64",
        "media_type": "image/jpeg",
        "data": base64.standard_b64encode(b"jpeg-bytes").decode(),
    }
    assert instruction["type"] == "text"
    assert req["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert "scale reference" in req["system"][0]["text"]
    assert req["output_config"]["format"]["type"] == "json_schema"
    assert req["output_config"]["effort"] == "medium"
    assert (req["betas"], req["fallbacks"]) == ([FALLBACK_BETA], "default")


async def test_haiku_gets_no_fallback() -> None:
    model, api = vision(
        [message(text=json.dumps(FINDINGS), model="claude-haiku-5-5")], "claude-haiku-5-5"
    )
    await model.analyze(b"jpeg", "f001")
    assert api.requests[0]["betas"] is anthropic.omit
    assert api.requests[0]["fallbacks"] is anthropic.omit


async def test_invalid_output_is_retried_once_with_errors() -> None:
    bad = {**FINDINGS, "lines": [{**GAS_LINE, "confidence": 1.7, "evidence": []}]}
    model, api = vision([message(text=json.dumps(bad)), message(text=json.dumps(FINDINGS))])

    analysis, usage = await model.analyze(b"jpeg", "f001")

    assert len(analysis.lines) == 1
    assert len(usage) == 2
    retry = api.requests[1]["messages"]
    assert [m["role"] for m in retry] == ["user", "assistant", "user"]
    assert "lines.0.confidence" in retry[2]["content"]
    assert "lines.0.evidence" in retry[2]["content"]


async def test_invalid_output_twice_fails_with_usage() -> None:
    bad = json.dumps({**FINDINGS, "lines": [{**GAS_LINE, "confidence": 2}]})
    model, _ = vision([message(text=bad), message(text=bad)])

    with pytest.raises(FrameAnalysisError, match="invalid output after retry") as exc:
        await model.analyze(b"jpeg", "f001")
    assert len(exc.value.usage) == 2


@pytest.mark.parametrize(
    ("reply", "error"),
    [
        (
            message(
                stop_reason="refusal",
                stop_details={"type": "refusal", "category": "cyber", "explanation": None},
            ),
            "refused \\(category: cyber\\)",
        ),
        (message(text='{"is_trench', stop_reason="max_tokens"), "truncated"),
        (message(), "no text output"),
    ],
)
async def test_unusable_responses_fail_the_frame(reply: BetaMessage, error: str) -> None:
    model, _ = vision([reply])
    with pytest.raises(FrameAnalysisError, match=error) as exc:
        await model.analyze(b"jpeg", "f001")
    assert len(exc.value.usage) == 1


async def test_api_errors_fail_the_frame_without_usage() -> None:
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    overloaded = anthropic.InternalServerError(
        "overloaded", response=httpx2.Response(529, request=request), body=None
    )
    model, _ = vision([overloaded])
    with pytest.raises(FrameAnalysisError, match="API error 529") as exc:
        await model.analyze(b"jpeg", "f001")
    assert exc.value.usage == []


async def test_fallback_model_is_billed_at_its_own_price() -> None:
    model, _ = vision([message(text=json.dumps(FINDINGS), model="claude-sonnet-5")])
    _, [u] = await model.analyze(b"jpeg", "f001")
    assert u.model == "claude-sonnet-5"


def test_pricing() -> None:
    assert cost_usd("claude-sonnet-5-5", input_tokens=1_000_000, output_tokens=1_000_000) == 12.0
    assert cost_usd(
        "claude-haiku-5-5", input_tokens=0, output_tokens=0, cache_read_tokens=1_000_000
    ) == pytest.approx(0.01)
    assert cost_usd("unknown-model", input_tokens=10, output_tokens=10) == 0.0
