"""Shared run->dispatch helpers (phase 1.8).

Direct build-artifact run, execution-template run, schedule trigger-now, and
schedule timer firing all create a task from a RESOLVED snapshot through the SAME
path as every other run: resolve the run (:mod:`services.resolve`), attach
provenance (:class:`TaskOrigin`), and hand the request to the artifact type's
executor. One code path -> identical Redis/disk/agent behavior and zero risk of a
second, drifting dispatch implementation.
"""

from __future__ import annotations

from typing import Any

from dopilot_protocol import ExecutionRunRequest, ExecutionRunResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ..config.settings import Settings
from ..executors.base import ExecutorContext
from ..executors.registry import get_executor
from ..models.execution import BuildArtifact
from ..models.scheduling import ExecutionTemplate
from ..redis.dispatcher import CommandDispatcher
from . import resolve
from . import templates as tmpl
from .executions import TaskOrigin


async def dispatch_resolved(
    session: AsyncSession,
    settings: Settings,
    dispatcher: CommandDispatcher,
    *,
    request: ExecutionRunRequest,
    snapshot: dict[str, Any],
    source: str,
    execution_template_id: str | None = None,
    schedule_id: str | None = None,
) -> ExecutionRunResponse:
    """Create + dispatch a task from a resolved run request + snapshot.

    May raise :class:`DispatchUnknownError` (XADD landed but the sent-mark commit
    was lost) — the caller decides whether to surface 202 (HTTP) or treat it as
    delivered (timer firing).
    """
    origin = TaskOrigin(
        source=source,
        execution_template_id=execution_template_id,
        schedule_id=schedule_id,
        template_snapshot=snapshot,
    )
    executor = get_executor(request.artifact_type)
    ctx = ExecutorContext(
        session=session, settings=settings, dispatcher=dispatcher
    )
    return await executor.run(request, ctx, origin)


async def run_direct_artifact(
    session: AsyncSession,
    settings: Settings,
    dispatcher: CommandDispatcher,
    artifact: BuildArtifact,
    *,
    overrides: dict[str, Any] | None = None,
    source: str = "direct_artifact",
) -> ExecutionRunResponse:
    """Direct build-artifact run: synthesize an ad-hoc snapshot (no template)."""
    request, snapshot = resolve.resolve_run(
        build_artifact=artifact,
        template_defaults={},
        overrides=resolve.sanitize_overrides(overrides),
        name=overrides.get("name") if overrides else None,
    )
    return await dispatch_resolved(
        session,
        settings,
        dispatcher,
        request=request,
        snapshot=snapshot,
        source=source,
    )


async def run_execution_template(
    session: AsyncSession,
    settings: Settings,
    dispatcher: CommandDispatcher,
    template: ExecutionTemplate,
    *,
    source: str,
    schedule_id: str | None = None,
    overrides: dict[str, Any] | None = None,
) -> ExecutionRunResponse:
    """Run from an execution template (+ optional schedule overrides)."""
    request, snapshot = await tmpl.build_run_request(
        session, template, overrides=overrides
    )
    return await dispatch_resolved(
        session,
        settings,
        dispatcher,
        request=request,
        snapshot=snapshot,
        source=source,
        execution_template_id=template.id,
        schedule_id=schedule_id,
    )
