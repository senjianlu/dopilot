"""Build-artifact endpoints (phase 1.8).

The canonical product entity is the build artifact. Phase 1.8 only makes Scrapy
eggs runnable, so the writer is still the Scrapy egg upload — but it now creates
or reuses a ``build_artifacts`` row after the filesystem manifest is written.
Listing reconciles the on-disk Scrapy store into the DB so existing eggs surface
as build artifacts. A build artifact can be run directly (ad-hoc snapshot).
"""

from __future__ import annotations

from dopilot_protocol import ExecutionRunResponse
from fastapi import APIRouter, Depends, File, Form, Response, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ...artifacts.scrapy_store import ScrapyArtifactStore
from ...auth.agent_dependencies import require_server_token
from ...auth.dependencies import AdminContext, get_current_admin
from ...config.loader import get_settings
from ...config.settings import Settings
from ...db.engine import get_session
from ...executors.base import DispatchUnknownError
from ...redis.dispatcher import CommandDispatcher
from ...services import artifacts as svc
from ...services import dispatch as dispatch_svc
from .schemas import (
    ArtifactRunRequest,
    BuildArtifactsResponse,
    BuildArtifactUploadResponse,
    BuildArtifactView,
    TaskRunResponse,
)
from .tasks import get_dispatcher

router = APIRouter(tags=["artifacts"])


def _store(settings: Settings) -> ScrapyArtifactStore:
    return ScrapyArtifactStore(settings.artifacts.root_dir)


@router.get("/artifacts", response_model=BuildArtifactsResponse)
async def list_build_artifacts(
    _admin: AdminContext = Depends(get_current_admin),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> BuildArtifactsResponse:
    """List canonical build artifacts (reconciling on-disk Scrapy eggs first)."""
    await svc.reconcile_scrapy_store(session, _store(settings))
    artifacts = await svc.list_build_artifacts(session)
    return BuildArtifactsResponse(
        artifacts=[
            BuildArtifactView(**svc.build_artifact_view(a)) for a in artifacts
        ]
    )


@router.post(
    "/artifacts/scrapy/egg", response_model=BuildArtifactUploadResponse
)
async def upload_scrapy_egg(
    file: UploadFile = File(...),
    project: str | None = Form(default=None),
    version: str | None = Form(default=None),
    _admin: AdminContext = Depends(get_current_admin),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> BuildArtifactUploadResponse:
    """Validate + store a Scrapy egg, then create/reuse its build artifact row.

    ``project`` / ``version`` are accepted for backward-compatible form posts;
    the stored artifact version is content-derived from sha256.
    """
    _ = version
    egg_bytes = await file.read()
    filename = file.filename or "crawler.egg"
    manifest = _store(settings).save(
        filename=filename, content=egg_bytes, project_hint=project
    )
    artifact = await svc.upsert_scrapy(session, manifest)
    await session.commit()
    return BuildArtifactUploadResponse(
        artifact=BuildArtifactView(**svc.build_artifact_view(artifact)),
        spiders=list(manifest.spiders),
    )


@router.post("/artifacts/{artifact_id}/run", response_model=TaskRunResponse)
async def run_build_artifact(
    artifact_id: str,
    body: ArtifactRunRequest,
    response: Response,
    _admin: AdminContext = Depends(get_current_admin),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
    dispatcher: CommandDispatcher = Depends(get_dispatcher),
) -> TaskRunResponse:
    """Direct build-artifact run: create + dispatch a task from an ad-hoc snapshot."""
    artifact = await svc.get_runnable_artifact_or_404(session, artifact_id)
    try:
        result: ExecutionRunResponse = await dispatch_svc.run_direct_artifact(
            session,
            settings,
            dispatcher,
            artifact,
            overrides=body.model_dump(exclude_unset=True),
        )
        return TaskRunResponse(task_id=result.task_id, status=result.status)
    except DispatchUnknownError as exc:
        response.status_code = 202
        return TaskRunResponse(task_id=exc.task_id, status="queued")


@router.get("/artifacts/scrapy/{sha256}/egg")
async def download_scrapy_egg(
    sha256: str,
    _: None = Depends(require_server_token),
    settings: Settings = Depends(get_settings),
) -> FileResponse:
    store = _store(settings)
    manifest = store.get(sha256)
    return FileResponse(
        store.egg_path(sha256),
        media_type="application/octet-stream",
        filename=manifest.filename,
    )
