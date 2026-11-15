import base64
import logging
import time
from typing import ClassVar, Literal

import anthropic
from anthropic.types.beta import (
    BetaMessage,
    BetaMessageParam,
    BetaOutputConfigParam,
    BetaTextBlockParam,
    BetaToolParam,
)
from pydantic import ValidationError

from app.adapters.llm.pricing import cost_usd
from app.adapters.llm.prompts import load_prompt
from app.adapters.llm.schemas import FrameFindings
from app.domain.errors import FrameAnalysisError, ModelCallError
from app.domain.models import FrameAnalysis, LLMUsage

logger = logging.getLogger(__name__)

type Effort = Literal["low", "medium", "high", "xhigh", "max"]

FALLBACK_BETA = "server-side-fallback-2026-07-01"
MODELS_WITH_FALLBACKS = frozenset({"claude-opus-5-5", "claude-sonnet-5-5"})

ANALYZE_INSTRUCTION = "Analyze this trench image and return the findings."


def usage_from_response(response: BetaMessage, prompt_version: str, latency_s: float) -> LLMUsage:
    u = response.usage
    cache_read = u.cache_read_input_tokens or 0
    cache_write = u.cache_creation_input_tokens or 0
    return LLMUsage(
        model=response.model,
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


def validation_summary(error: ValidationError, limit: int = 10) -> str:
    lines = [
        f"- {'.'.join(str(p) for p in e['loc']) or '(root)'}: {e['msg']}"
        for e in error.errors()[:limit]
    ]
    return "\n".join(lines)


class ClaudeClient:
    error_type: ClassVar[type[ModelCallError]] = ModelCallError

    def __init__(
        self,
        client: anthropic.AsyncAnthropic,
        model: str,
        *,
        prompt_version: str,
        max_tokens: int = 16_000,
        refusal_fallback: bool = True,
    ) -> None:
        self.client = client
        self.model = model
        self.prompt_version = prompt_version
        self.max_tokens = max_tokens
        self.use_fallback = refusal_fallback and model in MODELS_WITH_FALLBACKS

    @staticmethod
    def cached_system(text: str) -> list[BetaTextBlockParam]:
        return [{"type": "text", "text": text, "cache_control": {"type": "ephemeral"}}]

    async def _create(
        self,
        messages: list[BetaMessageParam],
        usage: list[LLMUsage],
        *,
        system: list[BetaTextBlockParam],
        output_config: BetaOutputConfigParam,
        tools: list[BetaToolParam] | None = None,
    ) -> BetaMessage:
        started = time.perf_counter()
        try:
            response = await self.client.beta.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=system,
                messages=messages,
                output_config=output_config,
                tools=tools if tools is not None else anthropic.omit,
                betas=[FALLBACK_BETA] if self.use_fallback else anthropic.omit,
                fallbacks="default" if self.use_fallback else anthropic.omit,
            )
        except anthropic.AuthenticationError as e:
            raise self.error_type("Anthropic API authentication failed", usage) from e
        except anthropic.APIStatusError as e:
            raise self.error_type(f"Anthropic API error {e.status_code}: {e.message}", usage) from e
        except anthropic.APIConnectionError as e:
            raise self.error_type(f"Anthropic API unreachable: {e}", usage) from e

        usage.append(
            usage_from_response(response, self.prompt_version, time.perf_counter() - started)
        )
        if response.model != self.model:
            logger.warning("request for %s was served by fallback %s", self.model, response.model)
        if response.stop_reason == "refusal":
            category = response.stop_details.category if response.stop_details else None
            raise self.error_type(f"model refused (category: {category})", usage)
        if response.stop_reason == "max_tokens":
            raise self.error_type("output truncated at max_tokens", usage)
        return response


class ClaudeVisionModel(ClaudeClient):
    error_type = FrameAnalysisError

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
        super().__init__(
            client,
            model,
            prompt_version=prompt_version,
            max_tokens=max_tokens,
            refusal_fallback=refusal_fallback,
        )
        self._system = self.cached_system(load_prompt("analyze_frame", prompt_version))
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
            response = await self._create(
                messages, usage, system=self._system, output_config=self._output_config
            )
            text = "".join(b.text for b in response.content if b.type == "text")
            if not text:
                raise FrameAnalysisError(
                    f"no text output (stop_reason: {response.stop_reason})", usage
                )
            try:
                findings = FrameFindings.model_validate_json(text)
            except ValidationError as e:
                if attempt == 2:
                    raise FrameAnalysisError(
                        f"invalid output after retry:\n{validation_summary(e)}", usage
                    ) from e
                logger.info("frame %s: invalid output, retrying once", frame_id)
                messages += [
                    {"role": "assistant", "content": response.content},
                    {
                        "role": "user",
                        "content": "Your JSON did not pass validation:\n"
                        f"{validation_summary(e)}\nReturn the corrected JSON.",
                    },
                ]
                continue
            return findings.to_domain(frame_id), usage

        raise AssertionError("unreachable")  # pragma: no cover
