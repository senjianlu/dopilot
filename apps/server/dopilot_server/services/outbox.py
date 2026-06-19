"""Command-outbox service (phase 1.5).

Creates server -> agent command rows in the SAME PostgreSQL transaction as their
execution/attempt (the transactional producer-outbox), cancels unsent rows on
execution cancel (CAS), and provides the coalesce primitive the scheduler will
use to avoid piling up same-source commands while Redis is unavailable.

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
    OUTBOX_UNRESOLVED,
    CommandOutbox,
)
from ..models.execution import Execution
from .states import EXEC_ACTIVE

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
    execution_id: str,
    attempt_id: str,
    agent_id: str,
    payload: dict,
    manual: bool,
) -> CommandOutbox:
    """Create a pending ``run`` command row (same tx as execution/attempt)."""
    expire_at, give_up_at = _windows(manual)
    row = CommandOutbox(
        command_id=_new_id(),
        agent_id=agent_id,
        execution_id=execution_id,
        attempt_id=attempt_id,
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
    execution_id: str,
    attempt_id: str,
    agent_id: str,
    intent: StopIntent,
) -> CommandOutbox:
    """Create a ``stop`` command (carries intent=cancel|reclaim)."""
    expire_at, give_up_at = _windows(manual=False)
    row = CommandOutbox(
        command_id=_new_id(),
        agent_id=agent_id,
        execution_id=execution_id,
        attempt_id=attempt_id,
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
    execution_id: str,
    attempt_id: str,
    agent_id: str,
) -> CommandOutbox:
    """Create a ``cleanup_logs`` command (idempotent on the agent)."""
    expire_at, give_up_at = _windows(manual=False)
    row = CommandOutbox(
        command_id=_new_id(),
        agent_id=agent_id,
        execution_id=execution_id,
        attempt_id=attempt_id,
        type="cleanup_logs",
        payload={},
        status=OUTBOX_PENDING,
        expire_at=expire_at,
        give_up_at=give_up_at,
    )
    session.add(row)
    return row


async def cancel_unsent_outbox(session: AsyncSession, execution_id: str) -> int:
    """CAS every still-unsent outbox row of an execution to ``canceled``.

    Returns the number of rows transitioned. Any delivery path MUST re-read the
    row status before XADD, so a canceled row is never dispatched. "Unsent"
    does NOT mean "never left the server" — the caller must still send a
    ``stop(intent=cancel)`` for already-dispatched/unknown rows.
    """
    result = await session.execute(
        update(CommandOutbox)
        .where(
            CommandOutbox.execution_id == execution_id,
            CommandOutbox.status.in_(tuple(OUTBOX_UNRESOLVED)),
        )
        .values(status=OUTBOX_CANCELED)
    )
    return int(result.rowcount or 0)


async def has_unterminated_for_target(session: AsyncSession, target: str) -> bool:
    """Coalesce primitive: is there an un-terminated execution OR unresolved
    outbox for ``target``?

    The scheduler (phase 2) calls this to suppress duplicate same-source
    triggers while Redis is unavailable (refactor/00 §任务投递 coalesce). A
    queued execution counts as un-terminated; a pending/dispatching outbox row
    tied to such an execution counts too.
    """
    active = await session.execute(
        select(Execution.id).where(
            Execution.target == target,
            Execution.status.in_(tuple(EXEC_ACTIVE)),
        )
    )
    if active.first() is not None:
        return True
    unresolved = await session.execute(
        select(CommandOutbox.command_id)
        .join(Execution, Execution.id == CommandOutbox.execution_id)
        .where(
            Execution.target == target,
            CommandOutbox.status.in_(tuple(OUTBOX_UNRESOLVED)),
        )
    )
    return unresolved.first() is not None
