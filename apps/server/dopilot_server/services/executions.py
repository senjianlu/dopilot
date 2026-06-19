"""Execution orchestration helpers: creation, queries, and view builders.

Endpoints stay thin; the create/query/view logic lives here so it can be unit
tested directly against a session.
"""

from __future__ import annotations

import uuid
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
    ExecutionAttempt,
    ExecutionLogFile,
)
from ..models.node import Node
from . import states


def new_id() -> str:
    return uuid.uuid4().hex


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


def create_execution(
    session: AsyncSession, request: ExecutionRunRequest
) -> Execution:
    execution = Execution(
        id=new_id(),
        task_type=request.task_type,
        target=request.target or "",
        node_strategy=request.node_strategy or "all",
        status=states.EXEC_QUEUED,
        params=dict(request.params or {}),
    )
    session.add(execution)
    return execution


def create_attempt(
    session: AsyncSession, execution: Execution, node: Node
) -> ExecutionAttempt:
    attempt = ExecutionAttempt(
        id=new_id(),
        execution_id=execution.id,
        agent_id=node.agent_id,
        node_id=str(node.id) if node.id is not None else None,
        endpoint=node.endpoint,
        status=states.ATTEMPT_PENDING,
        error_detail={},
    )
    session.add(attempt)
    return attempt


def create_log_file(
    session: AsyncSession,
    settings: Settings,
    execution: Execution,
    attempt: ExecutionAttempt,
    stream: str = "log",
) -> ExecutionLogFile:
    now = datetime.now(UTC)
    path = files.log_path(
        settings.logs.root_dir, now, execution.id, attempt.id, stream
    )
    log_file = ExecutionLogFile(
        execution_id=execution.id,
        attempt_id=attempt.id,
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


async def get_execution(
    session: AsyncSession, execution_id: str
) -> Execution | None:
    result = await session.execute(
        select(Execution).where(Execution.id == execution_id)
    )
    return result.scalar_one_or_none()


async def get_execution_or_404(
    session: AsyncSession, execution_id: str
) -> Execution:
    execution = await get_execution(session, execution_id)
    if execution is None:
        raise ApiError(
            404,
            "execution.not_found",
            "errors.executionNotFound",
            {"execution_id": execution_id},
        )
    return execution


async def get_attempt(
    session: AsyncSession, attempt_id: str
) -> ExecutionAttempt | None:
    result = await session.execute(
        select(ExecutionAttempt).where(ExecutionAttempt.id == attempt_id)
    )
    return result.scalar_one_or_none()


async def list_attempts(
    session: AsyncSession, execution_id: str
) -> list[ExecutionAttempt]:
    result = await session.execute(
        select(ExecutionAttempt)
        .where(ExecutionAttempt.execution_id == execution_id)
        .order_by(ExecutionAttempt.created_at)
    )
    return list(result.scalars().all())


async def list_executions(
    session: AsyncSession, limit: int = 200
) -> list[Execution]:
    result = await session.execute(
        select(Execution).order_by(Execution.created_at.desc()).limit(limit)
    )
    return list(result.scalars().all())


async def get_log_file(
    session: AsyncSession,
    execution_id: str,
    attempt_id: str,
    stream: str = "log",
) -> ExecutionLogFile | None:
    result = await session.execute(
        select(ExecutionLogFile).where(
            ExecutionLogFile.execution_id == execution_id,
            ExecutionLogFile.attempt_id == attempt_id,
            ExecutionLogFile.stream == stream,
        )
    )
    return result.scalar_one_or_none()


def primary_attempt(
    attempts: list[ExecutionAttempt],
) -> ExecutionAttempt | None:
    """Default attempt for log endpoints when no attempt_id is given."""
    return attempts[0] if attempts else None


async def resolve_attempt(
    session: AsyncSession, execution_id: str, attempt_id: str | None
) -> ExecutionAttempt:
    attempts = await list_attempts(session, execution_id)
    if attempt_id:
        for a in attempts:
            if a.id == attempt_id:
                return a
        raise ApiError(
            404,
            "execution.attempt_not_found",
            "errors.attemptNotFound",
            {"execution_id": execution_id, "attempt_id": attempt_id},
        )
    chosen = primary_attempt(attempts)
    if chosen is None:
        raise ApiError(
            404,
            "execution.attempt_not_found",
            "errors.attemptNotFound",
            {"execution_id": execution_id},
        )
    return chosen


# ---------------------------------------------------------------------------
# view builders (frozen web-facing JSON)
# ---------------------------------------------------------------------------


def attempt_view(attempt: ExecutionAttempt) -> dict[str, Any]:
    return {
        "id": attempt.id,
        "execution_id": attempt.execution_id,
        "agent_id": attempt.agent_id,
        "node_id": attempt.node_id,
        "endpoint": attempt.endpoint,
        "remote_job_id": attempt.remote_job_id,
        "status": attempt.status,
        "started_at": _iso(attempt.started_at),
        "finished_at": _iso(attempt.finished_at),
        "exit_code": attempt.exit_code,
        "error_code": attempt.error_code,
        "error_detail": attempt.error_detail or {},
    }


def execution_view(
    execution: Execution, attempts: list[ExecutionAttempt]
) -> dict[str, Any]:
    return {
        "id": execution.id,
        "task_type": execution.task_type,
        "target": execution.target,
        "status": execution.status,
        "node_strategy": execution.node_strategy,
        "params": execution.params or {},
        "created_at": _iso(execution.created_at),
        "started_at": _iso(execution.started_at),
        "finished_at": _iso(execution.finished_at),
        "attempts": [attempt_view(a) for a in attempts],
    }


def execution_summary(
    execution: Execution, attempt_count: int
) -> dict[str, Any]:
    return {
        "id": execution.id,
        "task_type": execution.task_type,
        "target": execution.target,
        "status": execution.status,
        "node_strategy": execution.node_strategy,
        "created_at": _iso(execution.created_at),
        "started_at": _iso(execution.started_at),
        "finished_at": _iso(execution.finished_at),
        "attempt_count": attempt_count,
    }
