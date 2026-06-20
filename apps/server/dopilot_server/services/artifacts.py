"""Build-artifact service (phase 1.8): canonical ``build_artifacts`` rows.

A :class:`BuildArtifact` is the canonical product entity (the *thing that runs*).
Phase 1.8 only makes Scrapy eggs runnable, so the only writer here is the Scrapy
egg upload: after the filesystem manifest is written, :func:`upsert_scrapy`
creates or returns the matching row, deduped on ``(artifact_type, content_hash)``
= ``("scrapy", sha256)``.

Listing reconciles the on-disk Scrapy store into ``build_artifacts`` first, so a
deployment that has eggs on disk but a fresh DB (or whose rows predate this
table) still surfaces every artifact — the runtime equivalent of the migration
backfill. PostgreSQL stays the source of truth; the filesystem store keeps the
egg bodies.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..artifacts.scrapy_store import ScrapyArtifactManifest, ScrapyArtifactStore
from ..errors import ApiError
from ..models.execution import BuildArtifact
from . import states
from .executions import _iso, new_id


def scrapy_fetch_path(sha256: str) -> str:
    """The server egg-download path an agent uses to fetch a Scrapy artifact."""
    return f"/api/v1/artifacts/scrapy/{sha256}/egg"


def _scrapy_metadata(manifest: ScrapyArtifactManifest) -> dict[str, Any]:
    return {
        "project": manifest.project,
        "version": manifest.version,
        "spiders": list(manifest.spiders),
        "fetch_path": scrapy_fetch_path(manifest.sha256),
    }


async def get_by_type_hash(
    session: AsyncSession, artifact_type: str, content_hash: str
) -> BuildArtifact | None:
    result = await session.execute(
        select(BuildArtifact).where(
            BuildArtifact.artifact_type == artifact_type,
            BuildArtifact.content_hash == content_hash,
        )
    )
    return result.scalar_one_or_none()


async def upsert_scrapy(
    session: AsyncSession, manifest: ScrapyArtifactManifest
) -> BuildArtifact:
    """Create or return the ``scrapy``/``egg`` build artifact for ``manifest``.

    Deduped on ``("scrapy", sha256)``. An existing row's metadata is refreshed
    from the manifest (spiders/project/version may have been re-derived). The
    caller commits.
    """
    existing = await get_by_type_hash(
        session, states.ARTIFACT_SCRAPY, manifest.sha256
    )
    metadata = _scrapy_metadata(manifest)
    if existing is not None:
        existing.name = manifest.project or manifest.filename
        existing.filename = manifest.filename
        existing.size_bytes = manifest.size_bytes
        existing.artifact_metadata = metadata
        return existing
    artifact = BuildArtifact(
        id=new_id(),
        artifact_type=states.ARTIFACT_SCRAPY,
        package_format=states.ARTIFACT_PACKAGE_FORMAT[states.ARTIFACT_SCRAPY],
        name=manifest.project or manifest.filename,
        filename=manifest.filename,
        content_hash=manifest.sha256,
        size_bytes=manifest.size_bytes,
        artifact_metadata=metadata,
    )
    session.add(artifact)
    return artifact


async def reconcile_scrapy_store(
    session: AsyncSession, store: ScrapyArtifactStore
) -> None:
    """Backfill ``build_artifacts`` from on-disk Scrapy manifests (idempotent)."""
    changed = False
    for manifest in store.list():
        existing = await get_by_type_hash(
            session, states.ARTIFACT_SCRAPY, manifest.sha256
        )
        if existing is None:
            await upsert_scrapy(session, manifest)
            changed = True
    if changed:
        await session.commit()


async def list_build_artifacts(session: AsyncSession) -> list[BuildArtifact]:
    result = await session.execute(
        select(BuildArtifact).order_by(BuildArtifact.created_at.desc())
    )
    return list(result.scalars().all())


async def get_build_artifact(
    session: AsyncSession, artifact_id: str
) -> BuildArtifact | None:
    result = await session.execute(
        select(BuildArtifact).where(BuildArtifact.id == artifact_id)
    )
    return result.scalar_one_or_none()


async def get_build_artifact_or_404(
    session: AsyncSession, artifact_id: str
) -> BuildArtifact:
    artifact = await get_build_artifact(session, artifact_id)
    if artifact is None:
        raise ApiError(
            404,
            "artifact.not_found",
            "errors.artifactNotFound",
            {"artifact_id": artifact_id},
        )
    return artifact


async def get_runnable_artifact_or_404(
    session: AsyncSession, artifact_id: str
) -> BuildArtifact:
    """Resolve a build artifact that is runnable in phase 1.8 (scrapy/egg)."""
    artifact = await get_build_artifact_or_404(session, artifact_id)
    if artifact.artifact_type not in states.RUNNABLE_ARTIFACT_TYPES:
        raise ApiError(
            400,
            "artifact.not_runnable",
            "errors.artifactNotRunnable",
            {
                "artifact_id": artifact_id,
                "artifact_type": artifact.artifact_type,
            },
        )
    return artifact


def artifact_snapshot(artifact: BuildArtifact) -> dict[str, Any]:
    """The immutable build-artifact descriptor frozen onto a task snapshot."""
    meta = dict(artifact.artifact_metadata or {})
    return {
        "id": artifact.id,
        "artifact_type": artifact.artifact_type,
        "package_format": artifact.package_format,
        "name": artifact.name,
        "filename": artifact.filename,
        "content_hash": artifact.content_hash,
        "size_bytes": artifact.size_bytes,
        "project": meta.get("project"),
        "version": meta.get("version"),
        "spiders": list(meta.get("spiders") or []),
        "fetch_path": meta.get("fetch_path"),
    }


def build_artifact_view(artifact: BuildArtifact) -> dict[str, Any]:
    meta = dict(artifact.artifact_metadata or {})
    return {
        "id": artifact.id,
        "artifact_type": artifact.artifact_type,
        "package_format": artifact.package_format,
        "name": artifact.name,
        "filename": artifact.filename,
        "content_hash": artifact.content_hash,
        "size_bytes": artifact.size_bytes,
        "project": meta.get("project"),
        "version": meta.get("version"),
        "spiders": list(meta.get("spiders") or []),
        "fetch_path": meta.get("fetch_path"),
        "runnable": artifact.artifact_type in states.RUNNABLE_ARTIFACT_TYPES,
        "created_at": _iso(artifact.created_at),
        "updated_at": _iso(artifact.updated_at),
    }
