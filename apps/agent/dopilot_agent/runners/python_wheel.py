"""Python-wheel shell-command runner (phase 2b packet 2).

Launches ``/bin/sh -c <shell_command>`` in its own session (process group) with
the installed wheel ``site`` directory on ``PYTHONPATH``, merging child stdout +
stderr into one ``job.log`` so the existing :class:`LogPublisher` tails the same
single ``log`` stream the Scrapy path uses.

Lifecycle (driven by :class:`CommandConsumer`):

- :meth:`start` spawns the child (``start_new_session=True``), records the
  pid/pgid, and starts a private reaper that resolves :meth:`wait` once the
  child exits (so ``wait`` can be awaited by the consumer's background task
  without racing the cancel path on ``Process.wait``);
- :meth:`wait` returns the :class:`WheelOutcome` (exit code + whether a cancel
  was requested) — the consumer maps it to ``finished`` / ``failed``;
- :meth:`terminate` implements the SIGTERM -> grace -> SIGKILL flow against the
  whole process group, used by both ``cancel`` and ``reclaim``;
- :meth:`terminate_pgid` is the best-effort orphan kill used by boot recovery,
  when no in-process handle exists.

This runner never resolves dependencies and never touches the agent's main
interpreter — the wheel was installed with ``pip install --no-deps --target``
by :class:`PythonWheelCache`.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# Hard-coded SIGTERM grace before SIGKILL (brief: "wait a hard-coded 10
# seconds"). Overridable in the ctor only so tests can exercise the SIGKILL
# branch without a real 10s sleep.
TERM_GRACE_SECONDS = 10.0


class WheelRunnerError(Exception):
    """A wheel spawn/working-dir error; carries a structured detail payload."""

    def __init__(
        self,
        message: str,
        *,
        error_code: str = "wheel_spawn_error",
        detail: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.detail: dict = detail if detail is not None else {}


@dataclass
class StartedWheel:
    pid: int
    pgid: int
    log_path: str
    workspace_path: str


@dataclass
class WheelOutcome:
    exit_code: int
    canceled: bool


class PythonWheelRunner:
    """Spawn/stop/track ``/bin/sh -c`` shell-command jobs for Python wheels."""

    def __init__(
        self,
        *,
        workspace_root: str | Path,
        grace_seconds: float = TERM_GRACE_SECONDS,
    ) -> None:
        self._root = Path(workspace_root)
        self._grace = grace_seconds
        self._procs: dict[str, asyncio.subprocess.Process] = {}
        self._pgids: dict[str, int] = {}
        self._logs: dict[str, object] = {}
        self._exits: dict[str, asyncio.Future[int]] = {}
        self._reapers: dict[str, asyncio.Task[None]] = {}
        self._canceled: set[str] = set()

    # --- layout ------------------------------------------------------------
    def workspace_for(self, execution_id: str) -> Path:
        return self._root / execution_id

    def log_path_for(self, execution_id: str) -> Path:
        return self.workspace_for(execution_id) / "job.log"

    def _resolve_cwd(self, workspace: Path, working_dir: str | None) -> Path:
        """Resolve ``working_dir`` under the workspace; reject escapes.

        Absolute paths and any ``..`` component are rejected (a wheel run must
        stay inside its per-execution workspace).
        """
        if not working_dir:
            return workspace
        candidate = Path(working_dir)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise WheelRunnerError(
                "invalid working_dir",
                error_code="working_dir_invalid",
                detail={"working_dir": working_dir},
            )
        resolved = (workspace / candidate).resolve()
        if resolved != workspace.resolve() and workspace.resolve() not in resolved.parents:
            raise WheelRunnerError(
                "working_dir escapes workspace",
                error_code="working_dir_invalid",
                detail={"working_dir": working_dir},
            )
        return resolved

    # --- lifecycle ---------------------------------------------------------
    async def start(
        self,
        *,
        execution_id: str,
        task_id: str,
        shell_command: str,
        install_path: str,
        working_dir: str | None = None,
        env: dict[str, str] | None = None,
        runtime_context: dict[str, str] | None = None,
    ) -> StartedWheel:
        """Spawn the shell command and begin reaping it. Returns process info."""
        workspace = self.workspace_for(execution_id)
        workspace.mkdir(parents=True, exist_ok=True)
        cwd = self._resolve_cwd(workspace, working_dir)
        cwd.mkdir(parents=True, exist_ok=True)

        log_path = self.log_path_for(execution_id)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_fh = open(log_path, "ab", buffering=0)  # noqa: SIM115 - closed in reaper

        child_env = dict(os.environ)
        site = str(install_path)
        existing_pp = child_env.get("PYTHONPATH", "")
        child_env["PYTHONPATH"] = (
            site + (os.pathsep + existing_pp if existing_pp else "")
        )
        # Force unbuffered output so the tailed log is timely; a future task env
        # may override it (the server currently emits ``env={}``).
        child_env["PYTHONUNBUFFERED"] = "1"
        for key, value in (env or {}).items():
            child_env[str(key)] = str(value)
        # Dopilot-owned context wins at the final child-environment merge point.
        for key, value in (runtime_context or {}).items():
            child_env[str(key)] = str(value)

        try:
            proc = await asyncio.create_subprocess_exec(
                "/bin/sh",
                "-c",
                shell_command,
                cwd=str(cwd),
                env=child_env,
                stdout=log_fh,
                stderr=asyncio.subprocess.STDOUT,
                start_new_session=True,
            )
        except OSError as exc:
            log_fh.close()
            raise WheelRunnerError(
                "failed to spawn shell command",
                error_code="wheel_spawn_error",
                detail={"error": str(exc)},
            ) from exc

        try:
            pgid = os.getpgid(proc.pid)
        except ProcessLookupError:
            # Child already exited; its own pid is its group leader id.
            pgid = proc.pid

        self._procs[execution_id] = proc
        self._pgids[execution_id] = pgid
        self._logs[execution_id] = log_fh
        self._exits[execution_id] = asyncio.get_running_loop().create_future()
        self._reapers[execution_id] = asyncio.create_task(
            self._reap(execution_id, proc)
        )

        return StartedWheel(
            pid=proc.pid,
            pgid=pgid,
            log_path=str(log_path),
            workspace_path=str(workspace),
        )

    async def _reap(self, execution_id: str, proc: asyncio.subprocess.Process) -> None:
        try:
            rc = await proc.wait()
        except Exception:  # noqa: BLE001 - never let the reaper crash silently
            logger.exception("wheel reaper failed for %s", execution_id)
            rc = -1
        self._close_log(execution_id)
        fut = self._exits.get(execution_id)
        if fut is not None and not fut.done():
            fut.set_result(rc)

    async def wait(self, execution_id: str) -> WheelOutcome:
        """Await the child's exit and return its outcome."""
        fut = self._exits.get(execution_id)
        if fut is None:
            return WheelOutcome(
                exit_code=-1, canceled=execution_id in self._canceled
            )
        rc = await fut
        return WheelOutcome(exit_code=rc, canceled=execution_id in self._canceled)

    async def terminate(self, execution_id: str) -> None:
        """SIGTERM the process group, wait the grace, then SIGKILL survivors."""
        self._canceled.add(execution_id)
        pgid = self._pgids.get(execution_id)
        proc = self._procs.get(execution_id)
        if pgid is None and proc is None:
            return  # nothing in-process to signal (process_missing)

        if pgid is not None:
            self._signal_group(pgid, signal.SIGTERM)

        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._grace
        while proc is not None and proc.returncode is None and loop.time() < deadline:
            await asyncio.sleep(0.05)
        if proc is not None and proc.returncode is None and pgid is not None:
            self._signal_group(pgid, signal.SIGKILL)
        # Ensure the child is reaped (its returncode resolved) before returning.
        if proc is not None:
            try:
                await asyncio.wait_for(self.wait(execution_id), timeout=self._grace)
            except TimeoutError:
                logger.warning("wheel %s did not reap after SIGKILL", execution_id)

    @staticmethod
    def terminate_pgid(pgid: int) -> None:
        """Best-effort orphan kill (boot recovery): SIGTERM then SIGKILL a group."""
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.killpg(pgid, sig)
            except (ProcessLookupError, PermissionError, OSError):
                return

    # --- helpers -----------------------------------------------------------
    @staticmethod
    def _signal_group(pgid: int, sig: int) -> None:
        try:
            os.killpg(pgid, sig)
        except (ProcessLookupError, PermissionError, OSError):
            pass

    def _close_log(self, execution_id: str) -> None:
        fh = self._logs.pop(execution_id, None)
        if fh is not None:
            try:
                fh.close()
            except OSError:
                pass

    async def aclose(self) -> None:
        """Terminate live children, then cancel reapers and close log handles.

        Shutdown cleanup: any wheel subprocess still tracked is killed with the
        same SIGTERM -> grace -> SIGKILL flow used by cancel/reclaim and reaped
        (its reaper resolves the exit future and closes the log handle) BEFORE
        we cancel any surviving reapers — otherwise a job launched with
        ``start_new_session=True`` would outlive agent shutdown. This emits no
        terminal events itself: terminal mapping stays the consumer's job, and
        the consumer already cancels its wait tasks before calling ``aclose``.
        """
        for execution_id in list(self._procs.keys()):
            proc = self._procs.get(execution_id)
            if proc is None or proc.returncode is not None:
                continue
            try:
                await self.terminate(execution_id)
            except Exception:  # noqa: BLE001 - best-effort; never block shutdown
                logger.exception("wheel shutdown terminate failed for %s", execution_id)
        for task in list(self._reapers.values()):
            task.cancel()
        for task in list(self._reapers.values()):
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        self._reapers.clear()
        for execution_id in list(self._logs.keys()):
            self._close_log(execution_id)
        # Drop stale bookkeeping so a reused runner keeps no dead handles.
        self._procs.clear()
        self._pgids.clear()
        self._exits.clear()
        self._canceled.clear()
