"""Web-facing request/response models for ``/api/v1``.

These match the FROZEN WEB-FACING JSON SHAPES exactly; the web TS types mirror
them. The error envelope itself is ``dopilot_protocol.ErrorResponse`` and is
emitted by the global exception handler, not declared here.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


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
    capabilities: dict[str, Any] = Field(default_factory=dict)
    # Extra health detail reported by the agent /health (phase 1: scrapyd
    # subprocess status, e.g. {"scrapyd": {"running": true, "port": 6801}}).
    health: dict[str, Any] = Field(default_factory=dict)
    last_seen_at: str | None = None


class NodesResponse(BaseModel):
    nodes: list[NodeView]


# ---------------------------------------------------------------------------
# phase 1: scrapy artifacts, executions, logs
# ---------------------------------------------------------------------------


class ArtifactView(BaseModel):
    """A deployed (uploaded) Scrapy egg recorded in ``scrapy_artifacts``."""

    id: str
    project: str
    version: str
    filename: str
    sha256: str
    size_bytes: int
    created_at: str | None = None


class EggDeployResult(BaseModel):
    """Response of ``POST /api/v1/artifacts/scrapy/egg``."""

    artifact: ArtifactView
    spiders: list[str] = Field(default_factory=list)
    # Which agent the egg was deployed to.
    agent_id: str | None = None
    endpoint: str | None = None


class AttemptView(BaseModel):
    """One execution attempt (one target node) of an execution."""

    id: str
    execution_id: str
    agent_id: str | None = None
    node_id: str | None = None
    endpoint: str | None = None
    remote_job_id: str | None = None
    status: str  # pending|running|finished|failed|canceled|lost
    started_at: str | None = None
    finished_at: str | None = None
    exit_code: int | None = None
    error_code: str | None = None
    error_detail: dict[str, Any] = Field(default_factory=dict)


class ExecutionView(BaseModel):
    """Full execution detail incl. its attempts."""

    id: str
    task_type: str
    target: str
    # queued|running|finalizing|complete|failed|canceled|lost
    status: str
    node_strategy: str
    params: dict[str, Any] = Field(default_factory=dict)
    created_at: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    attempts: list[AttemptView] = Field(default_factory=list)


class ExecutionSummary(BaseModel):
    """Compact row for the executions list."""

    id: str
    task_type: str
    target: str
    status: str
    node_strategy: str
    created_at: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    attempt_count: int = 0


class ExecutionsResponse(BaseModel):
    executions: list[ExecutionSummary]


class LogSnapshot(BaseModel):
    """A landed log slice returned by ``GET /executions/{id}/logs``."""

    execution_id: str
    attempt_id: str
    stream: str
    start_offset: int
    end_offset: int
    content: str
    # active|finalizing|complete|missing|expired
    status: str
    finished: bool = False


class StreamTokenResponse(BaseModel):
    """Short-lived SSE connect token (issued only when web auth is ON)."""

    stream_token: str
    expires_at: str
