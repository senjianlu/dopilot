"""Agent command consumer (phase 1.5).

Consumes ``dopilot:agent:{agent_id}:commands`` via a consumer group and drives
the existing :class:`ScrapyRunner`. Guarantees from refactor/00:

- **idempotency** keyed on ``execution_id``: a per-execution in-process lock plus
  the ``O_CREAT|O_EXCL`` reserved state file (cross-restart) ensure a re-delivered
  ``run`` never starts the spider twice — it re-emits the current event instead;
- **two-phase CAS**: reserve (O_EXCL) -> schedule on scrapyd -> promote started;
  a crash between reserve and schedule is recovered on boot as
  ``attempt.failed(spawn_aborted)`` (never stuck in accepted);
- **pending recovery**: on boot, claim the group's pending entries (XAUTOCLAIM)
  and reprocess them idempotently;
- **stop intent**: ``cancel`` -> authoritative ``attempt.canceled`` regardless of
  process state; ``reclaim`` -> kill if running but stay ``lost`` (emit a real
  terminal only if one is genuinely observed);
- **XACK = reliable takeover**, performed after the handler records state/events.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import shutil
import signal
import time
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from pathlib import Path

from dopilot_protocol import (
    COMMAND_GROUP,
    AgentCommand,
    AgentCommandType,
    AgentEventType,
    AgentRunRequest,
    AttemptStatus,
    DopilotRuntimeContext,
    LostReason,
    ScrapyCommandError,
    StopIntent,
    command_stream,
    from_stream_entry,
    parse_scrapy_command,
)
from redis.exceptions import TimeoutError as RedisTimeoutError

from ..artifacts.cache import ArtifactCacheError, ScrapyArtifactCache
from ..artifacts.wheel_cache import PythonWheelCache, WheelCacheError
from ..runners.python_wheel import PythonWheelRunner, WheelRunnerError
from ..runners.scrapyd import RunnerError, ScrapyRunner
from ..scrapyd.stats import log_size, parse_scrapy_stats, read_log_tail
from ..state.store import AttemptState, StateStore
from .events import EventPublisher
from .status import RedisRuntimeStatus

WHEEL_RUNNER_TYPE = "python_wheel"

logger = logging.getLogger(__name__)

_STATUS_TO_TERMINAL = {
    AttemptStatus.finished: AgentEventType.finished,
    AttemptStatus.failed: AgentEventType.failed,
    AttemptStatus.canceled: AgentEventType.canceled,
}


def _runtime_context_env(payload: dict) -> dict[str, str]:
    raw = payload.get("runtime_context")
    if raw is None:
        return {}
    return DopilotRuntimeContext.model_validate(raw).to_env_map()


def _runtime_context_scrapy_settings(payload: dict) -> dict[str, str]:
    raw = payload.get("runtime_context")
    if raw is None:
        return {}
    return DopilotRuntimeContext.model_validate(raw).to_scrapy_settings()


class CommandConsumer:
    """Reads + executes commands for one agent."""

    def __init__(
        self,
        *,
        redis: object,
        agent_id: str,
        runner: ScrapyRunner,
        store: StateStore,
        events: EventPublisher,
        pending_idle_ms: int = 30000,
        command_block_ms: int = 5000,
        batch: int = 16,
        status: RedisRuntimeStatus | None = None,
        artifact_cache: ScrapyArtifactCache | None = None,
        wheel_runner: PythonWheelRunner | None = None,
        wheel_cache: PythonWheelCache | None = None,
        attempt_heartbeat_interval_seconds: int = 60,
        max_job_log_bytes: int = 0,
        log_flood_kill_after_seconds: int = 30,
        stop_kill_after_seconds: int = 10,
        stop_confirm_timeout_seconds: int = 120,
        kill_retry_interval_seconds: int = 60,
        scrapyd_pid: Callable[[], int | None] | None = None,
        proc_root: str | os.PathLike[str] = "/proc",
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._redis = redis
        self._agent_id = agent_id
        self._runner = runner
        self._store = store
        self._events = events
        self._pending_idle_ms = pending_idle_ms
        self._block_ms = command_block_ms
        self._batch = batch
        self._stream = command_stream(agent_id)
        self._group = COMMAND_GROUP
        self._consumer = agent_id
        # Refcounted keyed locks: {execution_id: [asyncio.Lock, refcount]} (R-02).
        self._locks: dict[str, list] = {}
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self._status = status
        self._artifact_cache = artifact_cache
        self._wheel_runner = wheel_runner
        self._wheel_cache = wheel_cache
        # Python-wheel executions started in THIS process: their terminal events
        # come from a tracked background wait task; on boot a started wheel state
        # NOT in this set is an orphan we cannot reattach to (-> lost).
        self._inproc_wheel: set[str] = set()
        self._wait_tasks: dict[str, asyncio.Task[None]] = {}
        # Resource caps (R-04): execution ids whose command is being handled RIGHT
        # NOW (added around _process, before spawn/registration). The janitor uses
        # this so it never deletes a workspace whose command is mid-flight but not
        # yet in the runner's _procs / lacking a job.pgid sidecar.
        self._processing: set[str] = set()
        # Resource caps (C6): set after construction (the LogPublisher is built
        # later); lets cleanup drop the cursor + EOF dedup state for an execution.
        self._log_publisher: object | None = None
        # Attempt-liveness heartbeat pacing: {execution_id: last-emit monotonic}.
        # Only stamped on a SUCCESSFUL emit, so a failed XADD retries next pass.
        self._attempt_hb_interval = attempt_heartbeat_interval_seconds
        self._last_attempt_heartbeat: dict[str, float] = {}
        # Log-flood watchdog (second line of defence behind the in-process
        # logcap hook): cap in bytes (0 = off), escalation delay, a provider of
        # the MANAGED scrapyd pid (None in external-scrapyd mode -> the single-PID
        # kill level is disabled), the /proc root (tests substitute a fake) and a
        # wall clock (tests substitute a mock).
        self._log_cap = max(0, int(max_job_log_bytes))
        self._flood_kill_after = max(0, int(log_flood_kill_after_seconds))
        self._stop_kill_after = max(0, int(stop_kill_after_seconds))
        self._stop_confirm_timeout = max(0, int(stop_confirm_timeout_seconds))
        self._kill_retry_interval = max(0, int(kill_retry_interval_seconds))
        self._scrapyd_pid = scrapyd_pid
        self._proc_root = Path(proc_root)
        self._now = now or (lambda: datetime.now(UTC))

    def set_log_publisher(self, publisher: object) -> None:
        """Wire the LogPublisher so cleanup can release its per-execution state."""
        self._log_publisher = publisher

    def active_execution_ids(self) -> set[str]:
        """Execution ids the consumer is actively handling or running in-proc.

        Union of the command currently being processed and started in-process
        wheels. The janitor treats these as untouchable (resource caps, R-04).
        """
        return set(self._processing) | set(self._inproc_wheel)

    def execution_lock(self, execution_id: str):
        """Public per-execution lock context manager (janitor coordination, R-02).

        Returns the SAME refcounted keyed lock the consumer uses, so the janitor
        deleting an execution's files is mutually exclusive with a command handler
        for that execution.
        """
        return self._execution_lock(execution_id)

    def on_execution_eof(self, execution_id: str) -> None:
        """Terminal + EOF published: drop EOF-safe bookkeeping (resource caps, C6).

        Invoked by the LogPublisher right after it publishes an execution's EOF.
        Releases the in-process-wheel marker and the wheel runner's per-execution
        dicts/sets — safe at EOF because the terminal event is already delivered.
        The per-execution lock and the EOF dedup set are NOT touched here; they
        live until state cleanup (see :meth:`_handle_cleanup`).
        """
        self._inproc_wheel.discard(execution_id)
        if self._wheel_runner is not None:
            self._wheel_runner.forget(execution_id)

    @contextlib.asynccontextmanager
    async def _execution_lock(self, execution_id: str) -> AsyncIterator[None]:
        """Refcounted keyed per-execution lock (resource caps, R-02).

        The lock entry is created on first use and removed ONLY when the last
        holder/waiter leaves (refcount back to 0). Because the whole consumer runs
        on one event loop, the get-or-create + refcount increment below happens
        with no ``await`` in between, so it is atomic — a lock is never dropped
        while it is held or has waiters (which previously let two coroutines hold
        two different locks for the same execution), and it does not leak (removed
        at refcount 0 instead of only on cleanup).
        """
        entry = self._locks.get(execution_id)
        if entry is None:
            entry = [asyncio.Lock(), 0]
            self._locks[execution_id] = entry
        entry[1] += 1  # register as holder/waiter BEFORE awaiting acquire
        lock: asyncio.Lock = entry[0]
        await lock.acquire()
        try:
            yield
        finally:
            lock.release()
            entry[1] -= 1
            if entry[1] == 0 and self._locks.get(execution_id) is entry:
                del self._locks[execution_id]

    async def setup(self) -> None:
        await self._redis.ensure_group(self._stream, self._group)

    # --- startup recovery --------------------------------------------------
    async def recover_reserved_orphans(self) -> int:
        """Boot recovery: a ``reserved`` file with no spawn -> spawn_aborted.

        Accepted limitation (refactor/00 §幂等): the reserved state file has no
        scrapyd job id, so there is no reliable way to query whether a job was in
        fact scheduled. The crash window between ``schedule()`` returning a job id
        and ``promote_started()`` persisting it is sub-millisecond (no await
        between them); a SIGKILL in that window leaves an orphan scrapyd job that
        this recovery cannot correlate, so the attempt is declared
        ``spawn_aborted`` and the orphan job rotates out of scrapyd on its own.
        This matches the doc's accepted "reserved == not truly spawned" posture.
        """
        recovered = 0
        for execution_id in self._store.list_execution_ids():
            state = self._store.read(execution_id)
            if state is not None and state.phase == "reserved":
                await self._events.emit_terminal(
                    state.task_id,
                    execution_id,
                    AgentEventType.failed,
                    error_code="spawn_aborted",
                    lost_reason=LostReason.spawn_aborted,
                )
                self._store.mark_done(
                    execution_id,
                    result="failed",
                    error_code="spawn_aborted",
                    lost_reason="spawn_aborted",
                )
                recovered += 1
        return recovered

    async def recover(self) -> None:
        """Full boot recovery: replay event outbox + reserved orphans + pending."""
        await self.setup()
        await self._events.replay_outbox()
        await self.recover_reserved_orphans()
        await self.recover_wheel_orphans()
        await self._claim_pending()

    async def recover_wheel_orphans(self) -> int:
        """Boot recovery for ``started`` Python-wheel states from a prior process.

        Packet 2b-2 does not reattach to a running subprocess after an agent
        restart. A ``started`` wheel state that was NOT started in this process is
        an orphan: best-effort kill its recorded process group, then declare it
        ``lost`` with ``runner_recovered_unknown``. It is NEVER restarted (the
        terminal ``done`` marker also makes a re-delivered ``run`` idempotent).
        """
        recovered = 0
        for execution_id in self._store.list_execution_ids():
            state = self._store.read(execution_id)
            if (
                state is None
                or state.runner_type != WHEEL_RUNNER_TYPE
                or state.phase != "started"
                or execution_id in self._inproc_wheel
            ):
                continue
            if state.pgid and self._wheel_runner is not None:
                self._wheel_runner.terminate_pgid(state.pgid)
            self._store.mark_done(
                execution_id,
                result="lost",
                lost_reason=LostReason.runner_recovered_unknown.value,
            )
            await self._events.emit_terminal(
                state.task_id,
                execution_id,
                AgentEventType.lost,
                lost_reason=LostReason.runner_recovered_unknown,
            )
            recovered += 1
        return recovered

    async def reconcile_started_attempts(self) -> int:
        """Poll local scrapyd for started attempts and emit terminal events.

        The command stream only starts/cancels work; scrapyd process completion is
        discovered by the agent because the agent owns local scrapyd. This keeps
        terminal state agent-authoritative without reintroducing server->agent
        status polling.
        """
        reconciled = 0
        for execution_id in self._store.list_execution_ids():
            state = self._store.read(execution_id)
            if state is None:
                continue
            if state.phase != "started":
                # A finished attempt can still owe work: a terminal that never
                # reached ``emit``, a process that outlived its stop deadline, or
                # a ``cleanup_logs`` deferred while either was outstanding. The
                # cleanup command is long since XACKed, so this is the only
                # place left that can finish those.
                await self._reclaim_watchdog(state)
                continue
            # Python-wheel terminals come from the in-process background wait
            # task (or boot orphan recovery); never poll Scrapy status for them.
            # Liveness: heartbeat iff the in-process child is confirmed alive
            # (returncode still None).
            if state.runner_type == WHEEL_RUNNER_TYPE:
                if (
                    execution_id in self._inproc_wheel
                    and self._wheel_runner is not None
                    and execution_id in self._wheel_runner.active_execution_ids()
                ):
                    await self._maybe_emit_heartbeat(state.task_id, execution_id)
                continue
            # One sample per tick, taken INDEPENDENTLY of the flood cap: it
            # feeds both the flood watchdog (when the cap is on) and the
            # heartbeat's progress evidence (always). Sampling inside
            # _flood_watchdog would silently disable no-progress detection for
            # anyone running with max_job_log_bytes = 0.
            size = await self._sample_log_size(state)
            state = await self._flood_watchdog(state, size) or state
            if state.stop_requested_at:
                # A stop owns this execution's terminal now; skip the normal
                # status/heartbeat path entirely.
                await self._stop_watchdog(state)
                continue
            resp = await self._runner.status(execution_id, state.task_id)
            terminal = _STATUS_TO_TERMINAL.get(resp.status)
            if terminal is None:
                # ``running`` = scrapyd just listed the job (running/pending) ->
                # confirmed alive -> rate-limited heartbeat. ``unknown`` (scrapyd
                # unreachable / no state) is NOT confirmation; never heartbeat it.
                if resp.status == AttemptStatus.running:
                    await self._maybe_emit_heartbeat(
                        state.task_id, execution_id, log_bytes=size
                    )
                continue
            self._last_attempt_heartbeat.pop(execution_id, None)
            await self._finish_scrapy_attempt(state, terminal, exit_code=resp.exit_code)
            reconciled += 1
        return reconciled

    async def _finish_scrapy_attempt(
        self, state: AttemptState, terminal: AgentEventType, *, exit_code: int | None
    ) -> None:
        """Persist + emit a scrapyd attempt's terminal, with stats and flood override.

        Parses the scrapy stats block from the log tail (``error_count`` /
        ``finish_reason``) and the final local log size so the server can judge
        a ``finished`` run that was actually erroneous. A flood-stopped attempt
        (the watchdog saw the log at/over the cap) is ALWAYS reported as
        ``failed`` / ``log_flood`` regardless of scrapyd's own verdict.
        """
        execution_id = state.execution_id
        tail = await asyncio.to_thread(read_log_tail, state.log_path)
        stats = parse_scrapy_stats(tail)
        size = await asyncio.to_thread(log_size, state.log_path)
        log_bytes = max(size or 0, state.log_flood_bytes) if state.log_flood else size
        self._store.mark_stats(
            execution_id,
            error_count=stats.error_count,
            finish_reason=stats.finish_reason,
            log_bytes=log_bytes,
        )
        error_code: str | None = None
        error_detail: dict | None = None
        if state.log_flood:
            terminal = AgentEventType.failed
            error_code = "log_flood"
            error_detail = {
                "log_bytes": log_bytes,
                "cap": self._log_cap,
                "kill_escalation": state.log_flood_escalation,
            }
            # The process is gone: bound the local file for good (disk cap).
            await asyncio.to_thread(self._truncate_local_log, state.log_path)
        self._store.mark_done(
            execution_id,
            result=terminal.short,
            exit_code=exit_code,
            error_code=error_code,
        )
        await self._events.emit_terminal(
            state.task_id,
            execution_id,
            terminal,
            exit_code=exit_code,
            error_code=error_code,
            error_detail=error_detail,
            error_count=stats.error_count,
            finish_reason=stats.finish_reason,
            log_bytes=log_bytes,
        )

    # --- log-flood watchdog --------------------------------------------------
    def _flood_marker(self) -> bytes:
        return (
            f"\n[dopilot:job-log-truncated max_bytes={self._log_cap} "
            f"reason=size-cap]\n"
        ).encode()

    def _truncate_local_log(self, log_path: str) -> None:
        """Cut the local job.log back to ``cap`` + exactly one marker (idempotent).

        Any file at or past the cap ends up as ``<first cap bytes> + marker``:
        the first detection (even at cap + 1) is cut and marked, and a file
        that already carries the marker at ``cap`` is left alone unless it grew
        past it again. scrapy/scrapyd write with O_APPEND, so truncating under
        a live writer is safe: its next record lands after the marker and the
        next tick cuts it back again — disk use stays at cap + marker + one
        tick of writes.
        """
        if self._log_cap <= 0:
            return
        marker = self._flood_marker()
        cap = self._log_cap
        try:
            size = os.path.getsize(log_path)
        except OSError:
            return
        if size < cap:
            return
        with open(log_path, "r+b") as fh:
            if size == cap + len(marker):
                fh.seek(cap)
                if fh.read(len(marker)) == marker:
                    return  # already exactly cap + marker
            fh.truncate(cap)
            fh.seek(cap)
            fh.write(marker)
            fh.flush()

    async def _sample_log_size(self, state: AttemptState) -> int | None:
        """This tick's job.log size, or None when it cannot be read.

        Sampled independently of ``max_job_log_bytes``: the flood watchdog is an
        optional guard, but the heartbeat's progress evidence is not. Reading it
        inside the watchdog would make every heartbeat report ``None`` whenever
        the cap is disabled, which silently turns no-progress detection off.
        """
        if not state.log_path:
            return None
        return await asyncio.to_thread(log_size, state.log_path)

    async def _flood_watchdog(
        self, state: AttemptState, size: int | None = None
    ) -> AttemptState | None:
        """Per-tick log-flood check for one started scrapyd attempt.

        Returns the refreshed state when it changed, else None. Cap 0 = off.
        ``size`` is this tick's sample from :meth:`_sample_log_size` (passing it
        in keeps the read to one per execution per tick).
        """
        if self._log_cap <= 0 or not state.log_path:
            return None
        if size is None:
            return None
        execution_id = state.execution_id
        if not state.log_flood:
            if size < self._log_cap:
                return None
            requested_at = self._now().isoformat()
            state = self._store.mark_log_flood(
                execution_id, log_bytes=size, requested_at=requested_at,
                escalation="term",
            ) or state
            logger.warning(
                "log flood: %s job.log is %d bytes (cap %d); cancelling",
                execution_id, size, self._log_cap,
            )
            # Bound the disk RIGHT NOW (not only from the next tick): a writer
            # that bypasses the in-process FileHandler hook must not get a whole
            # tick interval of unbounded growth.
            await asyncio.to_thread(self._truncate_local_log, state.log_path)
            await self._flood_cancel(state, signal_name=None)
            return state

        # Already flooding: keep the disk bounded, then escalate the stop.
        await asyncio.to_thread(self._truncate_local_log, state.log_path)
        if size > state.log_flood_bytes:
            state = self._store.mark_log_flood(
                execution_id, log_bytes=size, requested_at=state.log_flood_requested_at
                or self._now().isoformat(),
            ) or state
        elapsed = self._flood_elapsed(state)
        if elapsed >= 2 * self._flood_kill_after:
            if state.log_flood_escalation != "pidkill":
                if await self._flood_pid_kill(state):
                    state = self._store.mark_log_flood(
                        execution_id, log_bytes=size,
                        requested_at=state.log_flood_requested_at or "",
                        escalation="pidkill",
                    ) or state
                    return state
            await self._flood_cancel(state, signal_name="KILL")
        elif elapsed >= self._flood_kill_after:
            if state.log_flood_escalation != "kill":
                state = self._store.mark_log_flood(
                    execution_id, log_bytes=size,
                    requested_at=state.log_flood_requested_at or "",
                    escalation="kill",
                ) or state
            await self._flood_cancel(state, signal_name="KILL")
        else:
            await self._flood_cancel(state, signal_name=None)
        return state

    def _flood_elapsed(self, state: AttemptState) -> float:
        if not state.log_flood_requested_at:
            return 0.0
        try:
            started = datetime.fromisoformat(state.log_flood_requested_at)
        except ValueError:
            return 0.0
        return max(0.0, (self._now() - started).total_seconds())

    async def _flood_cancel(self, state: AttemptState, *, signal_name: str | None) -> None:
        try:
            await self._runner.stop(
                state.execution_id, state.task_id, signal=signal_name
            )
        except Exception:  # noqa: BLE001 - retried every tick
            logger.warning(
                "log flood: scrapyd cancel (%s) failed for %s; will retry",
                signal_name or "TERM", state.execution_id, exc_info=True,
            )

    async def _flood_pid_kill(self, state: AttemptState) -> bool:
        """SIGKILL the single crawler PID provably owned by the managed scrapyd.

        Only in managed-scrapyd mode (a known scrapyd pid). The candidate must
        be the UNIQUE process whose argv carries ``crawl`` + ``_job=<job id>``
        and whose parent is that scrapyd pid; 0 or >1 candidates -> never kill
        (log an error, keep re-sending cancel). Never ``killpg``: scrapyd spawns
        crawlers without their own process group.
        """
        parent = self._scrapyd_pid() if self._scrapyd_pid is not None else None
        if parent is None:
            logger.warning(
                "log flood: no managed scrapyd pid (external mode); pid kill skipped for %s",
                state.execution_id,
            )
            return False
        candidates = await asyncio.to_thread(
            self._find_crawler_pids, state.scrapyd_job_id, parent
        )
        if len(candidates) != 1:
            logger.error(
                "log flood: %d crawler candidates for job %s (need exactly 1); not killing",
                len(candidates), state.scrapyd_job_id,
            )
            return False
        pid = candidates[0]
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            logger.warning("log flood: SIGKILL %d failed", pid, exc_info=True)
            return False
        logger.warning(
            "log flood: SIGKILLed crawler pid %d for %s", pid, state.execution_id
        )
        return True

    def _find_crawler_pids(self, job_id: str, parent_pid: int) -> list[int]:
        found: list[int] = []
        if not job_id:
            return found
        try:
            entries = os.listdir(self._proc_root)
        except OSError:
            return found
        for name in entries:
            if not name.isdigit():
                continue
            base = self._proc_root / name
            try:
                argv = (base / "cmdline").read_bytes().split(b"\0")
                stat = (base / "stat").read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            args = [a.decode("utf-8", errors="replace") for a in argv if a]
            # EXACT match on the scrapyd job argument (``-a _job=<id>`` is its
            # own argv token): a substring test would let ``_job=abc2`` stand
            # in for a vanished ``abc`` and SIGKILL the wrong crawler.
            if "crawl" not in args or f"_job={job_id}" not in args:
                continue
            # /proc/<pid>/stat: "pid (comm) state ppid ..." — comm may contain
            # spaces/parens, so split after the LAST ')'.
            try:
                ppid = int(stat.rsplit(")", 1)[1].split()[1])
            except (IndexError, ValueError):
                continue
            if ppid != parent_pid:
                continue
            found.append(int(name))
        return found

    async def _maybe_emit_heartbeat(
        self, task_id: str, execution_id: str, *, log_bytes: int | None = None
    ) -> None:
        """Rate-limited attempt-liveness heartbeat (caller confirmed alive).

        ``log_bytes`` is this tick's job.log size, the server's only evidence of
        actual progress; ``None`` (wheel runner, unreadable log) tells it to
        withhold judgement rather than assume a stall.
        """
        if self._attempt_hb_interval <= 0:
            return
        now = time.monotonic()
        last = self._last_attempt_heartbeat.get(execution_id)
        if last is not None and (now - last) < self._attempt_hb_interval:
            return
        # emit_heartbeat never raises; stamp only on success so a failed XADD
        # is retried on the next reconcile pass instead of a full interval later.
        if await self._events.emit_heartbeat(
            task_id, execution_id, log_bytes=log_bytes
        ):
            self._last_attempt_heartbeat[execution_id] = now

    # --- draining ----------------------------------------------------------
    async def _claim_pending(self) -> int:
        processed = 0
        start = "0-0"
        for _ in range(1000):  # bounded; breaks on empty/cycle
            next_id, claimed, _deleted = await self._redis.xautoclaim(
                self._stream, self._group, self._consumer,
                self._pending_idle_ms, start, count=self._batch,
            )
            for msg_id, fields in claimed:
                await self._process(msg_id, fields)
                processed += 1
            cursor = next_id.decode() if isinstance(next_id, bytes) else str(next_id)
            if not claimed or cursor in ("0-0", "0"):
                break
            start = cursor
        return processed

    async def drain_once(
        self, *, claim_pending: bool = True, block: int | None = None
    ) -> int:
        """Claim pending then read+process new commands. Returns count handled."""
        processed = 0
        if claim_pending:
            processed += await self._claim_pending()
        resp = await self._redis.xreadgroup(
            self._group, self._consumer, {self._stream: ">"},
            count=self._batch, block=block,
        )
        if self._status is not None:
            self._status.mark_command_read()
        for _stream, entries in resp or []:
            for msg_id, fields in entries:
                await self._process(msg_id, fields)
                processed += 1
        return processed

    async def _process(self, msg_id: object, fields: object) -> None:
        # Decode INSIDE the failure boundary: an undecodable entry (unknown
        # command type from a newer server, corrupt JSON) is logged and ACKed
        # instead of raising out of the drain loop, where it would be re-claimed
        # and re-raised forever as a poison message.
        try:
            cmd = from_stream_entry(AgentCommand, fields)
        except Exception:  # noqa: BLE001
            logger.warning(
                "undecodable command entry %s dropped (ACKed)", msg_id, exc_info=True
            )
            await self._redis.xack(self._stream, self._group, msg_id)
            return
        # Mark in-flight BEFORE taking the lock so the janitor's active-set check
        # (which it does under the same lock) always sees an in-progress command
        # even before the runner registers _procs / writes job.pgid (R-04).
        self._processing.add(cmd.execution_id)
        async with self._execution_lock(cmd.execution_id):
            try:
                if cmd.type == AgentCommandType.run:
                    await self._handle_run(cmd)
                elif cmd.type == AgentCommandType.stop:
                    await self._handle_stop(cmd)
                elif cmd.type == AgentCommandType.cleanup_logs:
                    await self._handle_cleanup(cmd)
                elif cmd.type == AgentCommandType.stop_logs:
                    self._handle_stop_logs(cmd)
            except Exception:  # noqa: BLE001 - record + ack; never poison-loop
                logger.exception("command handler failed: %s", cmd.command_id)
            finally:
                self._processing.discard(cmd.execution_id)
                # XACK = reliable takeover (success or idempotent skip).
                await self._redis.xack(self._stream, self._group, msg_id)

    def _handle_stop_logs(self, cmd: AgentCommand) -> None:
        """Server backpressure: stop tailing this execution's log (idempotent)."""
        if self._log_publisher is not None and hasattr(self._log_publisher, "cap"):
            self._log_publisher.cap(cmd.execution_id)
        else:
            self._store.mark_log_capped(cmd.execution_id)

    # --- handlers ----------------------------------------------------------
    async def _handle_run(self, cmd: AgentCommand) -> None:
        existing = self._store.read(cmd.execution_id)
        if existing is not None:
            # idempotent: already have this execution -> re-emit, do not restart.
            await self._events.republish_current(cmd.task_id, cmd.execution_id)
            return

        # Narrow phase-2b branch: a ``python_wheel`` run is a shell command, not
        # a ``scrapy crawl`` command. The Scrapy path below is unchanged.
        if cmd.task_type == WHEEL_RUNNER_TYPE:
            await self._handle_run_wheel(cmd)
            return

        payload = cmd.payload or {}
        artifact = payload.get("artifact") if isinstance(payload.get("artifact"), dict) else None
        project = str((artifact or {}).get("project") or "")
        version = (
            str((artifact or {}).get("version"))
            if (artifact or {}).get("version")
            else None
        )
        # Command-first: parse the authoritative ``scrapy crawl ...`` command into
        # spider/args/settings; project/version come from the artifact context.
        parsed = None
        command_error: dict = {}
        try:
            parsed = parse_scrapy_command(payload.get("command"))
        except ScrapyCommandError as exc:
            command_error = exc.detail
        spider = parsed.spider if parsed is not None else ""

        reserved = self._store.create_reserved(
            task_id=cmd.task_id,
            execution_id=cmd.execution_id,
            project=project,
            spider=spider,
            version=version,
        )
        if reserved is None:
            # lost the O_EXCL race (concurrent claim) -> re-emit, do not restart.
            await self._events.republish_current(cmd.task_id, cmd.execution_id)
            return

        await self._events.emit_accepted(cmd.task_id, cmd.execution_id)

        # Reject an invalid/missing command or missing artifact context with a
        # structured terminal failure (idempotent: state is now reserved).
        if parsed is None or not project:
            detail = dict(command_error)
            if not project:
                detail = {"reason": "artifact_missing", **detail}
            self._store.mark_done(
                cmd.execution_id, result="failed", error_code="command_invalid"
            )
            await self._events.emit_terminal(
                cmd.task_id,
                cmd.execution_id,
                AgentEventType.failed,
                error_code="command_invalid",
                error_detail=detail,
            )
            return

        # Ensure the egg is cached locally before scheduling, but only when the
        # artifact context carries a fetchable hash (server always sends one).
        has_fetchable_artifact = bool(
            artifact and (artifact.get("hash") or artifact.get("sha256"))
        )
        if has_fetchable_artifact:
            if self._artifact_cache is None:
                self._store.mark_done(
                    cmd.execution_id, result="failed", error_code="artifact_cache_unavailable"
                )
                await self._events.emit_terminal(
                    cmd.task_id,
                    cmd.execution_id,
                    AgentEventType.failed,
                    error_code="artifact_cache_unavailable",
                )
                return
            try:
                await self._artifact_cache.ensure(artifact, execution_id=cmd.execution_id)
            except ArtifactCacheError as exc:
                self._store.mark_done(
                    cmd.execution_id, result="failed", error_code="artifact_error"
                )
                await self._events.emit_terminal(
                    cmd.task_id,
                    cmd.execution_id,
                    AgentEventType.failed,
                    error_code="artifact_error",
                    error_detail=exc.detail,
                )
                return
        run_req = AgentRunRequest(
            task_id=cmd.task_id,
            execution_id=cmd.execution_id,
            project=project,
            spider=parsed.spider,
            version=version,
            # Platform runtime context is applied after parsed command settings
            # so user-supplied ``-s DOPILOT_*`` values cannot forge it.
            settings={
                **dict(parsed.settings),
                **_runtime_context_scrapy_settings(payload),
            },
            args=dict(parsed.args),
        )
        try:
            job_id = await self._runner.schedule(run_req)
        except RunnerError as exc:
            self._store.mark_done(
                cmd.execution_id, result="failed", error_code="scrapyd_error"
            )
            await self._events.emit_terminal(
                cmd.task_id,
                cmd.execution_id,
                AgentEventType.failed,
                error_code="scrapyd_error",
                error_detail=exc.detail,
            )
            return

        log_path = str(
            self._runner.log_path(run_req.project, run_req.spider, job_id)
        )
        promoted = self._store.promote_started(
            cmd.execution_id, scrapyd_job_id=job_id, log_path=log_path
        )
        if promoted is None:
            # The reserved state file vanished between reserve and promote (should
            # not happen under the per-attempt lock). Record a terminal rather than
            # emit a phantom `running` whose state file would later be recovered as
            # spawn_aborted, contradicting it.
            logger.warning("promote_started lost state for %s", cmd.execution_id)
            self._store.mark_done(
                cmd.execution_id, result="failed", error_code="spawn_aborted",
                lost_reason="spawn_aborted",
            )
            await self._events.emit_terminal(
                cmd.task_id, cmd.execution_id, AgentEventType.failed,
                error_code="spawn_aborted", lost_reason=LostReason.spawn_aborted,
            )
            return
        await self._events.emit_running(
            cmd.task_id, cmd.execution_id, remote_job_id=job_id
        )

    # --- python wheel ------------------------------------------------------
    async def _handle_run_wheel(self, cmd: AgentCommand) -> None:
        payload = cmd.payload or {}
        artifact = (
            payload.get("artifact")
            if isinstance(payload.get("artifact"), dict)
            else None
        )
        shell_command = str(payload.get("shell_command") or "").strip()
        working_dir = payload.get("working_dir")
        env = payload.get("env") if isinstance(payload.get("env"), dict) else {}
        runtime_context = _runtime_context_env(payload)

        reserved = self._store.create_reserved(
            task_id=cmd.task_id,
            execution_id=cmd.execution_id,
            runner_type=WHEEL_RUNNER_TYPE,
            shell_command=shell_command,
        )
        if reserved is None:
            # lost the O_EXCL race (concurrent claim) -> re-emit, do not restart.
            await self._events.republish_current(cmd.task_id, cmd.execution_id)
            return

        await self._events.emit_accepted(cmd.task_id, cmd.execution_id)

        # Reject an empty command or a missing/unfetchable wheel artifact with a
        # structured terminal failure (idempotent: state is now reserved).
        has_fetchable_artifact = bool(
            artifact and (artifact.get("hash") or artifact.get("sha256"))
        )
        if not shell_command or not has_fetchable_artifact:
            detail = {"missing": "shell_command" if not shell_command else "artifact"}
            self._store.mark_done(
                cmd.execution_id, result="failed", error_code="command_invalid"
            )
            await self._events.emit_terminal(
                cmd.task_id,
                cmd.execution_id,
                AgentEventType.failed,
                error_code="command_invalid",
                error_detail=detail,
            )
            return

        if self._wheel_runner is None or self._wheel_cache is None:
            self._store.mark_done(
                cmd.execution_id, result="failed", error_code="wheel_runner_unavailable"
            )
            await self._events.emit_terminal(
                cmd.task_id,
                cmd.execution_id,
                AgentEventType.failed,
                error_code="wheel_runner_unavailable",
            )
            return

        # Install the wheel once per sha256 (no deps) into its private site dir.
        try:
            install_path = await self._wheel_cache.ensure(
                artifact, execution_id=cmd.execution_id
            )
        except WheelCacheError as exc:
            self._store.mark_done(
                cmd.execution_id, result="failed", error_code="wheel_install_error"
            )
            await self._events.emit_terminal(
                cmd.task_id,
                cmd.execution_id,
                AgentEventType.failed,
                error_code="wheel_install_error",
                error_detail=exc.detail,
            )
            return

        # Spawn ``/bin/sh -c <shell_command>`` in its own session.
        try:
            started = await self._wheel_runner.start(
                execution_id=cmd.execution_id,
                task_id=cmd.task_id,
                shell_command=shell_command,
                install_path=install_path,
                working_dir=working_dir,
                env={str(k): str(v) for k, v in (env or {}).items()},
                runtime_context=runtime_context,
            )
        except WheelRunnerError as exc:
            self._store.mark_done(
                cmd.execution_id, result="failed", error_code=exc.error_code
            )
            await self._events.emit_terminal(
                cmd.task_id,
                cmd.execution_id,
                AgentEventType.failed,
                error_code=exc.error_code,
                error_detail=exc.detail,
            )
            return

        promoted = self._store.promote_started_wheel(
            cmd.execution_id,
            pid=started.pid,
            pgid=started.pgid,
            workspace_path=started.workspace_path,
            install_path=install_path,
            log_path=started.log_path,
        )
        if promoted is None:
            logger.warning("promote_started_wheel lost state for %s", cmd.execution_id)
            await self._wheel_runner.terminate(cmd.execution_id)
            self._store.mark_done(
                cmd.execution_id, result="failed", error_code="spawn_aborted",
                lost_reason="spawn_aborted",
            )
            await self._events.emit_terminal(
                cmd.task_id, cmd.execution_id, AgentEventType.failed,
                error_code="spawn_aborted", lost_reason=LostReason.spawn_aborted,
            )
            return

        self._inproc_wheel.add(cmd.execution_id)
        await self._events.emit_running(cmd.task_id, cmd.execution_id)
        self._spawn_wait_task(cmd.task_id, cmd.execution_id)

    def _spawn_wait_task(self, task_id: str, execution_id: str) -> None:
        task = asyncio.create_task(self._await_wheel(task_id, execution_id))
        self._wait_tasks[execution_id] = task
        task.add_done_callback(lambda _t: self._wait_tasks.pop(execution_id, None))

    async def _await_wheel(self, task_id: str, execution_id: str) -> None:
        """Background: map a wheel child's natural exit to a terminal event."""
        if self._wheel_runner is None:
            return
        try:
            outcome = await self._wheel_runner.wait(execution_id)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - never let the waiter crash the loop
            logger.exception("wheel wait failed for %s", execution_id)
            return
        async with self._execution_lock(execution_id):
            # The child exited (or was already finalized) either way: drop the
            # heartbeat pacing stamp so it cannot outlive the attempt (R-01).
            self._last_attempt_heartbeat.pop(execution_id, None)
            state = self._store.read(execution_id)
            if state is None or state.phase == "done":
                # cancel/reclaim already recorded an authoritative terminal.
                return
            if outcome.canceled:
                self._store.mark_done(execution_id, result="canceled")
                await self._events.emit_terminal(
                    task_id, execution_id, AgentEventType.canceled
                )
            elif outcome.exit_code == 0:
                self._store.mark_done(
                    execution_id, result="finished", exit_code=0
                )
                await self._events.emit_terminal(
                    task_id, execution_id, AgentEventType.finished, exit_code=0
                )
            else:
                self._store.mark_done(
                    execution_id, result="failed", exit_code=outcome.exit_code
                )
                await self._events.emit_terminal(
                    task_id,
                    execution_id,
                    AgentEventType.failed,
                    exit_code=outcome.exit_code,
                )

    async def _handle_stop(self, cmd: AgentCommand) -> None:
        # Every stop path below ends the attempt (canceled / real terminal /
        # stays-lost kill): drop the heartbeat pacing stamp up front (R-01).
        self._last_attempt_heartbeat.pop(cmd.execution_id, None)
        # Stop commands do not reliably carry the task type (the server stop
        # outbox sends an empty payload, so the dispatcher defaults to
        # ``scrapy``). Branch on the LOCAL state's ``runner_type`` instead.
        state = self._store.read(cmd.execution_id)
        runner_type = state.runner_type if state is not None else None
        is_wheel = (
            runner_type == WHEEL_RUNNER_TYPE and self._wheel_runner is not None
        )

        if cmd.intent == StopIntent.cancel:
            if is_wheel:
                # SIGTERM -> 10s -> SIGKILL the process group, then authoritative
                # canceled regardless of the child's exit code.
                await self._wheel_runner.terminate(cmd.execution_id)
                self._store.mark_done(cmd.execution_id, result="canceled")
                await self._events.emit_terminal(
                    cmd.task_id, cmd.execution_id, AgentEventType.canceled
                )
                return
            if state is None or state.phase != "started":
                # No local state (cancelled before it ever started), or already
                # wrapped up locally. There is nothing to drive across ticks, and
                # ``attempt.canceled`` is a must-deliver contract
                # (docs/architecture/03-execution-and-logs.md): report it now,
                # exactly as before. Never revive a finished attempt by pushing
                # its phase back to ``started``.
                await self._runner.stop(cmd.execution_id, cmd.task_id)
                self._store.mark_done(cmd.execution_id, result="canceled")
                await self._events.emit_terminal(
                    cmd.task_id, cmd.execution_id, AgentEventType.canceled
                )
                return
            await self._begin_stop(state, StopIntent.cancel)
            return

        # reclaim: kill if running, otherwise stay lost.
        if state is None:
            return  # process_missing -> idempotent ignore
        if is_wheel:
            # Kill resources but do NOT emit canceled (execution stays lost).
            await self._wheel_runner.terminate(cmd.execution_id)
            self._store.mark_done(cmd.execution_id, result="lost")
            return
        if state.phase != "started":
            # Already finished locally: re-emit whatever real terminal we hold
            # (agent>server override) and stop there. No signal, no revival.
            if state.result:
                await self._events.republish_current(cmd.task_id, cmd.execution_id)
            return
        if state.stop_requested_at:
            # A stop is already in flight and the watchdog owns this terminal.
            # This check MUST come before the status read below: by now we have
            # TERMed the job, so the runner's own ``mark_canceled`` makes a
            # departed job resolve as ``canceled`` -- reporting that would
            # overwrite the server's ``lost`` with a terminal we manufactured.
            return
        # Read the status BEFORE any signal goes out: once ``stop`` succeeds the
        # runner sets ``canceled`` on the state, after which a departed job
        # resolves as ``canceled`` -- our own doing, not an authoritative
        # terminal. This is the only point where an override is trustworthy.
        resp = await self._runner.status(cmd.execution_id, cmd.task_id)
        terminal = _STATUS_TO_TERMINAL.get(resp.status)
        if terminal is not None:
            # a genuine terminal exists -> agent>server override (with stats).
            await self._finish_scrapy_attempt(state, terminal, exit_code=resp.exit_code)
            return
        await self._begin_stop(state, StopIntent.reclaim)

    # --- stop state machine ------------------------------------------------
    async def _begin_stop(self, state: AttemptState, intent: StopIntent) -> None:
        """Record the stop intent, then make one best-effort TERM attempt.

        The write comes first on purpose: ``_process`` XACKs a command even when
        its handler raises, so an intent that never reached disk is gone for
        good. Once it is recorded, :meth:`_stop_watchdog` owns the rest -- across
        ticks, and across an agent restart.
        """
        execution_id = state.execution_id
        if state.stop_requested_at:
            return  # already stopping -> idempotent, do not re-signal
        self._store.mark_stop_requested(
            execution_id,
            intent=intent.value,
            requested_at=self._now().isoformat(),
        )
        # The tick loop owns this execution's terminal now; stop pacing liveness.
        self._last_attempt_heartbeat.pop(execution_id, None)
        await self._send_stop_signal(
            execution_id, state.task_id, signal_name=None, escalation="term"
        )

    async def _send_stop_signal(
        self,
        execution_id: str,
        task_id: str,
        *,
        signal_name: str | None,
        escalation: str,
    ) -> bool:
        """Ask scrapyd to stop a job. Returns True iff it acknowledged.

        ``stop_escalation`` advances ONLY on success, so a failed TERM/KILL is
        simply retried by the next tick instead of being mistaken for progress.
        """
        try:
            resp = await self._runner.stop(
                execution_id, task_id, signal=signal_name
            )
        except Exception as exc:  # noqa: BLE001 - scrapyd/transport failure
            logger.warning(
                "stop signal %s failed for %s: %s",
                signal_name or "TERM", execution_id, exc,
            )
            return False
        if (resp.detail or {}).get("reason") == "cancel_failed":
            logger.warning(
                "stop signal %s rejected for %s: %s",
                signal_name or "TERM", execution_id, resp.detail,
            )
            return False
        self._store.mark_stop_escalation(execution_id, escalation=escalation)
        return True

    def _elapsed_since(self, stamp: str | None) -> float:
        if not stamp:
            return 0.0
        try:
            started = datetime.fromisoformat(stamp)
        except ValueError:
            return 0.0
        if started.tzinfo is None:
            started = started.replace(tzinfo=UTC)
        return (self._now() - started).total_seconds()

    async def _stop_watchdog(self, state: AttemptState) -> None:
        """Drive one in-flight stop forward by a single tick.

        Order matters: the deadline is checked FIRST so it covers every path
        that would otherwise return early -- scrapyd unreachable, a signal that
        will not send, or a process that simply refuses to die. Checking it last
        would let a permanently unreachable scrapyd defer the terminal forever.
        """
        execution_id = state.execution_id
        elapsed = self._elapsed_since(state.stop_requested_at)

        if self._stop_confirm_timeout > 0 and elapsed >= self._stop_confirm_timeout:
            logger.warning(
                "stop for %s unconfirmed after %.0fs; reporting the terminal and "
                "keeping the job mapping for reclamation",
                execution_id, elapsed,
            )
            await self._finalize_stop(state, confirmed=False)
            return

        # Liveness first, so a job that already died is wrapped up instead of
        # being shot again. Liveness only, never the resolved status: that
        # reports a departed job as ``canceled`` once we have TERMed it, and
        # reports ``unknown`` both for an unreachable scrapyd AND for a
        # cancelled ``pending`` job that left no log -- which would strand the
        # latter until the deadline.
        alive = await self._runner.is_job_alive(execution_id)
        if alive is False:
            await self._finalize_stop(state, confirmed=True)
            return
        if alive is None:
            return  # scrapyd unreachable: signalling is pointless, wait it out

        if state.stop_escalation is None:
            await self._send_stop_signal(
                execution_id, state.task_id, signal_name=None, escalation="term"
            )
        elif state.stop_escalation == "term" and elapsed >= self._stop_kill_after:
            await self._send_stop_signal(
                execution_id, state.task_id, signal_name="KILL", escalation="kill"
            )

    async def _finalize_stop(
        self, state: AttemptState, *, confirmed: bool
    ) -> None:
        """Report the terminal for a stop, per its intent.

        ``confirmed`` says whether the process is known to be gone. When it is
        not, the terminal is still reported (the contract is time-bounded) but
        ``kill_pending`` keeps the state -- and with it the scrapyd job id --
        alive so :meth:`_reclaim_watchdog` can keep trying. Dropping the mapping
        here would leave a running process nothing can find.
        """
        execution_id = state.execution_id
        if state.stop_intent == StopIntent.reclaim.value:
            # Stays lost: emitting ``canceled`` here would overwrite the
            # server's lost verdict with a terminal we manufactured.
            self._store.mark_done(
                execution_id,
                result="lost",
                kill_pending=not confirmed,
                terminal_pending=False,
            )
        else:
            self._store.mark_done(
                execution_id,
                result="canceled",
                kill_pending=not confirmed,
                terminal_pending=True,
            )
            await self._events.emit_terminal(
                state.task_id, execution_id, AgentEventType.canceled
            )
            self._store.clear_terminal_pending(execution_id)
        if confirmed:
            await self._run_deferred_cleanup(execution_id)

    async def _reclaim_watchdog(self, state: AttemptState) -> None:
        """Finish the work a wrapped-up attempt may still owe.

        Covers three leftovers, in order of how badly they hurt: a terminal that
        never reached ``emit`` (the server would eventually mis-judge it lost), a
        process that outlived its stop deadline (an untracked orphan), and a
        cleanup that had to wait for both. The ``cleanup_logs`` command was
        XACKed long ago, so nothing else will come back for these.
        """
        execution_id = state.execution_id

        if state.terminal_pending:
            # mark_done landed but the process died before emit's own durable
            # persist; nothing is queued anywhere, so re-publish from the state.
            await self._events.republish_current(state.task_id, execution_id)
            self._store.clear_terminal_pending(execution_id)
            state = self._store.read(execution_id) or state

        if state.kill_pending:
            alive = await self._runner.is_job_alive(execution_id)
            if alive is False:
                self._store.clear_kill_pending(execution_id)
                await self._run_deferred_cleanup(execution_id)
                return
            if alive is True and (
                self._kill_retry_interval <= 0
                or state.kill_last_attempt_at is None
                or self._elapsed_since(state.kill_last_attempt_at)
                >= self._kill_retry_interval
            ):
                logger.warning(
                    "scrapyd job %s for execution %s is still running after its "
                    "stop deadline; re-sending KILL",
                    state.scrapyd_job_id, execution_id,
                )
                await self._send_stop_signal(
                    execution_id, state.task_id,
                    signal_name="KILL", escalation="kill",
                )
                self._store.mark_kill_attempt(
                    execution_id, at=self._now().isoformat()
                )
            return  # never clean up while the process may still be alive

        if state.cleanup_pending:
            await self._run_deferred_cleanup(execution_id)

    async def _run_deferred_cleanup(self, execution_id: str) -> None:
        """Run a cleanup that was deferred, once it is finally safe.

        All three conditions must hold: the process is gone (or we would drop
        the job mapping we still need), the terminal is handed over (or we would
        drop the result we still owe the server), and a cleanup was actually
        requested.
        """
        state = self._store.read(execution_id)
        if state is None or not state.cleanup_pending:
            return
        if state.kill_pending or state.terminal_pending:
            return
        try:
            await self._do_cleanup(execution_id)
        except OSError:
            # Keep the flag and let the reclaim watchdog try again: the
            # originating cleanup_logs command was XACKed long ago, so giving up
            # here leaks the log and the workspace forever.
            logger.warning(
                "deferred cleanup for %s failed; will retry", execution_id,
                exc_info=True,
            )

    async def _handle_cleanup(self, cmd: AgentCommand) -> None:
        state = self._store.read(cmd.execution_id)
        if state is not None and self._cleanup_must_wait(state):
            # Deleting the state now would take the scrapyd job mapping (and the
            # terminal we still owe) with it. Record the request instead -- the
            # command is about to be XACKed either way, so an unpersisted
            # deferral is a cleanup that never happens.
            self._store.mark_cleanup_pending(cmd.execution_id)
            return
        await self._do_cleanup(cmd.execution_id)

    @staticmethod
    def _cleanup_must_wait(state: AttemptState) -> bool:
        """True while a stop, a reclamation, or a terminal is still outstanding.

        The reclaim case is not an edge case: for a cancel, ``cleanup_logs``
        normally arrives AFTER the terminal (the server starts its drain window
        from ``finished_at``), i.e. exactly when the state is ``done`` with
        ``kill_pending`` still set.
        """
        if state.phase == "started" and state.stop_requested_at:
            return True
        return bool(state.kill_pending or state.terminal_pending)

    async def _do_cleanup(self, execution_id: str) -> None:
        """Drop an execution's artifacts and state. Idempotent."""
        state = self._store.read(execution_id)
        if state is not None:
            if state.log_path:
                try:
                    Path(state.log_path).unlink()
                except (FileNotFoundError, IsADirectoryError):
                    pass
            # Python-wheel runs own a per-execution workspace (which contains the
            # merged ``job.log`` + the job.pgid sidecar); remove it wholesale.
            if state.workspace_path:
                shutil.rmtree(state.workspace_path, ignore_errors=True)
        self._store.delete(execution_id)
        # Resource caps (C1/C6): release per-execution bookkeeping now that the
        # execution is gone — the .logpos cursor (previously leaked forever), the
        # EOF dedup entry, and any residual runner state. The per-execution LOCK is
        # NOT dropped here: its lifecycle is owned by the refcounted keyed lock
        # (R-02), which removes the entry only when no holder/waiter remains, so
        # cleanup can never orphan a held lock. Note: _handle_cleanup itself runs
        # inside that lock, so the entry is released when this handler exits.
        self._release_execution(execution_id)

    def _release_execution(self, execution_id: str) -> None:
        """Drop per-execution in-memory + on-disk artifacts for a gone id.

        Does NOT touch ``_locks`` — see R-02 / :meth:`_execution_lock`.
        """
        self._inproc_wheel.discard(execution_id)
        self._last_attempt_heartbeat.pop(execution_id, None)
        if self._wheel_runner is not None:
            self._wheel_runner.forget(execution_id)
        if self._log_publisher is not None:
            # deletes the .logpos cursor file + clears _eof_sent (C1/C6).
            self._log_publisher.forget(execution_id)

    # --- background loop ---------------------------------------------------
    async def _run(self) -> None:
        if self._status is not None:
            self._status.mark_command_running(True)
        try:
            try:
                await self.recover()
            except Exception as exc:  # noqa: BLE001
                if self._status is not None:
                    self._status.mark_error(exc)
                logger.warning("command consumer recovery failed", exc_info=True)
            while not self._stop.is_set():
                try:
                    # retry any durably-queued events from earlier Redis outages
                    await self._events.replay_outbox()
                    await self.reconcile_started_attempts()
                    await self.drain_once(claim_pending=False, block=self._block_ms)
                except RedisTimeoutError:
                    if self._status is not None:
                        self._status.mark_command_read()
                except Exception as exc:  # noqa: BLE001 - never let the loop die
                    if self._status is not None:
                        self._status.mark_error(exc)
                    logger.warning("command consumer drain failed", exc_info=True)
                    await asyncio.sleep(0.5)
        finally:
            if self._status is not None:
                self._status.mark_command_running(False)

    def start(self) -> None:
        if self._task is None:
            self._stop.clear()
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._task = None
        # Cancel + await tracked wheel wait tasks so no subprocess waiter leaks.
        for task in list(self._wait_tasks.values()):
            task.cancel()
        for task in list(self._wait_tasks.values()):
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        self._wait_tasks.clear()
        if self._wheel_runner is not None:
            await self._wheel_runner.aclose()
