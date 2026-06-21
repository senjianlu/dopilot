"""Atomic per-attempt JSON state store.

:class:`AttemptState` is the persisted mapping for one execution attempt.
:class:`StateStore` reads/writes/deletes/lists those files under
``{workdir}/state/executions``.

Naming (phase 2a clean-cut): the state file is keyed by the atomic
``execution_id`` (= server ``Execution.id``); ``task_id`` (= ``Task.id``) is
carried for context.

Durability rules:
- writes go to a temp file in the same directory then ``os.replace`` onto the
  final path, so a crash never leaves a half-written ``{execution_id}.json``;
- reads of a missing OR corrupt/half-written file return ``None`` (never raise
  to the caller), so a torn file behaves exactly like "no state".
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


def _utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()


class AttemptState(BaseModel):
    """Persisted state for one execution attempt.

    ``scrapyd_job_id`` is the job id local scrapyd assigned; ``log_path`` is the
    absolute path scrapyd writes the job log to. ``canceled`` records that a
    stop succeeded so ``/status`` can report ``canceled`` rather than
    ``finished`` for a job that left the running list after a cancel.

    Phase 1.5 two-phase CAS + terminal marker (cross-restart idempotency):
    - ``phase`` = ``reserved`` (O_EXCL placeholder, spawn not yet done) ->
      ``started`` (scrapyd job scheduled) -> ``done`` (a terminal was reported).
    - ``result`` / ``lost_reason`` / ``error_code`` / ``exit_code`` record the
      reported terminal so a re-delivered command re-emits it instead of
      restarting the spider.
    """

    task_id: str
    execution_id: str
    scrapyd_job_id: str = ""
    project: str = ""
    version: str | None = None
    spider: str = ""
    log_path: str = ""
    phase: str = "started"
    result: str | None = None
    lost_reason: str | None = None
    error_code: str | None = None
    exit_code: int | None = None
    created_at: str = Field(default_factory=_utcnow_iso)
    updated_at: str = Field(default_factory=_utcnow_iso)
    canceled: bool = False

    # --- phase 2b: additive runner/process fields (default keeps Scrapy state
    # files loading unchanged; ``runner_type`` defaults to ``scrapy``). -------
    runner_type: str = "scrapy"
    pid: int | None = None
    pgid: int | None = None
    workspace_path: str = ""
    install_path: str = ""
    shell_command: str = ""


class StateStore:
    """File-backed store of :class:`AttemptState` under a state directory."""

    def __init__(self, base_dir: str | os.PathLike[str]) -> None:
        # {workdir}/state/executions
        self._dir = Path(base_dir)

    @property
    def dir(self) -> Path:
        return self._dir

    def path_for(self, execution_id: str) -> Path:
        return self._dir / f"{execution_id}.json"

    def write(self, state: AttemptState) -> AttemptState:
        """Atomically persist ``state`` (refreshing ``updated_at``)."""
        state.updated_at = _utcnow_iso()
        self._dir.mkdir(parents=True, exist_ok=True)
        final = self.path_for(state.execution_id)
        tmp = final.with_suffix(f".{os.getpid()}.tmp")
        payload = json.dumps(state.model_dump(), ensure_ascii=False)
        with tmp.open("w", encoding="utf-8") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, final)
        return state

    def create_reserved(
        self,
        *,
        task_id: str,
        execution_id: str,
        project: str = "",
        spider: str = "",
        version: str | None = None,
        runner_type: str = "scrapy",
        shell_command: str = "",
    ) -> AttemptState | None:
        """Atomically reserve an execution (``O_CREAT|O_EXCL``) before spawning.

        Returns the reserved state, or ``None`` if a state file already exists
        (a duplicate command / lost race / cross-restart re-delivery). This is
        the cross-restart "don't start the same execution twice" guard; the caller
        promotes it to ``started`` once the work is spawned. ``runner_type`` /
        ``shell_command`` carry the phase-2b Python-wheel context (defaults keep
        Scrapy callers unchanged).
        """
        self._dir.mkdir(parents=True, exist_ok=True)
        final = self.path_for(execution_id)
        state = AttemptState(
            task_id=task_id,
            execution_id=execution_id,
            project=project,
            spider=spider,
            version=version,
            phase="reserved",
            runner_type=runner_type,
            shell_command=shell_command,
        )
        payload = json.dumps(state.model_dump(), ensure_ascii=False)
        try:
            fd = os.open(final, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            return None
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        return state

    def promote_started(
        self, execution_id: str, *, scrapyd_job_id: str, log_path: str
    ) -> AttemptState | None:
        """Promote a reserved execution to ``started`` with its scrapyd job id."""
        state = self.read(execution_id)
        if state is None:
            return None
        state.phase = "started"
        state.scrapyd_job_id = scrapyd_job_id
        state.log_path = log_path
        return self.write(state)

    def promote_started_wheel(
        self,
        execution_id: str,
        *,
        pid: int,
        pgid: int,
        workspace_path: str,
        install_path: str,
        log_path: str,
    ) -> AttemptState | None:
        """Promote a reserved Python-wheel execution to ``started`` (phase 2b).

        Records the child ``pid`` / process-group ``pgid`` (for SIGTERM/SIGKILL
        cancellation), the per-execution ``workspace_path``, the wheel
        ``install_path`` (its ``site`` dir), and the merged ``log_path`` so the
        existing :class:`LogPublisher` tails the single ``job.log`` stream.
        """
        state = self.read(execution_id)
        if state is None:
            return None
        state.phase = "started"
        state.pid = pid
        state.pgid = pgid
        state.workspace_path = workspace_path
        state.install_path = install_path
        state.log_path = log_path
        return self.write(state)

    def mark_done(
        self,
        execution_id: str,
        *,
        result: str,
        lost_reason: str | None = None,
        error_code: str | None = None,
        exit_code: int | None = None,
    ) -> AttemptState | None:
        """Record a reported terminal so a re-delivered command re-emits it."""
        state = self.read(execution_id)
        if state is None:
            return None
        state.phase = "done"
        state.result = result
        state.lost_reason = lost_reason
        state.error_code = error_code
        state.exit_code = exit_code
        if result == "canceled":
            state.canceled = True
        return self.write(state)

    def read(self, execution_id: str) -> AttemptState | None:
        """Return the persisted state, or ``None`` if missing/corrupt."""
        path = self.path_for(execution_id)
        try:
            raw = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        except OSError:
            return None
        try:
            data: Any = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            # Half-written / corrupt file: treat as missing, do not raise.
            return None
        try:
            return AttemptState.model_validate(data)
        except Exception:
            return None

    def delete(self, execution_id: str) -> bool:
        """Remove the state file. Returns ``True`` if a file was deleted."""
        path = self.path_for(execution_id)
        try:
            path.unlink()
            return True
        except FileNotFoundError:
            return False

    def list_execution_ids(self) -> list[str]:
        """Return execution ids that currently have a state file on disk."""
        if not self._dir.is_dir():
            return []
        ids: list[str] = []
        for entry in self._dir.iterdir():
            if entry.is_file() and entry.suffix == ".json":
                ids.append(entry.stem)
        return sorted(ids)
