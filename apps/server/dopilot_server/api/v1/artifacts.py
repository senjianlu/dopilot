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

import asyncio

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ...artifacts.scrapy_store import ScrapyArtifactStore
from ...artifacts.upload import (
    cleanup_temp,
    publish_lock,
    release_quota,
    reserve_quota,
    stream_to_staging,
)
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
    "/artifacts/{artifact_id}/archive", response_model=BuildArtifactView
)
async def archive_build_artifact(
    artifact_id: str,
    _admin: AdminContext = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
) -> BuildArtifactView:
    """Idempotently archive a build artifact (admin-only).

    Archiving keeps the artifact visible and runnable by templates already bound
    to it; it only blocks NEW/CHANGED template bindings. Re-archiving an already
    archived artifact keeps the original ``archived_at`` and returns 200.
    """
    artifact = await svc.get_build_artifact_or_404(session, artifact_id)
    svc.archive_artifact(artifact)
    await session.commit()
    await session.refresh(artifact)
    return BuildArtifactView(**svc.build_artifact_view(artifact))


@router.post(
    "/artifacts/{artifact_id}/unarchive", response_model=BuildArtifactView
)
async def unarchive_build_artifact(
    artifact_id: str,
    _admin: AdminContext = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
) -> BuildArtifactView:
    """Idempotently unarchive a build artifact (admin-only). Unarchiving an
    already-unarchived artifact is a no-op and returns 200."""
    artifact = await svc.get_build_artifact_or_404(session, artifact_id)
    svc.unarchive_artifact(artifact)
    await session.commit()
    await session.refresh(artifact)
    return BuildArtifactView(**svc.build_artifact_view(artifact))


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
    filename = file.filename or "crawler.egg"
    store = _store(settings)
    # Resource caps (B5): stream to a bounded temp file (413 over max_upload_bytes),
    # reserve against the aggregate quota (507), then publish + upsert. The temp
    # file and reservation are always cleaned up.
    tmp_path, size_bytes, sha256 = await stream_to_staging(
        file, settings.artifacts.root_dir, settings.artifacts.max_upload_bytes
    )
    token = None
    published = False
    try:
        # Serialize same-sha publishes (R-03): the existence check, publish, DB
        # commit and rollback must not interleave with another upload of the same
        # content, or a failing request could delete a body a concurrent COMMITTED
        # request references. Under the lock, a second same-sha upload sees
        # already_stored=True and never rolls back the shared body.
        async with publish_lock(sha256):
            already_stored = await asyncio.to_thread(store.egg_path(sha256).exists)
            token = await reserve_quota(
                session,
                size_bytes=size_bytes,
                max_total_bytes=settings.artifacts.max_total_bytes,
                already_stored=already_stored,
            )
            try:
                manifest = await asyncio.to_thread(
                    lambda: store.save_from_path(
                        filename=filename,
                        tmp_path=tmp_path,
                        sha256=sha256,
                        size_bytes=size_bytes,
                        project_hint=project,
                    )
                )
                published = True
                artifact = await svc.upsert_scrapy(session, manifest)
                await session.commit()
            except BaseException:
                # If the body was published but upsert/commit failed, delete the
                # published body so it is never left uncounted by the quota (R-04).
                # Only roll back bytes THIS upload created — a deduped pre-existing
                # artifact belongs to a prior success (and the sha lock guarantees
                # no concurrent same-sha request is mid-publish).
                if published and not already_stored:
                    await asyncio.to_thread(store.remove_stored, sha256)
                raise
        return BuildArtifactUploadResponse(
            artifact=BuildArtifactView(**svc.build_artifact_view(artifact)),
            spiders=list(manifest.spiders),
        )
    finally:
        # save_from_path renames the temp on success; on any failure it is left
        # behind — remove it. Always release the reservation.
        await cleanup_temp(tmp_path)
        release_quota(token)


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
    filename = file.filename or "package.whl"
    store = _wheel_store(settings)
    # Resource caps (B5): stream to a bounded temp (413), reserve quota (507),
    # then publish + upsert; temp file + reservation always cleaned up.
    tmp_path, size_bytes, sha256 = await stream_to_staging(
        file, settings.artifacts.root_dir, settings.artifacts.max_upload_bytes
    )
    token = None
    published = False
    try:
        # Serialize same-sha publishes (R-03) — see the egg endpoint for rationale.
        async with publish_lock(sha256):
            already_stored = await asyncio.to_thread(store.wheel_path(sha256).exists)
            token = await reserve_quota(
                session,
                size_bytes=size_bytes,
                max_total_bytes=settings.artifacts.max_total_bytes,
                already_stored=already_stored,
            )
            try:
                manifest = await asyncio.to_thread(
                    lambda: store.save_from_path(
                        filename=filename,
                        tmp_path=tmp_path,
                        sha256=sha256,
                        size_bytes=size_bytes,
                    )
                )
                published = True
                artifact = await svc.upsert_wheel(session, manifest)
                await session.commit()
            except BaseException:
                # Roll back a published-but-uncommitted body (R-04); only this
                # upload's new bytes, and the sha lock prevents a concurrent
                # same-sha request from being mid-publish.
                if published and not already_stored:
                    await asyncio.to_thread(store.remove_stored, sha256)
                raise
        return BuildArtifactUploadResponse(
            artifact=BuildArtifactView(**svc.build_artifact_view(artifact)),
            spiders=[],
        )
    finally:
        await cleanup_temp(tmp_path)
        release_quota(token)


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
