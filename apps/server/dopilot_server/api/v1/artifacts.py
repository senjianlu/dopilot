"""Build-artifact endpoints (phase 1.8).

The canonical product entity is the build artifact. Phase 1.8 only makes Scrapy
eggs runnable, so the writer is still the Scrapy egg upload — but it now creates
or reuses a ``build_artifacts`` row after the filesystem manifest is written.
Listing reconciles the on-disk Scrapy store into the DB so existing eggs surface
as build artifacts. Phase 1.8.1: a build artifact is NO LONGER directly runnable
— users create an execution template (with a command) and run/schedule that. The
``POST /artifacts/{id}/run`` direct-run entry point was removed.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ...artifacts.scrapy_store import ScrapyArtifactStore
from ...artifacts.wheel_store import WheelArtifactStore
from ...auth.agent_dependencies import require_server_token
from ...auth.dependencies import AdminContext, get_current_admin
from ...config.loader import get_settings
from ...config.settings import Settings
from ...db.engine import get_session
from ...services import artifacts as svc
from .schemas import (
    BuildArtifactsResponse,
    BuildArtifactUploadResponse,
    BuildArtifactView,
)

router = APIRouter(tags=["artifacts"])


def _store(settings: Settings) -> ScrapyArtifactStore:
    return ScrapyArtifactStore(settings.artifacts.root_dir)


def _wheel_store(settings: Settings) -> WheelArtifactStore:
    return WheelArtifactStore(settings.artifacts.root_dir)


@router.get("/artifacts", response_model=BuildArtifactsResponse)
async def list_build_artifacts(
    _admin: AdminContext = Depends(get_current_admin),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> BuildArtifactsResponse:
    """List canonical build artifacts (reconciling on-disk stores first)."""
    await svc.reconcile_scrapy_store(session, _store(settings))
    await svc.reconcile_wheel_store(session, _wheel_store(settings))
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


@router.post(
    "/artifacts/python_wheel/wheel", response_model=BuildArtifactUploadResponse
)
async def upload_python_wheel(
    file: UploadFile = File(...),
    _admin: AdminContext = Depends(get_current_admin),
    settings: Settings = Depends(get_settings),
    session: AsyncSession = Depends(get_session),
) -> BuildArtifactUploadResponse:
    """Validate + store a ``.whl``, then create/reuse its build artifact row.

    Deduped on ``("python_wheel", sha256)``. Phase 2b packet 1 only stores the
    wheel; the agent installs it (``pip install --no-deps --target`` + PYTHONPATH)
    in packet 2b-2 — the server never runs Python.
    """
    wheel_bytes = await file.read()
    filename = file.filename or "package.whl"
    manifest = _wheel_store(settings).save(
        filename=filename, content=wheel_bytes
    )
    artifact = await svc.upsert_wheel(session, manifest)
    await session.commit()
    return BuildArtifactUploadResponse(
        artifact=BuildArtifactView(**svc.build_artifact_view(artifact)),
        spiders=[],
    )


@router.get("/artifacts/python_wheel/{sha256}/wheel")
async def download_python_wheel(
    sha256: str,
    _: None = Depends(require_server_token),
    settings: Settings = Depends(get_settings),
) -> FileResponse:
    store = _wheel_store(settings)
    manifest = store.get(sha256)
    return FileResponse(
        store.wheel_path(sha256),
        media_type="application/octet-stream",
        filename=manifest.filename,
    )
