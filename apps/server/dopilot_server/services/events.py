"""Server-side event application (phase 1.5; phase-1.7 task/execution naming).

Applies one :class:`AgentEvent` to its execution/task with:

- **dedupe** by ``(stream, redis_msg_id)`` via the ``event_audit`` table;
- **terminal-not-regressed**: a hard agent terminal (finished/failed/canceled)
  is never overwritten by a non-terminal or another terminal;
- **lost soft-terminal override**: a server-inferred ``lost`` may be overridden
  by a later agent-authoritative terminal (records ``reconciled_from=lost``);
  between two ``lost`` events the agent-sourced reason wins (agent > server);
- **task convergence + rollup**: a ``running`` event moves a still-queued task
  to running (the ``dispatch_unknown`` convergence path); a set of terminal
  executions rolls the task up to its terminal.

Naming (phase 2a clean-cut): ``AgentEvent.execution_id`` is the atomic
:class:`Execution` id and the ``event_audit`` column has the same name. The
lookups go straight ``execution_id -> Execution.id`` and ``Execution.task_id ->
Task``.

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
from ..models.execution import Execution
from . import executions as svc
from . import outbox as outbox_svc
from . import states
from .states import (
    EXEC_LOST,
    EXEC_RUNNING,
    EXEC_TERMINAL,
    TASK_LOST,
    TASK_QUEUED,
    TASK_RUNNING,
    TASK_TERMINAL,
)

EVENT_STREAM_NAME = "dopilot:server:agent-events"
OUTCOME_SKIPPED_NO_ATTEMPT = "skipped_no_attempt"

_EVENT_TO_EXEC = {
    AgentEventType.accepted: states.EXEC_PENDING,
    AgentEventType.running: states.EXEC_RUNNING,
    AgentEventType.finished: states.EXEC_FINISHED,
    AgentEventType.failed: states.EXEC_FAILED,
    AgentEventType.canceled: states.EXEC_CANCELED,
    AgentEventType.lost: states.EXEC_LOST,
}


def _apply_status(
    execution: Execution, event: AgentEvent, new_status: str, now: datetime
) -> None:
    execution.status = new_status
    if new_status == EXEC_RUNNING:
        if execution.started_at is None:
            execution.started_at = now
        if event.remote_job_id:
            execution.remote_job_id = event.remote_job_id
    elif new_status in EXEC_TERMINAL:
        if execution.started_at is None:
            execution.started_at = now
        execution.finished_at = now
        if event.exit_code is not None:
            execution.exit_code = event.exit_code
        if event.error_code:
            execution.error_code = event.error_code
        if event.error_detail:
            execution.error_detail = dict(event.error_detail)
        if new_status == EXEC_LOST and event.lost_reason is not None:
            execution.lost_reason = event.lost_reason.value


def _maybe_update_lost_reason(execution: Execution, event: AgentEvent) -> None:
    """lost->lost upsert: agent-sourced reason wins over a server-sourced one."""
    if event.lost_reason is None:
        return
    if event.lost_reason.source == "agent" or execution.lost_reason is None:
        execution.lost_reason = event.lost_reason.value


async def _has_unresolved_reclaim(session: AsyncSession, execution_id: str) -> bool:
    res = await session.execute(
        select(CommandOutbox.command_id).where(
            CommandOutbox.execution_id == execution_id,
            CommandOutbox.type == "stop",
            CommandOutbox.intent == StopIntent.reclaim.value,
            CommandOutbox.status.in_(tuple(OUTBOX_UNRESOLVED)),
        )
    )
    return res.first() is not None


async def _request_reclaim(session: AsyncSession, execution: Execution) -> None:
    """Enqueue a single ``stop(intent=reclaim)`` for a server-lost execution
    whose agent has reported it is alive (cleanup-reconcile,
    refactor/00 §日志清理)."""
    if await _has_unresolved_reclaim(session, execution.id):
        return
    outbox_svc.create_stop_outbox(
        session,
        task_id=execution.task_id,
        execution_id=execution.id,
        agent_id=execution.agent_id or "",
        intent=StopIntent.reclaim,
    )


async def _update_task(
    session: AsyncSession, execution: Execution, now: datetime
) -> None:
    task = await svc.get_task(session, execution.task_id)
    if task is None:
        return
    # convergence: a running execution moves a still-queued task to running.
    if execution.status == EXEC_RUNNING and task.status == TASK_QUEUED:
        task.status = TASK_RUNNING
        if task.started_at is None:
            task.started_at = now
    # rollup: all executions terminal -> task terminal. A `lost` task is a soft
    # terminal: re-roll it when its execution is overridden to a hard terminal.
    executions = await svc.list_executions(session, task.id)
    rolled = states.rollup_task_status([e.status for e in executions])
    rerollable = task.status not in TASK_TERMINAL or task.status == TASK_LOST
    if (
        rolled is not None
        and rolled != task.status
        and rerollable
        and states.is_valid_task_transition(task.status, rolled)
    ):
        task.status = rolled
        task.finished_at = now


def _audit(
    session: AsyncSession, event: AgentEvent, redis_msg_id: str, outcome: str
) -> None:
    session.add(
        EventAudit(
            stream=EVENT_STREAM_NAME,
            redis_msg_id=redis_msg_id,
            event_id=event.event_id,
            execution_id=event.execution_id,
            event_type=event.type.value,
            outcome=outcome,
        )
    )


async def apply_event(
    session: AsyncSession, event: AgentEvent, redis_msg_id: str
) -> str:
    """Apply one event to its execution/task; returns the audit outcome."""
    # dedupe on the exact stream entry
    dup = await session.execute(
        select(EventAudit).where(
            EventAudit.stream == EVENT_STREAM_NAME,
            EventAudit.redis_msg_id == redis_msg_id,
        )
    )
    if dup.scalar_one_or_none() is not None:
        return OUTCOME_SKIPPED_DUP

    execution = await svc.get_execution(session, event.execution_id)
    if execution is None:
        _audit(session, event, redis_msg_id, OUTCOME_SKIPPED_NO_ATTEMPT)
        return OUTCOME_SKIPPED_NO_ATTEMPT

    new_status = _EVENT_TO_EXEC[event.type]
    now = datetime.now(UTC)
    current = execution.status

    if current == new_status:
        # idempotent re-delivery (e.g. running->running, lost->lost reason upsert)
        if current == EXEC_LOST:
            _maybe_update_lost_reason(execution, event)
        outcome = OUTCOME_APPLIED
    elif current == EXEC_LOST and event.type.is_authoritative_terminal:
        # soft-terminal override: agent terminal wins over server-lost.
        execution.reconciled_from = "lost"
        _apply_status(execution, event, new_status, now)
        outcome = OUTCOME_OVERRIDE_LOST
    elif current == EXEC_LOST and not event.type.is_terminal:
        # cleanup-reconcile (refactor/00 §日志清理): the agent reports it is alive
        # (accepted/running) on a server-lost execution. Do NOT regress to
        # running; reclaim the process (stop intent=reclaim) and wait for the
        # real terminal or drain timeout before cleanup. It stays `lost`.
        await _request_reclaim(session, execution)
        outcome = OUTCOME_RECLAIM_REQUESTED
    elif current in EXEC_TERMINAL:
        # hard terminal (or lost hit by a non-authoritative event): do not regress
        outcome = OUTCOME_SKIPPED_TERMINAL
    elif states.is_valid_execution_transition(current, new_status):
        _apply_status(execution, event, new_status, now)
        outcome = OUTCOME_APPLIED
    else:
        # invalid transition (e.g. running -> pending): no regress
        outcome = OUTCOME_SKIPPED_TERMINAL

    # agent produced an event -> it is alive; reset the event-stall clock.
    execution.last_event_at = now
    execution.stalled_at = None
    await _update_task(session, execution, now)
    _audit(session, event, redis_msg_id, outcome)
    return outcome
