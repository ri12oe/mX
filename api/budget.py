"""Monthly budget guard (design.md §16).

The month is the calendar month in the laptop's local time zone. Usage
timestamps are stored in UTC, so the local month's start and end are
converted to UTC and used as a plain indexed range. Daylight-saving changes
are handled because each boundary is converted on its own date.
"""
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timezone, tzinfo
from typing import Any, Literal

WARNING_SHARE = 0.80  # warn from 80% of the limit (a constant, not a setting)

BudgetState = Literal["ok", "warning", "brief"]


@dataclass(frozen=True)
class Month:
    label: str  # "2026-10"
    start_utc: str  # same ISO format as stored created_at values
    end_utc: str  # start of the next month (exclusive)
    resets_at: str  # next month's local midnight, with its UTC offset


@dataclass(frozen=True)
class BudgetStatus:
    state: BudgetState
    spent_usd: float
    limit_usd: float
    month: str
    resets_at: str
    unknown_cost_replies: int  # rows with no price, counted as $0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def local_midnight(year: int, month: int, tz: tzinfo | None = None) -> datetime:
    """Local midnight on the 1st. tz=None means the laptop's own time zone (with its DST rules)."""
    naive = datetime(year, month, 1)
    return naive.replace(tzinfo=tz) if tz is not None else naive.astimezone()


def month_window(year: int, month: int, tz: tzinfo | None = None) -> Month:
    next_year, next_month = (year + 1, 1) if month == 12 else (year, month + 1)
    start = local_midnight(year, month, tz)
    end = local_midnight(next_year, next_month, tz)
    return Month(
        label=f"{year:04d}-{month:02d}",
        start_utc=_utc_iso(start),
        end_utc=_utc_iso(end),
        resets_at=end.isoformat(),
    )


def current_month(now: datetime | None = None, tz: tzinfo | None = None) -> Month:
    """The local calendar month that `now` (default: now) falls in."""
    instant = now or datetime.now(timezone.utc)
    local = instant.astimezone(tz) if tz is not None else instant.astimezone()
    return month_window(local.year, local.month, tz)


def state_for(spent_usd: float, limit_usd: float) -> BudgetState:
    if spent_usd >= limit_usd:
        return "brief"
    if spent_usd >= limit_usd * WARNING_SHARE:
        return "warning"
    return "ok"


def parse_month(label: str) -> tuple[int, int]:
    """"2026-10" → (2026, 10). Raises ValueError for anything else."""
    year, _, month = label.partition("-")
    if len(year) != 4 or len(month) != 2 or not (year + month).isdigit() or not 1 <= int(month) <= 12:
        raise ValueError(f"month must look like 2026-10, got {label!r}")
    return int(year), int(month)


def budget_status(
    conn: sqlite3.Connection, limit_usd: float, now: datetime | None = None, tz: tzinfo | None = None
) -> BudgetStatus:
    """This month's spend from usage rows of every status (failed and aborted turns cost money too)."""
    return month_status(conn, current_month(now, tz), limit_usd)


def month_status(conn: sqlite3.Connection, month: Month, limit_usd: float) -> BudgetStatus:
    """Spend and state for any local month (the current one for the guard; any one for the cost page)."""
    spent, unknown = conn.execute(
        "SELECT COALESCE(SUM(cost_usd), 0), COUNT(*) - COUNT(cost_usd) FROM usage"
        " WHERE created_at >= ? AND created_at < ?",
        (month.start_utc, month.end_utc),
    ).fetchone()
    spent = round(spent, 6)
    return BudgetStatus(
        state=state_for(spent, limit_usd),
        spent_usd=spent,
        limit_usd=limit_usd,
        month=month.label,
        resets_at=month.resets_at,
        unknown_cost_replies=unknown,
    )


def _utc_iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat(timespec="microseconds")
