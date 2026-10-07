"""Monthly budget guard (design.md §16). No network, no cost."""
import sqlite3
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone, tzinfo

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from api import db
from api.budget import budget_status, current_month, month_window, state_for
from api.config import Settings, settings
from api.main import app, get_db, get_provider
from tests.fakes import FakeProvider
from tests.test_chat import HEADERS, parse_sse

EST = timezone(timedelta(hours=-5))


class ToyEastern(tzinfo):
    """US Eastern for 2026 only: EDT (-4) from 8 Mar 02:00 to 1 Nov 02:00, else EST (-5).

    Stands in for zoneinfo, which needs the tzdata package on Windows.
    """

    def utcoffset(self, dt: datetime | None) -> timedelta:
        assert dt is not None
        naive = dt.replace(tzinfo=None)
        in_dst = datetime(2026, 3, 8, 2) <= naive < datetime(2026, 11, 1, 2)
        return timedelta(hours=-4 if in_dst else -5)

    def dst(self, dt: datetime | None) -> timedelta:
        return self.utcoffset(dt) + timedelta(hours=5)

    def tzname(self, dt: datetime | None) -> str:
        return "EDT" if self.dst(dt) else "EST"


EASTERN = ToyEastern()


def spend(conn: sqlite3.Connection, cost: float | None, at: datetime, status: db.UsageStatus = "ok") -> None:
    usage = db.UsageRecord("anthropic", "claude-opus-5-5", "v", 1, 1, cost, 1, status=status)
    db.save_spend(conn, usage, now=at.astimezone(timezone.utc).isoformat(timespec="microseconds"))


# --- States ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("spent", "state"),
    [(0, "ok"), (15.99, "ok"), (16.0, "warning"), (19.99, "warning"), (20.0, "brief"), (35, "brief")],
)
def test_state_thresholds_for_a_20_dollar_limit(spent: float, state: str):
    assert state_for(spent, 20.0) == state


# --- Local-time months -----------------------------------------------------


def test_month_window_with_a_fixed_offset():
    month = month_window(2026, 10, EST)
    assert month.label == "2026-10"
    assert month.start_utc == "2026-10-01T05:00:00.000000+00:00"
    assert month.end_utc == "2026-11-01T05:00:00.000000+00:00"
    assert month.resets_at == "2026-11-01T00:00:00-05:00"


def test_month_window_across_daylight_saving():
    """October starts in EDT (-4); November 1 midnight is still EDT; December starts in EST (-5)."""
    october, november = month_window(2026, 10, EASTERN), month_window(2026, 11, EASTERN)
    assert (october.start_utc, october.end_utc) == (
        "2026-10-01T04:00:00.000000+00:00", "2026-11-01T04:00:00.000000+00:00")
    assert october.resets_at == "2026-11-01T00:00:00-04:00"
    assert (november.start_utc, november.end_utc) == (
        "2026-11-01T04:00:00.000000+00:00", "2026-12-01T05:00:00.000000+00:00")
    assert november.end_utc == month_window(2026, 12, EASTERN).start_utc  # no gap, no overlap


def test_december_rolls_into_january():
    december = month_window(2026, 12, EST)
    assert december.end_utc == "2027-01-01T05:00:00.000000+00:00"
    assert december.resets_at == "2027-01-01T00:00:00-05:00"


@pytest.mark.parametrize(
    ("utc", "label"),
    [
        ("2026-11-01T03:59:59+00:00", "2026-10"),  # 23:59:59 on Oct 31, local (EDT)
        ("2026-11-01T04:00:00+00:00", "2026-11"),  # local midnight: a new month
        ("2026-12-01T04:59:59+00:00", "2026-11"),  # 23:59:59 on Nov 30, local (EST)
        ("2026-12-01T05:00:00+00:00", "2026-12"),
    ],
)
def test_month_rolls_over_at_local_midnight(utc: str, label: str):
    assert current_month(datetime.fromisoformat(utc), EASTERN).label == label


def test_system_time_zone_is_used_by_default():
    """With no tz given, the laptop's own zone (and its DST rules for that date) is used."""
    local_start = datetime(2026, 10, 1).astimezone()
    expected = local_start.astimezone(timezone.utc).isoformat(timespec="microseconds")
    assert month_window(2026, 10).start_utc == expected


# --- Spend -----------------------------------------------------------------


def test_status_sums_this_local_month_only(conn: sqlite3.Connection):
    now = datetime(2026, 10, 20, 12, tzinfo=EST)
    spend(conn, 5.0, datetime(2026, 10, 1, 0, 30, tzinfo=EST))  # just after local midnight: October
    spend(conn, 7.0, datetime(2026, 10, 31, 23, 30, tzinfo=EST))  # 04:30 UTC Nov 1, still October locally
    spend(conn, 100.0, datetime(2026, 9, 30, 23, 30, tzinfo=EST))  # September
    spend(conn, 100.0, datetime(2026, 11, 1, 0, 0, tzinfo=EST))  # November
    status = budget_status(conn, 20.0, now=now, tz=EST)
    assert (status.month, status.spent_usd, status.state) == ("2026-10", 12.0, "ok")
    assert status.resets_at == "2026-11-01T00:00:00-05:00"


def test_failed_and_aborted_turns_count_and_unknown_costs_are_zero(conn: sqlite3.Connection):
    now = datetime(2026, 10, 20, 12, tzinfo=EST)
    spend(conn, 10.0, now)
    spend(conn, 4.0, now, status="failed")
    spend(conn, 2.5, now, status="aborted")
    spend(conn, None, now)  # a model with no price
    status = budget_status(conn, 20.0, now=now, tz=EST)
    assert (status.spent_usd, status.state, status.unknown_cost_replies) == (16.5, "warning", 1)


def test_empty_month(conn: sqlite3.Connection):
    status = budget_status(conn, 20.0, now=datetime(2026, 10, 20, tzinfo=EST), tz=EST)
    assert (status.spent_usd, status.state, status.unknown_cost_replies) == (0.0, "ok", 0)


# --- Setting ---------------------------------------------------------------


@pytest.mark.parametrize("value", [0, -5])
def test_budget_setting_must_be_positive(value: float):
    with pytest.raises(ValidationError, match="MONTHLY_BUDGET_USD"):
        Settings(monthly_budget_usd=value)


def test_budget_setting_defaults_to_20():
    assert Settings.model_fields["monthly_budget_usd"].default == 20.0


# --- /chat applies the guard -----------------------------------------------


@pytest.fixture
def fake() -> FakeProvider:
    return FakeProvider(chunks=["Ok."], model="claude-opus-5-5", input_tokens=500, output_tokens=40)


@pytest.fixture
def client(conn: sqlite3.Connection, fake: FakeProvider) -> Iterator[TestClient]:
    app.dependency_overrides[get_db] = lambda: conn
    app.dependency_overrides[get_provider] = lambda: fake
    yield TestClient(app)
    app.dependency_overrides.clear()


def spend_now(conn: sqlite3.Connection, cost: float) -> None:
    spend(conn, cost, datetime.now(timezone.utc))


def chat(client: TestClient, **body: object) -> list[tuple[str, dict]]:
    r = client.post("/chat", json={"message": "Explain limits", "mode": "normal", **body}, headers=HEADERS)
    assert r.status_code == 200
    return parse_sse(r.text)


def test_under_budget_uses_the_requested_mode(client: TestClient, fake: FakeProvider):
    meta = chat(client)[0][1]
    assert (meta["mode"], meta["tools"]) == ("normal", True)
    assert meta["budget"]["state"] == "ok" and meta["budget"]["forced"] is False
    assert meta["budget"]["limit_usd"] == settings.monthly_budget_usd
    assert fake.calls[0].opts["max_tokens"] == 16000


def test_warning_still_uses_the_requested_mode(client: TestClient, conn: sqlite3.Connection, fake: FakeProvider):
    spend_now(conn, 16.5)
    meta = chat(client)[0][1]
    assert (meta["mode"], meta["budget"]["state"], meta["budget"]["forced"]) == ("normal", "warning", False)
    assert fake.calls[0].opts["effort"] == "high"


def test_at_the_limit_forces_brief_mode_and_tools_off(client: TestClient, conn: sqlite3.Connection, fake: FakeProvider):
    spend_now(conn, 20.0)
    events = chat(client)
    meta = events[0][1]
    assert (meta["mode"], meta["tools"]) == ("brief", False)
    assert meta["budget"] | {"resets_at": None} == {
        "state": "brief", "spent_usd": 20.0, "limit_usd": 20.0, "resets_at": None, "forced": True}

    call = fake.calls[0]
    assert (call.opts["max_tokens"], call.opts["effort"]) == (2048, "low")
    assert "Mode: brief" in call.system[0].text
    assert conn.execute("SELECT mode FROM usage WHERE message_id IS NOT NULL").fetchone()[0] == "brief"


def test_override_runs_one_message_as_requested(client: TestClient, conn: sqlite3.Connection, fake: FakeProvider):
    spend_now(conn, 25.0)
    meta = chat(client, budget_override=True)[0][1]
    assert (meta["mode"], meta["tools"], meta["budget"]["forced"]) == ("normal", True, False)
    assert meta["budget"]["state"] == "brief"  # still over; the UI keeps showing it
    assert fake.calls[0].opts["max_tokens"] == 16000

    chat(client)  # the next message without the override is forced again
    assert fake.calls[1].opts["max_tokens"] == 2048


def test_done_reports_the_budget_after_this_reply(client: TestClient, conn: sqlite3.Connection):
    spend_now(conn, 15.999)
    done = chat(client)[-1][1]  # this reply: 500×$4 + 40×$20 per million = $0.0028
    assert done["budget"]["spent_usd"] == pytest.approx(16.0018)
    assert done["budget"]["state"] == "warning"


def test_limit_comes_from_the_setting(client: TestClient, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "monthly_budget_usd", 1.0)
    spend_now(conn, 1.0)
    meta = chat(client)[0][1]
    assert (meta["mode"], meta["budget"]["limit_usd"]) == ("brief", 1.0)
