"""Schedule endpoints (phase 1.7 packet 2): CRUD + trigger-now.

A schedule references one template and creates tasks from its snapshot.
``POST /schedules/{id}/trigger-now`` fires immediately through the same path as
a timer firing (and the same path as a manual run); it is never coalesced.

After any create/update/delete the in-process schedule runner (if running) is
reloaded so its live job set stays in sync without a server restart.
"""

from __future__ import annotations

from dopilot_protocol import ExecutionRunResponse
from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from ...auth.dependencies import AdminContext, get_current_admin
from ...config.loader import get_settings
from ...config.settings import Settings
from ...db.engine import get_session
from ...executors.base import DispatchUnknownError
from ...redis.dispatcher import CommandDispatcher
from ...services import schedules as svc
from .executions import get_dispatcher
from .schemas import (
    NextRunPreviewRequest,
    NextRunPreviewResponse,
    ScheduleCreateRequest,
    SchedulesResponse,
    ScheduleUpdateRequest,
    ScheduleView,
)

router = APIRouter(tags=["schedules"])


def _tz(settings: Settings) -> str:
    return settings.scheduler.timezone or "UTC"


async def _reload_runner(request: Request) -> None:
    """Resync the APScheduler job set if the runner is live (no-op in tests)."""
    runner = getattr(request.app.state, "schedule_runner", None)
    if runner is not None:
        await runner.reload()


@router.post("/schedules", response_model=ScheduleView)
async def create_schedule(
    body: ScheduleCreateRequest,
    request: Request,
    _admin: AdminContext = Depends(get_current_admin),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> ScheduleView:
    schedule = await svc.create_schedule(session, body.model_dump())
    await session.commit()
    await _reload_runner(request)
    return ScheduleView(**svc.schedule_view(schedule, timezone=_tz(settings)))


@router.post("/schedules/preview-next-run", response_model=NextRunPreviewResponse)
async def preview_next_run(
    body: NextRunPreviewRequest,
    _admin: AdminContext = Depends(get_current_admin),
    settings: Settings = Depends(get_settings),
) -> NextRunPreviewResponse:
    """Estimate the next run for an unsaved trigger (backs the create dialog)."""
    next_run = svc.preview_next_run(body.model_dump(), timezone=_tz(settings))
    return NextRunPreviewResponse(
        next_run_at=next_run.isoformat() if next_run else None
    )


@router.get("/schedules", response_model=SchedulesResponse)
async def list_schedules(
    _admin: AdminContext = Depends(get_current_admin),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> SchedulesResponse:
    schedules = await svc.list_schedules(session)
    tz = _tz(settings)
    return SchedulesResponse(
        schedules=[
            ScheduleView(**svc.schedule_view(s, timezone=tz)) for s in schedules
        ]
    )


@router.get("/schedules/{schedule_id}", response_model=ScheduleView)
async def get_schedule(
    schedule_id: str,
    _admin: AdminContext = Depends(get_current_admin),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> ScheduleView:
    schedule = await svc.get_schedule_or_404(session, schedule_id)
    return ScheduleView(**svc.schedule_view(schedule, timezone=_tz(settings)))


@router.put("/schedules/{schedule_id}", response_model=ScheduleView)
async def update_schedule(
    schedule_id: str,
    body: ScheduleUpdateRequest,
    request: Request,
    _admin: AdminContext = Depends(get_current_admin),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> ScheduleView:
    schedule = await svc.get_schedule_or_404(session, schedule_id)
    await svc.update_schedule(
        session, schedule, body.model_dump(exclude_unset=True)
    )
    await session.commit()
    # refresh the server-generated onupdate `updated_at` before viewing.
    await session.refresh(schedule)
    await _reload_runner(request)
    return ScheduleView(**svc.schedule_view(schedule, timezone=_tz(settings)))


@router.delete("/schedules/{schedule_id}")
async def delete_schedule(
    schedule_id: str,
    request: Request,
    _admin: AdminContext = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
) -> dict[str, bool]:
    schedule = await svc.get_schedule_or_404(session, schedule_id)
    await svc.delete_schedule(session, schedule)
    await session.commit()
    await _reload_runner(request)
    return {"deleted": True}


@router.post(
    "/schedules/{schedule_id}/trigger-now", response_model=ExecutionRunResponse
)
async def trigger_now(
    schedule_id: str,
    response: Response,
    _admin: AdminContext = Depends(get_current_admin),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
    dispatcher: CommandDispatcher = Depends(get_dispatcher),
) -> ExecutionRunResponse:
    """Immediately create + dispatch a task from the referenced template."""
    schedule = await svc.get_schedule_or_404(session, schedule_id)
    try:
        return await svc.trigger_now(session, settings, dispatcher, schedule)
    except DispatchUnknownError as exc:
        response.status_code = 202
        return ExecutionRunResponse(execution_id=exc.execution_id, status="queued")
