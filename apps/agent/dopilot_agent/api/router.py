"""Aggregate agent API router.

Agent endpoints live at the ROOT (no /api/v1 prefix): /health, /logs/tail,
/status, /executions/{attempt_id}/logs/cleanup.
"""

from __future__ import annotations

from fastapi import APIRouter

from . import health, logs, status

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(logs.router)
api_router.include_router(status.router)
