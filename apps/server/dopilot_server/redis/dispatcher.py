"""Command dispatcher (phase 1.5).

Scans the command outbox and XADDs un-sent rows to the agent command streams.
The single-row ``try_dispatch`` carries all the safety gating required by
refactor/00 §command outbox:

- ``run`` short-circuit: if the execution is already terminal (e.g. a manual
  run failed and left an orphan pending row), discard the row — never start a
  task twice;
- cancel CAS: re-read the row status before every XADD; a ``canceled`` row is
  never dispatched;
- at-least-once: an XADD failure leaves the row ``failed_retryable`` for the
  periodic loop; a manual caller asks to give up immediately (``failed``);
- give-up: past ``give_up_at`` / ``max_retry``, a ``run`` row fails its
  execution/attempt with ``dispatch_timeout``.

The actual write to Redis is the LAST step, after the business+outbox commit —
this is never a cross-resource pseudo-transaction.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from dopilot_protocol import AgentCommand, AgentCommandType, StopIntent
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..models.command_outbox import (
    OUTBOX_CANCELED,
    OUTBOX_DISPATCHABLE,
    OUTBOX_DISPATCHING,
    OUTBOX_FAILED,
    OUTBOX_FAILED_RETRYABLE,
    OUTBOX_SENT,
    CommandOutbox,
)
from ..services import executions as svc
from ..services import states
from .commands import CommandProducer

logger = logging.getLogger(__name__)

DISPATCH_TIMEOUT = "dispatch_timeout"
DISPATCH_UNAVAILABLE = "dispatch_unavailable"


def _aware(dt: datetime | None) -> datetime | None:
    """Coerce a stored timestamp to UTC-aware (SQLite returns naive)."""
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


@dataclass
class DispatchResult:
    """Outcome of one ``try_dispatch`` call."""

    outcome: str  # "sent" | "skipped" | "retry" | "failed"
    msg_id: str | None = None
    error: str | None = None


class CommandDispatcher:
    """Periodic + on-demand command delivery from the outbox to Redis."""

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        producer: CommandProducer,
        *,
        interval_seconds: float = 2.0,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._producer = producer
        self._interval = interval_seconds
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()

    # --- single-row dispatch ----------------------------------------------
    def _build_command(self, row: CommandOutbox) -> AgentCommand:
        return AgentCommand(
            command_id=row.command_id,
            type=AgentCommandType(row.type),
            agent_id=row.agent_id,
            task_id=row.task_id,
            execution_id=row.execution_id,
            task_type=str((row.payload or {}).get("task_type", "scrapy")),
            intent=StopIntent(row.intent) if row.intent else None,
            payload=dict(row.payload or {}),
            created_at=datetime.now(UTC).isoformat(),
        )

    async def try_dispatch(
        self, session: AsyncSession, row: CommandOutbox, *, give_up_on_fail: bool = False
    ) -> DispatchResult:
        """Attempt to deliver one outbox row. Mutates ``row`` (caller commits)."""
        # Re-read the row from the DB before dispatch (refactor/00 §Command outbox:
        # "每次 XADD 前都必须重读 outbox status"): a concurrent cancel may have CAS'd
        # this row to `canceled` in another session since it was queried.
        await session.refresh(row)
        if row.status == OUTBOX_SENT:
            return DispatchResult("sent", msg_id=row.redis_msg_id)
        # cancel CAS: never dispatch a canceled row.
        if row.status == OUTBOX_CANCELED:
            return DispatchResult("skipped", error="canceled")

        # run short-circuit: don't (re)start a task for a terminal task.
        if row.type == "run":
            task = await svc.get_task(session, row.task_id)
            if task is None or task.status in states.TASK_TERMINAL:
                row.status = OUTBOX_CANCELED
                row.last_error = "execution_not_dispatchable"
                return DispatchResult("skipped", error="execution_not_dispatchable")

        row.status = OUTBOX_DISPATCHING
        cmd = self._build_command(row)
        try:
            msg_id = await self._producer.send(cmd)
        except Exception as exc:  # noqa: BLE001 - Redis unavailable / XADD error
            row.retry_count += 1
            row.last_error = DISPATCH_UNAVAILABLE
            give_up_at = _aware(row.give_up_at)
            past_give_up = give_up_at is not None and datetime.now(UTC) >= give_up_at
            if give_up_on_fail or row.retry_count >= row.max_retry or past_give_up:
                row.status = OUTBOX_FAILED
                return DispatchResult("failed", error=str(exc))
            row.status = OUTBOX_FAILED_RETRYABLE
            return DispatchResult("retry", error=str(exc))

        row.status = OUTBOX_SENT
        row.redis_msg_id = msg_id
        return DispatchResult("sent", msg_id=msg_id)

    # --- give-up bookkeeping ----------------------------------------------
    async def _fail_execution_dispatch_timeout(
        self, session: AsyncSession, row: CommandOutbox
    ) -> None:
        """Mark a ``run`` row's execution/task failed with dispatch_timeout."""
        now = datetime.now(UTC)
        execution = await svc.get_execution(session, row.execution_id)
        if execution is not None and execution.status in states.EXEC_ACTIVE:
            execution.status = states.EXEC_FAILED
            execution.error_code = DISPATCH_TIMEOUT
            execution.finished_at = now
        task = await svc.get_task(session, row.task_id)
        if task is not None and task.status in states.TASK_ACTIVE:
            task.status = states.TASK_FAILED
            task.finished_at = now

    async def _process_row(self, session: AsyncSession, row: CommandOutbox) -> None:
        now = datetime.now(UTC)
        give_up_at = _aware(row.give_up_at)
        # past the give-up deadline: fail without further XADD attempts.
        if (
            give_up_at is not None
            and now >= give_up_at
            and row.status != OUTBOX_SENT
        ):
            row.status = OUTBOX_FAILED
            row.last_error = DISPATCH_TIMEOUT
            if row.type == "run":
                await self._fail_execution_dispatch_timeout(session, row)
            return

        result = await self.try_dispatch(session, row)
        if result.outcome == "failed" and row.type == "run":
            await self._fail_execution_dispatch_timeout(session, row)

    # --- periodic loop -----------------------------------------------------
    async def _tick(self) -> None:
        async with self._sessionmaker() as session:
            rows = (
                (
                    await session.execute(
                        select(CommandOutbox).where(
                            CommandOutbox.status.in_(tuple(OUTBOX_DISPATCHABLE))
                        )
                    )
                )
                .scalars()
                .all()
            )
            for row in rows:
                await self._process_row(session, row)
            await session.commit()

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                await self._tick()
            except Exception:  # noqa: BLE001 - never let the loop die
                logger.warning("command dispatcher tick failed", exc_info=True)
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
