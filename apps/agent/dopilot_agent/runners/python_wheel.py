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

# Read chunk for the stdout drain (resource caps, C2).
_DRAIN_CHUNK = 65536

# Sidecar file (resource caps, C1): holds the job's process-group id so the
# janitor can prove liveness even when the state JSON is missing/corrupt.
PGID_SIDECAR = "job.pgid"


def _job_log_truncation_marker(max_bytes: int) -> bytes:
    return (
        f"\n[dopilot:job-log-truncated max_bytes={max_bytes} "
        f"reason=size-cap]\n"
    ).encode()


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
        max_job_log_bytes: int = 0,
    ) -> None:
        self._root = Path(workspace_root)
        self._grace = grace_seconds
        # Resource caps (C2): per-job log size cap (0 = disabled).
        self._max_log_bytes = max_job_log_bytes
        self._procs: dict[str, asyncio.subprocess.Process] = {}
        self._pgids: dict[str, int] = {}
        self._logs: dict[str, object] = {}
        self._exits: dict[str, asyncio.Future[int]] = {}
        self._reapers: dict[str, asyncio.Task[None]] = {}
        self._drains: dict[str, asyncio.Task[None]] = {}
        self._canceled: set[str] = set()

    # --- layout ------------------------------------------------------------
    def workspace_for(self, execution_id: str) -> Path:
        return self._root / execution_id

    def log_path_for(self, execution_id: str) -> Path:
        return self.workspace_for(execution_id) / "job.log"

    def pgid_path_for(self, execution_id: str) -> Path:
        return self.workspace_for(execution_id) / PGID_SIDECAR

    def active_execution_ids(self) -> set[str]:
        """Execution ids with a live in-process subprocess (resource caps, C1/C4).

        The janitor uses this as the authoritative in-memory "running" set: an id
        here must never have its workspace/cache evicted.
        """
        return {
            eid
            for eid, proc in self._procs.items()
            if proc.returncode is None
        }

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
        # Resource caps (C2): capture stdout/stderr via a PIPE + drain task so the
        # runner can enforce the log size cap. The child MUST NOT block on a full
        # pipe, so the drain keeps reading (and discarding) past the cap.
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
                stdout=asyncio.subprocess.PIPE,
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

        # Resource caps (C1): write the pgid sidecar (atomic) right after spawn so
        # the janitor can prove liveness without relying on the state JSON. If the
        # sidecar cannot be written we must NOT leave a running-but-unattributable
        # job: kill it and fail the spawn.
        try:
            self._write_pgid_sidecar(execution_id, pgid)
        except OSError as exc:
            self._signal_group(pgid, signal.SIGKILL)
            log_fh.close()
            raise WheelRunnerError(
                "failed to write pgid sidecar",
                error_code="wheel_spawn_error",
                detail={"error": str(exc)},
            ) from exc

        self._procs[execution_id] = proc
        self._pgids[execution_id] = pgid
        self._logs[execution_id] = log_fh
        self._exits[execution_id] = asyncio.get_running_loop().create_future()
        self._drains[execution_id] = asyncio.create_task(
            self._drain(execution_id, proc, log_fh)
        )
        self._reapers[execution_id] = asyncio.create_task(
            self._reap(execution_id, proc)
        )

        return StartedWheel(
            pid=proc.pid,
            pgid=pgid,
            log_path=str(log_path),
            workspace_path=str(workspace),
        )

    def _write_pgid_sidecar(self, execution_id: str, pgid: int) -> None:
        """Atomically write ``{workspace}/job.pgid`` (resource caps, C1)."""
        path = self.pgid_path_for(execution_id)
        tmp = path.with_suffix(f".pgid.{os.getpid()}.tmp")
        tmp.write_text(str(pgid), encoding="utf-8")
        os.replace(tmp, path)

    async def _drain(
        self,
        execution_id: str,
        proc: asyncio.subprocess.Process,
        log_fh: object,
    ) -> None:
        """Pump child stdout into ``job.log`` under the size cap (C2).

        Keeps reading the pipe until EOF so the child NEVER blocks on a full pipe,
        even after the cap is hit: past the cap one truncation marker is written
        and further output is read-and-discarded. Blocking file writes are
        offloaded. Never raises — a drain failure must not affect the subprocess
        or its exit reporting.
        """
        cap = self._max_log_bytes
        reader = proc.stdout
        if reader is None:  # pragma: no cover - PIPE always sets stdout
            return
        written = 0
        truncated = False
        try:
            while True:
                chunk = await reader.read(_DRAIN_CHUNK)
                if not chunk:
                    break
                if truncated:
                    continue  # cap reached: keep draining, discard
                if cap <= 0:
                    await asyncio.to_thread(log_fh.write, chunk)
                    continue
                room = cap - written
                if len(chunk) <= room:
                    await asyncio.to_thread(log_fh.write, chunk)
                    written += len(chunk)
                else:
                    to_write = (
                        chunk[: max(0, room)]
                        + _job_log_truncation_marker(cap)
                    )
                    await asyncio.to_thread(log_fh.write, to_write)
                    truncated = True
        except Exception:  # noqa: BLE001 - drain must never break the job
            logger.exception("wheel drain failed for %s", execution_id)

    async def _reap(self, execution_id: str, proc: asyncio.subprocess.Process) -> None:
        try:
            rc = await proc.wait()
        except Exception:  # noqa: BLE001 - never let the reaper crash silently
            logger.exception("wheel reaper failed for %s", execution_id)
            rc = -1
        # Resource caps (C2): let the drain finish (reads until pipe EOF) before
        # closing the log handle, so no tail output is lost.
        drain = self._drains.get(execution_id)
        if drain is not None:
            try:
                await drain
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
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

    def forget(self, execution_id: str) -> None:
        """Drop all per-execution bookkeeping for a terminal job (C6).

        Called by the consumer once the execution is terminal AND its EOF has been
        published, so these dicts/sets do not grow for the process lifetime. Safe
        to call more than once (idempotent). The reaper/drain tasks have already
        completed by this point; the log handle is closed defensively.
        """
        self._close_log(execution_id)
        self._procs.pop(execution_id, None)
        self._pgids.pop(execution_id, None)
        self._exits.pop(execution_id, None)
        self._reapers.pop(execution_id, None)
        self._drains.pop(execution_id, None)
        self._canceled.discard(execution_id)

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
        for task in (*self._reapers.values(), *self._drains.values()):
            task.cancel()
        for task in (*self._reapers.values(), *self._drains.values()):
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        self._reapers.clear()
        self._drains.clear()
        for execution_id in list(self._logs.keys()):
            self._close_log(execution_id)
        # Drop stale bookkeeping so a reused runner keeps no dead handles.
        self._procs.clear()
        self._pgids.clear()
        self._exits.clear()
        self._canceled.clear()
