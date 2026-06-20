"""Health endpoint. Always HTTP 200; dependencies reflect reachability."""

from __future__ import annotations

import redis.asyncio as aioredis
from dopilot_protocol import HealthResponse
from fastapi import APIRouter, Depends
from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ... import __version__
from ...config.loader import get_settings
from ...config.settings import Settings
from ...db import engine as db_engine
from ...db.engine import get_session
from ...nodes.service import list_nodes

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> dict:
    """Return server/dashboard health. Always HTTP 200."""
    reachable = await db_engine.ping(session)
    db_version: str | None = None
    if reachable:
        try:
            result = await session.execute(text("select version()"))
            db_version = result.scalar_one_or_none()
        except Exception:  # noqa: BLE001 - status still reports DB reachable.
            db_version = None

    redis_status = "disabled"
    redis_version: str | None = None
    if settings.redis.url:
        redis_client = aioredis.from_url(
            settings.redis.url, decode_responses=True, socket_timeout=2
        )
        try:
            info = await redis_client.info("server")
            redis_status = "ok"
            redis_version = str(info.get("redis_version") or "")
        except RedisError:
            redis_status = "error"
        finally:
            await redis_client.aclose()

    nodes = await list_nodes(session, settings)
    online_count = sum(1 for node in nodes if node["status"] in {"healthy", "degraded"})
    healthy_count = sum(1 for node in nodes if node["status"] == "healthy")

    # Phase 1.7.1: agent (scheduling) health is judged ONLY over schedulable,
    # non-deleted nodes — offline/deleted nodes still report health on the Nodes
    # page but never colour the dashboard scheduling light.
    schedulable = [
        n
        for n in nodes
        if n.get("scheduling_enabled", True) and not n.get("deleted_at")
    ]
    schedulable_healthy = sum(1 for n in schedulable if n["status"] == "healthy")
    if schedulable_healthy == 0:
        # no schedulable healthy node (incl. the no-nodes case) -> red.
        agent_status = "red"
    elif schedulable_healthy == len(schedulable):
        # every schedulable node is healthy -> green.
        agent_status = "green"
    else:
        # some healthy, some degraded/unhealthy/unknown -> yellow.
        agent_status = "yellow"

    dependency_statuses = [
        "ok" if reachable else "error",
        redis_status if redis_status != "disabled" else "ok",
    ]
    overall_status = "ok" if all(s == "ok" for s in dependency_statuses) else "degraded"
    payload = HealthResponse(
        status=overall_status,
        service="dopilot-server",
        version=__version__,
        database="ok" if reachable else "error",
    )
    # Web contract is the 4-field subset; richer protocol fields (agent_id,
    # capabilities, workdir) are agent-side only.
    return {
        "status": payload.status,
        "service": payload.service,
        "version": payload.version,
        "database": payload.database,
        "postgresql": {
            "status": payload.database,
            "version": db_version,
        },
        "redis": {
            "status": redis_status,
            "version": redis_version,
        },
        "nodes": {
            "total": len(nodes),
            "online": online_count,
            "healthy": healthy_count,
        },
        # Phase 1.7.1: dashboard scheduling-health light (schedulable nodes only).
        "agent": {
            "status": agent_status,
            "schedulable": len(schedulable),
            "healthy": schedulable_healthy,
        },
    }
