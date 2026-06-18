"""Manage the local scrapyd child process.

The agent owns a single scrapyd subprocess bound to ``127.0.0.1:{port}`` (a
container-internal port never exposed to the host). :class:`ScrapydProcess`:

- writes a ``scrapyd.conf`` under ``{workdir}/scrapyd`` pointing scrapyd's
  ``eggs_dir`` / ``logs_dir`` / ``dbs_dir`` / ``items_dir`` into the workdir,
- launches the ``scrapyd`` console binary with ``cwd`` set to that dir so it
  reads the conf,
- best-effort installs ``PR_SET_PDEATHSIG`` so the child dies with the agent
  (glibc only; wrapped so non-Linux/musl still starts),
- reaps the child on ``stop()``.

The base image must be glibc (slim/debian), not Alpine: musl does not satisfy
the prctl parent-death signaling used here.
"""

from __future__ import annotations

import ctypes
import os
import signal
import subprocess
from pathlib import Path

# PR_SET_PDEATHSIG from <sys/prctl.h>; the child is signaled when the agent
# (its parent) dies, so a crashed agent never orphans scrapyd.
_PR_SET_PDEATHSIG = 1


def _set_pdeathsig() -> None:
    """Best-effort: ask the kernel to SIGTERM this child when its parent dies.

    glibc-only and silently skipped if libc/prctl is unavailable (e.g. musl),
    so the subprocess still launches on platforms without it.
    """
    try:
        libc = ctypes.CDLL("libc.so.6", use_errno=True)
        libc.prctl(_PR_SET_PDEATHSIG, signal.SIGTERM)
    except Exception:
        # Non-Linux / musl / no libc: parent-death signaling is best-effort.
        pass


class ScrapydProcess:
    """Lifecycle manager for the agent's local scrapyd subprocess."""

    def __init__(
        self,
        *,
        workdir: str | os.PathLike[str],
        host: str = "127.0.0.1",
        port: int = 6801,
        executable: str = "scrapyd",
    ) -> None:
        self._scrapyd_dir = Path(workdir) / "scrapyd"
        self._host = host
        self._port = port
        self._executable = executable
        self._proc: subprocess.Popen[bytes] | None = None

    @property
    def host(self) -> str:
        return self._host

    @property
    def port(self) -> int:
        return self._port

    @property
    def base_url(self) -> str:
        return f"http://{self._host}:{self._port}"

    @property
    def pid(self) -> int | None:
        return self._proc.pid if self._proc is not None else None

    @property
    def scrapyd_dir(self) -> Path:
        return self._scrapyd_dir

    def logs_dir(self) -> Path:
        return self._scrapyd_dir / "logs"

    def is_running(self) -> bool:
        """True iff a child process is alive (poll() returns None)."""
        return self._proc is not None and self._proc.poll() is None

    def _ensure_dirs(self) -> dict[str, Path]:
        dirs = {
            "eggs_dir": self._scrapyd_dir / "eggs",
            "logs_dir": self._scrapyd_dir / "logs",
            "dbs_dir": self._scrapyd_dir / "dbs",
            "items_dir": self._scrapyd_dir / "items",
        }
        for path in dirs.values():
            path.mkdir(parents=True, exist_ok=True)
        return dirs

    def write_conf(self) -> Path:
        """Write ``scrapyd.conf`` into the scrapyd dir and return its path."""
        dirs = self._ensure_dirs()
        conf_path = self._scrapyd_dir / "scrapyd.conf"
        conf = (
            "[scrapyd]\n"
            f"bind_address = {self._host}\n"
            f"http_port    = {self._port}\n"
            f"eggs_dir     = {dirs['eggs_dir']}\n"
            f"logs_dir     = {dirs['logs_dir']}\n"
            f"dbs_dir      = {dirs['dbs_dir']}\n"
            f"items_dir    = {dirs['items_dir']}\n"
        )
        conf_path.write_text(conf, encoding="utf-8")
        return conf_path

    def start(self) -> None:
        """Launch scrapyd (idempotent: a no-op if already running)."""
        if self.is_running():
            return
        self.write_conf()
        # cwd = scrapyd dir so scrapyd picks up our scrapyd.conf.
        self._proc = subprocess.Popen(  # noqa: S603 - fixed executable, no shell
            [self._executable],
            cwd=str(self._scrapyd_dir),
            preexec_fn=_set_pdeathsig,  # noqa: PLW1509 - intentional parent-death
        )

    def stop(self, timeout: float = 10.0) -> None:
        """Terminate scrapyd and reap it (idempotent)."""
        proc = self._proc
        if proc is None:
            return
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=timeout)
        self._proc = None
