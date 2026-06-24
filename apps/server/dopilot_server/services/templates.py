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

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from dopilot_protocol import ExecutionRunRequest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..errors import ApiError
from ..models.execution import BuildArtifact
from ..models.scheduling import ExecutionTemplate, Schedule
from . import artifacts as artifact_svc
from . import resolve, states
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
    # name + command are required; project/version are derived from the artifact.
    missing = [
        k for k in ("name", "command") if not (str(data.get(k) or "")).strip()
    ]
    if missing:
        raise ApiError(
            400,
            "template.invalid_params",
            "errors.invalidParams",
            {"missing": missing},
        )
    # Type-specific command grammar is validated AFTER the artifact binding is
    # resolved (scrapy parser vs python_wheel non-empty); here we only assert the
    # generic non-empty requirement above.


async def _ensure_unique_name(
    session: AsyncSession, name: str, *, exclude_id: str | None = None
) -> None:
    """Raise 409 if another template already uses ``name`` (phase 2.2).

    Checked in service code before commit so the API returns a deterministic
    ``template.name_conflict`` rather than surfacing a raw DB IntegrityError.
    ``exclude_id`` excludes the row being updated (rename self-exclusion).
    """
    stmt = select(ExecutionTemplate.id).where(ExecutionTemplate.name == name)
    if exclude_id is not None:
        stmt = stmt.where(ExecutionTemplate.id != exclude_id)
    if (await session.execute(stmt.limit(1))).first() is not None:
        raise ApiError(
            409,
            "template.name_conflict",
            "errors.templateNameConflict",
            {"name": name},
        )


async def _require_artifact(session: AsyncSession, build_artifact_id: str | None):
    """Resolve + validate the mandatory runnable build artifact binding.

    Runnable-ONLY: this is the runtime resolution used by template run / schedule
    dispatch (:func:`build_run_request`). It deliberately does NOT check archive
    state, so a template bound before its artifact was archived keeps running. New
    or changed bindings use :func:`_require_bindable_artifact` instead.
    """
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


async def _require_bindable_artifact(
    session: AsyncSession, build_artifact_id: str | None
):
    """Resolve + validate a build artifact for a NEW or CHANGED template binding.

    Bindable = runnable AND unarchived. Used by create + rebind-on-update only;
    NEVER by the run/dispatch path, so archiving an artifact does not break runs
    of templates already bound to it.
    """
    if not (build_artifact_id or "").strip():
        raise ApiError(
            400,
            "template.build_artifact_required",
            "errors.buildArtifactRequired",
            {},
        )
    return await artifact_svc.get_bindable_artifact_or_404(
        session, build_artifact_id
    )


def _validate_command_for_artifact(artifact: BuildArtifact, command: str) -> None:
    """Type-aware command validation for the bound artifact (phase 2b).

    Scrapy keeps the ``scrapy crawl`` parser + spider-in-artifact check; a
    Python wheel only requires a non-empty (free-form shell) command.
    """
    if artifact.artifact_type == states.ARTIFACT_SCRAPY:
        meta = dict(artifact.artifact_metadata or {})
        resolve.validate_command_for_artifact(command, meta.get("spiders"))
    else:
        resolve.validate_wheel_command(command)


async def create_template(
    session: AsyncSession, data: dict[str, Any]
) -> ExecutionTemplate:
    _validate_basics(data)
    name = str(data["name"]).strip()
    await _ensure_unique_name(session, name)
    # A brand-new binding must be runnable AND unarchived.
    artifact = await _require_bindable_artifact(
        session, data.get("build_artifact_id")
    )
    meta = dict(artifact.artifact_metadata or {})
    # Once the artifact is known, validate the command for its type.
    _validate_command_for_artifact(artifact, str(data["command"]).strip())
    template = ExecutionTemplate(
        id=new_id(),
        name=name,
        description=data.get("description"),
        build_artifact_id=artifact.id,
        # project/version come from the bound artifact, not the user.
        project=meta.get("project"),
        version=meta.get("version"),
        command=str(data["command"]).strip(),
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
        "command": data.get("command", template.command),
        "node_strategy": data.get("node_strategy", template.node_strategy),
    }
    _validate_basics(merged)
    new_name = str(merged["name"]).strip()
    await _ensure_unique_name(session, new_name, exclude_id=template.id)
    # build_artifact_id is mandatory on every update; default to the current one.
    # Only a CHANGE of binding must be runnable AND unarchived — keeping the
    # current binding (even if it was archived after binding) stays editable, so
    # the template remains editable for other fields. The empty/unknown/
    # not-runnable cases are still validated for both paths.
    new_artifact_id = data.get("build_artifact_id", template.build_artifact_id)
    is_rebind = (new_artifact_id or "").strip() != (
        template.build_artifact_id or ""
    ).strip()
    if is_rebind:
        artifact = await _require_bindable_artifact(session, new_artifact_id)
    else:
        artifact = await _require_artifact(session, new_artifact_id)
    meta = dict(artifact.artifact_metadata or {})
    # Once the artifact is known, validate the command for its type.
    _validate_command_for_artifact(artifact, str(merged["command"]).strip())
    template.name = new_name
    template.node_strategy = merged["node_strategy"]
    template.command = str(merged["command"]).strip()
    template.build_artifact_id = artifact.id
    template.project = meta.get("project")
    template.version = meta.get("version")
    if "description" in data:
        template.description = data["description"]
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
        "command": template.command,
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
        overrides=resolve.sanitize_overrides(
            overrides, artifact_type=artifact.artifact_type
        ),
        name=template.name,
        execution_template_id=template.id,
    )


async def artifact_type_for_template(
    session: AsyncSession, template: ExecutionTemplate
) -> str:
    """Resolve the core-domain ``artifact_type`` from the bound build artifact.

    Templates carry no ``task_type`` column; the type is derived from the bound
    artifact. Falls back to ``scrapy`` for a legacy/dangling binding.
    """
    if not template.build_artifact_id:
        return states.ARTIFACT_SCRAPY
    artifact = await artifact_svc.get_build_artifact(
        session, template.build_artifact_id
    )
    return artifact.artifact_type if artifact else states.ARTIFACT_SCRAPY


@dataclass(frozen=True)
class TemplateArtifactMeta:
    """The live, artifact-derived bits the template view needs.

    Resolved from the bound :class:`BuildArtifact` (not frozen on the template):
    ``artifact_type`` plus reversible archive state. A legacy/dangling binding
    (no ``build_artifact_id`` or a missing artifact) falls back to the default
    ``scrapy`` type and unarchived state.
    """

    artifact_type: str = states.ARTIFACT_SCRAPY
    archived_at: datetime | None = None


async def artifact_meta_for_template(
    session: AsyncSession, template: ExecutionTemplate
) -> TemplateArtifactMeta:
    """Resolve the live artifact meta (type + archive state) for one template.

    The artifact row is loaded once here, so the single-row create/get/update
    template views get archive state for free (no extra round-trip).
    """
    if not template.build_artifact_id:
        return TemplateArtifactMeta()
    artifact = await artifact_svc.get_build_artifact(
        session, template.build_artifact_id
    )
    if artifact is None:
        return TemplateArtifactMeta()
    return TemplateArtifactMeta(artifact.artifact_type, artifact.archived_at)


async def artifact_meta_for_templates(
    session: AsyncSession, templates: list[ExecutionTemplate]
) -> dict[str, TemplateArtifactMeta]:
    """Batch ``build_artifact_id -> TemplateArtifactMeta`` for a template list.

    One ``IN (...)`` query over the referenced artifacts, so the list endpoint
    never does a per-template artifact lookup (no N+1).
    """
    ids = {t.build_artifact_id for t in templates if t.build_artifact_id}
    if not ids:
        return {}
    rows = await session.execute(
        select(
            BuildArtifact.id,
            BuildArtifact.artifact_type,
            BuildArtifact.archived_at,
        ).where(BuildArtifact.id.in_(ids))
    )
    return {
        row[0]: TemplateArtifactMeta(row[1], row[2]) for row in rows.all()
    }


def template_view(
    template: ExecutionTemplate, meta: TemplateArtifactMeta | None = None
) -> dict[str, Any]:
    meta = meta or TemplateArtifactMeta()
    return {
        "id": template.id,
        "name": template.name,
        "description": template.description,
        "build_artifact_id": template.build_artifact_id,
        "artifact_type": meta.artifact_type,
        "project": template.project,
        "version": template.version,
        "command": template.command,
        "node_strategy": template.node_strategy,
        "node_ids": list(template.node_ids or []),
        # Live archive state of the bound artifact (not a frozen snapshot). A
        # dangling/legacy binding serializes as not-archived.
        "build_artifact_archived": meta.archived_at is not None,
        "build_artifact_archived_at": _iso(meta.archived_at),
        "created_at": _iso(template.created_at),
        "updated_at": _iso(template.updated_at),
    }
