"""Task cancel (phase 1.5; phase-1.7 task/execution naming).

Cancel is uniform and asynchronous: CAS every still-unsent command to
``canceled`` (so it is never dispatched), then send a ``stop(intent=cancel)`` for
each active execution. The agent replies with an authoritative
``attempt.canceled`` regardless of process/state presence (refactor/00 §command
outbox), so the task converges to ``canceled`` via the event consumer — it is
NOT marked canceled synchronously here. "Unsent" does not mean "never left the
server" (``dispatch_unknown``), which is exactly why the stop is always sent.
"""

from __future__ import annotations

from dopilot_protocol import StopIntent
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.execution import Task
from ..redis.dispatcher import CommandDispatcher
from . import executions as svc
from . import states
from .outbox import cancel_unsent_outbox, create_stop_outbox


async def request_cancel(
    session: AsyncSession, dispatcher: CommandDispatcher, task: Task
) -> int:
    """Request cancel of ``task``; returns the number of stop commands sent."""
    await cancel_unsent_outbox(session, task.id)
    executions = await svc.list_executions(session, task.id)
    stops = []
    for execution in executions:
        if execution.status in states.EXEC_TERMINAL:
            continue
        stops.append(
            create_stop_outbox(
                session,
                task_id=task.id,
                execution_id=execution.id,
                agent_id=execution.agent_id or "",
                intent=StopIntent.cancel,
            )
        )
    await session.commit()
    for outbox in stops:
        await dispatcher.try_dispatch(session, outbox)
    await session.commit()
    return len(stops)
