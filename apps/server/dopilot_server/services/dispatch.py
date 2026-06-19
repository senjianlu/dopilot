"""Shared template->task dispatch helper (phase 1.7 packet 2).

Run-from-template, schedule trigger-now, and schedule timer firing all create a
task from a template snapshot through the SAME path as a manual run: build the
run request, attach provenance (:class:`TaskOrigin`), and hand it to the
type's executor. One code path → identical Redis/disk/agent behavior and zero
risk of a second, drifting dispatch implementation.
"""

from __future__ import annotations

from dopilot_protocol import ExecutionRunResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ..config.settings import Settings
from ..executors.base import ExecutorContext
from ..executors.registry import get_executor
from ..models.scheduling import TaskTemplate
from ..redis.dispatcher import CommandDispatcher
from . import templates as tmpl
from .executions import TaskOrigin


async def dispatch_from_template(
    session: AsyncSession,
    settings: Settings,
    dispatcher: CommandDispatcher,
    template: TaskTemplate,
    *,
    source: str,
    schedule_id: str | None = None,
) -> ExecutionRunResponse:
    """Create + dispatch a task from ``template`` with the given provenance.

    May raise :class:`DispatchUnknownError` (XADD landed but the sent-mark
    commit was lost) — the caller decides whether to surface 202 (HTTP) or
    treat it as delivered (timer firing).
    """
    request, snapshot = tmpl.build_run_request(template)
    origin = TaskOrigin(
        source=source,
        template_id=template.id,
        schedule_id=schedule_id,
        template_snapshot=snapshot,
    )
    executor = get_executor(template.task_type)
    ctx = ExecutorContext(
        session=session, settings=settings, dispatcher=dispatcher
    )
    return await executor.run(request, ctx, origin)
