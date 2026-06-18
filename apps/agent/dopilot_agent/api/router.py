"""Aggregate agent API router.

Agent endpoints live at the ROOT (no /api/v1 prefix): /health, /run, /stop,
/status, /logs/tail, /executions/{attempt_id}/logs/cleanup,
/artifacts/scrapy/egg.
"""

from __future__ import annotations

from fastapi import APIRouter

from . import artifacts, health, logs, run, status

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(run.router)
api_router.include_router(status.router)
api_router.include_router(logs.router)
api_router.include_router(artifacts.router)
