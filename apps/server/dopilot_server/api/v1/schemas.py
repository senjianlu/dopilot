"""Web-facing request/response models for ``/api/v1``.

These match the FROZEN WEB-FACING JSON SHAPES exactly; the web TS types mirror
them. The error envelope itself is ``dopilot_protocol.ErrorResponse`` and is
emitted by the global exception handler, not declared here.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    mode: str  # "on" | "off"
    access_token: str | None = None
    token_type: str = "bearer"
    expires_at: str | None = None


class MeResponse(BaseModel):
    authenticated: bool
    mode: str  # "on" | "off"
    username: str | None = None
    expires_at: str | None = None


class NodeView(BaseModel):
    id: str | None = None
    agent_id: str | None = None
    endpoint: str
    status: str  # "unknown" | "healthy" | "unhealthy"
    capabilities: dict[str, Any] = {}
    last_seen_at: str | None = None


class NodesResponse(BaseModel):
    nodes: list[NodeView]
