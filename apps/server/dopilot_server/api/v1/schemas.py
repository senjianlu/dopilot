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
    status: str  # "unknown" | "healthy" | "degraded" | "unhealthy"
    capabilities: dict[str, Any] = Field(default_factory=dict)
    # Extra health detail reported by the agent /health (phase 1: scrapyd
    # subprocess status, e.g. {"scrapyd": {"running": true, "port": 6801}}).
    health: dict[str, Any] = Field(default_factory=dict)
    last_seen_at: str | None = None
    # Phase 1.7.1: scheduling-control state, separate from health. offline =
    # not scheduling_enabled; deleted = deleted_at set. The web badge precedence
    # is deleted (gray) > offline (red) > healthy (green) > degraded/unhealthy/
    # unknown (yellow).
    scheduling_enabled: bool = True
    scheduling_disabled_at: str | None = None
    deleted_at: str | None = None


class NodesResponse(BaseModel):
    nodes: list[NodeView]


# ---------------------------------------------------------------------------
# phase 1: scrapy artifacts, executions, logs
# ---------------------------------------------------------------------------


class ArtifactView(BaseModel):
    """A validated Scrapy egg artifact."""

    id: str
    project: str
    version: str
    filename: str
    sha256: str
    size_bytes: int
    spiders: list[str] = Field(default_factory=list)
    valid: bool = True
    uploaded_at: str | None = None
    created_at: str | None = None


class ArtifactsResponse(BaseModel):
    artifacts: list[ArtifactView]


class EggDeployResult(BaseModel):
    """Response of ``POST /api/v1/artifacts/scrapy/egg``."""

    artifact: ArtifactView
    spiders: list[str] = Field(default_factory=list)
    agent_id: str | None = None
    endpoint: str | None = None


# NOTE (phase 1.7 public/web seam): the web JSON still uses the phase-1.5
# vocabulary — a parent run is an "execution" (``ExecutionView`` with
# ``attempts[]``) and an atomic unit is an "attempt" (``AttemptView`` whose
# ``execution_id`` is the parent task id). The server domain renamed these to
# task/execution; the public clean-cut is a later packet. Keep these shapes
# frozen so the web does not break in this packet.


class AttemptView(BaseModel):
    """One atomic execution (one target node) of a task/run.

    ``execution_id`` is the PARENT id (a task id in the server domain) — the web
    vocabulary still calls the parent an "execution".
    """

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
    """Full task/run detail incl. its atomic executions (``attempts``)."""

    id: str
    task_type: str
    target: str
    # queued|running|finalizing|complete|failed|canceled|lost|no_target
    status: str
    # Phase 1.7: set on a terminal that has no child execution to explain it
    # (currently the zero-node ``no_target`` task). NULL on normal runs.
    status_reason: str | None = None
    status_detail: dict[str, Any] = Field(default_factory=dict)
    node_strategy: str
    params: dict[str, Any] = Field(default_factory=dict)
    # Phase 1.7 packet 2: provenance. source = manual | schedule_trigger_now |
    # schedule_timer; template_id/schedule_id are null for an ad-hoc manual run.
    source: str = "manual"
    template_id: str | None = None
    schedule_id: str | None = None
    created_at: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    attempts: list[AttemptView] = Field(default_factory=list)


class ExecutionSummary(BaseModel):
    """Compact row for the tasks/runs list."""

    id: str
    task_type: str
    target: str
    # Phase 1.7.1: task-level spider (backs the execution-list spider filter).
    spider: str | None = None
    status: str
    status_reason: str | None = None
    node_strategy: str
    source: str = "manual"
    template_id: str | None = None
    schedule_id: str | None = None
    created_at: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    attempt_count: int = 0


class ExecutionsResponse(BaseModel):
    """Server-side paginated tasks/runs list (phase 1.7.1).

    ``spiders`` is the distinct set of known spider values across all tasks, so
    the web can offer a spider filter without a second round-trip.
    """

    executions: list[ExecutionSummary]
    page: int = 1
    page_size: int = 20
    total: int = 0
    spiders: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# phase 1.7 packet 2: task templates + schedules
# ---------------------------------------------------------------------------


class TemplateView(BaseModel):
    """A reusable Scrapy run definition."""

    id: str
    name: str
    description: str | None = None
    task_type: str = "scrapy"
    project: str | None = None
    version: str | None = None
    spider: str | None = None
    artifact: dict[str, Any] = Field(default_factory=dict)
    settings: dict[str, str] = Field(default_factory=dict)
    args: dict[str, str] = Field(default_factory=dict)
    node_strategy: str = "all"
    node_ids: list[str] = Field(default_factory=list)
    created_at: str | None = None
    updated_at: str | None = None


class TemplateCreateRequest(BaseModel):
    name: str
    description: str | None = None
    task_type: str = "scrapy"
    project: str | None = None
    version: str | None = None
    spider: str | None = None
    artifact: dict[str, Any] = Field(default_factory=dict)
    settings: dict[str, str] = Field(default_factory=dict)
    args: dict[str, str] = Field(default_factory=dict)
    node_strategy: str = "all"
    node_ids: list[str] = Field(default_factory=list)


class TemplateUpdateRequest(BaseModel):
    """All fields optional; only the provided ones are patched."""

    name: str | None = None
    description: str | None = None
    task_type: str | None = None
    project: str | None = None
    version: str | None = None
    spider: str | None = None
    artifact: dict[str, Any] | None = None
    settings: dict[str, str] | None = None
    args: dict[str, str] | None = None
    node_strategy: str | None = None
    node_ids: list[str] | None = None


class TemplatesResponse(BaseModel):
    templates: list[TemplateView]


class ScheduleView(BaseModel):
    """A timer referencing one template (interval or cron)."""

    id: str
    name: str
    description: str | None = None
    template_id: str
    trigger_type: str = "interval"  # interval | cron
    interval_seconds: int | None = None
    cron: str | None = None
    # Phase 1.7.1: estimated next fire time. For interval triggers this is an
    # estimate (now + interval); for cron it is computed from the expression.
    next_run_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class ScheduleCreateRequest(BaseModel):
    name: str
    description: str | None = None
    template_id: str
    trigger_type: str = "interval"
    interval_seconds: int | None = None
    cron: str | None = None


class ScheduleUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    template_id: str | None = None
    trigger_type: str | None = None
    interval_seconds: int | None = None
    cron: str | None = None


class SchedulesResponse(BaseModel):
    schedules: list[ScheduleView]


# ---------------------------------------------------------------------------
# phase 1.7.1: dashboard stats + schedule next-run preview
# ---------------------------------------------------------------------------


class DailyTaskCount(BaseModel):
    """One calendar-day bucket of the dashboard 30-day chart."""

    date: str  # YYYY-MM-DD (local calendar day in the scheduler timezone)
    tasks: int = 0
    executions: int = 0


class DailyTaskStatsResponse(BaseModel):
    days: int
    timezone: str
    buckets: list[DailyTaskCount] = Field(default_factory=list)


class NextRunPreviewRequest(BaseModel):
    trigger_type: str = "interval"
    interval_seconds: int | None = None
    cron: str | None = None


class NextRunPreviewResponse(BaseModel):
    next_run_at: str | None = None


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
