"""Server-side event application (phase 1.5).

Applies one :class:`AgentEvent` to its attempt/execution with:

- **dedupe** by ``(stream, redis_msg_id)`` via the ``event_audit`` table;
- **terminal-not-regressed**: a hard agent terminal (finished/failed/canceled)
  is never overwritten by a non-terminal or another terminal;
- **lost soft-terminal override**: a server-inferred ``lost`` may be overridden
  by a later agent-authoritative terminal (records ``reconciled_from=lost``);
  between two ``lost`` events the agent-sourced reason wins (agent > server);
- **execution convergence + rollup**: a ``running`` event moves a still-queued
  execution to running (the ``dispatch_unknown`` convergence path); a set of
  terminal attempts rolls the execution up to its terminal.

``last_event_at`` is stamped (and ``stalled_at`` cleared) on every applied event
so the reconcile loop's event-stall clock is decoupled from ``updated_at``.
"""

from __future__ import annotations

from datetime import UTC, datetime

from dopilot_protocol import AgentEvent, AgentEventType, StopIntent
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.command_outbox import OUTBOX_UNRESOLVED, CommandOutbox
from ..models.event_audit import (
    OUTCOME_APPLIED,
    OUTCOME_OVERRIDE_LOST,
    OUTCOME_RECLAIM_REQUESTED,
    OUTCOME_SKIPPED_DUP,
    OUTCOME_SKIPPED_TERMINAL,
    EventAudit,
)
from ..models.execution import ExecutionAttempt
from . import executions as svc
from . import outbox as outbox_svc
from . import states
from .states import (
    ATTEMPT_LOST,
    ATTEMPT_RUNNING,
    ATTEMPT_TERMINAL,
    EXEC_LOST,
    EXEC_QUEUED,
    EXEC_RUNNING,
    EXEC_TERMINAL,
)

EVENT_STREAM_NAME = "dopilot:server:agent-events"
OUTCOME_SKIPPED_NO_ATTEMPT = "skipped_no_attempt"

_EVENT_TO_ATTEMPT = {
    AgentEventType.accepted: states.ATTEMPT_PENDING,
    AgentEventType.running: states.ATTEMPT_RUNNING,
    AgentEventType.finished: states.ATTEMPT_FINISHED,
    AgentEventType.failed: states.ATTEMPT_FAILED,
    AgentEventType.canceled: states.ATTEMPT_CANCELED,
    AgentEventType.lost: states.ATTEMPT_LOST,
}


def _apply_status(
    attempt: ExecutionAttempt, event: AgentEvent, new_status: str, now: datetime
) -> None:
    attempt.status = new_status
    if new_status == ATTEMPT_RUNNING:
        if attempt.started_at is None:
            attempt.started_at = now
        if event.remote_job_id:
            attempt.remote_job_id = event.remote_job_id
    elif new_status in ATTEMPT_TERMINAL:
        if attempt.started_at is None:
            attempt.started_at = now
        attempt.finished_at = now
        if event.exit_code is not None:
            attempt.exit_code = event.exit_code
        if event.error_code:
            attempt.error_code = event.error_code
        if event.error_detail:
            attempt.error_detail = dict(event.error_detail)
        if new_status == ATTEMPT_LOST and event.lost_reason is not None:
            attempt.lost_reason = event.lost_reason.value


def _maybe_update_lost_reason(attempt: ExecutionAttempt, event: AgentEvent) -> None:
    """lost->lost upsert: agent-sourced reason wins over a server-sourced one."""
    if event.lost_reason is None:
        return
    if event.lost_reason.source == "agent" or attempt.lost_reason is None:
        attempt.lost_reason = event.lost_reason.value


async def _has_unresolved_reclaim(session: AsyncSession, attempt_id: str) -> bool:
    res = await session.execute(
        select(CommandOutbox.command_id).where(
            CommandOutbox.attempt_id == attempt_id,
            CommandOutbox.type == "stop",
            CommandOutbox.intent == StopIntent.reclaim.value,
            CommandOutbox.status.in_(tuple(OUTBOX_UNRESOLVED)),
        )
    )
    return res.first() is not None


async def _request_reclaim(session: AsyncSession, attempt: ExecutionAttempt) -> None:
    """Enqueue a single ``stop(intent=reclaim)`` for a server-lost attempt whose
    agent has reported it is alive (cleanup-reconcile, refactor/00 §日志清理)."""
    if await _has_unresolved_reclaim(session, attempt.id):
        return
    outbox_svc.create_stop_outbox(
        session,
        execution_id=attempt.execution_id,
        attempt_id=attempt.id,
        agent_id=attempt.agent_id or "",
        intent=StopIntent.reclaim,
    )


async def _update_execution(
    session: AsyncSession, attempt: ExecutionAttempt, now: datetime
) -> None:
    execution = await svc.get_execution(session, attempt.execution_id)
    if execution is None:
        return
    # convergence: a running attempt moves a still-queued execution to running.
    if attempt.status == ATTEMPT_RUNNING and execution.status == EXEC_QUEUED:
        execution.status = EXEC_RUNNING
        if execution.started_at is None:
            execution.started_at = now
    # rollup: all attempts terminal -> execution terminal. A `lost` execution is a
    # soft terminal: re-roll it when its attempt is overridden to a hard terminal.
    attempts = await svc.list_attempts(session, execution.id)
    rolled = states.rollup_execution_status([a.status for a in attempts])
    rerollable = execution.status not in EXEC_TERMINAL or execution.status == EXEC_LOST
    if (
        rolled is not None
        and rolled != execution.status
        and rerollable
        and states.is_valid_execution_transition(execution.status, rolled)
    ):
        execution.status = rolled
        execution.finished_at = now


def _audit(
    session: AsyncSession, event: AgentEvent, redis_msg_id: str, outcome: str
) -> None:
    session.add(
        EventAudit(
            stream=EVENT_STREAM_NAME,
            redis_msg_id=redis_msg_id,
            event_id=event.event_id,
            attempt_id=event.attempt_id,
            event_type=event.type.value,
            outcome=outcome,
        )
    )


async def apply_event(
    session: AsyncSession, event: AgentEvent, redis_msg_id: str
) -> str:
    """Apply one event to its attempt/execution; returns the audit outcome."""
    # dedupe on the exact stream entry
    dup = await session.execute(
        select(EventAudit).where(
            EventAudit.stream == EVENT_STREAM_NAME,
            EventAudit.redis_msg_id == redis_msg_id,
        )
    )
    if dup.scalar_one_or_none() is not None:
        return OUTCOME_SKIPPED_DUP

    attempt = await svc.get_attempt(session, event.attempt_id)
    if attempt is None:
        _audit(session, event, redis_msg_id, OUTCOME_SKIPPED_NO_ATTEMPT)
        return OUTCOME_SKIPPED_NO_ATTEMPT

    new_status = _EVENT_TO_ATTEMPT[event.type]
    now = datetime.now(UTC)
    current = attempt.status

    if current == new_status:
        # idempotent re-delivery (e.g. running->running, lost->lost reason upsert)
        if current == ATTEMPT_LOST:
            _maybe_update_lost_reason(attempt, event)
        outcome = OUTCOME_APPLIED
    elif current == ATTEMPT_LOST and event.type.is_authoritative_terminal:
        # soft-terminal override: agent terminal wins over server-lost.
        attempt.reconciled_from = "lost"
        _apply_status(attempt, event, new_status, now)
        outcome = OUTCOME_OVERRIDE_LOST
    elif current == ATTEMPT_LOST and not event.type.is_terminal:
        # cleanup-reconcile (refactor/00 §日志清理): the agent reports it is alive
        # (accepted/running) on a server-lost attempt. Do NOT regress to running;
        # reclaim the process (stop intent=reclaim) and wait for the real terminal
        # or drain timeout before cleanup. The attempt stays `lost`.
        await _request_reclaim(session, attempt)
        outcome = OUTCOME_RECLAIM_REQUESTED
    elif current in ATTEMPT_TERMINAL:
        # hard terminal (or lost hit by a non-authoritative event): do not regress
        outcome = OUTCOME_SKIPPED_TERMINAL
    elif states.is_valid_attempt_transition(current, new_status):
        _apply_status(attempt, event, new_status, now)
        outcome = OUTCOME_APPLIED
    else:
        # invalid transition (e.g. running -> pending): no regress
        outcome = OUTCOME_SKIPPED_TERMINAL

    # agent produced an event -> it is alive; reset the event-stall clock.
    attempt.last_event_at = now
    attempt.stalled_at = None
    await _update_execution(session, attempt, now)
    _audit(session, event, redis_msg_id, outcome)
    return outcome
