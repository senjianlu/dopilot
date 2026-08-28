"""Command-outbox service (phase 1.5; phase-1.7 task/execution naming).

Creates server -> agent command rows in the SAME PostgreSQL transaction as their
task/execution (the transactional producer-outbox), cancels unsent rows on
cancel (CAS), and provides the coalesce primitive the scheduler will use to
avoid piling up same-source commands while Redis is unavailable.

The ``CommandOutbox`` row carries the columns ``task_id`` (= :class:`Task` id)
and ``execution_id`` (= atomic :class:`Execution` id); the create/cancel helpers
below take those names as parameters. Callers pass ``task.id`` as ``task_id`` and
``execution.id`` as ``execution_id``.

The actual XADD to Redis happens later, in the dispatcher — never here. This
keeps the outbox a PG-internal producer-outbox, not a cross-resource pseudo-tx.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from dopilot_protocol import StopIntent
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.command_outbox import (
    OUTBOX_CANCELED,
    OUTBOX_PENDING,
    OUTBOX_SENT,
    OUTBOX_UNRESOLVED,
    CommandOutbox,
)
from ..models.execution import Task
from .states import TASK_QUEUED

# Give-up windows. Manual/sync run uses a short window (the request waits on the
# first dispatch); scheduled/async triggers tolerate a longer outage.
MANUAL_GIVE_UP_SECONDS = 120
SCHEDULED_GIVE_UP_SECONDS = 900


def _new_id() -> str:
    return uuid.uuid4().hex


def _windows(manual: bool) -> tuple[datetime, datetime]:
    secs = MANUAL_GIVE_UP_SECONDS if manual else SCHEDULED_GIVE_UP_SECONDS
    deadline = datetime.now(UTC) + timedelta(seconds=secs)
    return deadline, deadline  # (expire_at, give_up_at)


def create_run_outbox(
    session: AsyncSession,
    *,
    task_id: str,
    execution_id: str,
    agent_id: str,
    payload: dict,
    manual: bool,
) -> CommandOutbox:
    """Create a pending ``run`` command row (same tx as the execution)."""
    expire_at, give_up_at = _windows(manual)
    row = CommandOutbox(
        command_id=_new_id(),
        agent_id=agent_id,
        task_id=task_id,
        execution_id=execution_id,
        type="run",
        payload=dict(payload),
        status=OUTBOX_PENDING,
        expire_at=expire_at,
        give_up_at=give_up_at,
    )
    session.add(row)
    return row


def create_stop_outbox(
    session: AsyncSession,
    *,
    task_id: str,
    execution_id: str,
    agent_id: str,
    intent: StopIntent,
) -> CommandOutbox:
    """Create a ``stop`` command (carries intent=cancel|reclaim)."""
    expire_at, give_up_at = _windows(manual=False)
    row = CommandOutbox(
        command_id=_new_id(),
        agent_id=agent_id,
        task_id=task_id,
        execution_id=execution_id,
        type="stop",
        intent=intent.value,
        payload={},
        status=OUTBOX_PENDING,
        expire_at=expire_at,
        give_up_at=give_up_at,
    )
    session.add(row)
    return row


def create_cleanup_outbox(
    session: AsyncSession,
    *,
    task_id: str,
    execution_id: str,
    agent_id: str,
) -> CommandOutbox:
    """Create a ``cleanup_logs`` command (idempotent on the agent)."""
    expire_at, give_up_at = _windows(manual=False)
    row = CommandOutbox(
        command_id=_new_id(),
        agent_id=agent_id,
        task_id=task_id,
        execution_id=execution_id,
        type="cleanup_logs",
        payload={},
        status=OUTBOX_PENDING,
        expire_at=expire_at,
        give_up_at=give_up_at,
    )
    session.add(row)
    return row


async def create_stop_logs_outbox(
    session: AsyncSession,
    *,
    task_id: str,
    execution_id: str,
    agent_id: str,
) -> CommandOutbox | None:
    """Queue a ``stop_logs`` backpressure command (log-flood guard).

    Idempotent per execution: when an un-terminated ``stop_logs`` row already
    exists for this execution nothing is added and ``None`` is returned. No
    business-state change is involved; the agent simply stops tailing.
    """
    existing = await session.execute(
        select(CommandOutbox.command_id).where(
            CommandOutbox.execution_id == execution_id,
            CommandOutbox.type == "stop_logs",
            CommandOutbox.status.in_(sorted(OUTBOX_UNRESOLVED | {OUTBOX_SENT})),
        )
    )
    if existing.first() is not None:
        return None
    expire_at, give_up_at = _windows(manual=False)
    row = CommandOutbox(
        command_id=_new_id(),
        agent_id=agent_id,
        task_id=task_id,
        execution_id=execution_id,
        type="stop_logs",
        payload={},
        status=OUTBOX_PENDING,
        expire_at=expire_at,
        give_up_at=give_up_at,
    )
    session.add(row)
    return row


async def reclaim_ever_issued(session: AsyncSession, execution_id: str) -> bool:
    """True if a ``stop(intent=reclaim)`` was EVER enqueued for this execution.

    Deliberately status-blind (a ``sent`` or even ``failed`` row still counts):
    both consumers ask "was a reclaim ever attempted", not "is one in flight" —
    the heartbeat path uses it for its at-most-once reclaim (a heartbeat is
    periodic; an unresolved-only check would re-enqueue every interval once the
    first stop turns ``sent``), and ``finalize_drained_logs`` uses it as the
    cleanup gate for server-lost attempts.
    """
    res = await session.execute(
        select(CommandOutbox.command_id).where(
            CommandOutbox.execution_id == execution_id,
            CommandOutbox.type == "stop",
            CommandOutbox.intent == StopIntent.reclaim.value,
        )
    )
    return res.first() is not None


async def cancel_unsent_outbox(session: AsyncSession, task_id: str) -> int:
    """CAS every still-unsent outbox row of a task to ``canceled``.

    Returns the number of rows transitioned. Any delivery path MUST re-read the
    row status before XADD, so a canceled row is never dispatched. "Unsent"
    does NOT mean "never left the server" — the caller must still send a
    ``stop(intent=cancel)`` for already-dispatched/unknown rows.
    """
    result = await session.execute(
        update(CommandOutbox)
        .where(
            CommandOutbox.task_id == task_id,
            CommandOutbox.status.in_(tuple(OUTBOX_UNRESOLVED)),
        )
        .values(status=OUTBOX_CANCELED)
    )
    return int(result.rowcount or 0)


async def has_undispatched_backlog_for_schedule(
    session: AsyncSession, schedule_id: str
) -> bool:
    """Schedule-keyed coalesce primitive (phase 1.7 packet 2).

    Returns True iff the schedule has an UNDISPATCHED backlog task: a task with
    this ``schedule_id`` that is still ``queued`` AND has an unresolved
    (pending / dispatching / failed_retryable) command-outbox row. That is the
    Redis-outage backlog the scheduler must coalesce (refactor/00 §任务投递).

    Deliberately narrow — this predicate answers ONLY "is there an undispatched
    backlog", never "is the schedule too busy". Concurrency is a separate gate
    (``services.schedules.acquire_firing_slot``, decision 0022) that superseded
    the old "concurrent repeated runs are always allowed" stance; the two run
    back to back inside the same locked region:

    - a ``running`` task does NOT count HERE — suppressing a firing because an
      older run is still active is the concurrency gate's job, not this one's;
    - a queued task whose outbox is already ``sent`` does NOT count — the
      command reached Redis, so it is dispatched, not backlog;
    - manual + trigger-now never call this (only the timer firing does); they are
      still subject to the concurrency gate.

    ``CommandOutbox.task_id`` is the task id, so it joins on ``Task.id``.
    """
    result = await session.execute(
        select(Task.id)
        .join(CommandOutbox, CommandOutbox.task_id == Task.id)
        .where(
            Task.schedule_id == schedule_id,
            Task.status == TASK_QUEUED,
            CommandOutbox.status.in_(tuple(OUTBOX_UNRESOLVED)),
        )
        .limit(1)
    )
    return result.first() is not None
