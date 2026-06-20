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
import logging
from pathlib import Path

from dopilot_protocol import (
    COMMAND_GROUP,
    AgentCommand,
    AgentCommandType,
    AgentEventType,
    AgentRunRequest,
    AttemptStatus,
    LostReason,
    ScrapyCommandError,
    StopIntent,
    command_stream,
    from_stream_entry,
    parse_scrapy_command,
)
from redis.exceptions import TimeoutError as RedisTimeoutError

from ..artifacts.cache import ArtifactCacheError, ScrapyArtifactCache
from ..runners.scrapyd import RunnerError, ScrapyRunner
from ..state.store import StateStore
from .events import EventPublisher
from .status import RedisRuntimeStatus

logger = logging.getLogger(__name__)

_STATUS_TO_TERMINAL = {
    AttemptStatus.finished: AgentEventType.finished,
    AttemptStatus.failed: AgentEventType.failed,
    AttemptStatus.canceled: AgentEventType.canceled,
}


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
        self._locks: dict[str, asyncio.Lock] = {}
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self._status = status
        self._artifact_cache = artifact_cache

    def _lock_for(self, execution_id: str) -> asyncio.Lock:
        lock = self._locks.get(execution_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[execution_id] = lock
        return lock

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
        await self._claim_pending()

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
            if state is None or state.phase != "started":
                continue
            resp = await self._runner.status(execution_id, state.task_id)
            terminal = _STATUS_TO_TERMINAL.get(resp.status)
            if terminal is None:
                continue
            self._store.mark_done(
                execution_id,
                result=terminal.short,
                exit_code=resp.exit_code,
            )
            await self._events.emit_terminal(
                state.task_id,
                execution_id,
                terminal,
                exit_code=resp.exit_code,
            )
            reconciled += 1
        return reconciled

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
        cmd = from_stream_entry(AgentCommand, fields)
        async with self._lock_for(cmd.execution_id):
            try:
                if cmd.type == AgentCommandType.run:
                    await self._handle_run(cmd)
                elif cmd.type == AgentCommandType.stop:
                    await self._handle_stop(cmd)
                elif cmd.type == AgentCommandType.cleanup_logs:
                    await self._handle_cleanup(cmd)
            except Exception:  # noqa: BLE001 - record + ack; never poison-loop
                logger.exception("command handler failed: %s", cmd.command_id)
            finally:
                # XACK = reliable takeover (success or idempotent skip).
                await self._redis.xack(self._stream, self._group, msg_id)

    # --- handlers ----------------------------------------------------------
    async def _handle_run(self, cmd: AgentCommand) -> None:
        existing = self._store.read(cmd.execution_id)
        if existing is not None:
            # idempotent: already have this execution -> re-emit, do not restart.
            await self._events.republish_current(cmd.task_id, cmd.execution_id)
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
            settings=dict(parsed.settings),
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

    async def _handle_stop(self, cmd: AgentCommand) -> None:
        if cmd.intent == StopIntent.cancel:
            # authoritative canceled regardless of process/state presence.
            await self._runner.stop(cmd.execution_id, cmd.task_id)
            self._store.mark_done(cmd.execution_id, result="canceled")
            await self._events.emit_terminal(
                cmd.task_id, cmd.execution_id, AgentEventType.canceled
            )
            return

        # reclaim: kill if running, otherwise stay lost.
        state = self._store.read(cmd.execution_id)
        if state is None:
            return  # process_missing -> idempotent ignore
        resp = await self._runner.status(cmd.execution_id, cmd.task_id)
        terminal = _STATUS_TO_TERMINAL.get(resp.status)
        if terminal is not None:
            # a genuine terminal exists -> agent>server override.
            self._store.mark_done(cmd.execution_id, result=terminal.short)
            await self._events.emit_terminal(
                cmd.task_id, cmd.execution_id, terminal, exit_code=resp.exit_code
            )
        else:
            # still running -> kill to reclaim resources; execution stays lost.
            await self._runner.stop(cmd.execution_id, cmd.task_id)
            self._store.mark_done(cmd.execution_id, result="lost")

    async def _handle_cleanup(self, cmd: AgentCommand) -> None:
        state = self._store.read(cmd.execution_id)
        if state is not None and state.log_path:
            try:
                Path(state.log_path).unlink()
            except FileNotFoundError:
                pass
        self._store.delete(cmd.execution_id)

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
