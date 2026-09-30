"""Model prices and reply cost (design.md §9).

Prices are USD per million tokens (input, output), from Anthropic's model
table, checked 2026-09-30. Verify against https://www.anthropic.com/pricing
when adding or changing a model.
"""
import logging

logger = logging.getLogger(__name__)

PRICES_PER_MTOK: dict[str, tuple[float, float]] = {
    "claude-opus-5-5": (4.00, 20.00),    # PRIMARY_MODEL
    "claude-opus-5": (5.00, 25.00),      # possible refusal fallback for Opus 5.5
    "claude-opus-4-8": (5.00, 25.00),    # possible refusal fallback (cyber)
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-sonnet-5": (2.00, 10.00),    # possible refusal fallback for Sonnet 5.5
}


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> float | None:
    """Cost of one reply, or None (with a warning) if the model has no price."""
    prices = PRICES_PER_MTOK.get(model)
    if prices is None:
        logger.warning("No price for model %r; cost_usd will be NULL.", model)
        return None
    input_price, output_price = prices
    return round((input_tokens * input_price + output_tokens * output_price) / 1_000_000, 6)
