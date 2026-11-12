"""Per-model token prices (USD per 1M tokens) for cost logging. Fill in from current pricing."""

PRICES_PER_MTOK: dict[str, tuple[float, float]] = {
    # model: (input, output)
}


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    inp, out = PRICES_PER_MTOK.get(model, (0.0, 0.0))
    return (input_tokens * inp + output_tokens * out) / 1_000_000
