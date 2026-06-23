"""Task/execution orchestration helpers: creation, queries, and view builders.

Phase 1.7 domain vocabulary: a :class:`Task` is the parent logical run and an
:class:`Execution` is the atomic per-node unit (see ``models/execution.py``).

Naming (phase 2a clean-cut): the wire/disk/DB ids now match the domain — the
log-file index, command outbox and Redis payloads key on ``task_id`` (=
:class:`Task` id) and ``execution_id`` (= :class:`Execution` id), the same names
the public API/web already use. The public JSON uses Task for the parent run
(``TaskView`` with ``executions[]``) and Execution for the atomic per-node unit
(``ExecutionView`` with a ``task_id`` back-reference); there is no public
``attempts[]`` array.

Endpoints stay thin; the create/query/view logic lives here so it can be unit
tested directly against a session.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from dopilot_protocol import (
    ExecutionRunRequest,
    ScrapyCommandError,
    parse_scrapy_command,
)
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
    """Provenance of a task creation (phase 1.7 packet 2 / 1.8).

    ``source`` is one of :data:`states.TASK_SOURCES`. ``execution_template_id`` /
    ``schedule_id`` are NULL for a direct build-artifact run.
    ``template_snapshot`` is the resolved run snapshot (build artifact + params +
    node strategy/ids) that makes the task immutable against later template edits.
    """

    source: str = states.TASK_SOURCE_DIRECT
    execution_template_id: str | None = None
    schedule_id: str | None = None
    template_snapshot: dict[str, Any] = field(default_factory=dict)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def parse_scrapy_params(request: ExecutionRunRequest) -> dict[str, Any]:
    """Validate the command-first scrapy inputs carried in ``params``.

    Re-validates the ``command`` with the shared parser at the dispatch boundary
    (the server is authoritative) and requires the build-artifact ``artifact``
    context (project, since the command alone names no scrapyd project). Returns
    the ``command`` + ``artifact`` the Redis run payload carries plus the DERIVED
    ``spider`` (for ``Task.spider``). Raises a 400 ``ApiError`` on an invalid
    command or missing artifact context.
    """
    params = request.params or {}
    artifact = params.get("artifact") if isinstance(params.get("artifact"), dict) else None
    command = params.get("command")
    project = params.get("project") or (artifact or {}).get("project")
    try:
        parsed = parse_scrapy_command(command)
    except ScrapyCommandError as exc:
        raise ApiError(400, exc.code, exc.message_key, exc.detail) from exc
    if not project:
        raise ApiError(
            400,
            "execution.invalid_params",
            "errors.invalidParams",
            {"missing": ["project"]},
        )
    return {
        "command": str(command),
        "project": str(project),
        "spider": parsed.spider,
        "version": (
            str(params["version"])
            if params.get("version")
            else (str(artifact["version"]) if (artifact or {}).get("version") else None)
        ),
        "artifact": dict(artifact or {}),
    }


def parse_wheel_params(request: ExecutionRunRequest) -> dict[str, Any]:
    """Validate the Python-wheel run inputs carried in ``params`` (phase 2b).

    The wheel run is command-first: ``shell_command`` is a free-form shell
    command (NOT a ``scrapy crawl`` command) serialized to the agent payload, and
    ``artifact`` is the build-artifact fetch context the agent needs to download
    + install the wheel (``pip install --no-deps --target`` + PYTHONPATH, packet
    2b-2). ``env`` defaults to ``{}`` and ``working_dir`` to ``None``. Raises a
    400 on an empty command or a missing wheel fetch context. The server NEVER
    executes Python here.
    """
    params = request.params or {}
    artifact = (
        params.get("artifact") if isinstance(params.get("artifact"), dict) else None
    )
    shell_command = str(
        params.get("shell_command") or params.get("command") or ""
    ).strip()
    if not shell_command:
        raise ApiError(
            400,
            "execution.invalid_params",
            "errors.invalidParams",
            {"missing": ["shell_command"]},
        )
    if not artifact or not artifact.get("fetch_path"):
        raise ApiError(
            400,
            "execution.invalid_params",
            "errors.invalidParams",
            {"missing": ["artifact"]},
        )
    env = params.get("env") if isinstance(params.get("env"), dict) else {}
    working_dir = params.get("working_dir")
    return {
        "shell_command": shell_command,
        "artifact": dict(artifact),
        "env": {str(k): str(v) for k, v in (env or {}).items()},
        "working_dir": str(working_dir) if working_dir else None,
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
        artifact_type=request.artifact_type,
        target=request.target or "",
        node_strategy=request.node_strategy or "all",
        spider=str(spider) if spider else None,
        status=states.TASK_QUEUED,
        params=params,
        source=origin.source,
        execution_template_id=origin.execution_template_id,
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
    # Log path + index key on (task_id=task.id, execution_id=execution.id).
    path = files.log_path(
        settings.logs.root_dir, now, task.id, execution.id, stream
    )
    log_file = ExecutionLogFile(
        task_id=task.id,
        execution_id=execution.id,
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
            "task.not_found",
            "errors.taskNotFound",
            {"task_id": task_id},
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


def _task_build_artifact_id():
    """SQL expression for the task's build-artifact id (from the snapshot).

    The build artifact is frozen at task creation into
    ``template_snapshot["build_artifact"]`` (see :func:`resolve.resolve_run`); its
    ``id`` is the stable filter key. Indexing + ``.as_string()`` works on both the
    SQLite test DB (``json_extract``) and PostgreSQL JSONB. NULL for legacy/direct
    tasks that carry no snapshot.
    """
    return Task.template_snapshot["build_artifact"]["id"].as_string()


async def list_tasks_page(
    session: AsyncSession,
    *,
    page: int,
    page_size: int,
    spider: str | None = None,
    build_artifact_id: str | None = None,
    status: str | None = None,
) -> tuple[list[Task], int]:
    """Return one page of tasks (newest first) + the total matching count.

    The product filter is ``build_artifact_id`` (matched against the immutable
    snapshot build artifact), which works for scrapy and python_wheel alike.
    The legacy ``spider`` filter (indexed task-level column) is kept for
    compatibility. ``status`` filters by the task status column. All supplied
    filters AND together. Caller validates ``page`` / ``page_size`` / ``status``.
    """
    from sqlalchemy import func as _func

    base = select(Task)
    count_q = select(_func.count()).select_from(Task)
    if build_artifact_id:
        ba_expr = _task_build_artifact_id()
        base = base.where(ba_expr == build_artifact_id)
        count_q = count_q.where(ba_expr == build_artifact_id)
    if spider:
        base = base.where(Task.spider == spider)
        count_q = count_q.where(Task.spider == spider)
    if status:
        base = base.where(Task.status == status)
        count_q = count_q.where(Task.status == status)

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
    """Distinct non-null spider values across all tasks (legacy filter helper)."""
    rows = await session.execute(
        select(Task.spider).where(Task.spider.is_not(None)).distinct()
    )
    return sorted({s for (s,) in rows.all() if s})


def _build_artifact_label(
    name: str | None,
    version: str | None,
    distribution: str | None,
    project: str | None,
    artifact_id: str,
) -> str:
    """Human-readable label for a build artifact (scrapy or python_wheel)."""
    base = name or distribution or project or artifact_id
    return f"{base} ({version})" if version else str(base)


def build_artifact_option(
    *,
    id: str,
    name: str | None,
    artifact_type: str | None,
    version: str | None,
    distribution: str | None,
    project: str | None,
) -> dict[str, Any]:
    """The public build-artifact descriptor (filter option / per-task column).

    Carries id + name + artifact_type + version/distribution/project plus a
    derived human-readable ``label``.
    """
    return {
        "id": id,
        "name": name,
        "artifact_type": artifact_type,
        "version": version,
        "distribution": distribution,
        "project": project,
        "label": _build_artifact_label(name, version, distribution, project, id),
    }


def task_build_artifact(task: Task) -> dict[str, Any] | None:
    """The immutable build-artifact descriptor of a task, or None if absent.

    Reads ``template_snapshot["build_artifact"]`` (frozen at creation). Legacy /
    direct tasks created without a snapshot return None — no crash, no column.
    """
    ba = (task.template_snapshot or {}).get("build_artifact") or {}
    artifact_id = ba.get("id")
    if not artifact_id:
        return None
    return build_artifact_option(
        id=str(artifact_id),
        name=ba.get("name"),
        artifact_type=ba.get("artifact_type"),
        version=ba.get("version"),
        distribution=ba.get("distribution"),
        project=ba.get("project"),
    )


async def list_task_build_artifacts(
    session: AsyncSession,
) -> list[dict[str, Any]]:
    """Distinct build-artifact filter options derived from existing tasks.

    Reads the immutable snapshot fields directly in SQL (DISTINCT at the DB, no
    full-snapshot load), then dedupes by artifact id in Python and sorts by
    label. Tasks without a snapshot artifact contribute no option.
    """
    ba = Task.template_snapshot["build_artifact"]
    id_expr = ba["id"].as_string()
    rows = await session.execute(
        select(
            id_expr,
            ba["name"].as_string(),
            ba["artifact_type"].as_string(),
            ba["version"].as_string(),
            ba["distribution"].as_string(),
            ba["project"].as_string(),
        )
        .where(id_expr.is_not(None))
        .distinct()
    )
    options: dict[str, dict[str, Any]] = {}
    for artifact_id, name, artifact_type, version, distribution, project in rows.all():
        if not artifact_id or artifact_id in options:
            continue
        options[artifact_id] = build_artifact_option(
            id=str(artifact_id),
            name=name,
            artifact_type=artifact_type,
            version=version,
            distribution=distribution,
            project=project,
        )
    return sorted(
        options.values(), key=lambda o: ((o["label"] or "").lower(), o["id"])
    )


async def get_log_file(
    session: AsyncSession,
    task_id: str,
    execution_id: str,
    stream: str = "log",
) -> ExecutionLogFile | None:
    # task_id = Task.id, execution_id = Execution.id — they map straight onto the
    # ExecutionLogFile index columns.
    result = await session.execute(
        select(ExecutionLogFile).where(
            ExecutionLogFile.task_id == task_id,
            ExecutionLogFile.execution_id == execution_id,
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

    ``execution_id`` is the atomic :class:`Execution` id (web query param
    ``execution_id``), the same name used on the log index.
    """
    executions = await list_executions(session, task_id)
    if execution_id:
        for e in executions:
            if e.id == execution_id:
                return e
        raise ApiError(
            404,
            "task.execution_not_found",
            "errors.executionNotFound",
            {"task_id": task_id, "execution_id": execution_id},
        )
    chosen = primary_execution(executions)
    if chosen is None:
        raise ApiError(
            404,
            "task.execution_not_found",
            "errors.executionNotFound",
            {"task_id": task_id},
        )
    return chosen


# ---------------------------------------------------------------------------
# view builders (public Task/Execution JSON — phase 1.8 clean-cut)
# ---------------------------------------------------------------------------
# Public vocabulary: a parent run is a TASK (``TaskView`` with ``executions[]``);
# an atomic per-node row is an EXECUTION (``ExecutionView`` with a ``task_id``
# back-reference). The Redis/disk/agent ids use the same ``task_id`` /
# ``execution_id`` names internally.


def execution_view(execution: Execution) -> dict[str, Any]:
    """One atomic per-node execution as the public ``ExecutionView`` row."""
    return {
        "id": execution.id,
        "task_id": execution.task_id,
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
    """A task plus its atomic executions as the public ``TaskView``."""
    return {
        "id": task.id,
        "artifact_type": task.artifact_type,
        "target": task.target,
        "status": task.status,
        "status_reason": task.status_reason,
        "status_detail": task.status_detail or {},
        "node_strategy": task.node_strategy,
        "params": task.params or {},
        "build_artifact": (task.template_snapshot or {}).get("build_artifact") or {},
        "source": task.source,
        "execution_template_id": task.execution_template_id,
        "schedule_id": task.schedule_id,
        "created_at": _iso(task.created_at),
        "started_at": _iso(task.started_at),
        "finished_at": _iso(task.finished_at),
        "executions": [execution_view(e) for e in executions],
    }


def task_summary(task: Task, execution_count: int) -> dict[str, Any]:
    """Compact task row for the list view (public ``TaskSummary``)."""
    return {
        "id": task.id,
        "artifact_type": task.artifact_type,
        "target": task.target,
        "spider": task.spider,
        # The immutable build artifact (frozen snapshot) backs the list column +
        # the build-artifact filter; None for legacy/direct tasks (snapshot-less).
        "build_artifact": task_build_artifact(task),
        "status": task.status,
        "status_reason": task.status_reason,
        "node_strategy": task.node_strategy,
        "source": task.source,
        "execution_template_id": task.execution_template_id,
        "schedule_id": task.schedule_id,
        "created_at": _iso(task.created_at),
        "started_at": _iso(task.started_at),
        "finished_at": _iso(task.finished_at),
        "execution_count": execution_count,
    }
