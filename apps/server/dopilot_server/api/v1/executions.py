"""Execution endpoints: run, list, detail, cancel, log snapshot + SSE stream."""

from __future__ import annotations

import asyncio
import json
import time
from datetime import UTC, datetime

from dopilot_protocol import ExecutionRunRequest, ExecutionRunResponse
from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ...auth.dependencies import AdminContext, get_current_admin
from ...config.loader import get_settings
from ...config.settings import Settings
from ...db.engine import get_session
from ...errors import ApiError
from ...executors.base import DispatchUnknownError, ExecutorContext
from ...executors.registry import get_executor
from ...logs import files
from ...logs.sse import CLOSE, SubscriptionManager, get_subscriptions
from ...logs.stream_token import issue_stream_token, verify_stream_token
from ...redis.dispatcher import CommandDispatcher
from ...services import executions as svc
from ...services import states
from ...services.cancel import request_cancel
from .schemas import (
    ExecutionsResponse,
    ExecutionSummary,
    ExecutionView,
    LogSnapshot,
    StreamTokenResponse,
)

router = APIRouter(tags=["executions"])


def get_request_sessionmaker(request: Request) -> async_sessionmaker[AsyncSession]:
    """Return the app's request sessionmaker for short-lived preflight sessions.

    Used by the SSE endpoint so it can open and CLOSE a session before streaming
    (a long-lived ``Depends(get_session)`` would pin a pool connection for the
    whole stream). Overridable in tests.
    """
    maker = getattr(request.app.state, "sessionmaker", None)
    if maker is None:  # pragma: no cover - set by create_app/lifespan or tests
        raise ApiError(
            500, "server.sessionmaker_unconfigured", "errors.internal", {}
        )
    return maker


def get_dispatcher(request: Request) -> CommandDispatcher:
    """Return the app-wide command dispatcher (built in the lifespan).

    Tests override this with a dispatcher wrapping a fake Redis client.
    """
    dispatcher = getattr(request.app.state, "command_dispatcher", None)
    if dispatcher is None:
        raise ApiError(
            503,
            "execution.dispatcher_unavailable",
            "errors.dispatcherUnavailable",
            {},
        )
    return dispatcher

_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",  # disable proxy buffering for SSE
}
_SSE_HEARTBEAT_SECONDS = 15.0
_SSE_MAX_LIFETIME_SECONDS = 1800.0  # 30 min connection cap


@router.post("/executions/run", response_model=ExecutionRunResponse)
async def run_execution(
    body: ExecutionRunRequest,
    response: Response,
    _admin: AdminContext = Depends(get_current_admin),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
    dispatcher: CommandDispatcher = Depends(get_dispatcher),
) -> ExecutionRunResponse:
    """Resolve the executor and dispatch a run over the Redis command stream.

    Returns 200 (execution ``queued``, command dispatched), 503
    ``dispatch_unavailable`` (Redis down), or 202 ``dispatch_unknown`` (command
    XADDed but the sent-mark commit was lost — convergence via the running event).
    """
    executor = get_executor(body.task_type)
    ctx = ExecutorContext(
        session=session, settings=settings, dispatcher=dispatcher
    )
    try:
        return await executor.run(body, ctx)
    except DispatchUnknownError as exc:
        response.status_code = 202
        return ExecutionRunResponse(execution_id=exc.execution_id, status="queued")


@router.get("/executions", response_model=ExecutionsResponse)
async def list_executions(
    _admin: AdminContext = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
) -> ExecutionsResponse:
    tasks = await svc.list_tasks(session)
    summaries: list[ExecutionSummary] = []
    for task in tasks:
        executions = await svc.list_executions(session, task.id)
        summaries.append(
            ExecutionSummary(**svc.task_summary(task, len(executions)))
        )
    return ExecutionsResponse(executions=summaries)


@router.get("/executions/{execution_id}", response_model=ExecutionView)
async def get_execution(
    execution_id: str,
    _admin: AdminContext = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
) -> ExecutionView:
    # Web seam: the route's ``execution_id`` is the parent (task) id.
    task = await svc.get_task_or_404(session, execution_id)
    executions = await svc.list_executions(session, execution_id)
    return ExecutionView(**svc.task_view(task, executions))


@router.post("/executions/{execution_id}/cancel", response_model=ExecutionView)
async def cancel_execution(
    execution_id: str,
    _admin: AdminContext = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
    dispatcher: CommandDispatcher = Depends(get_dispatcher),
) -> ExecutionView:
    """Request cancel: CAS unsent commands + send stop(intent=cancel) to agents.

    Convergence to ``canceled`` is asynchronous (the agent's ``attempt.canceled``
    events roll the execution up), so the returned view may still show an active
    status.
    """
    task = await svc.get_task_or_404(session, execution_id)
    if task.status not in states.TASK_TERMINAL:
        await request_cancel(session, dispatcher, task)
        task = await svc.get_task_or_404(session, execution_id)
    executions = await svc.list_executions(session, execution_id)
    return ExecutionView(**svc.task_view(task, executions))


@router.get("/executions/{execution_id}/logs", response_model=LogSnapshot)
async def get_logs(
    execution_id: str,
    attempt_id: str | None = Query(default=None),
    stream: str = Query(default="log"),
    offset: int = Query(default=0, ge=0),
    max_bytes: int | None = Query(default=None, ge=1),
    _admin: AdminContext = Depends(get_current_admin),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> LogSnapshot:
    await svc.get_task_or_404(session, execution_id)
    execution = await svc.resolve_execution(session, execution_id, attempt_id)
    log_file = await svc.get_log_file(session, execution_id, execution.id, stream)
    cap = max_bytes or settings.logs.max_tail_bytes_per_pull
    finished = execution.status in states.EXEC_TERMINAL
    if log_file is None:
        return LogSnapshot(
            execution_id=execution_id,
            attempt_id=execution.id,
            stream=stream,
            start_offset=offset,
            end_offset=offset,
            content="",
            status=states.LOG_MISSING,
            finished=finished,
        )
    start, end, content = files.read_slice(log_file.storage_path, offset, cap)
    return LogSnapshot(
        execution_id=execution_id,
        attempt_id=execution.id,
        stream=stream,
        start_offset=start,
        end_offset=end,
        content=content,
        status=log_file.status,
        finished=finished or log_file.status == states.LOG_COMPLETE,
    )


@router.post(
    "/executions/{execution_id}/logs/stream-token",
    response_model=StreamTokenResponse,
)
async def issue_log_stream_token(
    execution_id: str,
    _admin: AdminContext = Depends(get_current_admin),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> StreamTokenResponse:
    """Exchange the admin bearer for a short-lived SSE connect token.

    Only meaningful when web auth is ON (EventSource cannot send a bearer). When
    auth is OFF the SSE endpoint needs no token, so this returns 400.
    """
    if not settings.auth.enabled:
        raise ApiError(
            400,
            "auth.stream_token_not_required",
            "errors.streamTokenNotRequired",
            {},
        )
    await svc.get_task_or_404(session, execution_id)
    token, exp = issue_stream_token(
        settings.auth.token_secret or "",
        execution_id,
        settings.auth.stream_token_ttl_seconds,
    )
    return StreamTokenResponse(
        stream_token=token,
        expires_at=datetime.fromtimestamp(exp, UTC).isoformat(),
    )


def _sse_event(event: str, data: dict, *, event_id: int | None = None) -> str:
    lines = []
    if event_id is not None:
        lines.append(f"id: {event_id}")
    lines.append(f"event: {event}")
    lines.append(f"data: {json.dumps(data, ensure_ascii=False)}")
    return "\n".join(lines) + "\n\n"


@router.get("/executions/{execution_id}/logs/stream")
async def stream_logs(
    execution_id: str,
    request: Request,
    attempt_id: str | None = Query(default=None),
    stream: str = Query(default="log"),
    stream_token: str | None = Query(default=None),
    settings: Settings = Depends(get_settings),
    sessionmaker: async_sessionmaker[AsyncSession] = Depends(
        get_request_sessionmaker
    ),
    manager: SubscriptionManager = Depends(get_subscriptions),
) -> StreamingResponse:
    """Realtime log stream (server->web SSE).

    Auth: when web auth is ON, a valid short-lived ``stream_token`` (bound to
    this execution) is required because ``EventSource`` cannot send a bearer.
    Reconnect: the browser sends ``Last-Event-ID`` (the last server-file
    offset); the server backfills from there. Multiple windows on the same
    execution share one pull loop + this fan-out.

    The preflight lookups run in a SHORT-LIVED session that is closed before the
    (possibly 30-min) stream starts, so the stream never pins a pooled DB
    connection; the generator below touches only the on-disk file + the
    in-memory SSE queue, never the DB.
    """
    if settings.auth.enabled and not (
        stream_token
        and verify_stream_token(
            settings.auth.token_secret or "", stream_token, execution_id
        )
    ):
        raise ApiError(401, "auth.stream_unauthorized", "errors.unauthorized", {})

    async with sessionmaker() as session:
        task = await svc.get_task_or_404(session, execution_id)
        execution = await svc.resolve_execution(session, execution_id, attempt_id)
        log_file = await svc.get_log_file(
            session, execution_id, execution.id, stream
        )
        path = log_file.storage_path if log_file is not None else None
        already_terminal = task.status in states.TASK_TERMINAL
        exec_status = task.status

    last_event_id = request.headers.get("last-event-id")
    try:
        resume_from = int(last_event_id) if last_event_id else None
    except ValueError:
        resume_from = None

    async def generator():
        # Subscribe BEFORE backfilling so nothing produced during backfill is
        # lost; dedup forwarded events by server-file offset.
        queue = manager.subscribe(execution_id)
        cursor = 0
        try:
            if path is not None:
                if resume_from is not None:
                    cursor = resume_from
                else:
                    # first screen: last N lines / M bytes.
                    s, e, text = files.tail_screen(
                        path,
                        settings.logs.first_screen_max_lines,
                        settings.logs.first_screen_max_bytes,
                    )
                    if text:
                        yield _sse_event(
                            "log",
                            {"start_offset": s, "end_offset": e, "content": text},
                            event_id=e,
                        )
                    cursor = e
                # backfill any bytes between cursor and current size.
                size_now = files.size(path)
                while cursor < size_now:
                    s, e, text = files.read_slice(
                        path, cursor, settings.logs.max_tail_bytes_per_pull
                    )
                    if e <= cursor:
                        break
                    yield _sse_event(
                        "log",
                        {"start_offset": s, "end_offset": e, "content": text},
                        event_id=e,
                    )
                    cursor = e

            if already_terminal and (path is None or cursor >= files.size(path)):
                yield _sse_event("complete", {"status": exec_status})
                return

            deadline = time.monotonic() + _SSE_MAX_LIFETIME_SECONDS
            while True:
                if await request.is_disconnected():
                    return
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return
                try:
                    item = await asyncio.wait_for(
                        queue.get(),
                        timeout=min(_SSE_HEARTBEAT_SECONDS, remaining),
                    )
                except TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                if item is CLOSE:
                    return
                if item.get("type") == "complete":
                    yield _sse_event("complete", {"status": item.get("status")})
                    return
                # log event: dedup against backfilled cursor.
                end = int(item.get("end_offset", 0))
                if end <= cursor:
                    continue
                yield _sse_event(
                    "log",
                    {
                        "start_offset": int(item.get("start_offset", cursor)),
                        "end_offset": end,
                        "content": item.get("content", ""),
                    },
                    event_id=end,
                )
                cursor = end
        finally:
            manager.unsubscribe(execution_id, queue)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )
