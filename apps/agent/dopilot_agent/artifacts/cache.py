"""Concurrency-safe Scrapy egg cache for agent runs."""

from __future__ import annotations

import asyncio
import hashlib
import os
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import httpx

from ..scrapyd.client import ScrapydClient, ScrapydError


class ArtifactCacheError(Exception):
    def __init__(self, message: str, *, detail: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.detail = detail or {}


class ScrapyArtifactCache:
    def __init__(
        self,
        *,
        root_dir: str | os.PathLike[str],
        server_url: str,
        server_shared_token: str = "",
        scrapyd: ScrapydClient,
        wait_timeout_seconds: float = 60.0,
    ) -> None:
        self._dir = Path(root_dir) / "scrapy"
        self._server_url = server_url.rstrip("/") + "/"
        self._token = server_shared_token
        self._scrapyd = scrapyd
        self._wait_timeout = wait_timeout_seconds

    def _egg_path(self, sha256: str) -> Path:
        return self._dir / f"{sha256}.egg"

    def _ready_path(self, sha256: str) -> Path:
        return self._dir / f"{sha256}.egg.ready"

    def _lock_path(self, sha256: str) -> Path:
        return self._dir / f"{sha256}.egg.lock"

    def _tmp_path(self, sha256: str, attempt_id: str) -> Path:
        return self._dir / f"{sha256}.egg.tmp.{os.getpid()}.{attempt_id}"

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"} if self._token else {}

    async def ensure(self, artifact: dict[str, Any], *, attempt_id: str) -> None:
        sha256 = str(artifact.get("hash") or artifact.get("sha256") or "")
        if not sha256:
            raise ArtifactCacheError("artifact hash is required")
        project = str(artifact.get("project") or "")
        version = str(artifact.get("version") or "")
        fetch_path = str(artifact.get("fetch_path") or f"/api/v1/artifacts/scrapy/{sha256}/egg")
        if not project or not version:
            raise ArtifactCacheError(
                "artifact project/version is required",
                detail={"hash": sha256},
            )

        self._dir.mkdir(parents=True, exist_ok=True)
        if self._ready_path(sha256).is_file():
            return

        deadline = asyncio.get_running_loop().time() + self._wait_timeout
        while True:
            if self._ready_path(sha256).is_file():
                return
            lock_fd = self._try_lock(sha256)
            if lock_fd is not None:
                try:
                    await self._fetch_verify_deploy(
                        sha256=sha256,
                        project=project,
                        version=version,
                        fetch_path=fetch_path,
                        attempt_id=attempt_id,
                    )
                    self._ready_path(sha256).write_text("", encoding="utf-8")
                    return
                finally:
                    os.close(lock_fd)
                    self._lock_path(sha256).unlink(missing_ok=True)
            if asyncio.get_running_loop().time() >= deadline:
                raise ArtifactCacheError(
                    "timed out waiting for artifact cache lock",
                    detail={"hash": sha256},
                )
            await asyncio.sleep(0.2)

    def _try_lock(self, sha256: str) -> int | None:
        try:
            return os.open(
                self._lock_path(sha256),
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                0o644,
            )
        except FileExistsError:
            return None

    async def _fetch_verify_deploy(
        self,
        *,
        sha256: str,
        project: str,
        version: str,
        fetch_path: str,
        attempt_id: str,
    ) -> None:
        egg_path = self._egg_path(sha256)
        if not egg_path.is_file() or self._sha256(egg_path) != sha256:
            tmp = self._tmp_path(sha256, attempt_id)
            tmp.unlink(missing_ok=True)
            url = urljoin(self._server_url, fetch_path.lstrip("/"))
            try:
                async with httpx.AsyncClient(timeout=60.0) as client:
                    resp = await client.get(url, headers=self._headers())
                    resp.raise_for_status()
            except httpx.HTTPError as exc:
                raise ArtifactCacheError(
                    "failed to fetch artifact",
                    detail={"hash": sha256, "url": url},
                ) from exc
            tmp.write_bytes(resp.content)
            if hashlib.sha256(resp.content).hexdigest() != sha256:
                tmp.unlink(missing_ok=True)
                raise ArtifactCacheError(
                    "artifact sha256 mismatch",
                    detail={"hash": sha256},
                )
            os.replace(tmp, egg_path)

        egg_bytes = egg_path.read_bytes()
        try:
            await self._scrapyd.addversion(project, version, egg_bytes)
        except ScrapydError as exc:
            raise ArtifactCacheError(
                "failed to deploy artifact to scrapyd",
                detail={"hash": sha256, "scrapyd": exc.detail},
            ) from exc

    @staticmethod
    def _sha256(path: Path) -> str:
        h = hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()
