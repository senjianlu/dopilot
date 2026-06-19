"""Aggregate v1 router mounted at ``/api/v1`` by the app factory."""

from __future__ import annotations

from fastapi import APIRouter

from . import (
    artifacts,
    auth,
    executions,
    health,
    heartbeat,
    nodes,
    schedules,
    templates,
)

router = APIRouter(prefix="/api/v1")
router.include_router(health.router)
router.include_router(auth.router)
router.include_router(nodes.router)
router.include_router(heartbeat.router)
router.include_router(executions.router)
router.include_router(artifacts.router)
router.include_router(templates.router)
router.include_router(schedules.router)
