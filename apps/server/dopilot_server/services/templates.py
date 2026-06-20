"""Execution-template service (phase 1.8): CRUD + run resolution.

An :class:`ExecutionTemplate` is a reusable run definition bound to exactly one
:class:`BuildArtifact`. Every new/updated template MUST bind a runnable build
artifact (application validation); the core-domain ``artifact_type`` is derived
from that artifact, so templates no longer carry a ``task_type``. At run time the
template defaults flow through :func:`resolve.resolve_run`, which copies the
resolved run into an immutable ``Task.template_snapshot``.

Endpoints stay thin; create/query/view + the template->run translation live here
so they can be unit-tested directly against a session.
"""

from __future__ import annotations

from typing import Any

from dopilot_protocol import ExecutionRunRequest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..errors import ApiError
from ..models.scheduling import ExecutionTemplate, Schedule
from . import artifacts as artifact_svc
from . import resolve
from .executions import _iso, new_id

VALID_NODE_STRATEGIES = frozenset({"all", "random", "selected"})


def _validate_basics(data: dict[str, Any]) -> None:
    strategy = data.get("node_strategy") or "all"
    if strategy not in VALID_NODE_STRATEGIES:
        raise ApiError(
            400,
            "template.invalid_node_strategy",
            "errors.invalidNodeStrategy",
            {"node_strategy": strategy},
        )
    # name + spider are required; project/version are derived from the artifact.
    missing = [
        k for k in ("name", "spider") if not (str(data.get(k) or "")).strip()
    ]
    if missing:
        raise ApiError(
            400,
            "template.invalid_params",
            "errors.invalidParams",
            {"missing": missing},
        )


async def _require_artifact(session: AsyncSession, build_artifact_id: str | None):
    """Resolve + validate the mandatory runnable build artifact binding."""
    if not (build_artifact_id or "").strip():
        raise ApiError(
            400,
            "template.build_artifact_required",
            "errors.buildArtifactRequired",
            {},
        )
    return await artifact_svc.get_runnable_artifact_or_404(
        session, build_artifact_id
    )


async def create_template(
    session: AsyncSession, data: dict[str, Any]
) -> ExecutionTemplate:
    _validate_basics(data)
    artifact = await _require_artifact(session, data.get("build_artifact_id"))
    meta = dict(artifact.artifact_metadata or {})
    template = ExecutionTemplate(
        id=new_id(),
        name=str(data["name"]).strip(),
        description=data.get("description"),
        build_artifact_id=artifact.id,
        # project/version come from the bound artifact, not the user.
        project=meta.get("project"),
        version=meta.get("version"),
        spider=str(data["spider"]).strip(),
        settings={str(k): str(v) for k, v in (data.get("settings") or {}).items()},
        args={str(k): str(v) for k, v in (data.get("args") or {}).items()},
        node_strategy=data.get("node_strategy") or "all",
        node_ids=[str(n) for n in (data.get("node_ids") or [])],
    )
    session.add(template)
    return template


async def update_template(
    session: AsyncSession, template: ExecutionTemplate, data: dict[str, Any]
) -> ExecutionTemplate:
    """Patch mutable template fields. Always re-validates the artifact binding."""
    merged = {
        "name": data.get("name", template.name),
        "spider": data.get("spider", template.spider),
        "node_strategy": data.get("node_strategy", template.node_strategy),
    }
    _validate_basics(merged)
    # build_artifact_id is mandatory on every update; default to the current one.
    artifact = await _require_artifact(
        session, data.get("build_artifact_id", template.build_artifact_id)
    )
    meta = dict(artifact.artifact_metadata or {})
    template.name = str(merged["name"]).strip()
    template.node_strategy = merged["node_strategy"]
    template.spider = str(merged["spider"]).strip()
    template.build_artifact_id = artifact.id
    template.project = meta.get("project")
    template.version = meta.get("version")
    if "description" in data:
        template.description = data["description"]
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
) -> ExecutionTemplate | None:
    result = await session.execute(
        select(ExecutionTemplate).where(ExecutionTemplate.id == template_id)
    )
    return result.scalar_one_or_none()


async def get_template_or_404(
    session: AsyncSession, template_id: str
) -> ExecutionTemplate:
    template = await get_template(session, template_id)
    if template is None:
        raise ApiError(
            404,
            "template.not_found",
            "errors.templateNotFound",
            {"execution_template_id": template_id},
        )
    return template


async def list_templates(
    session: AsyncSession, limit: int = 200
) -> list[ExecutionTemplate]:
    result = await session.execute(
        select(ExecutionTemplate)
        .order_by(ExecutionTemplate.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def delete_template(
    session: AsyncSession, template: ExecutionTemplate
) -> None:
    referenced = await session.execute(
        select(Schedule.id)
        .where(Schedule.execution_template_id == template.id)
        .limit(1)
    )
    if referenced.first() is not None:
        raise ApiError(
            409,
            "template.in_use",
            "errors.templateInUse",
            {"execution_template_id": template.id},
        )
    await session.delete(template)


def template_defaults(template: ExecutionTemplate) -> dict[str, Any]:
    """The execution-template fields fed into :func:`resolve.resolve_run`."""
    return {
        "name": template.name,
        "project": template.project,
        "version": template.version,
        "spider": template.spider,
        "settings": dict(template.settings or {}),
        "args": dict(template.args or {}),
        "node_strategy": template.node_strategy,
        "node_ids": list(template.node_ids or []),
    }


async def build_run_request(
    session: AsyncSession,
    template: ExecutionTemplate,
    *,
    overrides: dict[str, Any] | None = None,
) -> tuple[ExecutionRunRequest, dict[str, Any]]:
    """Resolve a template (+ optional overrides) into a run request + snapshot."""
    artifact = await _require_artifact(session, template.build_artifact_id)
    return resolve.resolve_run(
        build_artifact=artifact,
        template_defaults=template_defaults(template),
        overrides=resolve.sanitize_overrides(overrides),
        name=template.name,
        execution_template_id=template.id,
    )


def template_view(template: ExecutionTemplate) -> dict[str, Any]:
    return {
        "id": template.id,
        "name": template.name,
        "description": template.description,
        "build_artifact_id": template.build_artifact_id,
        "artifact_type": "scrapy",
        "project": template.project,
        "version": template.version,
        "spider": template.spider,
        "settings": template.settings or {},
        "args": template.args or {},
        "node_strategy": template.node_strategy,
        "node_ids": list(template.node_ids or []),
        "created_at": _iso(template.created_at),
        "updated_at": _iso(template.updated_at),
    }
