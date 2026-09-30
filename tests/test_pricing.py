import logging

import pytest

from api.config import settings
from api.pricing import PRICES_PER_MTOK, cost_usd


def test_one_million_tokens_cost_the_listed_price():
    assert cost_usd("claude-opus-5-5", 1_000_000, 0) == 4.00
    assert cost_usd("claude-opus-5-5", 0, 1_000_000) == 20.00


def test_first_live_call_cost():
    """The task 6 smoke test: 32 input + 4 output tokens on Opus 5.5."""
    assert cost_usd("claude-opus-5-5", 32, 4) == pytest.approx(0.000208)


def test_zero_tokens_cost_nothing():
    assert cost_usd("claude-opus-5-5", 0, 0) == 0.0


def test_unknown_model_returns_none_and_warns(caplog: pytest.LogCaptureFixture):
    with caplog.at_level(logging.WARNING, logger="api.pricing"):
        assert cost_usd("claude-mystery-9", 100, 100) is None
    assert "claude-mystery-9" in caplog.text


def test_configured_model_has_a_price():
    assert settings.primary_model in PRICES_PER_MTOK


def test_prices_are_positive_and_output_costs_more():
    for model, (input_price, output_price) in PRICES_PER_MTOK.items():
        assert 0 < input_price < output_price, model
