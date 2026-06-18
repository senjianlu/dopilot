"""Reconcile operations: pull logs, poll status, finalize, cancel, mark lost.

These are the testable building blocks the background loop (:mod:`.loop`) and
the cancel endpoint call. Each takes an explicit session + agent client +
subscription manager so it can be unit/integration tested directly (no live
agent, no running loop).

Offset model (decision #11): the AGENT byte offset (``last_pulled_offset``) is
authoritative for the next pull; the SERVER file uses its own offset space
(``size_bytes``) for SSE event ids and snapshot reads, because the agent returns
decoded text whose re-encoded length need not equal its raw byte range. Bytes
are written to disk BEFORE the DB offset advances, so a crash yields at-most a
duplicate (never a gap).
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime

from dopilot_protocol import (
    AgentStatusResponse,
    AgentStopRequest,
    AttemptStatus,
    LogStream,
    TailRequest,
)
from sqlalchemy.ext.asyncio import AsyncSession

from ..clients.agent import AgentClient, AgentResponseError, AgentUnreachableError
from ..config.settings import Settings
from ..models.execution import Execution, ExecutionAttempt, ExecutionLogFile
from ..services import executions as svc
from ..services import states
from . import files
from .sse import SubscriptionManager


def _now() -> datetime:
    return datetime.now(UTC)


async def drain_attempt(
    session: AsyncSession,
    settings: Settings,
    agent_client: AgentClient,
    manager: SubscriptionManager,
    attempt: ExecutionAttempt,
    log_file: ExecutionLogFile,
) -> tuple[int, bool, bool]:
    """Pull one tail chunk, append to disk, advance offset, publish to SSE.

    Returns ``(bytes_written, eof, finished)``. Raises
    :class:`AgentUnreachableError` to the caller (lost handling lives there).
    """
    if log_file.status in (states.LOG_MISSING, states.LOG_EXPIRED):
        return 0, True, True
    req = TailRequest(
        execution_id=attempt.execution_id,
        attempt_id=attempt.id,
        stream=LogStream.log,
        offset=log_file.last_pulled_offset,
        max_bytes=settings.logs.max_tail_bytes_per_pull,
    )
    try:
        resp = await agent_client.tail(attempt.endpoint or "", req)
    except AgentResponseError as exc:
        if "attempt_not_found" in str(exc.body.get("code", "")):
            # agent already cleaned this attempt's log -> mark missing.
            log_file.status = states.LOG_MISSING
            log_file.final_offset = log_file.size_bytes
            await session.commit()
            return 0, True, True
        raise

    content_bytes = resp.content.encode("utf-8")
    start_server = log_file.size_bytes
    if content_bytes:
        # write_increment is offset-idempotent: replaying the same range after a
        # lost DB commit (file written, offset not advanced) is a no-op, so a
        # crash yields at-most-a-duplicate -> here, zero duplicates.
        try:
            log_file.size_bytes = files.write_increment(
                log_file.storage_path, start_server, content_bytes
            )
        except files.LogGapError:
            # on-disk file is shorter than our offset (truncated/lost).
            log_file.status = states.LOG_MISSING
            log_file.final_offset = log_file.size_bytes
            await session.commit()
            return 0, True, True
    # advance the AGENT-space offset to the agent's authoritative end.
    log_file.last_pulled_offset = resp.end_offset
    await session.commit()

    if content_bytes:
        manager.publish(
            attempt.execution_id,
            {
                "type": "log",
                "start_offset": start_server,
                "end_offset": log_file.size_bytes,
                "content": resp.content,
            },
        )
    return len(content_bytes), resp.eof, resp.finished


async def poll_attempt_status(
    agent_client: AgentClient, attempt: ExecutionAttempt
) -> AgentStatusResponse | None:
    """Poll the agent for an attempt's status.

    Returns ``None`` when the agent is unreachable (transient). An agent that
    answers but cannot resolve the attempt yields ``status=unknown``.
    """
    try:
        return await agent_client.status(
            attempt.endpoint or "", attempt.execution_id, attempt.id
        )
    except AgentUnreachableError:
        return None
    except AgentResponseError:
        return AgentStatusResponse(
            execution_id=attempt.execution_id,
            attempt_id=attempt.id,
            status=AttemptStatus.unknown,
        )


async def _maybe_complete_execution(
    session: AsyncSession,
    manager: SubscriptionManager,
    execution_id: str,
) -> bool:
    """If all attempts are terminal, roll the execution up to its terminal.

    Returns True when the execution became terminal (so the caller can emit the
    SSE ``complete`` event and close subscribers).
    """
    execution = await svc.get_execution(session, execution_id)
    if execution is None or execution.status in states.EXEC_TERMINAL:
        return execution is not None and execution.status in states.EXEC_TERMINAL
    attempts = await svc.list_attempts(session, execution_id)
    rolled = states.rollup_execution_status([a.status for a in attempts])
    if rolled is None:
        return False
    execution.status = rolled
    execution.finished_at = _now()
    await session.commit()
    return True


def _emit_complete(manager: SubscriptionManager, execution: Execution) -> None:
    manager.publish(
        execution.id,
        {"type": "complete", "status": execution.status},
    )
    manager.close(execution.id)


async def finalize_attempt(
    session: AsyncSession,
    settings: Settings,
    agent_client: AgentClient,
    manager: SubscriptionManager,
    attempt: ExecutionAttempt,
    target_status: str,
    *,
    exit_code: int | None = None,
    poll_step: float | None = None,
    sleep=asyncio.sleep,
    clock=time.monotonic,
) -> None:
    """Final-drain an attempt's log then mark it (and maybe the execution) done.

    Drains until EOF is stable for ``eof_stable_seconds`` or
    ``final_drain_hard_timeout_seconds`` elapses, whichever comes first.
    """
    log_file = await svc.get_log_file(
        session, attempt.execution_id, attempt.id
    )
    execution = await svc.get_execution(session, attempt.execution_id)
    if execution is not None and execution.status == states.EXEC_RUNNING:
        execution.status = states.EXEC_FINALIZING
    if log_file is not None and log_file.status == states.LOG_ACTIVE:
        log_file.status = states.LOG_FINALIZING
    await session.commit()

    step = poll_step
    if step is None:
        step = min(max(settings.logs.realtime_drain_interval_seconds, 0.05), 1.0)
    eof_stable = settings.logs.eof_stable_seconds
    deadline = clock() + settings.logs.final_drain_hard_timeout_seconds
    stable_since: float | None = None

    if log_file is not None:
        while clock() < deadline:
            try:
                pulled, eof, _finished = await drain_attempt(
                    session, settings, agent_client, manager, attempt, log_file
                )
            except AgentUnreachableError:
                break
            if pulled > 0:
                stable_since = None
            elif eof:
                if stable_since is None:
                    stable_since = clock()
                elif clock() - stable_since >= eof_stable:
                    break
            await sleep(step)

    now = _now()
    if log_file is not None:
        if log_file.status != states.LOG_MISSING:
            log_file.status = states.LOG_COMPLETE
        log_file.final_offset = log_file.size_bytes
        log_file.finished_at = now
    attempt.status = target_status
    attempt.finished_at = now
    if exit_code is not None:
        attempt.exit_code = exit_code
    await session.commit()

    # best-effort cleanup of the agent-side job.log (only after final drain).
    try:
        await agent_client.cleanup(
            attempt.endpoint or "", attempt.id, attempt.execution_id
        )
    except (AgentUnreachableError, AgentResponseError):
        pass

    if await _maybe_complete_execution(session, manager, attempt.execution_id):
        execution = await svc.get_execution(session, attempt.execution_id)
        if execution is not None:
            _emit_complete(manager, execution)


async def mark_attempt_lost(
    session: AsyncSession,
    manager: SubscriptionManager,
    attempt: ExecutionAttempt,
    reason: str,
) -> None:
    """Declare an attempt ``lost`` (agent unreachable too long / state gone)."""
    log_file = await svc.get_log_file(
        session, attempt.execution_id, attempt.id
    )
    now = _now()
    attempt.status = states.ATTEMPT_LOST
    attempt.finished_at = now
    attempt.error_code = "agent.lost"
    attempt.error_detail = {"reason": reason}
    if log_file is not None and log_file.status in (
        states.LOG_ACTIVE,
        states.LOG_FINALIZING,
    ):
        log_file.status = states.LOG_MISSING
        log_file.final_offset = log_file.size_bytes
        log_file.finished_at = now
    await session.commit()
    if await _maybe_complete_execution(session, manager, attempt.execution_id):
        execution = await svc.get_execution(session, attempt.execution_id)
        if execution is not None:
            _emit_complete(manager, execution)


async def cancel_execution(
    session: AsyncSession,
    settings: Settings,
    agent_client: AgentClient,
    manager: SubscriptionManager,
    execution: Execution,
    *,
    poll_step: float | None = None,
    sleep=asyncio.sleep,
    clock=time.monotonic,
) -> None:
    """Stop every active attempt of ``execution`` and finalize as canceled."""
    attempts = await svc.list_attempts(session, execution.id)
    for attempt in attempts:
        if attempt.status not in states.ATTEMPT_ACTIVE:
            continue
        try:
            await agent_client.stop(
                attempt.endpoint or "",
                AgentStopRequest(
                    execution_id=execution.id, attempt_id=attempt.id
                ),
            )
        except (AgentUnreachableError, AgentResponseError):
            # Stop is best-effort/idempotent; still finalize as canceled.
            pass
        await finalize_attempt(
            session,
            settings,
            agent_client,
            manager,
            attempt,
            states.ATTEMPT_CANCELED,
            poll_step=poll_step,
            sleep=sleep,
            clock=clock,
        )
