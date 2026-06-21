"""Execution-template endpoints (phase 1.8): CRUD + run-from-template.

An execution template is a reusable run definition bound to one build artifact.
``POST /templates/{id}/run`` creates a task from a resolved snapshot of the
template through the SAME dispatch path as a direct artifact run (and the same
zero-node ``no_target`` behavior).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from ...auth.dependencies import AdminContext, get_current_admin
from ...config.loader import get_settings
from ...config.settings import Settings
from ...db.engine import get_session
from ...executors.base import DispatchUnknownError
from ...redis.dispatcher import CommandDispatcher
from ...services import states
from ...services import templates as svc
from ...services.dispatch import run_execution_template
from .schemas import (
    ExecutionTemplateCreateRequest,
    ExecutionTemplatesResponse,
    ExecutionTemplateUpdateRequest,
    ExecutionTemplateView,
    TaskRunResponse,
)
from .tasks import get_dispatcher

router = APIRouter(tags=["templates"])


@router.post("/templates", response_model=ExecutionTemplateView)
async def create_template(
    body: ExecutionTemplateCreateRequest,
    _admin: AdminContext = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
) -> ExecutionTemplateView:
    template = await svc.create_template(session, body.model_dump())
    await session.commit()
    artifact_type = await svc.artifact_type_for_template(session, template)
    return ExecutionTemplateView(**svc.template_view(template, artifact_type))


@router.get("/templates", response_model=ExecutionTemplatesResponse)
async def list_templates(
    _admin: AdminContext = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
) -> ExecutionTemplatesResponse:
    templates = await svc.list_templates(session)
    type_map = await svc.artifact_types_for_templates(session, templates)
    return ExecutionTemplatesResponse(
        templates=[
            ExecutionTemplateView(
                **svc.template_view(
                    t, type_map.get(t.build_artifact_id or "", "scrapy")
                )
            )
            for t in templates
        ]
    )


@router.get("/templates/{template_id}", response_model=ExecutionTemplateView)
async def get_template(
    template_id: str,
    _admin: AdminContext = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
) -> ExecutionTemplateView:
    template = await svc.get_template_or_404(session, template_id)
    artifact_type = await svc.artifact_type_for_template(session, template)
    return ExecutionTemplateView(**svc.template_view(template, artifact_type))


@router.put("/templates/{template_id}", response_model=ExecutionTemplateView)
async def update_template(
    template_id: str,
    body: ExecutionTemplateUpdateRequest,
    _admin: AdminContext = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
) -> ExecutionTemplateView:
    template = await svc.get_template_or_404(session, template_id)
    # exclude_unset so absent fields are not patched to null.
    await svc.update_template(session, template, body.model_dump(exclude_unset=True))
    await session.commit()
    # refresh: the onupdate `updated_at` is server-generated, so reload it before
    # building the view (avoids a lazy-IO access on a stale attribute).
    await session.refresh(template)
    artifact_type = await svc.artifact_type_for_template(session, template)
    return ExecutionTemplateView(**svc.template_view(template, artifact_type))


@router.delete("/templates/{template_id}")
async def delete_template(
    template_id: str,
    _admin: AdminContext = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
) -> dict[str, bool]:
    template = await svc.get_template_or_404(session, template_id)
    await svc.delete_template(session, template)
    await session.commit()
    return {"deleted": True}


@router.post("/templates/{template_id}/run", response_model=TaskRunResponse)
async def run_template(
    template_id: str,
    response: Response,
    _admin: AdminContext = Depends(get_current_admin),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
    dispatcher: CommandDispatcher = Depends(get_dispatcher),
) -> TaskRunResponse:
    """Create + dispatch a task from this template's snapshot (source=template)."""
    template = await svc.get_template_or_404(session, template_id)
    try:
        result = await run_execution_template(
            session,
            settings,
            dispatcher,
            template,
            source=states.TASK_SOURCE_TEMPLATE,
        )
        return TaskRunResponse(task_id=result.task_id, status=result.status)
    except DispatchUnknownError as exc:
        response.status_code = 202
        return TaskRunResponse(task_id=exc.task_id, status="queued")
