"""Claude adapters (official `anthropic` SDK): VisionModel, ReportAgent and Verifier."""

import base64
import logging
import time
from typing import Literal
from uuid import UUID

import anthropic
from anthropic.types.beta import (
    BetaMessage,
    BetaMessageParam,
    BetaOutputConfigParam,
    BetaTextBlockParam,
)
from pydantic import ValidationError

from app.adapters.llm.pricing import cost_usd
from app.adapters.llm.prompts import load_prompt
from app.adapters.llm.schemas import FrameFindings
from app.domain.errors import FrameAnalysisError
from app.domain.models import FrameAnalysis, LLMUsage, TrenchReport

logger = logging.getLogger(__name__)

type Effort = Literal["low", "medium", "high", "xhigh", "max"]

# Server-side fallback on a policy refusal: the API re-runs the request on a substitute
# model within the same call. Only some models accept it (not Haiku).
FALLBACK_BETA = "server-side-fallback-2026-07-01"
MODELS_WITH_FALLBACKS = frozenset({"claude-opus-5-5", "claude-sonnet-5-5"})

ANALYZE_INSTRUCTION = "Analyze this trench image and return the findings."


def usage_from_response(response: BetaMessage, prompt_version: str, latency_s: float) -> LLMUsage:
    u = response.usage
    cache_read = u.cache_read_input_tokens or 0
    cache_write = u.cache_creation_input_tokens or 0
    return LLMUsage(
        model=response.model,  # the model that actually served it (may be a fallback)
        prompt_version=prompt_version,
        input_tokens=u.input_tokens + cache_read + cache_write,
        output_tokens=u.output_tokens,
        cost_usd=cost_usd(
            response.model,
            input_tokens=u.input_tokens,
            output_tokens=u.output_tokens,
            cache_read_tokens=cache_read,
            cache_write_tokens=cache_write,
        ),
        latency_s=round(latency_s, 3),
    )


def _validation_summary(error: ValidationError, limit: int = 10) -> str:
    lines = [
        f"- {'.'.join(str(p) for p in e['loc']) or '(root)'}: {e['msg']}"
        for e in error.errors()[:limit]
    ]
    return "\n".join(lines)


class ClaudeVisionModel:
    """Per-frame extraction with structured output.

    The JSON schema is enforced by the API; constraints it cannot express (value ranges,
    minimum list length) are checked by Pydantic. On a validation error the model gets one
    retry with the errors, then the frame fails with `FrameAnalysisError`.
    """

    def __init__(
        self,
        client: anthropic.AsyncAnthropic,
        model: str,
        *,
        prompt_version: str = "v1",
        effort: Effort = "medium",
        max_tokens: int = 16_000,
        refusal_fallback: bool = True,
    ) -> None:
        self.client = client
        self.model = model
        self.prompt_version = prompt_version
        self.max_tokens = max_tokens
        self.use_fallback = refusal_fallback and model in MODELS_WITH_FALLBACKS
        # Same bytes for every frame, so the system prompt is a stable cache prefix.
        self._system: list[BetaTextBlockParam] = [
            {
                "type": "text",
                "text": load_prompt("analyze_frame", prompt_version),
                "cache_control": {"type": "ephemeral"},
            }
        ]
        self._output_config: BetaOutputConfigParam = {
            "effort": effort,
            "format": {
                "type": "json_schema",
                "schema": anthropic.transform_schema(FrameFindings.model_json_schema()),
            },
        }

    async def analyze(self, image: bytes, frame_id: str) -> tuple[FrameAnalysis, list[LLMUsage]]:
        messages: list[BetaMessageParam] = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/jpeg",
                            "data": base64.standard_b64encode(image).decode("ascii"),
                        },
                    },
                    {"type": "text", "text": ANALYZE_INSTRUCTION},
                ],
            }
        ]
        usage: list[LLMUsage] = []

        for attempt in (1, 2):
            response = await self._call(messages, usage)
            text = self._output_text(response, usage)
            try:
                findings = FrameFindings.model_validate_json(text)
            except ValidationError as e:
                if attempt == 2:
                    raise FrameAnalysisError(
                        f"invalid output after retry:\n{_validation_summary(e)}", usage
                    ) from e
                logger.info("frame %s: invalid output, retrying once", frame_id)
                messages += [
                    {"role": "assistant", "content": response.content},
                    {
                        "role": "user",
                        "content": "Your JSON did not pass validation:\n"
                        f"{_validation_summary(e)}\nReturn the corrected JSON.",
                    },
                ]
                continue
            return findings.to_domain(frame_id), usage

        raise AssertionError("unreachable")  # pragma: no cover

    async def _call(self, messages: list[BetaMessageParam], usage: list[LLMUsage]) -> BetaMessage:
        started = time.perf_counter()
        try:
            response = await self.client.beta.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=self._system,
                messages=messages,
                output_config=self._output_config,
                betas=[FALLBACK_BETA] if self.use_fallback else anthropic.omit,
                fallbacks="default" if self.use_fallback else anthropic.omit,
            )
        except anthropic.AuthenticationError as e:
            raise FrameAnalysisError("Anthropic API authentication failed", usage) from e
        except anthropic.APIStatusError as e:  # after the SDK's own retries
            raise FrameAnalysisError(
                f"Anthropic API error {e.status_code}: {e.message}", usage
            ) from e
        except anthropic.APIConnectionError as e:
            raise FrameAnalysisError(f"Anthropic API unreachable: {e}", usage) from e

        usage.append(
            usage_from_response(response, self.prompt_version, time.perf_counter() - started)
        )
        if response.model != self.model:
            logger.warning("request for %s was served by fallback %s", self.model, response.model)
        return response

    @staticmethod
    def _output_text(response: BetaMessage, usage: list[LLMUsage]) -> str:
        if response.stop_reason == "refusal":
            category = response.stop_details.category if response.stop_details else None
            raise FrameAnalysisError(f"model refused (category: {category})", usage)
        if response.stop_reason == "max_tokens":
            raise FrameAnalysisError("output truncated at max_tokens", usage)
        text = "".join(b.text for b in response.content if b.type == "text")
        if not text:
            raise FrameAnalysisError(f"no text output (stop_reason: {response.stop_reason})", usage)
        return text


class ClaudeReportAgent:
    """Hand-written tool-use loop. Tools: get_frame_findings, get_frame_image, submit_report."""

    def __init__(
        self,
        client: anthropic.AsyncAnthropic,
        model: str,
        *,
        prompt_version: str = "v1",
        max_turns: int = 10,
    ) -> None:
        self.client = client
        self.model = model
        self.prompt_version = prompt_version
        self.max_turns = max_turns

    async def consolidate(
        self, job_id: UUID, analyses: list[FrameAnalysis]
    ) -> tuple[TrenchReport, list[LLMUsage]]:
        raise NotImplementedError


class ClaudeVerifier:
    def __init__(
        self, client: anthropic.AsyncAnthropic, model: str, *, prompt_version: str = "v1"
    ) -> None:
        self.client = client
        self.model = model
        self.prompt_version = prompt_version

    async def verify(
        self, report: TrenchReport, analyses: list[FrameAnalysis]
    ) -> tuple[list[str], LLMUsage]:
        raise NotImplementedError
