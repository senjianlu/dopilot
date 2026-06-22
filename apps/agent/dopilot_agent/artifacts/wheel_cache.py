"""Concurrency-safe Python-wheel install cache for agent runs (phase 2b).

Mirrors :class:`ScrapyArtifactCache` for ``.whl`` artifacts but, instead of
deploying an egg to scrapyd, installs the wheel ONCE per sha256 into a private
``site`` directory with::

    python -m pip install --no-deps --target <root>/python_wheel/<sha>/site <wheel>

``--no-deps`` is the user-selected phase-2b strategy: dopilot does NOT resolve or
install dependencies and never mutates the agent's main interpreter (no venv).
The agent runner injects the returned ``site`` directory onto ``PYTHONPATH`` when
launching the shell command.

Idempotency under concurrency uses the same primitive as the egg cache: a per-sha
``O_CREAT|O_EXCL`` lock file plus a ``.ready`` marker — once the marker exists the
install is reused, so a redelivered run (or a second concurrent run of the same
sha) never reinstalls.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import httpx


class WheelCacheError(Exception):
    def __init__(self, message: str, *, detail: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.detail = detail or {}


def _safe_wheel_name(filename: str, sha256: str) -> str:
    """A pip-acceptable wheel filename for the cached bytes.

    pip parses the wheel filename for name/version/tags, so the original
    ``{dist}-{ver}-...whl`` name is preserved when present (and sanitized of any
    path separators); otherwise a ``<sha>.whl`` fallback is used.
    """
    base = os.path.basename(filename or "")
    if base.lower().endswith(".whl"):
        return base
    return f"{sha256}.whl"


class PythonWheelCache:
    """Fetch + verify + install a Python wheel once per sha256."""

    def __init__(
        self,
        *,
        root_dir: str | os.PathLike[str],
        server_url: str,
        agent_token: str = "",
        python_executable: str | None = None,
        wait_timeout_seconds: float = 120.0,
        install_timeout_seconds: float = 300.0,
    ) -> None:
        self._dir = Path(root_dir) / "python_wheel"
        self._server_url = server_url.rstrip("/") + "/"
        self._token = agent_token
        self._python = python_executable or sys.executable
        self._wait_timeout = wait_timeout_seconds
        self._install_timeout = install_timeout_seconds

    # --- layout ------------------------------------------------------------
    def _sha_dir(self, sha256: str) -> Path:
        return self._dir / sha256

    def site_dir(self, sha256: str) -> Path:
        return self._sha_dir(sha256) / "site"

    def _ready_path(self, sha256: str) -> Path:
        return self._sha_dir(sha256) / ".ready"

    def _lock_path(self, sha256: str) -> Path:
        return self._sha_dir(sha256) / ".lock"

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"} if self._token else {}

    # --- public ------------------------------------------------------------
    async def ensure(self, artifact: dict[str, Any], *, execution_id: str) -> str:
        """Fetch + verify + install the wheel and return its ``site`` directory.

        Idempotent: a ``.ready`` marker short-circuits to the existing install.
        Raises :class:`WheelCacheError` (with a structured ``detail``) on a
        missing hash, fetch/verify failure, or a non-zero ``pip install``.
        """
        sha256 = str(artifact.get("hash") or artifact.get("sha256") or "")
        if not sha256:
            raise WheelCacheError("artifact hash is required")
        fetch_path = str(
            artifact.get("fetch_path")
            or f"/api/v1/artifacts/python_wheel/{sha256}/wheel"
        )
        filename = str(artifact.get("filename") or "")

        site = self.site_dir(sha256)
        self._sha_dir(sha256).mkdir(parents=True, exist_ok=True)
        if self._ready_path(sha256).is_file():
            return str(site)

        deadline = asyncio.get_running_loop().time() + self._wait_timeout
        while True:
            if self._ready_path(sha256).is_file():
                return str(site)
            lock_fd = self._try_lock(sha256)
            if lock_fd is not None:
                try:
                    await self._fetch_verify_install(
                        sha256=sha256,
                        fetch_path=fetch_path,
                        filename=filename,
                        execution_id=execution_id,
                    )
                    self._ready_path(sha256).write_text("", encoding="utf-8")
                    return str(site)
                finally:
                    os.close(lock_fd)
                    self._lock_path(sha256).unlink(missing_ok=True)
            if asyncio.get_running_loop().time() >= deadline:
                raise WheelCacheError(
                    "timed out waiting for wheel cache lock",
                    detail={"hash": sha256},
                )
            await asyncio.sleep(0.2)

    # --- internals ---------------------------------------------------------
    def _try_lock(self, sha256: str) -> int | None:
        try:
            return os.open(
                self._lock_path(sha256),
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                0o644,
            )
        except FileExistsError:
            return None

    async def _fetch_verify_install(
        self,
        *,
        sha256: str,
        fetch_path: str,
        filename: str,
        execution_id: str,
    ) -> None:
        wheel_path = self._sha_dir(sha256) / _safe_wheel_name(filename, sha256)
        if not wheel_path.is_file() or self._sha256(wheel_path) != sha256:
            tmp = wheel_path.with_suffix(f".tmp.{os.getpid()}.{execution_id}")
            tmp.unlink(missing_ok=True)
            url = urljoin(self._server_url, fetch_path.lstrip("/"))
            try:
                async with httpx.AsyncClient(timeout=60.0) as client:
                    resp = await client.get(url, headers=self._headers())
                    resp.raise_for_status()
            except httpx.HTTPError as exc:
                raise WheelCacheError(
                    "failed to fetch wheel artifact",
                    detail={"hash": sha256, "url": url},
                ) from exc
            if hashlib.sha256(resp.content).hexdigest() != sha256:
                raise WheelCacheError(
                    "wheel artifact sha256 mismatch",
                    detail={"hash": sha256},
                )
            tmp.write_bytes(resp.content)
            os.replace(tmp, wheel_path)

        site = self.site_dir(sha256)
        site.mkdir(parents=True, exist_ok=True)
        await self._pip_install(wheel_path, site, sha256=sha256)

    async def _pip_install(self, wheel_path: Path, site: Path, *, sha256: str) -> None:
        try:
            proc = await asyncio.create_subprocess_exec(
                self._python,
                "-m",
                "pip",
                "install",
                "--no-deps",
                "--target",
                str(site),
                str(wheel_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
        except OSError as exc:
            raise WheelCacheError(
                "failed to launch pip",
                detail={"hash": sha256, "error": str(exc)},
            ) from exc
        try:
            out, _ = await asyncio.wait_for(
                proc.communicate(), timeout=self._install_timeout
            )
        except TimeoutError as exc:
            proc.kill()
            await proc.wait()
            raise WheelCacheError(
                "pip install timed out",
                detail={"hash": sha256},
            ) from exc
        if proc.returncode != 0:
            raise WheelCacheError(
                "pip install failed",
                detail={
                    "hash": sha256,
                    "returncode": proc.returncode,
                    "output": (out or b"").decode("utf-8", "replace")[-2000:],
                },
            )

    @staticmethod
    def _sha256(path: Path) -> str:
        h = hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()
