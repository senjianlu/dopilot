"""Task / execution / log-file state machine.

Phase 1.7 domain vocabulary (the parent/atomic split was inverted from the
phase-1.5 names — see ``docs/phases/phase-1.7/00-brief.md``):

- **task**: the parent logical run (was ``execution``). One task fans out to one
  atomic execution per selected healthy node.
- **execution**: the atomic per-node unit (was ``attempt``). It is the agent's
  idempotency key on the Redis/disk/agent wire, where it is called
  ``execution_id`` (see :mod:`dopilot_protocol.streams`).

Server-side states (not the agent's :class:`dopilot_protocol.AttemptStatus`):

- task:       queued -> running -> finalizing -> complete
              (+ failed/canceled/lost, and the terminal ``no_target`` set at
              creation when there is no healthy node — never via roll-up)
- execution:  pending -> running -> finished (+ failed/canceled/lost)
- log file:   active -> finalizing -> complete (+ missing/expired)

The agent reports its own ``AttemptStatus``; :data:`AGENT_TO_EXEC` maps it onto
the server execution state. Roll-up turns per-execution terminals into the task
terminal.
"""

from __future__ import annotations

from dopilot_protocol import AttemptStatus

# ---- task (parent logical run) ----
TASK_QUEUED = "queued"
TASK_RUNNING = "running"
TASK_FINALIZING = "finalizing"
TASK_COMPLETE = "complete"
TASK_FAILED = "failed"
TASK_CANCELED = "canceled"
TASK_LOST = "lost"
# Phase 1.7: terminal state for a task that found no healthy target node, so it
# was created with ZERO executions. It is set at creation time, NEVER via
# roll-up (a zero-execution roll-up returns None and would otherwise hang the
# task in `queued` forever). status_reason/status_detail on the task row carry
# the human/audit explanation (no fake execution, no task-events table).
TASK_NO_TARGET = "no_target"

TASK_ACTIVE = frozenset({TASK_QUEUED, TASK_RUNNING, TASK_FINALIZING})
TASK_TERMINAL = frozenset(
    {TASK_COMPLETE, TASK_FAILED, TASK_CANCELED, TASK_LOST, TASK_NO_TARGET}
)

# ---- build artifact type (core-domain discriminator; phase 1.8) ----
# Replaces the misleading ``task_type``. Only ``scrapy`` is runnable in 1.8;
# ``python_wheel`` / ``docker_image`` are reserved type values (not executable).
ARTIFACT_SCRAPY = "scrapy"
ARTIFACT_PYTHON_WHEEL = "python_wheel"
ARTIFACT_DOCKER_IMAGE = "docker_image"
ARTIFACT_TYPES = frozenset(
    {ARTIFACT_SCRAPY, ARTIFACT_PYTHON_WHEEL, ARTIFACT_DOCKER_IMAGE}
)
# Only these may actually run in phase 1.8.
RUNNABLE_ARTIFACT_TYPES = frozenset({ARTIFACT_SCRAPY})
# Default package_format per artifact type.
ARTIFACT_PACKAGE_FORMAT = {
    ARTIFACT_SCRAPY: "egg",
    ARTIFACT_PYTHON_WHEEL: "wheel",
    ARTIFACT_DOCKER_IMAGE: "image",
}
# Resolved artifact type -> the node capability a dispatch target must advertise.
ARTIFACT_CAPABILITY = {
    ARTIFACT_SCRAPY: "scrapy",
    ARTIFACT_PYTHON_WHEEL: "python_wheel",
    ARTIFACT_DOCKER_IMAGE: "docker_runtime",
}

# ---- task source (provenance; phase 1.7 packet 2 / 1.8) ----
# Who created the task. A direct build-artifact run is ``direct_artifact``; a
# run from an execution template is ``template``; a schedule's immediate trigger
# is ``schedule_trigger_now``; a schedule timer firing is ``schedule_timer``.
# Legacy rows may carry ``manual``. Only timer firings are subject to the
# schedule-keyed coalesce (see services/outbox.py).
TASK_SOURCE_MANUAL = "manual"  # legacy data only
TASK_SOURCE_DIRECT = "direct_artifact"
TASK_SOURCE_TEMPLATE = "template"
TASK_SOURCE_TRIGGER_NOW = "schedule_trigger_now"
TASK_SOURCE_TIMER = "schedule_timer"
TASK_SOURCES = frozenset(
    {
        TASK_SOURCE_MANUAL,
        TASK_SOURCE_DIRECT,
        TASK_SOURCE_TEMPLATE,
        TASK_SOURCE_TRIGGER_NOW,
        TASK_SOURCE_TIMER,
    }
)

# ---- execution (atomic per-node unit; ``attempt`` on the wire/disk seam) ----
EXEC_PENDING = "pending"
EXEC_RUNNING = "running"
EXEC_FINISHED = "finished"
EXEC_FAILED = "failed"
EXEC_CANCELED = "canceled"
EXEC_LOST = "lost"

EXEC_ACTIVE = frozenset({EXEC_PENDING, EXEC_RUNNING})
EXEC_TERMINAL = frozenset(
    {EXEC_FINISHED, EXEC_FAILED, EXEC_CANCELED, EXEC_LOST}
)

# ---- log file ----
LOG_ACTIVE = "active"
LOG_FINALIZING = "finalizing"
LOG_COMPLETE = "complete"
LOG_MISSING = "missing"
LOG_EXPIRED = "expired"

# agent-reported status -> server execution state (unknown is decided by policy)
AGENT_TO_EXEC: dict[AttemptStatus, str | None] = {
    AttemptStatus.pending: EXEC_PENDING,
    AttemptStatus.running: EXEC_RUNNING,
    AttemptStatus.finished: EXEC_FINISHED,
    AttemptStatus.failed: EXEC_FAILED,
    AttemptStatus.canceled: EXEC_CANCELED,
    AttemptStatus.unknown: None,
}

# Allowed transitions (terminal states have no outgoing edges). Same->same is
# permitted as an idempotent no-op.
_TASK_EDGES: dict[str, frozenset[str]] = {
    TASK_QUEUED: frozenset(
        {TASK_QUEUED, TASK_RUNNING, TASK_FAILED, TASK_CANCELED, TASK_LOST}
    ),
    TASK_RUNNING: frozenset(
        {
            TASK_RUNNING,
            TASK_FINALIZING,
            TASK_COMPLETE,
            TASK_FAILED,
            TASK_CANCELED,
            TASK_LOST,
        }
    ),
    TASK_FINALIZING: frozenset(
        {
            TASK_FINALIZING,
            TASK_COMPLETE,
            TASK_FAILED,
            TASK_CANCELED,
            TASK_LOST,
        }
    ),
    # Phase 1.5: task `lost` is a SOFT terminal (mirrors execution `lost`).
    # When a lost execution is overridden by a later agent-authoritative
    # terminal, its task re-rolls to the correct terminal.
    TASK_LOST: frozenset(
        {TASK_LOST, TASK_COMPLETE, TASK_FAILED, TASK_CANCELED}
    ),
}

_EXEC_EDGES: dict[str, frozenset[str]] = {
    EXEC_PENDING: frozenset(
        {
            EXEC_PENDING,
            EXEC_RUNNING,
            EXEC_FINISHED,
            EXEC_FAILED,
            EXEC_CANCELED,
            EXEC_LOST,
        }
    ),
    EXEC_RUNNING: frozenset(
        {
            EXEC_RUNNING,
            EXEC_FINISHED,
            EXEC_FAILED,
            EXEC_CANCELED,
            EXEC_LOST,
        }
    ),
    # Phase 1.5: `lost` is a SOFT terminal. A later agent-authoritative terminal
    # (finished/failed/canceled) may override it (recorded as
    # reconciled_from=lost). finished/failed/canceled stay mutually
    # non-transitionable. See refactor/00 §状态事件可靠性.
    EXEC_LOST: frozenset(
        {EXEC_LOST, EXEC_FINISHED, EXEC_FAILED, EXEC_CANCELED}
    ),
}


def is_valid_task_transition(old: str, new: str) -> bool:
    # `lost` is the one soft task terminal (overridable when its execution is
    # reconciled); all other terminals (incl. `no_target`) only permit the
    # same->same no-op.
    if old in TASK_TERMINAL and old != TASK_LOST:
        return old == new
    return new in _TASK_EDGES.get(old, frozenset())


def is_valid_execution_transition(old: str, new: str) -> bool:
    # `lost` is the one soft terminal: its override out-edges live in
    # _EXEC_EDGES; all other terminals only permit the same->same no-op.
    if old in EXEC_TERMINAL and old != EXEC_LOST:
        return old == new
    return new in _EXEC_EDGES.get(old, frozenset())


def rollup_task_status(execution_statuses: list[str]) -> str | None:
    """Map a set of execution states to the task terminal, or ``None``.

    Returns ``None`` while any execution is still active, AND for the empty set
    (a zero-execution task is never rolled up — it is set to ``no_target`` at
    creation instead). Precedence among terminals: failed > lost > canceled >
    complete.
    """
    if not execution_statuses or not all(
        s in EXEC_TERMINAL for s in execution_statuses
    ):
        return None
    if any(s == EXEC_FAILED for s in execution_statuses):
        return TASK_FAILED
    if any(s == EXEC_LOST for s in execution_statuses):
        return TASK_LOST
    if any(s == EXEC_CANCELED for s in execution_statuses):
        return TASK_CANCELED
    return TASK_COMPLETE
