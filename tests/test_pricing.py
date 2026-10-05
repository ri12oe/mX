import logging

import pytest

from api.config import settings
from api.pricing import CODE_RUN_FEE_USD, PRICES, WEB_SEARCH_FEE_USD, cost_usd


def test_one_million_tokens_cost_the_listed_price():
    assert cost_usd("claude-opus-5-5", 1_000_000, 0) == 4.00
    assert cost_usd("claude-opus-5-5", 0, 1_000_000) == 20.00
    assert cost_usd("claude-opus-5-5", 0, 0, cache_write_5m_tokens=1_000_000) == 5.00
    assert cost_usd("claude-opus-5-5", 0, 0, cache_write_1h_tokens=1_000_000) == 8.00
    assert cost_usd("claude-opus-5-5", 0, 0, cache_read_tokens=1_000_000) == 0.20


def test_first_live_call_cost():
    """The Phase 1 smoke test: 32 input + 4 output tokens on Opus 5.5."""
    assert cost_usd("claude-opus-5-5", 32, 4) == pytest.approx(0.000208)


def test_full_turn_worked_by_hand():
    """Opus 5.5, every kind of token plus two searches and a code run.

    (1,000×4 + 800×20 + 2,000×5 + 500×8 + 10,000×0.20) / 1e6 = 0.036, + 2 × $0.01 = 0.056
    """
    cost = cost_usd(
        "claude-opus-5-5", 1_000, 800,
        cache_write_5m_tokens=2_000, cache_write_1h_tokens=500, cache_read_tokens=10_000,
        web_searches=2, code_runs=1,
    )
    assert cost == pytest.approx(0.056)


def test_cache_only_turn():
    """A cached prompt: 100k tokens read from cache cost $0.02 instead of $0.40 uncached."""
    assert cost_usd("claude-opus-5-5", 0, 0, cache_read_tokens=100_000) == pytest.approx(0.02)
    assert cost_usd("claude-opus-5-5", 100_000, 0) == pytest.approx(0.40)


def test_tool_fees():
    assert WEB_SEARCH_FEE_USD == 0.01  # $10 per 1,000 searches
    assert CODE_RUN_FEE_USD == 0.0  # free alongside web_search_20260209
    assert cost_usd("claude-opus-5-5", 0, 0, web_searches=3) == pytest.approx(0.03)
    assert cost_usd("claude-opus-5-5", 0, 0, code_runs=5) == 0.0


def test_zero_tokens_cost_nothing():
    assert cost_usd("claude-opus-5-5", 0, 0) == 0.0


def test_unknown_model_returns_none_and_warns(caplog: pytest.LogCaptureFixture):
    with caplog.at_level(logging.WARNING, logger="api.pricing"):
        assert cost_usd("claude-mystery-9", 100, 100, web_searches=1) is None
    assert "claude-mystery-9" in caplog.text


def test_configured_model_has_a_price():
    assert settings.primary_model in PRICES


@pytest.mark.parametrize("model", list(PRICES))
def test_prices_follow_anthropics_multipliers(model: str):
    """Catches typos: cache writes are 1.25x / 2x input; reads 0.1x (0.05x on Opus 5.5)."""
    p = PRICES[model]
    assert 0 < p.input < p.output
    assert p.cache_write_5m == pytest.approx(p.input * 1.25)
    assert p.cache_write_1h == pytest.approx(p.input * 2)
    read_multiplier = 0.05 if model == "claude-opus-5-5" else 0.1
    assert p.cache_read == pytest.approx(p.input * read_multiplier)
