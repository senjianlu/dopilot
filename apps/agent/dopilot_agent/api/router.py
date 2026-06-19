"""Aggregate agent API router.

Phase 1.5 removed the server->agent run/status/logs-tail/cleanup HTTP main paths
(now Redis Streams + commands). The agent's surviving root endpoints are:
``/health`` (container healthcheck only — no longer a server discovery/health
source) and ``/artifacts/scrapy/egg`` (egg deploy stays HTTP).
"""

from __future__ import annotations

from fastapi import APIRouter

from . import artifacts, health

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(artifacts.router)
