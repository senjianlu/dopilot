"""Manual maintenance services (phase 1.8.2).

Two operator-driven, manual-only maintenance actions. NEITHER runs on a timer —
phase 1.8.2 is explicitly manual cleanup, not automatic retention.

1. :func:`cleanup_terminal_data` — delete OLD TERMINAL task data (tasks +
   their executions + log index rows + the on-disk log bodies + their
   command-outbox rows). It never touches a queued/running/finalizing task. A
   ``dry_run`` computes the would-delete counts without mutating anything.

2. :func:`mark_task_lost` — manually mark a STUCK ACTIVE task ``lost`` (its
   non-terminal executions become ``lost`` with a manual reason). It NEVER
   hard-deletes active data; it reuses the same soft-terminal ``lost`` semantics
   as the reconcile loop (:func:`dopilot_server.redis.reconcile.mark_lost`), so a
   late agent-authoritative terminal can still override it.

Naming (phase 2a clean-cut): the log index + command outbox key on ``task_id``
(= the parent :class:`Task` id) and ``execution_id`` (= the atomic
:class:`Execution` id). The queries below filter on ``task_id``.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta

from dopilot_protocol import StopIntent
from dopilot_protocol.streams import EVENT_STREAM, LOG_STREAM
from sqlalchemy import delete, exists, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..config.settings import Settings
from ..errors import ApiError
from ..logs import files
from ..logs.dir_gauge import LogsDirGauge, file_size
from ..models.command_outbox import (
    OUTBOX_CANCELED,
    OUTBOX_FAILED,
    OUTBOX_SENT,
    OUTBOX_UNRESOLVED,
    CommandOutbox,
)
from ..models.event_audit import EventAudit
from ..models.execution import Execution, ExecutionLogFile, Task
from ..models.node import Node
from ..models.notification import (
    SEVERITY_ERROR,
    SEVERITY_INFO,
    TYPE_LOGS_DIR_OVER_BUDGET,
    TYPE_STALE_COMMAND_STREAMS_DELETED,
)
from ..redis import reconcile
from ..redis.client import RedisStreamClient
from . import executions as svc
from . import notifications as notif
from . import states
from .logs import INTEGRITY_TRUNCATED

log = logging.getLogger(__name__)

# Reason recorded on manually lost executions/tasks (audit in error/status detail).
MANUAL_LOST_REASON = "manual_cleanup"


@dataclass
class CleanupSummary:
    """Counts deleted (or, for a dry run, that WOULD be deleted)."""

    dry_run: bool
    cutoff: str
    tasks: int = 0
    executions: int = 0
    log_files: int = 0
    log_files_removed: int = 0
    log_bytes: int = 0
    command_outbox: int = 0

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class MarkLostSummary:
    task_id: str
    task_status: str
    executions_marked: int = 0
    already_terminal: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return asdict(self)


def _terminal_before(cutoff: datetime):
    """SQL predicate: a TERMINAL task whose effective time is before ``cutoff``.

    Effective time is ``finished_at`` when present, else ``created_at`` (a
    conservative fallback for terminal rows that never recorded a finish time).
    """
    return (
        Task.status.in_(tuple(states.TASK_TERMINAL)),
        or_(
            Task.finished_at < cutoff,
            (Task.finished_at.is_(None)) & (Task.created_at < cutoff),
        ),
    )


#: Log-file lifecycle states that are still being written / drained; tasks
#: owning one are NOT eligible for retention deletion or truncation.
_UNSEALED_LOG_STATUSES = (states.LOG_ACTIVE, states.LOG_FINALIZING)


#: Task sources whose outcome feeds a schedule's consecutive-error run; such a
#: task must be RECORDED (``outcome_recorded_at``) before retention may delete it.
_COUNTED_SOURCES = (states.TASK_SOURCE_TIMER, states.TASK_SOURCE_TRIGGER_NOW)


async def _sealed_terminal_task_ids(
    session: AsyncSession, cutoff: datetime | None, *, limit: int | None = None,
    only: list[str] | None = None, exclude: set[str] | None = None,
) -> list[str]:
    """Terminal tasks (before ``cutoff`` if given) eligible for retention.

    Log-flood guard: (1) every log file must be sealed — a task whose log is
    still ``active`` / ``finalizing`` may still receive increments from the
    single LogConsumer writer, so retention must never truncate or unlink it
    (single-writer invariant, ``files.py``); (2) a schedule task whose outcome
    has not been recorded yet (``outcome_recorded_at IS NULL``) is kept, so the
    recorder — which works in bounded batches and runs concurrently with the
    sweep — can never lose a consecutive-error entry to retention.
    """
    open_tasks = select(ExecutionLogFile.task_id).where(
        ExecutionLogFile.status.in_(_UNSEALED_LOG_STATUSES)
    )
    unrecorded_schedule_task = (
        Task.schedule_id.is_not(None)
        & Task.source.in_(_COUNTED_SOURCES)
        & Task.outcome_recorded_at.is_(None)
    )
    conds = [
        Task.status.in_(tuple(states.TASK_TERMINAL)),
        Task.id.not_in(open_tasks),
        ~unrecorded_schedule_task,
    ]
    if exclude:
        conds.append(Task.id.not_in(list(exclude)))
    if cutoff is not None:
        conds.append(
            or_(
                Task.finished_at < cutoff,
                (Task.finished_at.is_(None)) & (Task.created_at < cutoff),
            )
        )
    if only:
        conds.append(Task.id.in_(only))
    stmt = select(Task.id).where(*conds).order_by(
        Task.finished_at.asc().nulls_first(), Task.created_at.asc(), Task.id.asc()
    )
    if limit:
        stmt = stmt.limit(limit)
    return [tid for (tid,) in (await session.execute(stmt)).all()]


async def cleanup_terminal_data(
    session: AsyncSession,
    settings: Settings,
    *,
    cutoff: datetime,
    dry_run: bool = False,
    gauge: LogsDirGauge | None = None,
    only_task_ids: list[str] | None = None,
) -> CleanupSummary:
    """Delete terminal task data older than ``cutoff`` — failure-safe.

    Used by BOTH the manual maintenance API and the automatic retention sweep
    (:class:`RetentionSweepLoop`). Because the automatic sweep runs unattended, the
    deletion is ordered so an interruption can NEVER leave a live index row
    pointing at an already-deleted body (which would be an unmarked dangling
    index, violating the "log gaps are visible audit facts" invariant):

    STEP 1 — mark every matching ``execution_log_files`` row ``status='expired'``
      and **commit**. Once committed, an absent body is an explicit, auditable
      state (``expired``), not silent corruption.
    STEP 2 — unlink the on-disk bodies (offloaded so the blocking unlink/rmdir
      never runs on the event loop). A missing file is idempotent; a real unlink
      failure is logged and the row is left for the next sweep to retry.
    STEP 3 — delete the rows in FK-safe order (``execution_log_files`` ->
      ``executions`` -> ``command_outbox`` -> ``tasks``) and **commit**.

    A crash between any steps leaves expired-marked rows; the next sweep re-selects
    them (still terminal + old) and idempotently completes the deletion. Only
    terminal tasks are eligible, so a queued/running/finalizing task is never
    touched. ``dry_run`` returns the counts without mutating, unlinking, or
    committing anything (and is what the manual API preview uses).

    Unlike the pre-resource-caps version, this function OWNS its commits when not
    ``dry_run`` (it must, for the two-phase safety); callers no longer commit.
    """
    summary = CleanupSummary(dry_run=dry_run, cutoff=cutoff.isoformat())

    # Eligibility (log-flood guard): terminal AND every log file sealed.
    task_ids = await _sealed_terminal_task_ids(session, cutoff, only=only_task_ids)
    if not task_ids:
        return summary
    summary.tasks = len(task_ids)
    if not dry_run:
        # Lock order task -> log files: hold the rows for the whole two-phase
        # run so the LogConsumer / recorder cannot interleave on them.
        await session.execute(
            select(Task.id).where(Task.id.in_(task_ids)).with_for_update()
        )

    # Child executions (FK -> tasks.id). Counted for the summary; deleted below.
    exec_rows = (
        await session.execute(
            select(Execution.id).where(Execution.task_id.in_(task_ids))
        )
    ).all()
    summary.executions = len(exec_rows)

    # Log index rows keyed by task_id.
    lf_stmt = select(ExecutionLogFile).where(ExecutionLogFile.task_id.in_(task_ids))
    if not dry_run:
        lf_stmt = lf_stmt.with_for_update()
    log_files = (await session.execute(lf_stmt)).scalars().all()
    summary.log_files = len(log_files)
    summary.log_bytes = sum(int(lf.size_bytes or 0) for lf in log_files)

    # Command-outbox rows keyed by task_id. Safe to drop wholesale — the parent
    # task is terminal, so none of its commands are still in flight.
    outbox_rows = (
        await session.execute(
            select(CommandOutbox.command_id).where(
                CommandOutbox.task_id.in_(task_ids)
            )
        )
    ).all()
    summary.command_outbox = len(outbox_rows)

    if dry_run:
        return summary

    # STEP 1: mark bodies expired + commit BEFORE any unlink (audit fact first).
    await session.execute(
        update(ExecutionLogFile)
        .where(ExecutionLogFile.task_id.in_(task_ids))
        .values(status=states.LOG_EXPIRED, log_integrity=states.LOG_EXPIRED)
    )
    await session.commit()

    # STEP 2: unlink bodies. A body that could NOT be removed (permission error,
    # or a hard OSError) leaves its task OUT of the row deletion below, so the
    # expired row keeps pointing at the still-present file and the next sweep
    # retries the unlink. Never delete an index whose body still exists — that
    # would orphan the file forever (R-03). A missing file is idempotent success.
    failed_task_ids: set[str] = set()
    for lf in log_files:
        try:
            if await _aremove_settled(lf.storage_path, gauge):
                summary.log_files_removed += 1
                continue
        except OSError:
            log.error(
                "retention: error unlinking log body %s (retry next sweep)",
                lf.storage_path, exc_info=True,
            )
            failed_task_ids.add(lf.task_id)
            continue
        # aremove returned False: either already-gone (ok to delete the row) or
        # the file still exists (removal failed silently — must NOT delete the row).
        if await files.aexists(lf.storage_path):
            log.error(
                "retention: could not unlink log body %s (retry next sweep)",
                lf.storage_path,
            )
            failed_task_ids.add(lf.task_id)

    # STEP 3: delete only tasks whose bodies are fully gone, FK-safe + commit.
    # Tasks with a failed unlink stay (rows expired, retried next sweep).
    deletable = [tid for tid in task_ids if tid not in failed_task_ids]
    if deletable:
        await session.execute(
            delete(ExecutionLogFile).where(
                ExecutionLogFile.task_id.in_(deletable)
            )
        )
        await session.execute(
            delete(Execution).where(Execution.task_id.in_(deletable))
        )
        await session.execute(
            delete(CommandOutbox).where(CommandOutbox.task_id.in_(deletable))
        )
        await session.execute(delete(Task).where(Task.id.in_(deletable)))
    await session.commit()
    summary.tasks = len(deletable)
    return summary


async def _aremove_settled(path: str, gauge: LogsDirGauge | None) -> bool:
    """Unlink ``path`` and settle the logs-dir gauge in ONE critical section."""
    if gauge is None:
        return await files.aremove(path)
    async with gauge.writer():
        before = file_size(path)
        removed = await files.aremove(path)
        gauge.sub(before - file_size(path))
        return removed


def _maintenance_marker(cap: int) -> bytes:
    return f"\n[dopilot:log-truncated max_bytes={cap} reason=maintenance]\n".encode()


# Any dopilot truncation marker (consumer size-cap / maintenance / agent-side)
# that may legitimately sit right after ``cap`` in an already-processed file.
_ANY_CAP_MARKER = re.compile(rb"\A\n\[dopilot:(?:job-)?log-truncated [^\n\]]*\]\n\Z")
_MAX_MARKER_LEN = 160


def _already_capped(path: str, cap: int, size: int) -> bool:
    """True when the file is exactly ``cap`` + one dopilot marker (idempotent
    state). A raw ``cap + 1`` file with no marker is NOT in that state."""
    if size <= cap or size - cap > _MAX_MARKER_LEN:
        return False
    try:
        with open(path, "rb") as fh:
            fh.seek(cap)
            tail = fh.read(_MAX_MARKER_LEN + 1)
    except OSError:
        return False
    return _ANY_CAP_MARKER.match(tail) is not None


def _truncate_file(path: str, cap: int, marker: bytes) -> tuple[int, int]:
    """Cut ``path`` to ``cap`` + marker (thread). Returns ``(before, after)``.

    Candidate = anything above ``cap`` (a raw ``cap + 1`` file included); the
    only no-op above the cap is the already-cut ``cap + marker`` state."""
    before = file_size(path)
    if before <= cap or _already_capped(path, cap, before):
        return before, before
    with open(path, "r+b") as fh:
        fh.truncate(cap)
        fh.seek(cap)
        fh.write(marker)
        fh.flush()
    return before, file_size(path)


async def truncate_oversized_log_files(
    session: AsyncSession,
    settings: Settings,
    *,
    gauge: LogsDirGauge | None = None,
    limit: int = 500,
) -> int:
    """Cut SEALED log files above ``logs.max_file_bytes`` back to the cap.

    Only files whose lifecycle is ``complete`` (sealed by finalize / the outcome
    recorder) are touched — never one still being drained — and each is
    processed under ``task -> log_file`` row locks with a re-check. The cut is
    recorded as ``truncation_reason='maintenance'`` which does NOT count as an
    erroneous outcome (an already-recorded result never moves). Returns the
    number of files cut. Caller commits.
    """
    cap = settings.logs.max_file_bytes
    if cap <= 0:
        return 0
    marker = _maintenance_marker(cap)
    # Anything above the cap is a candidate. Rows the consumer / this step
    # already marked ``truncated`` are re-listed only while still above
    # ``cap + marker`` (legacy oversized files), so the settled ``cap + marker``
    # state never crowds the ``limit`` window; the on-disk tail check below is
    # the final idempotence guard.
    candidates = (
        await session.execute(
            select(ExecutionLogFile.task_id, ExecutionLogFile.execution_id, ExecutionLogFile.stream)
            .where(
                ExecutionLogFile.size_bytes > cap,
                or_(
                    ExecutionLogFile.log_integrity.is_(None),
                    ExecutionLogFile.log_integrity != INTEGRITY_TRUNCATED,
                    ExecutionLogFile.size_bytes > cap + len(marker),
                ),
                ExecutionLogFile.status == states.LOG_COMPLETE,
                ExecutionLogFile.final_offset.is_not(None),
            )
            .limit(limit)
        )
    ).all()
    cut = 0
    for task_id, execution_id, stream in candidates:
        await svc.get_task(session, task_id, for_update=True)
        lf = await svc.get_log_file(session, task_id, execution_id, stream, for_update=True)
        if lf is None or lf.status != states.LOG_COMPLETE or lf.final_offset is None:
            continue
        path = lf.storage_path
        if gauge is not None:
            async with gauge.writer():
                before, after = await asyncio.to_thread(_truncate_file, path, cap, marker)
                gauge.sub(before - after)
        else:
            before, after = await asyncio.to_thread(_truncate_file, path, cap, marker)
        if after == before:
            continue
        lf.size_bytes = after
        lf.final_offset = after
        lf.log_integrity = "truncated"
        lf.truncation_reason = "maintenance"
        cut += 1
    return cut


async def evict_logs_dir_to_budget(
    session: AsyncSession,
    settings: Settings,
    *,
    gauge: LogsDirGauge | None,
    now: datetime,
    max_victims: int = 500,
) -> dict:
    """Evict the oldest SEALED terminal tasks until the logs dir fits the budget.

    Returns ``{"evicted": n, "recovered": bool, "bytes": value}``. When nothing
    sealed is left to evict (all remaining logs belong to active / draining
    runs) the budget cannot be recovered here — the consumer's admission hard
    limit keeps the directory bounded — and a ``logs_dir_over_budget`` error
    notification is raised (day-bucketed). Owns its commits (delegates to
    ``cleanup_terminal_data``).
    """
    budget = settings.logs.max_total_bytes
    result = {"evicted": 0, "recovered": True, "bytes": 0, "skipped": 0}
    if budget <= 0 or gauge is None:
        return result
    await gauge.calibrate(now=now.timestamp())
    result["bytes"] = gauge.value
    # A victim whose body could not be unlinked (its row stays ``expired`` for
    # the next sweep to retry) is skipped THIS pass so the remaining, deletable
    # candidates still get their turn; bounded by ``max_victims`` per pass.
    skipped: set[str] = set()
    attempts = 0
    while gauge.value > budget and attempts < max_victims:
        victims = await _sealed_terminal_task_ids(session, None, limit=1, exclude=skipped)
        if not victims:
            result["recovered"] = False
            break
        attempts += 1
        summary = await cleanup_terminal_data(
            session, settings, cutoff=now, gauge=gauge, only_task_ids=victims
        )
        if summary.tasks == 0:
            skipped.add(victims[0])
            log.warning("retention: could not evict task %s this pass; skipping", victims[0])
            continue
        result["evicted"] += summary.tasks
        result["bytes"] = gauge.value
    if gauge.value > budget and attempts >= max_victims:
        result["recovered"] = False
    result["skipped"] = len(skipped)
    if not result["recovered"]:
        try:
            await notif.notify(
                session,
                type=TYPE_LOGS_DIR_OVER_BUDGET,
                severity=SEVERITY_ERROR,
                payload={"bytes": gauge.value, "budget": budget, "evicted": result["evicted"]},
                dedupe_key=now.strftime("%Y-%m-%d"),
            )
            await session.commit()
        except Exception:  # noqa: BLE001
            log.warning("logs_dir_over_budget notify failed", exc_info=True)
    return result


async def delete_stale_command_streams(
    session: AsyncSession,
    settings: Settings,
    redis_client: RedisStreamClient | None,
    *,
    now: datetime,
) -> list[str]:
    """Delete per-agent command streams left behind by retired agent ids.

    An agent id qualifies only when ALL hold: (1) no ``nodes`` row, OR the node
    is soft-deleted, OR its ``last_seen_at`` is older than
    ``stale_command_stream_days``; (2) the stream's newest entry is older than
    that window; (3) the agent has no non-terminal execution; (4) the agent has
    no unresolved / sent outbox row. Healthy or recently-seen agents are always
    kept. Returns the deleted agent ids. Caller commits.
    """
    days = settings.maintenance.stale_command_stream_days
    if days <= 0 or redis_client is None:
        return []
    cutoff = now - timedelta(days=days)
    cutoff_ms = int(cutoff.timestamp() * 1000)
    keys = await redis_client.scan_keys("dopilot:agent:*:commands")
    nodes = {
        n.agent_id: n
        for n in (await session.execute(select(Node))).scalars().all()
        if n.agent_id
    }
    deleted: list[str] = []
    for key in keys:
        parts = key.split(":")
        if len(parts) != 4 or parts[0] != "dopilot" or parts[1] != "agent":
            continue
        agent_id = parts[2]
        node = nodes.get(agent_id)
        if node is not None:
            seen = node.last_seen_at
            if seen is not None and seen.tzinfo is None:
                seen = seen.replace(tzinfo=UTC)
            retired = node.deleted_at is not None or seen is None or seen < cutoff
            if not retired:
                continue
        info = await redis_client.xinfo_stream(key)
        last = info.get("last-generated-id") or info.get("last-entry")
        if isinstance(last, list | tuple) and last:
            last = last[0]
        if isinstance(last, bytes):
            last = last.decode()
        try:
            last_ms = int(str(last).split("-")[0]) if last else 0
        except ValueError:
            last_ms = 0
        if last_ms and last_ms >= cutoff_ms:
            continue
        active = await session.execute(
            select(Execution.id).where(
                Execution.agent_id == agent_id,
                Execution.status.in_(tuple(states.EXEC_ACTIVE)),
            ).limit(1)
        )
        if active.first() is not None:
            continue
        pending = await session.execute(
            select(CommandOutbox.command_id).where(
                CommandOutbox.agent_id == agent_id,
                CommandOutbox.status.in_(sorted(OUTBOX_UNRESOLVED | {"sent"})),
            ).limit(1)
        )
        if pending.first() is not None:
            continue
        await redis_client.delete(key)
        deleted.append(agent_id)
    if deleted:
        log.warning("retention: deleted stale command streams for %s", deleted)
        try:
            await notif.notify(
                session,
                type=TYPE_STALE_COMMAND_STREAMS_DELETED,
                severity=SEVERITY_INFO,
                payload={"agent_ids": deleted, "count": len(deleted)},
                dedupe_key=now.strftime("%Y-%m-%d"),
            )
        except Exception:  # noqa: BLE001
            log.warning("stale_command_streams notify failed", exc_info=True)
    return deleted


async def prune_event_audit(
    session: AsyncSession,
    settings: Settings,
    *,
    now: datetime,
) -> int:
    """Delete ``event_audit`` rows older than the configured window (B3).

    ``event_audit`` grows by one row per consumed agent status event (the
    fastest-growing table) and had no cleanup path before the resource caps. Rows
    older than ``maintenance.event_audit_retention_days`` are deleted in bounded
    batches (``event_audit_delete_batch``), COMMITTING per batch so a large
    backlog never holds a long table lock. Returns the number of rows deleted.
    A retention of 0 disables pruning.
    """
    days = settings.maintenance.event_audit_retention_days
    if days <= 0:
        return 0
    cutoff = now - timedelta(days=days)
    batch = max(1, settings.maintenance.event_audit_delete_batch)
    total = 0
    while True:
        ids = (
            await session.execute(
                select(EventAudit.id)
                .where(EventAudit.processed_at < cutoff)
                .limit(batch)
            )
        ).scalars().all()
        if not ids:
            break
        await session.execute(
            delete(EventAudit).where(EventAudit.id.in_(ids))
        )
        await session.commit()
        total += len(ids)
        if len(ids) < batch:
            break
    return total


#: Outbox rows that reached a terminal outbox state (dispatch settled). The
#: complement of ``OUTBOX_UNRESOLVED`` — in-flight rows are NEVER pruned.
OUTBOX_RESOLVED = (OUTBOX_SENT, OUTBOX_FAILED, OUTBOX_CANCELED)


async def prune_resolved_outbox(
    session: AsyncSession,
    settings: Settings,
    *,
    now: datetime,
) -> int:
    """Delete RESOLVED command-outbox rows of settled tasks (OOM guard).

    ``sent`` rows used to stay forever ("a sent row normally stays sent") and
    grew unbounded — 424k rows OOM-looped the server on 2026-08-26. Rows in a
    RESOLVED outbox state (``sent`` / ``failed`` / ``canceled``) older than
    ``maintenance.outbox_retention_days`` (by ``updated_at``, i.e. when they
    settled) are deleted in bounded batches (``outbox_delete_batch``),
    COMMITTING per batch so a large backlog never holds a long table lock.
    Returns the number of rows deleted. A retention of 0 disables pruning.

    Safety boundary — NEVER deleted here, regardless of age:

    - ``stop(intent=reclaim)`` rows: :func:`~.outbox.reclaim_ever_issued` is
      deliberately status-blind (a ``sent`` or even ``failed`` row counts) and
      backs both the heartbeat path's at-most-once reclaim and the
      ``finalize_drained_logs`` cleanup gate for server-lost executions. The
      fact must live as long as the task; ``cleanup_terminal_data`` removes it
      with the task. At most one such row exists per execution, so the
      table-size impact of keeping them is negligible.
    - rows whose task is ACTIVE or ``lost``: ``lost`` is a SOFT terminal (a
      late agent event may still flip it), so its rows also only go with the
      task. Orphan rows (task row already gone) and hard-terminal tasks'
      rows are eligible.
    - ``OUTBOX_UNRESOLVED`` rows (pending / dispatching / failed_retryable):
      not in the RESOLVED whitelist — in-flight commands are untouchable.
    """
    days = settings.maintenance.outbox_retention_days
    if days <= 0:
        return 0
    cutoff = now - timedelta(days=days)
    batch = max(1, settings.maintenance.outbox_delete_batch)
    unsafe_task = tuple(states.TASK_ACTIVE) + (states.TASK_LOST,)
    total = 0
    while True:
        ids = (
            (
                await session.execute(
                    select(CommandOutbox.command_id)
                    .where(
                        CommandOutbox.status.in_(OUTBOX_RESOLVED),
                        CommandOutbox.updated_at < cutoff,
                        ~(
                            (CommandOutbox.type == "stop")
                            & (CommandOutbox.intent == StopIntent.reclaim.value)
                        ),
                        ~exists().where(
                            (Task.id == CommandOutbox.task_id)
                            & Task.status.in_(unsafe_task)
                        ),
                    )
                    .limit(batch)
                )
            )
            .scalars()
            .all()
        )
        if not ids:
            break
        await session.execute(
            delete(CommandOutbox).where(CommandOutbox.command_id.in_(ids))
        )
        await session.commit()
        total += len(ids)
        if len(ids) < batch:
            break
    return total


async def trim_log_streams(
    redis_client: RedisStreamClient | None,
    settings: Settings,
    *,
    now: datetime,
) -> dict[str, dict[str, int | str]]:
    """Time-trim the Redis log + event streams via ``XTRIM MINID`` (B4).

    Implements the previously-inert ``redis.log_retention_seconds``: entries
    older than the window are trimmed regardless of the per-XADD MAXLEN (the
    primary bound). ``minid`` is the millisecond epoch of ``now - retention`` —
    Redis stream ids are ``<ms>-<seq>``, so this drops every entry produced before
    that instant. A per-stream failure is logged and skipped (never aborts the
    automatic sweep), but — unlike the fire-and-forget original — it is REPORTED:
    each stream maps to ``{"trimmed": <n>}`` on success or ``{"error": "<msg>"}``
    on failure, so the manual ``sweep-now`` endpoint can surface a partial
    failure instead of silently swallowing it. Retention 0 (or no client)
    disables the time trim and returns an empty map.
    """
    seconds = settings.redis.log_retention_seconds
    if seconds <= 0 or redis_client is None:
        return {}
    minid = int((now.timestamp() - seconds) * 1000)
    if minid <= 0:
        return {}
    results: dict[str, dict[str, int | str]] = {}
    for stream in (LOG_STREAM, EVENT_STREAM):
        try:
            results[stream] = {
                "trimmed": await redis_client.xtrim(
                    stream, minid=minid, approximate=True
                )
            }
        except Exception as exc:  # noqa: BLE001 - one bad stream never aborts
            log.error(
                "retention: XTRIM %s MINID %s failed", stream, minid,
                exc_info=True,
            )
            results[stream] = {"error": f"{type(exc).__name__}: {exc}"}
    return results


async def mark_task_lost(
    session: AsyncSession, task: Task
) -> MarkLostSummary:
    """Manually mark a STUCK ACTIVE task (+ its active executions) ``lost``.

    Eligible only when the task is active (queued/running/finalizing). Active
    executions become ``lost`` with reason :data:`MANUAL_LOST_REASON` via the
    shared :func:`reconcile.mark_lost` (soft terminal, overridable by a later
    agent-authoritative terminal). The task is rolled up / forced to ``lost`` and
    the audit is recorded in ``status_reason`` / ``status_detail``. NEVER deletes.
    """
    if task.status not in states.TASK_ACTIVE:
        raise ApiError(
            409,
            "task.not_active",
            "errors.taskNotActive",
            {"task_id": task.id, "status": task.status},
        )

    now = datetime.now(UTC)
    # Terminal-writer protocol (log-flood guard): lock the task row first and
    # re-check it is still active under the lock (lock order task -> executions).
    locked = await svc.get_task(session, task.id, for_update=True)
    if locked is not None and locked is not task:
        await session.refresh(task)
    if task.status not in states.TASK_ACTIVE:
        raise ApiError(
            409,
            "task.not_active",
            "errors.taskNotActive",
            {"task_id": task.id, "status": task.status},
        )
    summary = MarkLostSummary(task_id=task.id, task_status=task.status)
    executions = await svc.list_executions(session, task.id)
    for execution in executions:
        if execution.status in states.EXEC_TERMINAL:
            summary.already_terminal.append(execution.id)
            continue
        if await reconcile.mark_lost(session, execution, MANUAL_LOST_REASON, now):
            summary.executions_marked += 1

    # reconcile.mark_lost rolls the task up when every execution is terminal; for
    # the zero-execution / not-yet-rolled case, force the active task to lost
    # (queued/running/finalizing -> lost is a valid transition).
    if task.status in states.TASK_ACTIVE and states.is_valid_task_transition(
        task.status, states.TASK_LOST
    ):
        task.status = states.TASK_LOST
        task.finished_at = now

    if task.status == states.TASK_LOST:
        task.status_reason = MANUAL_LOST_REASON
        task.status_detail = {
            "reason": MANUAL_LOST_REASON,
            "executions_marked": summary.executions_marked,
            "marked_at": now.isoformat(),
        }
    summary.task_status = task.status
    return summary
