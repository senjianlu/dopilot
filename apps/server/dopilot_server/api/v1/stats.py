"""Dashboard statistics endpoints (phase 1.7.1)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ...auth.dependencies import AdminContext, get_current_admin
from ...config.loader import get_settings
from ...config.settings import Settings
from ...db.engine import get_session
from ...services.stats import daily_task_counts
from .schemas import DailyTaskCount, DailyTaskStatsResponse

router = APIRouter(tags=["stats"])


@router.get("/stats/tasks/daily", response_model=DailyTaskStatsResponse)
async def get_daily_task_stats(
    days: int = Query(default=30, ge=1, le=365),
    _admin: AdminContext = Depends(get_current_admin),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> DailyTaskStatsResponse:
    """Per-day parent-task + atomic-execution counts for the last ``days``."""
    tz = settings.scheduler.timezone or "UTC"
    buckets = await daily_task_counts(session, days=days, timezone=tz)
    return DailyTaskStatsResponse(
        days=days,
        timezone=tz,
        buckets=[DailyTaskCount(**b) for b in buckets],
    )
