"""Seed built-in demo artifacts into the configured artifact store."""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from ..artifacts.scrapy_store import ScrapyArtifactStore, validate_egg
from ..artifacts.wheel_store import WheelArtifactStore, validate_wheel
from ..config.settings import Settings
from . import artifacts as artifact_svc

DEFAULT_BUILTIN_ARTIFACTS_DIR = "/app/builtin-artifacts"


async def _seed_scrapy(
    session: AsyncSession, store: ScrapyArtifactStore, path: Path
) -> bool:
    content = path.read_bytes()
    manifest = validate_egg(filename=path.name, content=content)
    existing = await artifact_svc.get_by_type_hash(
        session, "scrapy", manifest.sha256
    )
    store_complete = (
        store.egg_path(manifest.sha256).is_file()
        and store.manifest_path(manifest.sha256).is_file()
    )
    if existing is not None and store_complete:
        return False
    if not store_complete:
        manifest = store.save(filename=path.name, content=content)
    if existing is None:
        await artifact_svc.upsert_scrapy(session, manifest)
        return True
    return False


async def _seed_wheel(
    session: AsyncSession, store: WheelArtifactStore, path: Path
) -> bool:
    content = path.read_bytes()
    manifest = validate_wheel(filename=path.name, content=content)
    existing = await artifact_svc.get_by_type_hash(
        session, "python_wheel", manifest.sha256
    )
    store_complete = (
        store.wheel_path(manifest.sha256).is_file()
        and store.manifest_path(manifest.sha256).is_file()
    )
    if existing is not None and store_complete:
        return False
    if not store_complete:
        manifest = store.save(filename=path.name, content=content)
    if existing is None:
        await artifact_svc.upsert_wheel(session, manifest)
        return True
    return False


async def seed_builtin_artifacts(
    session: AsyncSession,
    settings: Settings,
    *,
    builtin_root: str | os.PathLike[str] | None = None,
) -> None:
    """Import baked demo artifacts on every server startup.

    Stores are content-addressed by sha256, so unchanged built-ins are
    idempotent. If the bundled default crawler/script changes, the new bytes get
    a new hash and a new ``build_artifacts`` row; older/user-uploaded artifacts
    remain untouched.
    """
    root = Path(
        builtin_root
        or os.getenv("DOPILOT_BUILTIN_ARTIFACTS_DIR")
        or DEFAULT_BUILTIN_ARTIFACTS_DIR
    )
    if not root.is_dir():
        return

    changed = False
    scrapy_store = ScrapyArtifactStore(settings.artifacts.root_dir)
    for egg in sorted((root / "scrapy").glob("*.egg")):
        changed = await _seed_scrapy(session, scrapy_store, egg) or changed

    wheel_store = WheelArtifactStore(settings.artifacts.root_dir)
    for wheel in sorted((root / "python_wheel").glob("*.whl")):
        changed = await _seed_wheel(session, wheel_store, wheel) or changed

    if changed:
        await session.commit()
