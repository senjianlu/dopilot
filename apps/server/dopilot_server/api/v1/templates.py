"""Task-template endpoints (phase 1.7 packet 2): CRUD + run-from-template.

A template is a reusable Scrapy run definition. ``POST /templates/{id}/run``
creates a task from an immutable snapshot of the template through the SAME
dispatch path as a manual run (and the same zero-node ``no_target`` behavior).
"""

from __future__ import annotations

from dopilot_protocol import ExecutionRunResponse
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
from ...services.dispatch import dispatch_from_template
from .executions import get_dispatcher
from .schemas import (
    TemplateCreateRequest,
    TemplatesResponse,
    TemplateUpdateRequest,
    TemplateView,
)

router = APIRouter(tags=["templates"])


@router.post("/templates", response_model=TemplateView)
async def create_template(
    body: TemplateCreateRequest,
    _admin: AdminContext = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
) -> TemplateView:
    template = svc.create_template(session, body.model_dump())
    await session.commit()
    return TemplateView(**svc.template_view(template))


@router.get("/templates", response_model=TemplatesResponse)
async def list_templates(
    _admin: AdminContext = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
) -> TemplatesResponse:
    templates = await svc.list_templates(session)
    return TemplatesResponse(
        templates=[TemplateView(**svc.template_view(t)) for t in templates]
    )


@router.get("/templates/{template_id}", response_model=TemplateView)
async def get_template(
    template_id: str,
    _admin: AdminContext = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
) -> TemplateView:
    template = await svc.get_template_or_404(session, template_id)
    return TemplateView(**svc.template_view(template))


@router.put("/templates/{template_id}", response_model=TemplateView)
async def update_template(
    template_id: str,
    body: TemplateUpdateRequest,
    _admin: AdminContext = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
) -> TemplateView:
    template = await svc.get_template_or_404(session, template_id)
    # exclude_unset so absent fields are not patched to null.
    svc.update_template(template, body.model_dump(exclude_unset=True))
    await session.commit()
    # refresh: the onupdate `updated_at` is server-generated, so reload it before
    # building the view (avoids a lazy-IO access on a stale attribute).
    await session.refresh(template)
    return TemplateView(**svc.template_view(template))


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


@router.post("/templates/{template_id}/run", response_model=ExecutionRunResponse)
async def run_template(
    template_id: str,
    response: Response,
    _admin: AdminContext = Depends(get_current_admin),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
    dispatcher: CommandDispatcher = Depends(get_dispatcher),
) -> ExecutionRunResponse:
    """Create + dispatch a task from this template's snapshot (source=manual)."""
    template = await svc.get_template_or_404(session, template_id)
    try:
        return await dispatch_from_template(
            session,
            settings,
            dispatcher,
            template,
            source=states.TASK_SOURCE_MANUAL,
        )
    except DispatchUnknownError as exc:
        response.status_code = 202
        return ExecutionRunResponse(execution_id=exc.execution_id, status="queued")
