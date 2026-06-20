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
# phase 1.8: build artifacts
# ---------------------------------------------------------------------------


class BuildArtifactView(BaseModel):
    """A canonical build artifact (phase 1.8). Phase 1.8 runs scrapy/egg only."""

    id: str
    artifact_type: str  # scrapy | python_wheel (reserved) | docker_image (reserved)
    package_format: str  # egg | wheel (reserved) | image (reserved)
    name: str
    filename: str | None = None
    content_hash: str | None = None
    size_bytes: int = 0
    # Scrapy type-specific metadata (also carried in artifact_metadata JSONB):
    project: str | None = None
    version: str | None = None
    spiders: list[str] = Field(default_factory=list)
    fetch_path: str | None = None
    runnable: bool = False
    created_at: str | None = None
    updated_at: str | None = None


class BuildArtifactsResponse(BaseModel):
    artifacts: list[BuildArtifactView]


class BuildArtifactUploadResponse(BaseModel):
    """Response of ``POST /api/v1/artifacts/scrapy/egg`` (creates/reuses a row)."""

    artifact: BuildArtifactView
    spiders: list[str] = Field(default_factory=list)


class RunOverrides(BaseModel):
    """Bounded schedule run overrides (phase 1.8.1, command-first).

    Only ``command`` / ``node_strategy`` / ``node_ids`` may be overridden — a
    ``command`` override FULLY replaces the template command. ``extra="forbid"``
    so an attempt to override a disallowed key (notably ``build_artifact_id`` or
    the legacy ``spider`` / ``settings`` / ``args``) is rejected at the schema
    boundary with a 422.
    """

    model_config = {"extra": "forbid"}

    command: str | None = None
    node_strategy: str | None = None
    node_ids: list[str] | None = None


class TaskRunResponse(BaseModel):
    """Acknowledgement of a dispatched run; ``task_id`` is the parent task."""

    task_id: str
    status: str


# ---------------------------------------------------------------------------
# phase 1.8: tasks (parent runs) + executions (atomic per-node units)
# ---------------------------------------------------------------------------


class ExecutionView(BaseModel):
    """One atomic per-node execution of a task. ``task_id`` is the parent."""

    id: str
    task_id: str
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


class TaskView(BaseModel):
    """Full parent-task detail incl. its atomic executions."""

    id: str
    artifact_type: str
    target: str
    # queued|running|finalizing|complete|failed|canceled|lost|no_target
    status: str
    status_reason: str | None = None
    status_detail: dict[str, Any] = Field(default_factory=dict)
    node_strategy: str
    params: dict[str, Any] = Field(default_factory=dict)
    # Resolved build-artifact snapshot frozen at task creation.
    build_artifact: dict[str, Any] = Field(default_factory=dict)
    # source = direct_artifact | template | schedule_trigger_now | schedule_timer
    source: str = "direct_artifact"
    execution_template_id: str | None = None
    schedule_id: str | None = None
    created_at: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    executions: list[ExecutionView] = Field(default_factory=list)


class TaskSummary(BaseModel):
    """Compact row for the tasks list."""

    id: str
    artifact_type: str
    target: str
    spider: str | None = None
    status: str
    status_reason: str | None = None
    node_strategy: str
    source: str = "direct_artifact"
    execution_template_id: str | None = None
    schedule_id: str | None = None
    created_at: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    execution_count: int = 0


class TasksResponse(BaseModel):
    """Server-side paginated tasks list (phase 1.8).

    ``spiders`` is the distinct set of known spider values across all tasks, so
    the web can offer a spider filter without a second round-trip.
    """

    tasks: list[TaskSummary]
    page: int = 1
    page_size: int = 20
    total: int = 0
    spiders: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# phase 1.8: execution templates + schedules
# ---------------------------------------------------------------------------


class ExecutionTemplateView(BaseModel):
    """A reusable run definition bound to one build artifact (command-first)."""

    id: str
    name: str
    description: str | None = None
    build_artifact_id: str | None = None
    artifact_type: str = "scrapy"
    # project/version are resolved from the bound artifact (read-only).
    project: str | None = None
    version: str | None = None
    # Phase 1.8.1: the authoritative execution input. NULL only for a legacy
    # template whose command could not be synthesized during migration.
    command: str | None = None
    node_strategy: str = "all"
    node_ids: list[str] = Field(default_factory=list)
    created_at: str | None = None
    updated_at: str | None = None


class ExecutionTemplateCreateRequest(BaseModel):
    name: str
    description: str | None = None
    build_artifact_id: str
    command: str
    node_strategy: str = "all"
    node_ids: list[str] = Field(default_factory=list)


class ExecutionTemplateUpdateRequest(BaseModel):
    """All fields optional; only the provided ones are patched."""

    name: str | None = None
    description: str | None = None
    build_artifact_id: str | None = None
    command: str | None = None
    node_strategy: str | None = None
    node_ids: list[str] | None = None


class ExecutionTemplatesResponse(BaseModel):
    templates: list[ExecutionTemplateView]


class ScheduleView(BaseModel):
    """A timer referencing one execution template (interval or cron)."""

    id: str
    name: str
    description: str | None = None
    execution_template_id: str
    trigger_type: str = "interval"  # interval | cron
    interval_seconds: int | None = None
    cron: str | None = None
    # Phase 1.8: bounded run overrides (never the build artifact).
    overrides: dict[str, Any] = Field(default_factory=dict)
    # Phase 1.7.1: estimated next fire time. For interval triggers this is an
    # estimate (now + interval); for cron it is computed from the expression.
    next_run_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class ScheduleCreateRequest(BaseModel):
    name: str
    description: str | None = None
    execution_template_id: str
    trigger_type: str = "interval"
    interval_seconds: int | None = None
    cron: str | None = None
    overrides: RunOverrides | None = None


class ScheduleUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    execution_template_id: str | None = None
    trigger_type: str | None = None
    interval_seconds: int | None = None
    cron: str | None = None
    overrides: RunOverrides | None = None


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
    """A landed log slice returned by ``GET /tasks/{task_id}/logs``.

    Public ids: ``task_id`` is the parent task, ``execution_id`` the atomic
    per-node execution. Internally these map to the frozen seam
    ``execution_id`` / ``attempt_id`` on the log index.
    """

    task_id: str
    execution_id: str
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


# ---------------------------------------------------------------------------
# Manual maintenance (phase 1.8.2)
# ---------------------------------------------------------------------------


class TerminalCleanupRequest(BaseModel):
    """Delete OLD TERMINAL task data. Provide ``older_than_days`` (preferred) or
    an absolute ``before`` ISO timestamp. ``dry_run`` previews the counts."""

    older_than_days: int | None = Field(default=None, ge=0)
    before: str | None = None
    dry_run: bool = False


class TerminalCleanupResponse(BaseModel):
    """Count summary of a terminal-data cleanup (or dry-run preview)."""

    dry_run: bool
    cutoff: str
    tasks: int = 0
    executions: int = 0
    log_files: int = 0
    log_files_removed: int = 0
    log_bytes: int = 0
    command_outbox: int = 0


class MarkTaskLostResponse(BaseModel):
    """Result of manually marking a stuck active task ``lost``."""

    task_id: str
    task_status: str
    executions_marked: int = 0
    already_terminal: list[str] = Field(default_factory=list)
