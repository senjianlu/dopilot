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

import logging
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
from ..models.notification import SEVERITY_WARNING, TYPE_LOG_FLOOD
from . import executions as svc
from . import notifications as notif
from . import outbox as outbox_svc
from . import states
from .states import (
    EXEC_LOST,
    EXEC_RUNNING,
    EXEC_TERMINAL,
    TASK_LOST,
    TASK_TERMINAL,
)

EVENT_STREAM_NAME = "dopilot:server:agent-events"
OUTCOME_SKIPPED_NO_ATTEMPT = "skipped_no_attempt"
# Return-value-only outcome for heartbeat events (never persisted to the audit
# table: at one heartbeat per attempt per minute, audit rows would dwarf the
# real lifecycle audit; a heartbeat is idempotent so it needs no dedupe either).
OUTCOME_HEARTBEAT = "heartbeat"
# Agent error_code for a run the log-flood watchdog stopped (see agent
# ``redis/commands.py``): surfaces as a ``log_flood`` notification here.
LOG_FLOOD_ERROR_CODE = "log_flood"
logger = logging.getLogger(__name__)

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
        # Log-flood guard: terminal-only scrapy stats + final local log size
        # (None = unknown; never overwrite a known value with None).
        if event.error_count is not None:
            execution.error_count = event.error_count
        if event.finish_reason is not None:
            execution.finish_reason = event.finish_reason
        if event.log_bytes is not None:
            execution.log_bytes = event.log_bytes


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
    # Terminal-writer protocol (log-flood guard): the task row is locked for
    # the rollup so it serialises with the outcome recorder / reconcile / the
    # dispatcher (lock order task -> executions -> log files -> schedule; the
    # execution row was locked by the caller before this point).
    task = await svc.get_task(session, execution.task_id, for_update=True)
    if task is None:
        return
    executions = await svc.list_executions(session, task.id)
    # convergence: any execution that left ``pending`` (running OR a terminal
    # that arrived without a preceding running event) moves a still-queued task
    # to running — the state machine requires it before a roll-up to complete.
    svc.converge_task(task, executions, now)
    # rollup: all executions terminal -> task terminal. A `lost` task is a soft
    # terminal: re-roll it when its execution is overridden to a hard terminal.
    rolled = states.rollup_task_status([e.status for e in executions])
    rerollable = task.status not in TASK_TERMINAL or task.status == TASK_LOST
    if (
        rolled is not None
        and rolled != task.status
        and rerollable
        and states.is_valid_task_transition(task.status, rolled)
    ):
        was_lost = task.status == TASK_LOST
        task.status = rolled
        task.finished_at = now
        if was_lost and task.outcome_recorded_at is not None:
            # A recorded soft-lost outcome was overridden by an authoritative
            # agent terminal: un-record it so the outcome recorder re-judges
            # the task and corrects the schedule ledger (auto-disable).
            task.outcome_recorded_at = None
            task.outcome_erroneous = None


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
    if event.type == AgentEventType.heartbeat:
        # Liveness-only: refresh the event-stall clock, never touch the state
        # machine (heartbeat has no _EVENT_TO_EXEC mapping), the task rollup,
        # or (except below) the audit table.
        execution = await svc.get_execution(session, event.execution_id)
        if execution is None:
            return OUTCOME_SKIPPED_NO_ATTEMPT
        now = datetime.now(UTC)
        execution.last_event_at = now
        execution.stalled_at = None
        if execution.status == EXEC_LOST:
            # cleanup-reconcile guard: on a server-lost execution a heartbeat
            # proves the process is still alive -> reclaim it; it stays lost.
            # At-most-once per execution: the ever-issued check is status-blind
            # (a heartbeat is periodic; an unresolved-only check would re-enqueue
            # every interval once the first stop turns ``sent``).
            if not await outbox_svc.reclaim_ever_issued(session, execution.id):
                outbox_svc.create_stop_outbox(
                    session,
                    task_id=execution.task_id,
                    execution_id=execution.id,
                    agent_id=execution.agent_id or "",
                    intent=StopIntent.reclaim,
                )
                _audit(session, event, redis_msg_id, OUTCOME_RECLAIM_REQUESTED)
            return OUTCOME_RECLAIM_REQUESTED
        return OUTCOME_HEARTBEAT

    # dedupe on the exact stream entry
    dup = await session.execute(
        select(EventAudit).where(
            EventAudit.stream == EVENT_STREAM_NAME,
            EventAudit.redis_msg_id == redis_msg_id,
        )
    )
    if dup.scalar_one_or_none() is not None:
        return OUTCOME_SKIPPED_DUP

    # Lock order task -> execution: take the task row first so a concurrent
    # terminal writer (reconcile mark_lost / dispatch timeout / recorder) and
    # this event never interleave on the same rows.
    await svc.get_task(session, event.task_id, for_update=True)
    execution = await svc.get_execution(session, event.execution_id, for_update=True)
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
    if (
        outcome in (OUTCOME_APPLIED, OUTCOME_OVERRIDE_LOST)
        and event.type.is_terminal
        and event.error_code == LOG_FLOOD_ERROR_CODE
    ):
        await _notify_log_flood(session, event)
    _audit(session, event, redis_msg_id, outcome)
    return outcome


async def _notify_log_flood(session: AsyncSession, event: AgentEvent) -> None:
    """Raise the ``log_flood`` alert (once per execution) for a flood-stopped run."""
    detail = dict(event.error_detail or {})
    try:
        await notif.notify(
            session,
            type=TYPE_LOG_FLOOD,
            severity=SEVERITY_WARNING,
            payload={
                "task_id": event.task_id,
                "execution_id": event.execution_id,
                "agent_id": event.agent_id,
                "log_bytes": event.log_bytes if event.log_bytes is not None
                else detail.get("log_bytes"),
                "cap": detail.get("cap"),
                "kill_escalation": detail.get("kill_escalation"),
            },
            dedupe_key=event.execution_id,
        )
    except Exception:  # noqa: BLE001 - alerting never breaks event application
        logger.warning("log_flood notify failed for %s", event.execution_id, exc_info=True)
