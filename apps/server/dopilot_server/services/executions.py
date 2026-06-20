"""Task/execution orchestration helpers: creation, queries, and view builders.

Phase 1.7 domain vocabulary: a :class:`Task` is the parent logical run and an
:class:`Execution` is the atomic per-node unit (see ``models/execution.py``).

Two stable seams are crossed here and are documented at each call site:

- **Wire/disk/agent seam** — the log-file index, command outbox and Redis
  payloads still key on ``execution_id`` (= task id) and ``attempt_id``
  (= execution id). Functions touching those (``create_log_file`` /
  ``get_log_file``) keep the seam parameter names.
- **Public HTTP/web seam** — the web JSON shapes still call the parent
  ``execution`` (with ``attempts[]`` children) and an atomic row ``attempt``
  (with ``execution_id`` = the task id). The view builders below emit those
  frozen keys; the public/web clean-cut is a later packet. Error codes
  (``execution.*``) are likewise kept verbatim for the web i18n contract.

Endpoints stay thin; the create/query/view logic lives here so it can be unit
tested directly against a session.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from dopilot_protocol import ExecutionRunRequest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config.settings import Settings
from ..errors import ApiError
from ..logs import files
from ..models.execution import (
    Execution,
    ExecutionLogFile,
    Task,
)
from ..models.node import Node
from . import states


def new_id() -> str:
    return uuid.uuid4().hex


@dataclass
class TaskOrigin:
    """Provenance of a task creation (phase 1.7 packet 2).

    ``source`` is one of :data:`states.TASK_SOURCES`. ``template_id`` /
    ``schedule_id`` are NULL for an ad-hoc manual run. ``template_snapshot`` is
    the copied template payload that makes the task immutable against later
    template edits.
    """

    source: str = states.TASK_SOURCE_MANUAL
    template_id: str | None = None
    schedule_id: str | None = None
    template_snapshot: dict[str, Any] = field(default_factory=dict)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def parse_scrapy_params(request: ExecutionRunRequest) -> dict[str, Any]:
    """Validate + normalize the scrapy inputs carried in ``params``.

    Raises a 400 ``ApiError`` when project or spider is missing.
    """
    params = request.params or {}
    artifact = params.get("artifact") if isinstance(params.get("artifact"), dict) else None
    project = params.get("project") or (artifact or {}).get("project")
    spider = params.get("spider")
    missing = [k for k, v in (("project", project), ("spider", spider)) if not v]
    if missing:
        raise ApiError(
            400,
            "execution.invalid_params",
            "errors.invalidParams",
            {"missing": missing},
        )
    return {
        "project": str(project),
        "spider": str(spider),
        "version": (
            str(params["version"])
            if params.get("version")
            else (str(artifact["version"]) if (artifact or {}).get("version") else None)
        ),
        "settings": {str(k): str(v) for k, v in (params.get("settings") or {}).items()},
        "args": {str(k): str(v) for k, v in (params.get("args") or {}).items()},
        "artifact": dict(artifact or {}),
    }


def create_task(
    session: AsyncSession,
    request: ExecutionRunRequest,
    origin: TaskOrigin | None = None,
) -> Task:
    origin = origin or TaskOrigin()
    params = dict(request.params or {})
    # Phase 1.7.1: copy the spider onto the task row so the execution-list spider
    # filter can query it directly instead of scanning the params JSON.
    spider = params.get("spider")
    task = Task(
        id=new_id(),
        task_type=request.task_type,
        target=request.target or "",
        node_strategy=request.node_strategy or "all",
        spider=str(spider) if spider else None,
        status=states.TASK_QUEUED,
        params=params,
        source=origin.source,
        template_id=origin.template_id,
        schedule_id=origin.schedule_id,
        template_snapshot=dict(origin.template_snapshot or {}),
    )
    session.add(task)
    return task


def mark_no_target(
    task: Task, *, strategy: str, node_ids: list[str], healthy_count: int
) -> Task:
    """Set a freshly-created task terminal ``no_target`` (no healthy node).

    The task carries ZERO executions, so roll-up never applies (it would hang
    in ``queued`` forever). ``status_reason``/``status_detail`` carry the audit
    explanation — no fake execution, no task-events table (brief item 3).
    """
    now = datetime.now(UTC)
    task.status = states.TASK_NO_TARGET
    task.status_reason = states.TASK_NO_TARGET
    task.status_detail = {
        "node_strategy": strategy,
        "node_ids": list(node_ids or []),
        "healthy_count": healthy_count,
    }
    task.started_at = task.started_at or now
    task.finished_at = now
    return task


def create_execution(
    session: AsyncSession, task: Task, node: Node
) -> Execution:
    """Create one atomic execution of ``task`` on ``node``."""
    execution = Execution(
        id=new_id(),
        task_id=task.id,
        agent_id=node.agent_id,
        node_id=str(node.id) if node.id is not None else None,
        endpoint=node.endpoint,
        status=states.EXEC_PENDING,
        error_detail={},
    )
    session.add(execution)
    return execution


def create_log_file(
    session: AsyncSession,
    settings: Settings,
    task: Task,
    execution: Execution,
    stream: str = "log",
) -> ExecutionLogFile:
    now = datetime.now(UTC)
    # Wire/disk seam: the log path + index key on (execution_id=task.id,
    # attempt_id=execution.id). Do not rename these path components.
    path = files.log_path(
        settings.logs.root_dir, now, task.id, execution.id, stream
    )
    log_file = ExecutionLogFile(
        execution_id=task.id,
        attempt_id=execution.id,
        stream=stream,
        storage_path=path,
        size_bytes=0,
        last_pulled_offset=0,
        status=states.LOG_ACTIVE,
        started_at=now,
    )
    session.add(log_file)
    return log_file


# ---------------------------------------------------------------------------
# queries
# ---------------------------------------------------------------------------


async def get_task(session: AsyncSession, task_id: str) -> Task | None:
    result = await session.execute(select(Task).where(Task.id == task_id))
    return result.scalar_one_or_none()


async def get_task_or_404(session: AsyncSession, task_id: str) -> Task:
    task = await get_task(session, task_id)
    if task is None:
        raise ApiError(
            404,
            "execution.not_found",
            "errors.executionNotFound",
            {"execution_id": task_id},
        )
    return task


async def get_execution(
    session: AsyncSession, execution_id: str
) -> Execution | None:
    result = await session.execute(
        select(Execution).where(Execution.id == execution_id)
    )
    return result.scalar_one_or_none()


async def list_executions(
    session: AsyncSession, task_id: str
) -> list[Execution]:
    """The atomic executions of one task, oldest first."""
    result = await session.execute(
        select(Execution)
        .where(Execution.task_id == task_id)
        .order_by(Execution.created_at)
    )
    return list(result.scalars().all())


async def list_tasks(session: AsyncSession, limit: int = 200) -> list[Task]:
    result = await session.execute(
        select(Task).order_by(Task.created_at.desc()).limit(limit)
    )
    return list(result.scalars().all())


# Phase 1.7.1: execution history grows by tens of thousands of rows/day, so the
# list is server-side paginated. Allowed page sizes are fixed; the web picks the
# closest size from table height but may only request one of these.
ALLOWED_PAGE_SIZES = (5, 10, 20, 50, 100)


async def list_tasks_page(
    session: AsyncSession,
    *,
    page: int,
    page_size: int,
    spider: str | None = None,
) -> tuple[list[Task], int]:
    """Return one page of tasks (newest first) + the total matching count.

    Optional ``spider`` filters on the indexed task-level ``spider`` column.
    Caller validates ``page`` / ``page_size`` (see :func:`validate_page`).
    """
    from sqlalchemy import func as _func

    base = select(Task)
    count_q = select(_func.count()).select_from(Task)
    if spider:
        base = base.where(Task.spider == spider)
        count_q = count_q.where(Task.spider == spider)

    total = int((await session.execute(count_q)).scalar_one())
    rows = await session.execute(
        base.order_by(Task.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return list(rows.scalars().all()), total


async def child_execution_counts(
    session: AsyncSession, task_ids: list[str]
) -> dict[str, int]:
    """Map ``task_id -> child execution count`` in ONE aggregate query.

    Avoids the per-row N+1 (one ``COUNT`` per task) the old list path incurred.
    Returns 0 for tasks with no executions (absent from the grouped result).
    """
    from sqlalchemy import func as _func

    if not task_ids:
        return {}
    rows = await session.execute(
        select(Execution.task_id, _func.count(Execution.id))
        .where(Execution.task_id.in_(task_ids))
        .group_by(Execution.task_id)
    )
    counts = {task_id: int(n) for task_id, n in rows.all()}
    return {tid: counts.get(tid, 0) for tid in task_ids}


async def list_task_spiders(session: AsyncSession) -> list[str]:
    """Distinct non-null spider values across all tasks, for the filter dropdown."""
    rows = await session.execute(
        select(Task.spider).where(Task.spider.is_not(None)).distinct()
    )
    return sorted({s for (s,) in rows.all() if s})


async def get_log_file(
    session: AsyncSession,
    execution_id: str,
    attempt_id: str,
    stream: str = "log",
) -> ExecutionLogFile | None:
    # Wire/disk seam parameters: execution_id = task id, attempt_id = execution
    # id. They map straight onto the ExecutionLogFile seam columns.
    result = await session.execute(
        select(ExecutionLogFile).where(
            ExecutionLogFile.execution_id == execution_id,
            ExecutionLogFile.attempt_id == attempt_id,
            ExecutionLogFile.stream == stream,
        )
    )
    return result.scalar_one_or_none()


def primary_execution(
    executions: list[Execution],
) -> Execution | None:
    """Default execution for log endpoints when none is specified."""
    return executions[0] if executions else None


async def resolve_execution(
    session: AsyncSession, task_id: str, execution_id: str | None
) -> Execution:
    """Resolve a task's atomic execution by id (or the primary one).

    ``execution_id`` is the atomic id (the web query param ``attempt_id``).
    """
    executions = await list_executions(session, task_id)
    if execution_id:
        for e in executions:
            if e.id == execution_id:
                return e
        raise ApiError(
            404,
            "execution.attempt_not_found",
            "errors.attemptNotFound",
            {"execution_id": task_id, "attempt_id": execution_id},
        )
    chosen = primary_execution(executions)
    if chosen is None:
        raise ApiError(
            404,
            "execution.attempt_not_found",
            "errors.attemptNotFound",
            {"execution_id": task_id},
        )
    return chosen


# ---------------------------------------------------------------------------
# view builders (frozen web-facing JSON)
# ---------------------------------------------------------------------------
# Public/web seam: keys stay in the phase-1.5 web vocabulary (a parent run is an
# "execution" with ``attempts[]``; an atomic row is an "attempt" whose
# ``execution_id`` is the parent task id). The web clean-cut is a later packet.


def execution_view(execution: Execution) -> dict[str, Any]:
    """One atomic execution as the frozen web ``attempt`` row."""
    return {
        "id": execution.id,
        "execution_id": execution.task_id,  # web seam: parent task id
        "agent_id": execution.agent_id,
        "node_id": execution.node_id,
        "endpoint": execution.endpoint,
        "remote_job_id": execution.remote_job_id,
        "status": execution.status,
        "started_at": _iso(execution.started_at),
        "finished_at": _iso(execution.finished_at),
        "exit_code": execution.exit_code,
        "error_code": execution.error_code,
        "error_detail": execution.error_detail or {},
    }


def task_view(task: Task, executions: list[Execution]) -> dict[str, Any]:
    """A task plus its atomic executions as the frozen web ``execution`` view."""
    return {
        "id": task.id,
        "task_type": task.task_type,
        "target": task.target,
        "status": task.status,
        "status_reason": task.status_reason,
        "status_detail": task.status_detail or {},
        "node_strategy": task.node_strategy,
        "params": task.params or {},
        "source": task.source,
        "template_id": task.template_id,
        "schedule_id": task.schedule_id,
        "created_at": _iso(task.created_at),
        "started_at": _iso(task.started_at),
        "finished_at": _iso(task.finished_at),
        "attempts": [execution_view(e) for e in executions],
    }


def task_summary(task: Task, execution_count: int) -> dict[str, Any]:
    """Compact task row for the list view (web ``execution`` summary)."""
    return {
        "id": task.id,
        "task_type": task.task_type,
        "target": task.target,
        "spider": task.spider,
        "status": task.status,
        "status_reason": task.status_reason,
        "node_strategy": task.node_strategy,
        "source": task.source,
        "template_id": task.template_id,
        "schedule_id": task.schedule_id,
        "created_at": _iso(task.created_at),
        "started_at": _iso(task.started_at),
        "finished_at": _iso(task.finished_at),
        "attempt_count": execution_count,
    }
