"""Scrapy-via-scrapyd executor (phase 1.5).

Selects heartbeat-live scrapy-capable nodes, creates the execution + one attempt
per node + a per-attempt ``run`` command-outbox row + the ``execution_log_files``
index in ONE atomic PostgreSQL transaction, then synchronously dispatches each
``run`` command to the agent command stream:

- all XADDs succeed -> execution stays ``queued`` (the agent's ``attempt.running``
  event converges it to running; we do NOT optimistically mark running here);
- every XADD fails (Redis down) -> execution/attempts/outbox marked ``failed``
  ``dispatch_unavailable``, the API returns 503;
- XADD succeeded but the ``sent`` mark fails to commit -> 202 ``dispatch_unknown``
  (the command may already be running; never report "not delivered").

The agent then drives its local scrapyd; the event/log consumers + reconcile
loop take over. No server->agent HTTP.
"""

from __future__ import annotations

from datetime import UTC, datetime

from dopilot_protocol import ExecutionRunRequest, ExecutionRunResponse

from ..errors import ApiError
from ..nodes.service import select_target_nodes
from ..redis.dispatcher import DISPATCH_UNAVAILABLE
from ..services import executions as svc
from ..services import states
from ..services.outbox import create_run_outbox
from .base import BaseExecutor, DispatchUnknownError, ExecutorContext


class ScrapydExecutor(BaseExecutor):
    """Dispatches Scrapy jobs to agents over the Redis command stream."""

    task_type = "scrapy"

    async def run(
        self, request: ExecutionRunRequest, ctx: ExecutorContext
    ) -> ExecutionRunResponse:
        scrapy = svc.parse_scrapy_params(request)

        # Raises a structured 409 if no heartbeat-live scrapy node — BEFORE any
        # row is created, so we never leave a half-baked execution.
        nodes = await select_target_nodes(
            ctx.session,
            request.node_strategy,
            request.node_ids,
            timeout_seconds=ctx.settings.agents.heartbeat_timeout_seconds,
        )

        execution = svc.create_execution(ctx.session, request)
        outboxes = []
        payload = {
            "project": scrapy["project"],
            "spider": scrapy["spider"],
            "version": scrapy["version"],
            "settings": scrapy["settings"],
            "args": scrapy["args"],
            "task_type": "scrapy",
        }
        for node in nodes:
            attempt = svc.create_attempt(ctx.session, execution, node)
            outbox = create_run_outbox(
                ctx.session,
                execution_id=execution.id,
                attempt_id=attempt.id,
                agent_id=node.agent_id or "",
                payload=payload,
                manual=True,
            )
            svc.create_log_file(ctx.session, ctx.settings, execution, attempt)
            outboxes.append(outbox)

        # Single atomic commit: execution + attempts + outbox + log files.
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
            await self._fail_dispatch_unavailable(ctx.session, execution)
            await ctx.session.commit()
            raise ApiError(
                503,
                "execution.dispatch_unavailable",
                "errors.dispatchUnavailable",
                {"execution_id": execution.id, "reason": DISPATCH_UNAVAILABLE},
            )

        # At least one command reached Redis. Persist the sent/failed marks.
        try:
            await ctx.session.commit()
        except Exception as exc:  # noqa: BLE001 - XADD done, sent-mark commit lost
            raise DispatchUnknownError(execution.id) from exc

        # Execution stays queued; agent's attempt.running converges it.
        return ExecutionRunResponse(
            execution_id=execution.id, status=execution.status
        )

    async def _fail_dispatch_unavailable(self, session, execution) -> None:
        now = datetime.now(UTC)
        execution.status = states.EXEC_FAILED
        execution.started_at = execution.started_at or now
        execution.finished_at = now
        for attempt in await svc.list_attempts(session, execution.id):
            if attempt.status in states.ATTEMPT_ACTIVE:
                attempt.status = states.ATTEMPT_FAILED
                attempt.error_code = DISPATCH_UNAVAILABLE
                attempt.finished_at = now
