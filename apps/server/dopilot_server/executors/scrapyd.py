"""Scrapy-via-scrapyd executor (phase 1).

Selects healthy scrapy-capable nodes, creates the execution + one attempt per
node, dispatches each to its agent ``POST /run``, and records the remote
scrapyd job id and the initial ``execution_log_files`` row. The reconcile loop
takes over from there (log pull + status -> finalize -> complete).
"""

from __future__ import annotations

from datetime import UTC, datetime

from dopilot_protocol import (
    AgentRunRequest,
    AttemptStatus,
    ExecutionRunRequest,
    ExecutionRunResponse,
)

from ..clients.agent import AgentResponseError, AgentUnreachableError
from ..nodes.service import select_target_nodes
from ..services import executions as svc
from ..services import states
from .base import BaseExecutor, ExecutorContext


class ScrapydExecutor(BaseExecutor):
    """Dispatches Scrapy jobs to agents (which drive their local scrapyd)."""

    task_type = "scrapy"

    async def run(
        self, request: ExecutionRunRequest, ctx: ExecutorContext
    ) -> ExecutionRunResponse:
        scrapy = svc.parse_scrapy_params(request)

        # Raises a structured 409 if no healthy scrapy node — BEFORE any row is
        # created, so we never leave a half-baked running execution.
        nodes = await select_target_nodes(
            ctx.session, request.node_strategy, request.node_ids
        )

        execution = svc.create_execution(ctx.session, request)
        now = datetime.now(UTC)
        attempts = []
        any_running = False

        for node in nodes:
            attempt = svc.create_attempt(ctx.session, execution, node)
            attempts.append(attempt)
            run_req = AgentRunRequest(
                execution_id=execution.id,
                attempt_id=attempt.id,
                project=scrapy["project"],
                spider=scrapy["spider"],
                version=scrapy["version"],
                settings=scrapy["settings"],
                args=scrapy["args"],
            )
            try:
                resp = await ctx.agent_client.run(node.endpoint, run_req)
            except (AgentUnreachableError, AgentResponseError) as exc:
                err = exc.to_api_error()
                attempt.status = states.ATTEMPT_FAILED
                attempt.error_code = err.code
                attempt.error_detail = err.detail
                attempt.started_at = now
                attempt.finished_at = now
                continue

            attempt.remote_job_id = resp.remote_job_id
            # ``unknown`` maps to None in AGENT_TO_ATTEMPT, so use ``or`` (not a
            # dict default) to avoid ever writing a NULL attempt.status.
            mapped = (
                states.ATTEMPT_RUNNING
                if resp.status in (AttemptStatus.running, AttemptStatus.pending)
                else (states.AGENT_TO_ATTEMPT.get(resp.status) or states.ATTEMPT_RUNNING)
            )
            attempt.status = mapped
            attempt.started_at = now
            svc.create_log_file(ctx.session, ctx.settings, execution, attempt)
            if mapped in states.ATTEMPT_TERMINAL:
                # rare: agent reports the job already terminal at /run time.
                attempt.finished_at = now
            else:
                any_running = True

        if any_running:
            execution.status = states.EXEC_RUNNING
            execution.started_at = now
        else:
            # every attempt is already terminal (immediate finish or all failed):
            # roll up to the correct terminal so the execution never sticks.
            execution.status = (
                states.rollup_execution_status([a.status for a in attempts])
                or states.EXEC_FAILED
            )
            execution.started_at = now
            execution.finished_at = now

        await ctx.session.commit()
        return ExecutionRunResponse(
            execution_id=execution.id, status=execution.status
        )
