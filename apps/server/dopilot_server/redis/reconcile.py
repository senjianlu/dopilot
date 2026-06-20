"""Heartbeat / event-stall reconcile (phase 1.5).

Replaces the phase-1 agent ``/status`` poll. The server never contacts the agent
over HTTP here — it reasons purely from PostgreSQL:

- **heartbeat_timeout**: an active attempt whose agent's ``nodes.last_seen_at``
  is stale (or absent) is declared ``lost(heartbeat_timeout)``. No stop is sent
  (the agent is unreachable; the cleanup-reconcile path handles it on recovery).
- **event_stall**: the agent heartbeat is fresh but the attempt produced no
  status event for ``stalled_attempt_seconds`` -> a one-shot ``stalled`` marker
  (operator-visible, NOT terminal); past ``lost_after_stalled_seconds`` ->
  ``lost(event_stall)`` AND a ``stop(intent=reclaim)`` command (the process is
  likely alive, so kill it to avoid a zombie).

A server-lost is a soft terminal (overridable by a later agent-authoritative
terminal, see the event consumer). Already-terminal attempts are short-circuited.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from dopilot_protocol import StopIntent
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..config.settings import Settings
from ..models.command_outbox import CommandOutbox
from ..models.execution import Execution, ExecutionLogFile, Task
from ..models.node import Node
from ..services import executions as svc
from ..services import outbox as outbox_svc
from ..services import states

# Agent-authoritative terminals — safe to clean up (the process is known done).
# A pure server-lost (status==lost, reconciled_from None) is NOT cleaned up here:
# the agent may still be running; the cleanup-reconcile path handles it.
_CLEANUP_TERMINALS = frozenset(
    {states.EXEC_FINISHED, states.EXEC_FAILED, states.EXEC_CANCELED}
)

logger = logging.getLogger(__name__)

LOST_HEARTBEAT_TIMEOUT = "heartbeat_timeout"
LOST_EVENT_STALL = "event_stall"


def _aware(dt: datetime | None) -> datetime | None:
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


@dataclass
class ReconcileReport:
    heartbeat_lost: int = 0
    event_stall_lost: int = 0
    stalled: int = 0
    reclaim_stops: int = 0
    lost_execution_ids: list[str] = field(default_factory=list)


async def _rollup(session: AsyncSession, task_id: str, now: datetime) -> None:
    task = await svc.get_task(session, task_id)
    if task is None or task.status in states.TASK_TERMINAL:
        return
    executions = await svc.list_executions(session, task_id)
    rolled = states.rollup_task_status([e.status for e in executions])
    if rolled is not None and states.is_valid_task_transition(
        task.status, rolled
    ):
        task.status = rolled
        task.finished_at = now


async def mark_lost(
    session: AsyncSession,
    execution: Execution,
    reason: str,
    now: datetime,
) -> bool:
    """Declare an active execution ``lost`` with ``reason``; roll up + finalize.

    Short-circuits (returns False) if the execution is already terminal — a
    server-lost must never overwrite an existing terminal.
    """
    if execution.status in states.EXEC_TERMINAL:
        return False
    execution.status = states.EXEC_LOST
    execution.lost_reason = reason
    execution.finished_at = now
    execution.error_code = "agent.lost"
    execution.error_detail = {"reason": reason}
    # The log stays drainable (FINALIZING), NOT complete: a later
    # agent-authoritative terminal or a reclaim must still be able to drive the
    # bounded drain -> cleanup_logs. finalize_drained_logs finalizes it.
    log_file = await svc.get_log_file(session, execution.task_id, execution.id)
    if log_file is not None and log_file.status == states.LOG_ACTIVE:
        log_file.status = states.LOG_FINALIZING
    await _rollup(session, execution.task_id, now)
    return True


async def _nodes_by_agent(session: AsyncSession) -> dict[str, Node]:
    rows = (await session.execute(select(Node))).scalars().all()
    return {n.agent_id: n for n in rows if n.agent_id}


async def reconcile_once(
    session: AsyncSession,
    settings: Settings,
    *,
    now: datetime | None = None,
) -> ReconcileReport:
    """One reconcile pass over all active attempts. The caller commits."""
    now = now or datetime.now(UTC)
    hb_timeout = settings.agents.heartbeat_timeout_seconds
    stall = settings.agents.stalled_attempt_seconds
    lost_after = settings.agents.lost_after_stalled_seconds
    report = ReconcileReport()

    executions = (
        (
            await session.execute(
                select(Execution)
                .join(Task, Execution.task_id == Task.id)
                .where(
                    Task.status.in_(tuple(states.TASK_ACTIVE)),
                    Execution.status.in_(tuple(states.EXEC_ACTIVE)),
                )
            )
        )
        .scalars()
        .all()
    )
    nodes = await _nodes_by_agent(session)

    for execution in executions:
        node = nodes.get(execution.agent_id or "")
        last_seen = _aware(node.last_seen_at) if node is not None else None

        # 1) heartbeat timeout: agent unreachable -> lost, no stop.
        if last_seen is None or (now - last_seen) > timedelta(seconds=hb_timeout):
            if await mark_lost(session, execution, LOST_HEARTBEAT_TIMEOUT, now):
                report.heartbeat_lost += 1
                report.lost_execution_ids.append(execution.id)
            continue

        # 2) event stall (heartbeat fresh): measure idle since last event.
        baseline = (
            _aware(execution.last_event_at)
            or _aware(execution.started_at)
            or _aware(execution.created_at)
        )
        idle = (now - baseline).total_seconds() if baseline is not None else 0.0

        if idle >= lost_after:
            if await mark_lost(session, execution, LOST_EVENT_STALL, now):
                report.event_stall_lost += 1
                report.lost_execution_ids.append(execution.id)
                # process likely alive -> reclaim it.
                outbox_svc.create_stop_outbox(
                    session,
                    task_id=execution.task_id,
                    execution_id=execution.id,
                    agent_id=execution.agent_id or "",
                    intent=StopIntent.reclaim,
                )
                report.reclaim_stops += 1
        elif idle >= stall and execution.stalled_at is None:
            execution.stalled_at = now  # one-shot operator-visible alert
            report.stalled += 1

    return report


async def finalize_drained_logs(
    session: AsyncSession,
    settings: Settings,
    *,
    now: datetime | None = None,
) -> int:
    """Bounded drain: finalize terminal attempts' logs + enqueue cleanup.

    After a terminal, the server keeps draining late log events for
    ``log_drain_timeout_seconds``; once the window passes it finalizes the log
    lifecycle (integrity stays ``partial`` if a gap was seen). NOT dependent on
    the lossy ``eof`` event. The caller commits.

    Cleanup gating (refactor/00 §日志清理): a ``cleanup_logs`` command is sent
    only when the agent process is known to be done — an agent-authoritative
    terminal (finished/failed/canceled, incl. a lost->terminal override), OR a
    server-lost attempt for which a ``stop(intent=reclaim)`` was already issued
    (we tried to kill it; after the drain window it is safe to clean). A PURE
    server-lost (heartbeat_timeout, agent unreachable, no reclaim) is NOT
    cleaned — the agent may still be running; cleanup waits for it to recover
    (which triggers a reclaim via the event consumer) — so it is left draining.
    """
    now = now or datetime.now(UTC)
    drain = settings.logs.log_drain_timeout_seconds
    terminal_statuses = tuple(_CLEANUP_TERMINALS | {states.EXEC_LOST})
    rows = (
        await session.execute(
            select(ExecutionLogFile, Execution)
            .join(
                Execution,
                Execution.id == ExecutionLogFile.execution_id,
            )
            .where(
                Execution.status.in_(terminal_statuses),
                ExecutionLogFile.status.in_(
                    (states.LOG_ACTIVE, states.LOG_FINALIZING)
                ),
            )
        )
    ).all()
    count = 0
    for log_file, execution in rows:
        finished = _aware(execution.finished_at)
        if finished is None or (now - finished) < timedelta(seconds=drain):
            continue
        cleanup_ok = execution.status in _CLEANUP_TERMINALS
        if execution.status == states.EXEC_LOST:
            # reclaimed-lost -> safe to clean; pure server-lost -> leave draining.
            cleanup_ok = await _reclaim_issued(session, execution.id)
            if not cleanup_ok:
                continue
        log_file.status = states.LOG_COMPLETE
        log_file.final_offset = log_file.size_bytes
        log_file.finished_at = now
        outbox_svc.create_cleanup_outbox(
            session,
            task_id=log_file.task_id,
            execution_id=log_file.execution_id,
            agent_id=execution.agent_id or "",
        )
        count += 1
    return count


async def _reclaim_issued(session: AsyncSession, execution_id: str) -> bool:
    """True if a ``stop(intent=reclaim)`` was ever enqueued for this execution."""
    res = await session.execute(
        select(CommandOutbox.command_id).where(
            CommandOutbox.execution_id == execution_id,
            CommandOutbox.type == "stop",
            CommandOutbox.intent == StopIntent.reclaim.value,
        )
    )
    return res.first() is not None


class RedisReconcileLoop:
    """Periodic heartbeat/event-stall reconcile (single-instance background loop)."""

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        settings: Settings,
        *,
        interval_seconds: float = 5.0,
    ) -> None:
        self._sm = sessionmaker
        self._settings = settings
        self._interval = interval_seconds
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()

    async def _tick(self) -> None:
        async with self._sm() as session:
            await reconcile_once(session, self._settings)
            await finalize_drained_logs(session, self._settings)
            await session.commit()

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                await self._tick()
            except Exception:  # noqa: BLE001 - never let the loop die
                logger.warning("reconcile tick failed", exc_info=True)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._interval)
            except TimeoutError:
                pass

    def start(self) -> None:
        if self._task is None:
            self._stop.clear()
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._task = None
