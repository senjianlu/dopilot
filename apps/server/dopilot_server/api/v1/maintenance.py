"""Manual maintenance endpoints (phase 1.8.2).

Operator-driven, manual-only. There is NO scheduled cleanup in phase 1.8.2.
Standard admin auth is enough (no extra RBAC layer).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ...auth.dependencies import AdminContext, get_current_admin
from ...config.loader import get_settings
from ...config.settings import Settings
from ...db.engine import get_session
from ...errors import ApiError
from ...services import maintenance as svc
from .schemas import (
    ResourceStatsResponse,
    RewriteAofResponse,
    SweepNowResponse,
    SweepStepResult,
    TerminalCleanupRequest,
    TerminalCleanupResponse,
)

log = logging.getLogger(__name__)

router = APIRouter(tags=["maintenance"])


def _resolve_cutoff(body: TerminalCleanupRequest) -> datetime:
    """Resolve the request to an aware cutoff datetime.

    ``before`` (absolute ISO) wins when given; otherwise ``older_than_days`` is
    subtracted from now. Exactly one must be provided.
    """
    if body.before:
        try:
            cutoff = datetime.fromisoformat(body.before)
        except ValueError as exc:
            raise ApiError(
                400,
                "maintenance.invalid_cutoff",
                "errors.invalidCutoff",
                {"before": body.before},
            ) from exc
        if cutoff.tzinfo is None:
            cutoff = cutoff.replace(tzinfo=UTC)
        return cutoff
    if body.older_than_days is not None:
        return datetime.now(UTC) - timedelta(days=body.older_than_days)
    raise ApiError(
        400,
        "maintenance.cutoff_required",
        "errors.cutoffRequired",
        {},
    )


@router.post(
    "/maintenance/terminal-cleanup", response_model=TerminalCleanupResponse
)
async def terminal_cleanup(
    body: TerminalCleanupRequest,
    _admin: AdminContext = Depends(get_current_admin),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> TerminalCleanupResponse:
    """Delete (or dry-run preview) old TERMINAL task data before a cutoff.

    Only terminal tasks (complete/failed/canceled/lost/no_target) older than the
    cutoff are affected; queued/running/finalizing tasks are never touched.
    """
    cutoff = _resolve_cutoff(body)
    # cleanup_terminal_data owns its commits (two-phase, failure-safe) when not a
    # dry run; the handler no longer commits.
    summary = await svc.cleanup_terminal_data(
        session, settings, cutoff=cutoff, dry_run=body.dry_run
    )
    return TerminalCleanupResponse(**summary.as_dict())


@router.get("/maintenance/resource-stats", response_model=ResourceStatsResponse)
async def resource_stats(
    request: Request,
    _admin: AdminContext = Depends(get_current_admin),
    settings: Settings = Depends(get_settings),
) -> ResourceStatsResponse:
    """Return the most recent cached resource snapshot (D3).

    Serves ONLY the in-memory snapshot the background ``ResourceStatsLoop``
    produces — it NEVER samples on the request path (directory walks / Redis
    INFO must not run per request). When no snapshot exists yet (sampler
    disabled via ``stats_interval_seconds=0``, first tick pending, or the
    lifespan never ran, e.g. under ASGITransport tests), it returns an empty
    "not sampled yet" body rather than walking the filesystem. The empty body
    still reports the true ``sweep_enabled`` from config, so a disabled
    auto-sweep is never mislabelled as on.
    """
    loop = getattr(request.app.state, "resource_stats", None)
    snapshot = getattr(loop, "snapshot", None) if loop is not None else None
    if not snapshot:
        return ResourceStatsResponse(
            sampled_at=None,
            sweep_enabled=settings.maintenance.enabled,
            scopes=[],
        )
    return ResourceStatsResponse(**snapshot)


@router.post("/maintenance/sweep-now", response_model=SweepNowResponse)
async def sweep_now(
    request: Request,
    _admin: AdminContext = Depends(get_current_admin),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> SweepNowResponse:
    """Run one retention sweep immediately (the same three steps as the automatic
    ``RetentionSweepLoop``), with per-step failure isolation.

    Each step runs independently: a failure in one (rolled back) never blocks the
    rest, and the response reports each step's outcome. Always HTTP 200 — the
    action was performed; the body carries the truth. A retention knob of 0 means
    "disabled", so that step is ``skipped`` (``logs.retention_days=0`` would
    otherwise compute cutoff=now and wipe all terminal history).
    """
    now = datetime.now(UTC)
    steps: dict[str, SweepStepResult] = {}

    # Step 1: terminal task data (0 = disabled, not "delete everything").
    if settings.logs.retention_days > 0:
        cutoff = now - timedelta(days=settings.logs.retention_days)
        try:
            summary = await svc.cleanup_terminal_data(
                session, settings, cutoff=cutoff
            )
            steps["cleanup"] = SweepStepResult(
                status="ok",
                result=TerminalCleanupResponse(**summary.as_dict()),
            )
        except Exception as exc:  # noqa: BLE001 - isolate, keep going
            await session.rollback()
            log.error("sweep-now: terminal cleanup failed", exc_info=True)
            steps["cleanup"] = SweepStepResult(
                status="failed", error=f"{type(exc).__name__}: {exc}"
            )
    else:
        steps["cleanup"] = SweepStepResult(status="skipped")

    # Step 2: event_audit prune (service treats retention 0 as disabled).
    if settings.maintenance.event_audit_retention_days > 0:
        try:
            pruned = await svc.prune_event_audit(session, settings, now=now)
            steps["event_audit"] = SweepStepResult(status="ok", pruned=pruned)
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            log.error("sweep-now: event_audit prune failed", exc_info=True)
            steps["event_audit"] = SweepStepResult(
                status="failed", error=f"{type(exc).__name__}: {exc}"
            )
    else:
        steps["event_audit"] = SweepStepResult(status="skipped")

    # Step 3: Redis stream time-trim (needs a client + a positive window).
    redis_client = getattr(request.app.state, "redis", None)
    if redis_client is None or settings.redis.log_retention_seconds <= 0:
        steps["stream_trim"] = SweepStepResult(status="skipped")
    else:
        try:
            trimmed = await svc.trim_log_streams(redis_client, settings, now=now)
            failed = any("error" in r for r in trimmed.values())
            steps["stream_trim"] = SweepStepResult(
                status="failed" if failed else "ok", streams=trimmed
            )
        except Exception as exc:  # noqa: BLE001
            log.error("sweep-now: stream trim failed", exc_info=True)
            steps["stream_trim"] = SweepStepResult(
                status="failed", error=f"{type(exc).__name__}: {exc}"
            )

    return SweepNowResponse(steps=steps)


@router.post(
    "/maintenance/redis-rewrite-aof", response_model=RewriteAofResponse
)
async def redis_rewrite_aof(
    request: Request,
    _admin: AdminContext = Depends(get_current_admin),
) -> RewriteAofResponse:
    """Trigger a Redis background AOF rewrite (operator "reclaim AOF now").

    503 when Redis is unavailable (no client wired, or the call raised)."""
    redis_client = getattr(request.app.state, "redis", None)
    if redis_client is None:
        raise ApiError(
            503,
            "maintenance.redis_unavailable",
            "errors.redisUnavailable",
            {},
        )
    try:
        await redis_client.bgrewriteaof()
    except Exception as exc:  # noqa: BLE001
        log.error("redis-rewrite-aof failed", exc_info=True)
        raise ApiError(
            503,
            "maintenance.redis_unavailable",
            "errors.redisUnavailable",
            {"error": f"{type(exc).__name__}: {exc}"},
        ) from exc
    return RewriteAofResponse(started=True)
