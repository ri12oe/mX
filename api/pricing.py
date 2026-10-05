"""Model prices, tool fees, and turn cost (design.md §9, §9.1).

Prices are USD per million tokens, from Anthropic's pricing page
(https://platform.claude.com/docs/en/about-claude/pricing), checked 2026-10-05.
Verify there when adding or changing a model.
"""
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ModelPrice:
    """USD per million tokens."""

    input: float  # uncached input
    output: float  # includes thinking
    cache_write_5m: float  # 1.25x input
    cache_write_1h: float  # 2x input
    cache_read: float  # 0.1x input (0.05x on Opus 5.5)


PRICES: dict[str, ModelPrice] = {
    "claude-opus-5-5": ModelPrice(4.00, 20.00, 5.00, 8.00, 0.20),     # PRIMARY_MODEL
    "claude-opus-5": ModelPrice(5.00, 25.00, 6.25, 10.00, 0.50),      # possible refusal fallback
    "claude-opus-4-8": ModelPrice(5.00, 25.00, 6.25, 10.00, 0.50),    # possible refusal fallback (cyber)
    "claude-sonnet-5-5": ModelPrice(2.00, 10.00, 2.50, 4.00, 0.20),
    "claude-sonnet-5": ModelPrice(2.00, 10.00, 2.50, 4.00, 0.20),     # possible refusal fallback
}

# Per-use fees on top of tokens. Web search: $10 per 1,000 (errored searches aren't billed).
# Code execution: free when the request includes web_search_20260209 or later, which mX's
# tool requests always do; otherwise 1,550 free hours/month, far above mX's use.
WEB_SEARCH_FEE_USD = 0.01
CODE_RUN_FEE_USD = 0.0


def cost_usd(
    model: str,
    input_tokens: int,
    output_tokens: int,
    *,
    cache_read_tokens: int = 0,
    cache_write_5m_tokens: int = 0,
    cache_write_1h_tokens: int = 0,
    web_searches: int = 0,
    code_runs: int = 0,
) -> float | None:
    """Cost of one turn (all its API requests summed), or None with a warning if the model has no price.

    `input_tokens` is uncached input only, as the API reports it; cached
    tokens are passed separately and priced at the cache rates.
    """
    price = PRICES.get(model)
    if price is None:
        logger.warning("No price for model %r; cost_usd will be NULL.", model)
        return None
    tokens = (
        input_tokens * price.input
        + output_tokens * price.output
        + cache_write_5m_tokens * price.cache_write_5m
        + cache_write_1h_tokens * price.cache_write_1h
        + cache_read_tokens * price.cache_read
    ) / 1_000_000
    fees = web_searches * WEB_SEARCH_FEE_USD + code_runs * CODE_RUN_FEE_USD
    return round(tokens + fees, 6)
