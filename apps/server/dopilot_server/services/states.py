"""Execution / attempt / log-file state machine.

Server-side states (not the agent's :class:`dopilot_protocol.AttemptStatus`):

- execution: queued -> running -> finalizing -> complete (+ failed/canceled/lost)
- attempt:   pending -> running -> finished (+ failed/canceled/lost)
- log file:  active -> finalizing -> complete (+ missing/expired)

The agent reports its own ``AttemptStatus``; :data:`AGENT_TO_ATTEMPT` maps it
onto the server attempt state. Roll-up turns per-attempt terminals into the
execution terminal.
"""

from __future__ import annotations

from dopilot_protocol import AttemptStatus

# ---- execution ----
EXEC_QUEUED = "queued"
EXEC_RUNNING = "running"
EXEC_FINALIZING = "finalizing"
EXEC_COMPLETE = "complete"
EXEC_FAILED = "failed"
EXEC_CANCELED = "canceled"
EXEC_LOST = "lost"

EXEC_ACTIVE = frozenset({EXEC_QUEUED, EXEC_RUNNING, EXEC_FINALIZING})
EXEC_TERMINAL = frozenset({EXEC_COMPLETE, EXEC_FAILED, EXEC_CANCELED, EXEC_LOST})

# ---- attempt ----
ATTEMPT_PENDING = "pending"
ATTEMPT_RUNNING = "running"
ATTEMPT_FINISHED = "finished"
ATTEMPT_FAILED = "failed"
ATTEMPT_CANCELED = "canceled"
ATTEMPT_LOST = "lost"

ATTEMPT_ACTIVE = frozenset({ATTEMPT_PENDING, ATTEMPT_RUNNING})
ATTEMPT_TERMINAL = frozenset(
    {ATTEMPT_FINISHED, ATTEMPT_FAILED, ATTEMPT_CANCELED, ATTEMPT_LOST}
)

# ---- log file ----
LOG_ACTIVE = "active"
LOG_FINALIZING = "finalizing"
LOG_COMPLETE = "complete"
LOG_MISSING = "missing"
LOG_EXPIRED = "expired"

# agent-reported status -> server attempt state (unknown is decided by policy)
AGENT_TO_ATTEMPT: dict[AttemptStatus, str | None] = {
    AttemptStatus.pending: ATTEMPT_PENDING,
    AttemptStatus.running: ATTEMPT_RUNNING,
    AttemptStatus.finished: ATTEMPT_FINISHED,
    AttemptStatus.failed: ATTEMPT_FAILED,
    AttemptStatus.canceled: ATTEMPT_CANCELED,
    AttemptStatus.unknown: None,
}

# Allowed transitions (terminal states have no outgoing edges). Same->same is
# permitted as an idempotent no-op.
_EXEC_EDGES: dict[str, frozenset[str]] = {
    EXEC_QUEUED: frozenset(
        {EXEC_QUEUED, EXEC_RUNNING, EXEC_FAILED, EXEC_CANCELED, EXEC_LOST}
    ),
    EXEC_RUNNING: frozenset(
        {
            EXEC_RUNNING,
            EXEC_FINALIZING,
            EXEC_COMPLETE,
            EXEC_FAILED,
            EXEC_CANCELED,
            EXEC_LOST,
        }
    ),
    EXEC_FINALIZING: frozenset(
        {
            EXEC_FINALIZING,
            EXEC_COMPLETE,
            EXEC_FAILED,
            EXEC_CANCELED,
            EXEC_LOST,
        }
    ),
}

_ATTEMPT_EDGES: dict[str, frozenset[str]] = {
    ATTEMPT_PENDING: frozenset(
        {
            ATTEMPT_PENDING,
            ATTEMPT_RUNNING,
            ATTEMPT_FINISHED,
            ATTEMPT_FAILED,
            ATTEMPT_CANCELED,
            ATTEMPT_LOST,
        }
    ),
    ATTEMPT_RUNNING: frozenset(
        {
            ATTEMPT_RUNNING,
            ATTEMPT_FINISHED,
            ATTEMPT_FAILED,
            ATTEMPT_CANCELED,
            ATTEMPT_LOST,
        }
    ),
}


def is_valid_execution_transition(old: str, new: str) -> bool:
    if old in EXEC_TERMINAL:
        return old == new
    return new in _EXEC_EDGES.get(old, frozenset())


def is_valid_attempt_transition(old: str, new: str) -> bool:
    if old in ATTEMPT_TERMINAL:
        return old == new
    return new in _ATTEMPT_EDGES.get(old, frozenset())


def rollup_execution_status(attempt_statuses: list[str]) -> str | None:
    """Map a set of attempt states to the execution terminal, or ``None``.

    Returns ``None`` while any attempt is still active. Precedence among
    terminals: failed > lost > canceled > complete.
    """
    if not attempt_statuses or not all(
        s in ATTEMPT_TERMINAL for s in attempt_statuses
    ):
        return None
    if any(s == ATTEMPT_FAILED for s in attempt_statuses):
        return EXEC_FAILED
    if any(s == ATTEMPT_LOST for s in attempt_statuses):
        return EXEC_LOST
    if any(s == ATTEMPT_CANCELED for s in attempt_statuses):
        return EXEC_CANCELED
    return EXEC_COMPLETE
