"""Health/identity response shared by server and agent health endpoints."""

from __future__ import annotations

from pydantic import BaseModel

from .common import CapabilitySet


class HealthResponse(BaseModel):
    """Service health + optional identity/capability fields.

    Server fills status/service/version/database; agent additionally fills
    agent_id/capabilities/workdir.
    """

    status: str
    service: str
    version: str
    database: str | None = None
    agent_id: str | None = None
    capabilities: CapabilitySet | None = None
    workdir: str | None = None
