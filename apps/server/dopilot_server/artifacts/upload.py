"""Bounded artifact-upload helpers (resource caps, B5).

Uploads used to be read whole into RAM (``await file.read()``) and handed to a
``bytes``-based store, so a single large upload could exhaust memory and disk and
nothing bounded the aggregate store size. This module replaces that with:

- :func:`stream_to_staging` — read the ``UploadFile`` in bounded chunks straight
  to a temp file under ``{root}/staging`` (same volume as the final store, so the
  store can publish it with an atomic ``os.replace``), computing the sha256 and
  size on the way and rejecting with HTTP 413 the moment the per-upload cap is
  exceeded. RAM stays bounded to one chunk.
- :func:`reserve_quota` / :func:`release_quota` — a process-wide aggregate size
  quota. Before a NEW artifact's bytes are published, the current stored total
  (sum of ``build_artifacts.size_bytes``) plus in-flight reservations plus this
  upload is checked under a lock; over the quota it raises HTTP 507. Archived
  artifacts are never auto-deleted (product decision), so the quota bounds growth
  by refusing new uploads. Single-server only (the lock is in-process).
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import itertools
import os
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from ..errors import ApiError
from ..services.artifacts import stored_total_bytes

_CHUNK = 1024 * 1024  # 1 MiB read/write chunk — bounds RAM per upload.
_STAGING = "staging"

# Aggregate-quota reservation state (single-server, in-process). The lock makes
# "read current total + reserve" atomic so two concurrent uploads that each fit
# alone but together exceed the quota cannot both be admitted.
_quota_lock = asyncio.Lock()
_in_flight: dict[int, int] = {}
_reservation_ids = itertools.count()

# Per-SHA publish serialization (resource caps, R-03). Two concurrent uploads of
# the SAME content must not interleave existence-check / publish / DB-commit /
# rollback, or a failing request could delete the body a concurrent COMMITTED
# request now references. Refcounted keyed lock: created on first use, removed
# when the last holder/waiter leaves (atomic get-or-create + refcount on one
# event loop, no await between). Same shape as the agent's execution lock.
_publish_locks: dict[str, list] = {}


@contextlib.asynccontextmanager
async def publish_lock(sha256: str) -> AsyncIterator[None]:
    """Serialize the check→publish→commit→rollback critical section per sha256."""
    entry = _publish_locks.get(sha256)
    if entry is None:
        entry = [asyncio.Lock(), 0]
        _publish_locks[sha256] = entry
    entry[1] += 1
    lock: asyncio.Lock = entry[0]
    await lock.acquire()
    try:
        yield
    finally:
        lock.release()
        entry[1] -= 1
        if entry[1] == 0 and _publish_locks.get(sha256) is entry:
            del _publish_locks[sha256]


def _staging_dir(root_dir: str) -> Path:
    return Path(root_dir) / _STAGING


async def stream_to_staging(
    file: UploadFile, root_dir: str, max_upload_bytes: int
) -> tuple[Path, int, str]:
    """Stream ``file`` to a temp file, returning ``(tmp_path, size, sha256)``.

    Reads in :data:`_CHUNK`-sized chunks (RAM bounded to one chunk). Raises
    :class:`ApiError` 413 as soon as ``max_upload_bytes`` (when > 0) is exceeded,
    unlinking the partial temp file. Blocking file writes are offloaded to a
    thread so the event loop is never blocked.
    """
    staging = _staging_dir(root_dir)
    await asyncio.to_thread(staging.mkdir, parents=True, exist_ok=True)
    tmp = staging / f"upload.{os.getpid()}.{next(_reservation_ids)}.tmp"
    hasher = hashlib.sha256()
    size = 0
    try:
        out = await asyncio.to_thread(open, tmp, "wb")
        try:
            while True:
                chunk = await file.read(_CHUNK)
                if not chunk:
                    break
                size += len(chunk)
                if max_upload_bytes > 0 and size > max_upload_bytes:
                    raise ApiError(
                        413,
                        "artifact.too_large",
                        "errors.artifactTooLarge",
                        {"max_upload_bytes": max_upload_bytes},
                    )
                hasher.update(chunk)
                await asyncio.to_thread(out.write, chunk)
        finally:
            await asyncio.to_thread(out.close)
    except BaseException:
        await asyncio.to_thread(_unlink, tmp)
        raise
    return tmp, size, hasher.hexdigest()


def _unlink(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


async def cleanup_temp(path: Path | None) -> None:
    """Best-effort remove a staging temp file (offloaded). Safe if already gone."""
    if path is not None:
        await asyncio.to_thread(_unlink, path)


async def reserve_quota(
    session: AsyncSession,
    *,
    size_bytes: int,
    max_total_bytes: int,
    already_stored: bool,
) -> int | None:
    """Reserve ``size_bytes`` against the aggregate store quota.

    Returns a reservation token to pass to :func:`release_quota`, or ``None`` when
    no reservation is needed (quota disabled, or the artifact's bytes are already
    on disk so publishing adds nothing). Raises :class:`ApiError` 507 when the
    stored total + in-flight reservations + this upload would exceed the quota.
    """
    if max_total_bytes <= 0 or already_stored or size_bytes <= 0:
        return None
    async with _quota_lock:
        current = await stored_total_bytes(session)
        reserved = sum(_in_flight.values())
        if current + reserved + size_bytes > max_total_bytes:
            raise ApiError(
                507,
                "artifact.quota_exceeded",
                "errors.artifactQuotaExceeded",
                {
                    "max_total_bytes": max_total_bytes,
                    "stored_bytes": current + reserved,
                    "upload_bytes": size_bytes,
                },
            )
        token = next(_reservation_ids)
        _in_flight[token] = size_bytes
        return token


def release_quota(token: int | None) -> None:
    """Release a reservation from :func:`reserve_quota` (idempotent)."""
    if token is not None:
        _in_flight.pop(token, None)
