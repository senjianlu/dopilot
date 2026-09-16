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

    # --- log-flood guard: additive fields (defaults keep old state files
    # loading unchanged). ``log_flood`` = the watchdog saw the local job.log at
    # or past the cap and is stopping the job; its terminal is reported as
    # ``failed`` / ``log_flood`` regardless of what scrapyd says. ``log_capped``
    # = the publisher stopped tailing this execution (cap reached or a
    # ``stop_logs`` backpressure command arrived). ``error_count`` /
    # ``finish_reason`` are the scrapy stats parsed from the log tail at
    # terminal; ``log_bytes`` the final local log size.
    log_flood: bool = False
    log_flood_bytes: int = 0
    log_flood_requested_at: str | None = None
    log_flood_escalation: str | None = None
    log_capped: bool = False
    error_count: int | None = None
    finish_reason: str | None = None
    log_bytes: int | None = None

    # --- stop state machine: additive fields (defaults keep old state files
    # loading unchanged). A stop is no longer handled inline -- waiting for the
    # process to die inside the command consumer would block every other
    # execution's heartbeat and flood check for the whole confirmation window.
    # Instead the intent is persisted here FIRST (the command is XACKed even if
    # the handler raises, so an unpersisted intent is simply lost) and the tick
    # loop drives TERM -> KILL -> confirmation across ticks.
    #
    # ``stop_escalation``: None = TERM not yet sent successfully, "term" = TERM
    # acknowledged, "kill" = KILL acknowledged.
    #
    # Terminal reporting is BOUNDED (``stop_confirm_timeout_seconds``) but
    # process reclamation is NOT: when the deadline passes with the process
    # still alive we report the terminal per contract and keep ``kill_pending``
    # (plus the scrapyd job mapping!) so the reclaim watchdog can keep trying.
    # Dropping the mapping to "finish" the stop would recreate exactly the
    # invisible-orphan problem this machinery exists to remove.
    stop_intent: str | None = None
    stop_requested_at: str | None = None
    stop_escalation: str | None = None
    cleanup_pending: bool = False
    kill_pending: bool = False
    kill_last_attempt_at: str | None = None
    # Terminal persisted but not yet handed to ``emit`` (whose own outbox makes
    # it at-least-once). Crashing in that window would otherwise lose a
    # ``canceled`` the server is contractually owed.
    terminal_pending: bool = False


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
        kill_pending: bool | None = None,
        terminal_pending: bool | None = None,
    ) -> AttemptState | None:
        """Record a reported terminal so a re-delivered command re-emits it.

        ``kill_pending`` / ``terminal_pending`` are written in the SAME atomic
        write as the terminal itself. Splitting them into a second write opens a
        crash window that loses the reclaim task (``done`` with
        ``kill_pending`` still false means the reclaim watchdog walks past it,
        and a pending cleanup would then delete the job mapping) or loses the
        terminal the server is owed.
        """
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
        if kill_pending is not None:
            state.kill_pending = kill_pending
        if terminal_pending is not None:
            state.terminal_pending = terminal_pending
        return self.write(state)

    def mark_stop_requested(
        self, execution_id: str, *, intent: str, requested_at: str
    ) -> AttemptState | None:
        """Persist the stop INTENT before any network call.

        ``_process`` XACKs a command even when its handler raises, so an intent
        that lives only in memory is gone for good; the watchdog recovers from
        this record alone (including across an agent restart).
        """
        state = self.read(execution_id)
        if state is None:
            return None
        state.stop_intent = intent
        state.stop_requested_at = requested_at
        state.stop_escalation = None
        return self.write(state)

    def mark_stop_escalation(
        self, execution_id: str, *, escalation: str
    ) -> AttemptState | None:
        """Record that a stop signal was ACKNOWLEDGED by scrapyd.

        Only ever called after a successful request: a failed TERM/KILL must
        leave the previous value so the next tick retries it.
        """
        state = self.read(execution_id)
        if state is None:
            return None
        state.stop_escalation = escalation
        return self.write(state)

    def mark_cleanup_pending(self, execution_id: str) -> AttemptState | None:
        """Defer a ``cleanup_logs`` that arrived while the stop/reclaim runs."""
        state = self.read(execution_id)
        if state is None:
            return None
        state.cleanup_pending = True
        return self.write(state)

    def mark_kill_attempt(self, execution_id: str, *, at: str) -> AttemptState | None:
        """Throttle stamp for the unbounded post-deadline KILL retries."""
        state = self.read(execution_id)
        if state is None:
            return None
        state.kill_last_attempt_at = at
        return self.write(state)

    def clear_kill_pending(self, execution_id: str) -> AttemptState | None:
        """The process is confirmed gone: reclamation is done."""
        state = self.read(execution_id)
        if state is None:
            return None
        state.kill_pending = False
        return self.write(state)

    def clear_terminal_pending(self, execution_id: str) -> AttemptState | None:
        """The terminal reached ``emit`` (and thus its durable outbox)."""
        state = self.read(execution_id)
        if state is None:
            return None
        state.terminal_pending = False
        return self.write(state)

    def mark_canceled(self, execution_id: str) -> AttemptState | None:
        """Record a successful stop by RE-READING the state (merge, never a
        stale whole-object write-back: the log publisher may have set
        ``log_capped`` while the cancel request was in flight)."""
        state = self.read(execution_id)
        if state is None:
            return None
        if state.canceled:
            return state
        state.canceled = True
        return self.write(state)

    def mark_log_flood(
        self,
        execution_id: str,
        *,
        log_bytes: int,
        requested_at: str,
        escalation: str | None = None,
    ) -> AttemptState | None:
        """Record that the flood watchdog is stopping this execution."""
        state = self.read(execution_id)
        if state is None:
            return None
        state.log_flood = True
        state.log_flood_bytes = max(state.log_flood_bytes, log_bytes)
        if state.log_flood_requested_at is None:
            state.log_flood_requested_at = requested_at
        if escalation is not None:
            state.log_flood_escalation = escalation
        return self.write(state)

    def mark_log_capped(self, execution_id: str) -> AttemptState | None:
        """Record that the log publisher stopped tailing this execution."""
        state = self.read(execution_id)
        if state is None or state.log_capped:
            return state
        state.log_capped = True
        return self.write(state)

    def mark_stats(
        self,
        execution_id: str,
        *,
        error_count: int | None,
        finish_reason: str | None,
        log_bytes: int | None,
    ) -> AttemptState | None:
        """Persist the scrapy stats parsed at terminal (None = unknown)."""
        state = self.read(execution_id)
        if state is None:
            return None
        state.error_count = error_count
        state.finish_reason = finish_reason
        state.log_bytes = log_bytes
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
