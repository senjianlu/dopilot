"""Task-template service (phase 1.7 packet 2): CRUD + snapshot builder.

A :class:`TaskTemplate` is a reusable Scrapy run definition. At run time its
payload is COPIED into an immutable ``Task.template_snapshot`` + the run params,
so editing the template afterwards never mutates a historical task.

Endpoints stay thin; create/query/view + the template->run-request translation
live here so they can be unit-tested directly against a session.
"""

from __future__ import annotations

from typing import Any

from dopilot_protocol import ExecutionRunRequest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..errors import ApiError
from ..models.scheduling import Schedule, TaskTemplate
from .executions import _iso, new_id

# Only "scrapy" is valid in phase 1.7 (script/docker are later phases).
VALID_TASK_TYPES = frozenset({"scrapy"})
VALID_NODE_STRATEGIES = frozenset({"all", "random", "selected"})


def _validate(data: dict[str, Any]) -> None:
    task_type = data.get("task_type") or "scrapy"
    if task_type not in VALID_TASK_TYPES:
        raise ApiError(
            400,
            "template.invalid_task_type",
            "errors.invalidTaskType",
            {"task_type": task_type},
        )
    strategy = data.get("node_strategy") or "all"
    if strategy not in VALID_NODE_STRATEGIES:
        raise ApiError(
            400,
            "template.invalid_node_strategy",
            "errors.invalidNodeStrategy",
            {"node_strategy": strategy},
        )
    # scrapy needs a project + spider to be runnable (parse_scrapy_params).
    missing = [
        k for k in ("name", "project", "spider") if not (data.get(k) or "").strip()
    ]
    if missing:
        raise ApiError(
            400,
            "template.invalid_params",
            "errors.invalidParams",
            {"missing": missing},
        )


def create_template(session: AsyncSession, data: dict[str, Any]) -> TaskTemplate:
    _validate(data)
    template = TaskTemplate(
        id=new_id(),
        name=str(data["name"]).strip(),
        description=data.get("description"),
        task_type=data.get("task_type") or "scrapy",
        project=data.get("project"),
        version=data.get("version"),
        spider=data.get("spider"),
        artifact=dict(data.get("artifact") or {}),
        settings={str(k): str(v) for k, v in (data.get("settings") or {}).items()},
        args={str(k): str(v) for k, v in (data.get("args") or {}).items()},
        node_strategy=data.get("node_strategy") or "all",
        node_ids=[str(n) for n in (data.get("node_ids") or [])],
    )
    session.add(template)
    return template


def update_template(
    template: TaskTemplate, data: dict[str, Any]
) -> TaskTemplate:
    """Patch mutable template fields. Run params merge name+project+spider in."""
    merged = {
        "name": data.get("name", template.name),
        "project": data.get("project", template.project),
        "spider": data.get("spider", template.spider),
        "task_type": data.get("task_type", template.task_type),
        "node_strategy": data.get("node_strategy", template.node_strategy),
    }
    _validate(merged)
    template.name = str(merged["name"]).strip()
    template.task_type = merged["task_type"]
    template.node_strategy = merged["node_strategy"]
    template.project = merged["project"]
    template.spider = merged["spider"]
    if "description" in data:
        template.description = data["description"]
    if "version" in data:
        template.version = data["version"]
    if "artifact" in data:
        template.artifact = dict(data.get("artifact") or {})
    if "settings" in data:
        template.settings = {
            str(k): str(v) for k, v in (data.get("settings") or {}).items()
        }
    if "args" in data:
        template.args = {
            str(k): str(v) for k, v in (data.get("args") or {}).items()
        }
    if "node_ids" in data:
        template.node_ids = [str(n) for n in (data.get("node_ids") or [])]
    return template


async def get_template(
    session: AsyncSession, template_id: str
) -> TaskTemplate | None:
    result = await session.execute(
        select(TaskTemplate).where(TaskTemplate.id == template_id)
    )
    return result.scalar_one_or_none()


async def get_template_or_404(
    session: AsyncSession, template_id: str
) -> TaskTemplate:
    template = await get_template(session, template_id)
    if template is None:
        raise ApiError(
            404,
            "template.not_found",
            "errors.templateNotFound",
            {"template_id": template_id},
        )
    return template


async def list_templates(
    session: AsyncSession, limit: int = 200
) -> list[TaskTemplate]:
    result = await session.execute(
        select(TaskTemplate)
        .order_by(TaskTemplate.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def delete_template(session: AsyncSession, template: TaskTemplate) -> None:
    referenced = await session.execute(
        select(Schedule.id).where(Schedule.template_id == template.id).limit(1)
    )
    if referenced.first() is not None:
        raise ApiError(
            409,
            "template.in_use",
            "errors.templateInUse",
            {"template_id": template.id},
        )
    await session.delete(template)


def template_snapshot(template: TaskTemplate) -> dict[str, Any]:
    """The immutable copy of a template's run-defining fields stored on a task."""
    return {
        "template_id": template.id,
        "name": template.name,
        "task_type": template.task_type,
        "project": template.project,
        "version": template.version,
        "spider": template.spider,
        "artifact": dict(template.artifact or {}),
        "settings": dict(template.settings or {}),
        "args": dict(template.args or {}),
        "node_strategy": template.node_strategy,
        "node_ids": list(template.node_ids or []),
    }


def build_run_request(
    template: TaskTemplate,
) -> tuple[ExecutionRunRequest, dict[str, Any]]:
    """Translate a template into a run request + its immutable snapshot."""
    snapshot = template_snapshot(template)
    params: dict[str, Any] = {
        "project": template.project,
        "spider": template.spider,
        "version": template.version,
        "settings": dict(template.settings or {}),
        "args": dict(template.args or {}),
    }
    if template.artifact:
        params["artifact"] = dict(template.artifact)
    target = template.name or f"{template.project}:{template.spider}"
    request = ExecutionRunRequest(
        task_type=template.task_type,
        target=target,
        node_strategy=template.node_strategy,
        node_ids=list(template.node_ids or []),
        params=params,
    )
    return request, snapshot


def template_view(template: TaskTemplate) -> dict[str, Any]:
    return {
        "id": template.id,
        "name": template.name,
        "description": template.description,
        "task_type": template.task_type,
        "project": template.project,
        "version": template.version,
        "spider": template.spider,
        "artifact": template.artifact or {},
        "settings": template.settings or {},
        "args": template.args or {},
        "node_strategy": template.node_strategy,
        "node_ids": list(template.node_ids or []),
        "created_at": _iso(template.created_at),
        "updated_at": _iso(template.updated_at),
    }
