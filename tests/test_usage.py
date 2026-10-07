"""GET /usage/budget and /usage/summary (design.md §5, §16). No network, no cost."""
import sqlite3
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from api import db
from api.budget import current_month
from api.main import app, get_db
from api.usage import cache_hit_rate, summarize
from tests.test_chat import HEADERS

EST = timezone(timedelta(hours=-5))


def spend(
    conn: sqlite3.Connection, at: datetime, cost: float | None = 0.01, status: db.UsageStatus = "ok", **counts: int,
) -> None:
    values = {"input_tokens": 100, "output_tokens": 10, **counts}
    usage = db.UsageRecord("anthropic", "claude-opus-5-5", "v", values.pop("input_tokens"),
                           values.pop("output_tokens"), cost, 1, status=status, **values)  # type: ignore[arg-type]
    db.save_spend(conn, usage, now=at.astimezone(timezone.utc).isoformat(timespec="microseconds"))


@pytest.fixture
def client(conn: sqlite3.Connection) -> Iterator[TestClient]:
    app.dependency_overrides[get_db] = lambda: conn
    yield TestClient(app)
    app.dependency_overrides.clear()


# --- Summary logic (time zone injected) -------------------------------------


def test_empty_month(conn: sqlite3.Connection):
    s = summarize(conn, "2026-10", 20.0, tz=EST)
    assert (s["month"], s["spent_usd"], s["state"], s["days"]) == ("2026-10", 0.0, "ok", [])
    assert s["totals"]["replies"] == 0 and s["totals"]["cache_hit_rate"] is None
    assert s["resets_at"] == "2026-11-01T00:00:00-05:00"


def test_days_are_local_dates(conn: sqlite3.Connection):
    """A reply at 23:30 local is 04:30 UTC the next day, but belongs to the local day."""
    spend(conn, datetime(2026, 10, 5, 23, 30, tzinfo=EST), cost=0.02)
    spend(conn, datetime(2026, 10, 6, 0, 30, tzinfo=EST), cost=0.03)
    days = summarize(conn, "2026-10", 20.0, tz=EST)["days"]
    assert [(d["date"], d["cost_usd"], d["replies"]) for d in days] == [("2026-10-05", 0.02, 1), ("2026-10-06", 0.03, 1)]


def test_other_months_are_excluded(conn: sqlite3.Connection):
    spend(conn, datetime(2026, 9, 30, 23, 59, tzinfo=EST), cost=5.0)
    spend(conn, datetime(2026, 10, 1, 0, 0, tzinfo=EST), cost=1.0)
    spend(conn, datetime(2026, 10, 31, 23, 59, tzinfo=EST), cost=2.0)
    spend(conn, datetime(2026, 11, 1, 0, 0, tzinfo=EST), cost=7.0)
    s = summarize(conn, "2026-10", 20.0, tz=EST)
    assert s["spent_usd"] == 3.0
    assert [d["date"] for d in s["days"]] == ["2026-10-01", "2026-10-31"]


def test_totals_count_failed_turns_and_cache_hit_rate(conn: sqlite3.Connection):
    day = datetime(2026, 10, 7, 12, tzinfo=EST)
    spend(conn, day, cost=0.01, input_tokens=100, cache_read_tokens=800, cache_write_5m_tokens=100)
    spend(conn, day, cost=0.004, status="failed", input_tokens=50, output_tokens=0)
    spend(conn, day, cost=0.002, status="aborted", input_tokens=50, output_tokens=0, web_searches=1, code_runs=2)
    spend(conn, day, cost=None)
    s = summarize(conn, "2026-10", 20.0, tz=EST)
    t = s["totals"]
    assert (t["replies"], t["failed_turns"], t["unknown_cost_replies"]) == (2, 2, 1)
    assert (t["input_tokens"], t["cache_read_tokens"], t["cache_write_tokens"]) == (300, 800, 100)
    assert (t["web_searches"], t["code_runs"]) == (1, 2)
    assert t["cache_hit_rate"] == 0.6667  # 800 / (300 + 800 + 100), rounded to 4 places
    assert s["spent_usd"] == pytest.approx(0.016)  # failed and stopped turns cost money too
    assert s["days"][0]["cache_hit_rate"] == 0.6667


def test_state_is_measured_against_the_limit(conn: sqlite3.Connection):
    spend(conn, datetime(2026, 10, 7, tzinfo=EST), cost=17.0)
    assert summarize(conn, "2026-10", 20.0, tz=EST)["state"] == "warning"
    assert summarize(conn, "2026-10", 10.0, tz=EST)["state"] == "brief"


def test_cache_hit_rate_math():
    assert cache_hit_rate(100, 900, 0) == 0.9
    assert cache_hit_rate(0, 0, 0) is None
    assert cache_hit_rate(1000, 0, 0) == 0.0


# --- Endpoints ---------------------------------------------------------------


def test_budget_endpoint(client: TestClient, conn: sqlite3.Connection):
    spend(conn, datetime.now(timezone.utc), cost=4.12)
    body = client.get("/usage/budget", headers=HEADERS).json()
    month = current_month()
    assert body == {"state": "ok", "spent_usd": 4.12, "limit_usd": 20.0,
                    "month": month.label, "resets_at": month.resets_at}


def test_summary_defaults_to_this_month(client: TestClient, conn: sqlite3.Connection):
    now = datetime.now(timezone.utc)
    spend(conn, now, cost=0.5)
    body = client.get("/usage/summary", headers=HEADERS).json()
    assert body["month"] == current_month().label
    assert body["spent_usd"] == 0.5
    assert body["days"][0]["date"] == now.astimezone().date().isoformat()  # the laptop's local date


def test_summary_for_a_chosen_month(client: TestClient, conn: sqlite3.Connection):
    body = client.get("/usage/summary", params={"month": "2026-01"}, headers=HEADERS).json()
    assert (body["month"], body["days"]) == ("2026-01", [])


@pytest.mark.parametrize("month", ["2026-13", "2026-1", "26-10", "october", "2026-00", "1999-10"])
def test_bad_month_is_422(client: TestClient, month: str):
    assert client.get("/usage/summary", params={"month": month}, headers=HEADERS).status_code == 422


@pytest.mark.parametrize("path", ["/usage/budget", "/usage/summary"])
def test_auth_required(client: TestClient, path: str):
    assert client.get(path).status_code == 401
