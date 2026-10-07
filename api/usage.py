"""Cost endpoints: the month's budget and a per-day summary (design.md §5, §16).

Days are local calendar dates: the month's rows are fetched by their UTC
range and grouped by local date here, not in SQL.
"""
import sqlite3
from collections import defaultdict
from datetime import datetime, tzinfo
from typing import Any

from fastapi import APIRouter, Depends, Query

from api import budget
from api.config import settings
from api.deps import get_db, require_auth

router = APIRouter(prefix="/usage", dependencies=[Depends(require_auth)])

MONTH_PATTERN = r"^20\d{2}-(0[1-9]|1[0-2])$"
COUNTERS = ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens",
            "web_searches", "code_runs")


@router.get("/budget")
def get_budget(conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """This month's spend against MONTHLY_BUDGET_USD. The status card calls it on load."""
    status = budget.budget_status(conn, settings.monthly_budget_usd)
    return {"state": status.state, "spent_usd": status.spent_usd, "limit_usd": status.limit_usd,
            "month": status.month, "resets_at": status.resets_at}


@router.get("/summary")
def get_summary(
    month: str | None = Query(default=None, pattern=MONTH_PATTERN, description="YYYY-MM; default: this month"),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    """Month totals and one row per local day with any usage, oldest first."""
    return summarize(conn, month, settings.monthly_budget_usd)


def summarize(
    conn: sqlite3.Connection, label: str | None, limit_usd: float, tz: tzinfo | None = None
) -> dict[str, Any]:
    window = budget.current_month(tz=tz) if label is None else budget.month_window(*budget.parse_month(label), tz)
    status = budget.month_status(conn, window, limit_usd)
    rows = conn.execute(
        "SELECT created_at, status, cost_usd, input_tokens, output_tokens, cache_read_tokens,"
        " cache_write_5m_tokens + cache_write_1h_tokens AS cache_write_tokens, web_searches, code_runs"
        " FROM usage WHERE created_at >= ? AND created_at < ? ORDER BY created_at",
        (window.start_utc, window.end_utc),
    ).fetchall()

    totals = _tally(rows)
    by_day: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for row in rows:
        by_day[_local_date(row["created_at"], tz)].append(row)
    days = []
    for date, day_rows in sorted(by_day.items()):
        day = _tally(day_rows)
        days.append({"date": date, "cost_usd": day["cost_usd"], "replies": day["replies"],
                     "web_searches": day["web_searches"], "code_runs": day["code_runs"],
                     "cache_hit_rate": day["cache_hit_rate"]})
    totals.pop("cost_usd")
    return {
        "month": status.month, "limit_usd": status.limit_usd, "spent_usd": status.spent_usd,
        "state": status.state, "resets_at": status.resets_at, "totals": totals, "days": days,
    }


def _tally(rows: list[sqlite3.Row]) -> dict[str, Any]:
    """Sums for a set of usage rows. `replies` are completed turns; failed and stopped ones are separate."""
    sums = {name: sum(row[name] for row in rows) for name in COUNTERS}
    return {
        "replies": sum(row["status"] == "ok" for row in rows),
        "failed_turns": sum(row["status"] != "ok" for row in rows),
        **sums,
        "cost_usd": round(sum(row["cost_usd"] or 0 for row in rows), 6),
        "cache_hit_rate": cache_hit_rate(sums["input_tokens"], sums["cache_read_tokens"], sums["cache_write_tokens"]),
        "unknown_cost_replies": sum(row["cost_usd"] is None for row in rows),
    }


def cache_hit_rate(input_tokens: int, cache_read: int, cache_write: int) -> float | None:
    """Share of the prompt that came from the cache (design.md §15). None when there was no prompt."""
    total = input_tokens + cache_read + cache_write
    return round(cache_read / total, 4) if total else None


def _local_date(created_at: str, tz: tzinfo | None) -> str:
    moment = datetime.fromisoformat(created_at)
    return (moment.astimezone(tz) if tz is not None else moment.astimezone()).date().isoformat()
