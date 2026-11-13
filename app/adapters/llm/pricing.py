"""Per-model token prices for cost logging (Anthropic first-party API, USD per 1M tokens).

Prices as of 2026-11. Cache writes (5 min TTL) cost 1.25x the input price, cache reads 0.1x
unless the model's price sheet says otherwise.
"""

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Price:
    input: float
    output: float
    cache_read: float
    cache_write: float


def _price(per_input: float, per_output: float, cache_read: float | None = None) -> Price:
    return Price(
        input=per_input,
        output=per_output,
        cache_read=cache_read if cache_read is not None else per_input * 0.1,
        cache_write=per_input * 1.25,
    )


PRICES: frozendict[str, Price] = frozendict(
    {
        "claude-opus-5-5": _price(4.00, 20.00, cache_read=0.20),
        "claude-sonnet-5-5": _price(2.00, 10.00, cache_read=0.10),
        "claude-sonnet-5": _price(2.00, 10.00),  # refusal fallback target of Sonnet 5.5
        "claude-haiku-5-5": _price(0.10, 0.50),  # prompts up to 100K tokens
    }
)


def cost_usd(
    model: str,
    *,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> float:
    """`input_tokens` is the uncached part only, as reported by the API."""
    price = PRICES.get(model)
    if price is None:
        logger.warning("no price for model %s, cost recorded as 0", model)
        return 0.0
    total = (
        input_tokens * price.input
        + output_tokens * price.output
        + cache_read_tokens * price.cache_read
        + cache_write_tokens * price.cache_write
    )
    return round(total / 1_000_000, 6)
