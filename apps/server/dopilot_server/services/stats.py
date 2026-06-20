"""Dashboard statistics (phase 1.7.1): daily task/run counts.

A compact 30-day series of parent-task and child-execution counts bucketed by
local calendar day in the scheduler timezone (falling back to UTC). Used by the
dashboard's native SVG bar chart — no heavyweight chart dependency.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import Date, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from ..models.execution import Execution, Task

MAX_DAYS = 365


def _zone(timezone: str) -> ZoneInfo:
    try:
        return ZoneInfo(timezone)
    except Exception:  # noqa: BLE001 - unknown tz name -> UTC fallback
        return ZoneInfo("UTC")


def _local_day(col: ColumnElement, tz_name: str, dialect: str) -> ColumnElement:
    """SQL expression for the local calendar day of a timestamptz column.

    PostgreSQL converts the instant into ``tz_name`` first (``timezone(zone,
    ts)``) so the grouping matches the scheduler-timezone bucket boundaries the
    dashboard expects. SQLite (the test DB) has no tz-aware casting; rows there
    are UTC-stored and the suite only exercises UTC, so ``date()`` on the raw
    column is the correct equivalent.
    """
    if dialect == "postgresql":
        return cast(func.timezone(tz_name, col), Date)
    return func.date(col)


async def daily_task_counts(
    session: AsyncSession,
    *,
    days: int = 30,
    timezone: str = "UTC",
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Per-day ``tasks`` (parent runs) + ``executions`` (atomic) counts.

    Returns ``days`` buckets ascending by date (oldest first), each
    ``{"date": "YYYY-MM-DD", "tasks": int, "executions": int}``. Days with no
    activity are present with zero counts so the chart has a stable x-axis.
    """
    days = max(1, min(int(days), MAX_DAYS))
    tz = _zone(timezone)
    now = (now or datetime.now(UTC)).astimezone(tz)
    today = now.date()
    start_date = today - timedelta(days=days - 1)
    # UTC cutoff covering the local window start (subtract a day of slack so a
    # row whose local date is start_date but UTC instant is earlier is included).
    cutoff = datetime.combine(start_date, datetime.min.time(), tz) - timedelta(
        days=1
    )

    buckets: dict[str, dict[str, int]] = {
        (start_date + timedelta(days=i)).isoformat(): {"tasks": 0, "executions": 0}
        for i in range(days)
    }

    # Aggregate in the database (GROUP BY local day) rather than streaming every
    # timestamp into Python — at tens of thousands of rows/day the per-refresh
    # transfer would otherwise be the whole window. Returns one row per active
    # day, which we fold into the pre-zeroed bucket map.
    dialect = session.bind.dialect.name if session.bind is not None else "sqlite"
    tz_name = tz.key

    async def _counts(col: ColumnElement) -> dict[str, int]:
        day = _local_day(col, tz_name, dialect)
        rows = await session.execute(
            select(day.label("day"), func.count())
            .where(col >= cutoff)
            .group_by(day)
        )
        out: dict[str, int] = {}
        for day_value, count in rows.all():
            if day_value is None:
                continue
            key = day_value.isoformat() if isinstance(day_value, date) else str(day_value)
            out[key] = int(count)
        return out

    for key, count in (await _counts(Task.created_at)).items():
        if key in buckets:
            buckets[key]["tasks"] += count
    for key, count in (await _counts(Execution.created_at)).items():
        if key in buckets:
            buckets[key]["executions"] += count

    return [
        {"date": day, "tasks": v["tasks"], "executions": v["executions"]}
        for day, v in sorted(buckets.items())
    ]
