"""Python-wheel shell-command executor (phase 2b packet 1).

Dispatch-only: this executor mirrors :class:`ScrapydExecutor`'s
transaction/outbox shape exactly — it selects heartbeat-live ``script``-capable
nodes, creates the task + one atomic execution per node + a per-execution ``run``
command-outbox row + the ``execution_log_files`` index in ONE atomic PostgreSQL
transaction, then synchronously best-effort dispatches each ``run`` command to
the agent command stream as a :class:`PythonWheelRunPayload` carrying
``task_type="python_wheel"``.

It NEVER runs Python on the server: the agent downloads + installs the wheel
(``pip install --no-deps --target`` + ``PYTHONPATH``) and launches the shell
command in packet 2b-2. The capability the target node must advertise is
``script`` (``states.ARTIFACT_CAPABILITY["python_wheel"]``), deliberately
distinct from the wire runner discriminator ``python_wheel``.
"""

from __future__ import annotations

from datetime import UTC, datetime

from dopilot_protocol import (
    ExecutionRunRequest,
    ExecutionRunResponse,
    PythonWheelRunPayload,
)

from ..errors import ApiError
from ..nodes.service import resolve_target_nodes
from ..redis.dispatcher import DISPATCH_UNAVAILABLE
from ..services import executions as svc
from ..services import states
from ..services.executions import TaskOrigin
from ..services.outbox import create_run_outbox
from .base import BaseExecutor, DispatchUnknownError, ExecutorContext


class PythonWheelExecutor(BaseExecutor):
    """Dispatches Python-wheel shell-command jobs over the Redis command stream."""

    artifact_type = "python_wheel"

    async def run(
        self,
        request: ExecutionRunRequest,
        ctx: ExecutorContext,
        origin: TaskOrigin | None = None,
    ) -> ExecutionRunResponse:
        wheel = svc.parse_wheel_params(request)

        # Create the task FIRST, then select healthy nodes. Zero healthy nodes
        # short-circuits into a persisted terminal ``no_target`` task (mirrors
        # the Scrapy executor) — no 409 raised here.
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
        for node in nodes:
            execution = svc.create_execution(ctx.session, task, node)
            # Command-first wheel payload: the agent fetches + installs the wheel
            # from ``artifact`` and runs ``shell_command`` (packet 2b-2). Runtime
            # context is per concrete execution, so it is built after
            # ``create_execution`` and inside the per-node loop.
            payload = PythonWheelRunPayload(
                shell_command=wheel["shell_command"],
                artifact=wheel["artifact"],
                env=wheel["env"],
                working_dir=wheel["working_dir"],
                runtime_context=svc.runtime_context_for(
                    task=task,
                    execution=execution,
                    artifact_type=self.artifact_type,
                    task_type="python_wheel",
                ),
            ).model_dump()
            outbox = create_run_outbox(
                ctx.session,
                task_id=task.id,
                execution_id=execution.id,
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
            await self._fail_dispatch_unavailable(ctx.session, task)
            await ctx.session.commit()
            raise ApiError(
                503,
                "execution.dispatch_unavailable",
                "errors.dispatchUnavailable",
                {"task_id": task.id, "reason": DISPATCH_UNAVAILABLE},
            )

        try:
            await ctx.session.commit()
        except Exception as exc:  # noqa: BLE001 - XADD done, sent-mark commit lost
            raise DispatchUnknownError(task.id) from exc

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
