"""Execution cancel (phase 1.5).

Cancel is uniform and asynchronous: CAS every still-unsent command to
``canceled`` (so it is never dispatched), then send a ``stop(intent=cancel)`` for
each active attempt. The agent replies with an authoritative ``attempt.canceled``
regardless of process/state presence (refactor/00 §command outbox), so the
execution converges to ``canceled`` via the event consumer — it is NOT marked
canceled synchronously here. "Unsent" does not mean "never left the server"
(``dispatch_unknown``), which is exactly why the stop is always sent.
"""

from __future__ import annotations

from dopilot_protocol import StopIntent
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.execution import Execution
from ..redis.dispatcher import CommandDispatcher
from . import executions as svc
from . import states
from .outbox import cancel_unsent_outbox, create_stop_outbox


async def request_cancel(
    session: AsyncSession, dispatcher: CommandDispatcher, execution: Execution
) -> int:
    """Request cancel of ``execution``; returns the number of stop commands sent."""
    await cancel_unsent_outbox(session, execution.id)
    attempts = await svc.list_attempts(session, execution.id)
    stops = []
    for attempt in attempts:
        if attempt.status in states.ATTEMPT_TERMINAL:
            continue
        stops.append(
            create_stop_outbox(
                session,
                execution_id=execution.id,
                attempt_id=attempt.id,
                agent_id=attempt.agent_id or "",
                intent=StopIntent.cancel,
            )
        )
    await session.commit()
    for outbox in stops:
        await dispatcher.try_dispatch(session, outbox)
    await session.commit()
    return len(stops)
