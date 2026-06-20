"""Scrapy-via-scrapyd executor (phase 1.5; phase-1.7 task/execution naming).

Selects heartbeat-live scrapy-capable nodes, creates the task + one atomic
execution per node + a per-execution ``run`` command-outbox row + the
``execution_log_files`` index in ONE atomic PostgreSQL transaction, then
synchronously dispatches each ``run`` command to the agent command stream:

- all XADDs succeed -> task stays ``queued`` (the agent's ``attempt.running``
  event converges it to running; we do NOT optimistically mark running here);
- every XADD fails (Redis down) -> task/executions/outbox marked ``failed``
  ``dispatch_unavailable``, the API returns 503;
- XADD succeeded but the ``sent`` mark fails to commit -> 202 ``dispatch_unknown``
  (the command may already be running; never report "not delivered").

⚠️ Wire seam unchanged: the command outbox row keys ``execution_id`` = task id
and ``attempt_id`` = atomic execution id, matching the agent payloads.

The agent then drives its local scrapyd; the event/log consumers + reconcile
loop take over. No server->agent HTTP.
"""

from __future__ import annotations

from datetime import UTC, datetime

from dopilot_protocol import ExecutionRunRequest, ExecutionRunResponse

from ..errors import ApiError
from ..nodes.service import resolve_target_nodes
from ..redis.dispatcher import DISPATCH_UNAVAILABLE
from ..services import executions as svc
from ..services import states
from ..services.executions import TaskOrigin
from ..services.outbox import create_run_outbox
from .base import BaseExecutor, DispatchUnknownError, ExecutorContext


class ScrapydExecutor(BaseExecutor):
    """Dispatches Scrapy jobs to agents over the Redis command stream."""

    artifact_type = "scrapy"

    async def run(
        self,
        request: ExecutionRunRequest,
        ctx: ExecutorContext,
        origin: TaskOrigin | None = None,
    ) -> ExecutionRunResponse:
        scrapy = svc.parse_scrapy_params(request)

        # Phase 1.7 packet 2: create the task FIRST, then select healthy nodes.
        # Zero healthy nodes short-circuits into a persisted terminal
        # ``no_target`` task (zero executions) — we do NOT raise a 409 here.
        task = svc.create_task(ctx.session, request, origin)

        nodes, healthy_count = await resolve_target_nodes(
            ctx.session,
            request.node_strategy,
            request.node_ids,
            capability=states.ARTIFACT_CAPABILITY[self.artifact_type],
            timeout_seconds=ctx.settings.agents.heartbeat_timeout_seconds,
        )
        if not nodes:
            svc.mark_no_target(
                task,
                strategy=request.node_strategy,
                node_ids=request.node_ids,
                healthy_count=healthy_count,
            )
            await ctx.session.commit()
            return ExecutionRunResponse(task_id=task.id, status=task.status)

        outboxes = []
        payload = {
            "project": scrapy["project"],
            "spider": scrapy["spider"],
            "version": scrapy["version"],
            "settings": scrapy["settings"],
            "args": scrapy["args"],
            "task_type": "scrapy",
        }
        if scrapy["artifact"]:
            payload["artifact"] = scrapy["artifact"]
        for node in nodes:
            execution = svc.create_execution(ctx.session, task, node)
            outbox = create_run_outbox(
                ctx.session,
                # wire seam: execution_id = task id, attempt_id = execution id.
                execution_id=task.id,
                attempt_id=execution.id,
                agent_id=node.agent_id or "",
                payload=payload,
                manual=True,
            )
            svc.create_log_file(ctx.session, ctx.settings, task, execution)
            outboxes.append(outbox)

        # Single atomic commit: task + executions + outbox + log files.
        await ctx.session.commit()

        # Manual run: synchronous best-effort dispatch of each row.
        results = []
        for outbox in outboxes:
            results.append(
                await ctx.dispatcher.try_dispatch(
                    ctx.session, outbox, give_up_on_fail=True
                )
            )

        if not any(r.outcome == "sent" for r in results):
            # Redis fully unavailable: no command reached Redis.
            await self._fail_dispatch_unavailable(ctx.session, task)
            await ctx.session.commit()
            raise ApiError(
                503,
                "execution.dispatch_unavailable",
                "errors.dispatchUnavailable",
                {"task_id": task.id, "reason": DISPATCH_UNAVAILABLE},
            )

        # At least one command reached Redis. Persist the sent/failed marks.
        try:
            await ctx.session.commit()
        except Exception as exc:  # noqa: BLE001 - XADD done, sent-mark commit lost
            raise DispatchUnknownError(task.id) from exc

        # Task stays queued; agent's attempt.running converges it.
        return ExecutionRunResponse(task_id=task.id, status=task.status)

    async def _fail_dispatch_unavailable(self, session, task) -> None:
        now = datetime.now(UTC)
        task.status = states.TASK_FAILED
        task.started_at = task.started_at or now
        task.finished_at = now
        for execution in await svc.list_executions(session, task.id):
            if execution.status in states.EXEC_ACTIVE:
                execution.status = states.EXEC_FAILED
                execution.error_code = DISPATCH_UNAVAILABLE
                execution.finished_at = now
