"""Scrapy artifact (egg) endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import FileResponse

from ...artifacts.scrapy_store import ScrapyArtifactManifest, ScrapyArtifactStore
from ...auth.agent_dependencies import require_server_token
from ...auth.dependencies import AdminContext, get_current_admin
from ...config.loader import get_settings
from ...config.settings import Settings
from .schemas import ArtifactsResponse, ArtifactView, EggDeployResult

router = APIRouter(tags=["artifacts"])


def _store(settings: Settings) -> ScrapyArtifactStore:
    return ScrapyArtifactStore(settings.artifacts.root_dir)


def _artifact_view(manifest: ScrapyArtifactManifest) -> ArtifactView:
    return ArtifactView(
        id=manifest.sha256,
        project=manifest.project,
        version=manifest.version,
        filename=manifest.filename,
        sha256=manifest.sha256,
        size_bytes=manifest.size_bytes,
        spiders=list(manifest.spiders),
        valid=manifest.valid,
        uploaded_at=manifest.uploaded_at,
        created_at=manifest.uploaded_at,
    )


@router.get("/artifacts/scrapy", response_model=ArtifactsResponse)
async def list_scrapy_artifacts(
    _admin: AdminContext = Depends(get_current_admin),
    settings: Settings = Depends(get_settings),
) -> ArtifactsResponse:
    artifacts = [_artifact_view(m) for m in _store(settings).list()]
    return ArtifactsResponse(artifacts=artifacts)


@router.post("/artifacts/scrapy/egg", response_model=EggDeployResult)
async def upload_scrapy_egg(
    file: UploadFile = File(...),
    project: str | None = Form(default=None),
    version: str | None = Form(default=None),
    _admin: AdminContext = Depends(get_current_admin),
    settings: Settings = Depends(get_settings),
) -> EggDeployResult:
    """Validate and store a Scrapy egg on the server filesystem.

    ``project`` and ``version`` are accepted for backward-compatible form posts.
    The stored artifact version is content-derived from sha256.
    """
    _ = version
    egg_bytes = await file.read()
    filename = file.filename or "crawler.egg"
    manifest = _store(settings).save(
        filename=filename, content=egg_bytes, project_hint=project
    )
    artifact = _artifact_view(manifest)
    return EggDeployResult(
        artifact=artifact,
        spiders=list(manifest.spiders),
        agent_id=None,
        endpoint=None,
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
