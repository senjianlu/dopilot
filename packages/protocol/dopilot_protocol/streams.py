"""Redis Streams protocol: server<->agent command/event/log/heartbeat schemas.

Phase-1.5 communication model (see
``docs/refactor/00-redis-streams-agent-communication.md``, the authoritative
design):

- the **server** dispatches commands to a per-agent command stream,
- the **agent** consumes commands, executes, and publishes status events and log
  increments to shared server streams,
- health is a separate agent->server heartbeat POST (NOT Redis).

This supersedes the phase-1 HTTP ``run`` / ``status`` / ``tail`` contracts in
:mod:`dopilot_protocol.agent` and :mod:`dopilot_protocol.logs`, which are now
legacy.

The module also owns the **stream topology** (names + consumer-group names) and
the **wire codec** (:func:`to_stream_entry` / :func:`from_stream_entry`) so the
server and agent cannot drift: a stream message is a single ``data`` field
holding the model's JSON body. Everything here is pure (pydantic + stdlib); the
``redis`` dependency lives in each app, never in this shared package.

Naming (phase 2a clean-cut). The wire ids now match the server domain directly:
``task_id`` is the **task id** (parent logical run, ``Task.id``) and
``execution_id`` is the **atomic execution id** (``Execution.id``) — the agent's
idempotency key + state-file name + on-disk ``{task_id}/{execution_id}.log`` path
component. There is no longer a seam translation: the server's event/log
consumers read these names as-is. The wire cannot be half-renamed, so protocol,
server, and agent ship as one lockstep version.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, TypeVar

from pydantic import BaseModel, Field, computed_field

from .common import CapabilitySet
from .logs import LogStream

# --------------------------------------------------------------------------- #
# Stream topology (single source of truth shared by server + agent)
# --------------------------------------------------------------------------- #


def command_stream(agent_id: str) -> str:
    """Per-agent command stream the server XADDs run/stop/cleanup_logs into."""
    return f"dopilot:agent:{agent_id}:commands"


#: Shared stream all agents publish status events to; the server consumes it.
EVENT_STREAM = "dopilot:server:agent-events"
#: Shared stream all agents publish log increments to; the server consumes it.
LOG_STREAM = "dopilot:server:logs"

#: Consumer group the agent uses on its own command stream.
COMMAND_GROUP = "agent"
#: Consumer group the server uses on the shared event stream.
EVENT_GROUP = "server-events"
#: Consumer group the server uses on the shared log stream.
LOG_GROUP = "server-logs"


# --------------------------------------------------------------------------- #
# Commands (server -> agent)
# --------------------------------------------------------------------------- #


class AgentCommandType(str, Enum):
    """The only command types carried on the agent command stream."""

    run = "run"
    stop = "stop"
    cleanup_logs = "cleanup_logs"


class StopIntent(str, Enum):
    """Disambiguates why a ``stop`` was issued.

    ``cancel`` (user cancel): the agent's authoritative terminal is always
    ``attempt.canceled``, regardless of process state. ``reclaim`` (server has
    already judged the attempt ``lost`` and wants the real process killed to
    free resources): the attempt stays ``lost`` (not re-judged ``canceled``).
    """

    cancel = "cancel"
    reclaim = "reclaim"


class AgentCommand(BaseModel):
    """A single command on ``dopilot:agent:{agent_id}:commands``.

    ``command_id`` is the outbox row / audit id, NOT the agent execution
    idempotency key — that is always ``execution_id``. ``intent`` is required when
    ``type == stop``. For ``type == run`` the scrapy params live in ``payload``
    (project/spider/version/settings/args).
    """

    command_id: str
    type: AgentCommandType
    agent_id: str
    task_id: str
    execution_id: str
    task_type: str = "scrapy"
    intent: StopIntent | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: str


# --------------------------------------------------------------------------- #
# Status events (agent -> server)
# --------------------------------------------------------------------------- #


class AgentEventType(str, Enum):
    """Attempt lifecycle events the agent publishes to the event stream."""

    accepted = "attempt.accepted"
    running = "attempt.running"
    finished = "attempt.finished"
    failed = "attempt.failed"
    canceled = "attempt.canceled"
    lost = "attempt.lost"

    @property
    def short(self) -> str:
        """The bare status name, e.g. ``attempt.running`` -> ``running``."""
        return self.value.split(".", 1)[1]

    @property
    def is_terminal(self) -> bool:
        return self in _TERMINAL_EVENT_TYPES

    @property
    def is_authoritative_terminal(self) -> bool:
        """``finished`` / ``failed`` / ``canceled`` are agent-authoritative hard
        terminals; ``lost`` is a soft terminal that they may override."""
        return self in _AUTHORITATIVE_TERMINAL_EVENT_TYPES


_TERMINAL_EVENT_TYPES = frozenset(
    {
        AgentEventType.finished,
        AgentEventType.failed,
        AgentEventType.canceled,
        AgentEventType.lost,
    }
)
_AUTHORITATIVE_TERMINAL_EVENT_TYPES = frozenset(
    {AgentEventType.finished, AgentEventType.failed, AgentEventType.canceled}
)


class LostReason(str, Enum):
    """Why an attempt was declared ``lost``.

    Server-inferred reasons (``heartbeat_timeout`` / ``event_stall``) and
    agent-reported local-recovery failures (``state_missing`` /
    ``process_missing`` / ``runner_recovered_unknown`` / ``spawn_aborted``) must
    stay distinguishable so the API/Web can tell "agent unreachable" from "event
    stall" from "agent local recovery failed".
    """

    # server-inferred
    heartbeat_timeout = "heartbeat_timeout"
    event_stall = "event_stall"
    # agent-reported local recovery failures
    state_missing = "state_missing"
    process_missing = "process_missing"
    runner_recovered_unknown = "runner_recovered_unknown"
    spawn_aborted = "spawn_aborted"

    @property
    def source(self) -> str:
        """``"server"`` for server-inferred reasons, else ``"agent"``."""
        return "server" if self in _SERVER_LOST_REASONS else "agent"


_SERVER_LOST_REASONS = frozenset({LostReason.heartbeat_timeout, LostReason.event_stall})


class AgentEvent(BaseModel):
    """A status event on ``dopilot:server:agent-events``.

    ``type`` is authoritative; the denormalized ``status`` (computed from
    ``type``) is carried on the wire for convenience. ``lost_reason`` is set iff
    ``type == lost``.
    """

    event_id: str
    agent_id: str
    task_id: str
    execution_id: str
    type: AgentEventType
    remote_job_id: str | None = None
    exit_code: int | None = None
    error_code: str | None = None
    error_detail: dict[str, Any] = Field(default_factory=dict)
    lost_reason: LostReason | None = None
    created_at: str

    @computed_field  # type: ignore[prop-decorator]
    @property
    def status(self) -> str:
        return self.type.short


# --------------------------------------------------------------------------- #
# Log increments (agent -> server)
# --------------------------------------------------------------------------- #


class AgentLogEvent(BaseModel):
    """A log increment on ``dopilot:server:logs``.

    ``content_b64`` is base64 of the **raw bytes** of the agent's local log file
    (not decoded text), so ``offset`` / ``size_bytes`` live in the agent's byte
    space and are immune to UTF-8 boundary / newline translation. ``offset`` is
    the agent-local logical byte offset; the server's ``last_pulled_offset`` is
    the consumption-progress authority.
    """

    agent_id: str
    task_id: str
    execution_id: str
    stream: LogStream = LogStream.log
    offset: int
    content_b64: str
    size_bytes: int
    eof: bool = False
    created_at: str


# --------------------------------------------------------------------------- #
# Heartbeat (agent -> server, over HTTP not Redis)
# --------------------------------------------------------------------------- #


class AgentHeartbeatRequest(BaseModel):
    """``POST /api/v1/agents/{agent_id}/heartbeat`` body.

    ``capabilities`` reuses the shared :class:`CapabilitySet` (no second
    same-shape schema). ``load`` carries e.g. ``{"running_attempts": int}`` and
    ``detail`` e.g. ``{"scrapyd": {...}}``.
    """

    agent_id: str
    version: str
    capabilities: CapabilitySet = Field(default_factory=CapabilitySet)
    load: dict[str, Any] = Field(default_factory=dict)
    detail: dict[str, Any] = Field(default_factory=dict)
    # The agent's server-reachable base endpoint (host:port or URL) for the
    # surviving egg-deploy HTTP path. None when the agent does not advertise one.
    endpoint: str | None = None
    reported_at: str


class AgentHeartbeatResponse(BaseModel):
    """Server acknowledgement of a heartbeat."""

    ok: bool = True
    server_time: str


# --------------------------------------------------------------------------- #
# Wire codec: one Redis stream field ``data`` holding the model JSON body
# --------------------------------------------------------------------------- #

#: The single Redis stream field every dopilot message is stored under.
STREAM_FIELD = b"data"

_T = TypeVar("_T", bound=BaseModel)


def to_stream_entry(model: BaseModel) -> dict[bytes, bytes]:
    """Encode a protocol model as Redis stream fields (``{data: json bytes}``)."""
    return {STREAM_FIELD: model.model_dump_json().encode("utf-8")}


def from_stream_entry(model_cls: type[_T], fields: Any) -> _T:
    """Decode Redis stream fields (bytes- or str-keyed) back into ``model_cls``."""
    raw = None
    if isinstance(fields, dict):
        raw = fields.get(STREAM_FIELD)
        if raw is None:
            raw = fields.get("data")
    if raw is None:
        raise ValueError("stream entry missing 'data' field")
    return model_cls.model_validate_json(raw)
