"""Manual maintenance: terminal-data cleanup + stuck-task mark-lost (phase 1.8.2)."""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from dopilot_server.config.settings import Settings
from dopilot_server.errors import ApiError
from dopilot_server.logs import files
from dopilot_server.models.command_outbox import (
    OUTBOX_SENT,
    CommandOutbox,
)
from dopilot_server.models.execution import (
    Execution,
    ExecutionLogFile,
    Task,
)
from dopilot_server.services import maintenance as maint
from dopilot_server.services import states
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


def _new_id() -> str:
    return uuid.uuid4().hex


async def _make_task(
    session: AsyncSession,
    settings: Settings,
    *,
    status: str,
    age_days: float,
    exec_status: str,
    with_log: bool = True,
    use_created_at: bool = False,
) -> tuple[Task, Execution, ExecutionLogFile | None]:
    """Seed one task + execution (+ optional on-disk log) at a given age."""
    when = datetime.now(UTC) - timedelta(days=age_days)
    task = Task(
        id=_new_id(),
        artifact_type="scrapy",
        target="demo:phase1",
        node_strategy="all",
        status=status,
        params={"project": "demo", "spider": "phase1"},
        created_at=when,
        finished_at=None if (use_created_at or status in states.TASK_ACTIVE) else when,
    )
    session.add(task)
    execution = Execution(
        id=_new_id(),
        task_id=task.id,
        agent_id="agent-1",
        node_id="n1",
        endpoint="http://agent:6800",
        status=exec_status,
        error_detail={},
    )
    session.add(execution)
    log_file = None
    if with_log:
        path = files.log_path(
            settings.logs.root_dir, when, task.id, execution.id
        )
        files.append(path, b"phase1 demo spider started\nphase1 demo spider done\n")
        log_file = ExecutionLogFile(
            task_id=task.id,
            execution_id=execution.id,
            stream="log",
            storage_path=path,
            size_bytes=files.size(path),
            last_pulled_offset=0,
            status=states.LOG_COMPLETE,
        )
        session.add(log_file)
    await session.commit()
    return task, execution, log_file


# ---------------------------------------------------------------------------
# terminal cleanup
# ---------------------------------------------------------------------------


async def test_cleanup_deletes_only_old_terminal_tasks(
    db_session: AsyncSession, exec_settings: Settings
):
    old_done, _, old_log = await _make_task(
        db_session, exec_settings,
        status=states.TASK_COMPLETE, age_days=40, exec_status=states.EXEC_FINISHED,
    )
    recent_done, _, _ = await _make_task(
        db_session, exec_settings,
        status=states.TASK_COMPLETE, age_days=5, exec_status=states.EXEC_FINISHED,
    )

    cutoff = datetime.now(UTC) - timedelta(days=30)
    summary = await maint.cleanup_terminal_data(
        db_session, exec_settings, cutoff=cutoff
    )
    await db_session.commit()

    assert summary.tasks == 1
    assert summary.executions == 1
    assert summary.log_files == 1
    # the old terminal task is gone; the recent terminal one stays.
    assert await db_session.get(Task, old_done.id) is None
    assert await db_session.get(Task, recent_done.id) is not None
    # log index + on-disk body for the deleted task are removed.
    assert summary.log_files_removed == 1
    assert old_log is not None and not os.path.exists(old_log.storage_path)


@pytest.mark.parametrize(
    "status", [states.TASK_QUEUED, states.TASK_RUNNING, states.TASK_FINALIZING]
)
async def test_cleanup_never_deletes_active_tasks(
    db_session: AsyncSession, exec_settings: Settings, status: str
):
    active, _, log = await _make_task(
        db_session, exec_settings,
        status=status, age_days=99, exec_status=states.EXEC_RUNNING,
    )
    cutoff = datetime.now(UTC) - timedelta(days=30)
    summary = await maint.cleanup_terminal_data(
        db_session, exec_settings, cutoff=cutoff
    )
    await db_session.commit()
    assert summary.tasks == 0
    assert await db_session.get(Task, active.id) is not None
    assert log is not None and os.path.exists(log.storage_path)


async def test_cleanup_unlinks_log_files_and_rows(
    db_session: AsyncSession, exec_settings: Settings
):
    task, execution, log = await _make_task(
        db_session, exec_settings,
        status=states.TASK_FAILED, age_days=40, exec_status=states.EXEC_FAILED,
    )
    assert log is not None and os.path.exists(log.storage_path)

    cutoff = datetime.now(UTC) - timedelta(days=30)
    await maint.cleanup_terminal_data(db_session, exec_settings, cutoff=cutoff)
    await db_session.commit()

    assert not os.path.exists(log.storage_path)
    remaining_logs = (
        await db_session.execute(
            select(ExecutionLogFile).where(
                ExecutionLogFile.task_id == task.id
            )
        )
    ).scalars().all()
    assert remaining_logs == []
    assert await db_session.get(Execution, execution.id) is None


async def test_cleanup_deletes_only_safe_outbox_rows(
    db_session: AsyncSession, exec_settings: Settings
):
    old_done, _, _ = await _make_task(
        db_session, exec_settings,
        status=states.TASK_COMPLETE, age_days=40, exec_status=states.EXEC_FINISHED,
        with_log=False,
    )
    active, _, _ = await _make_task(
        db_session, exec_settings,
        status=states.TASK_RUNNING, age_days=40, exec_status=states.EXEC_RUNNING,
        with_log=False,
    )
    # one resolved outbox row per task (task_id == the parent task id).
    for tid in (old_done.id, active.id):
        db_session.add(
            CommandOutbox(
                command_id=_new_id(),
                agent_id="agent-1",
                task_id=tid,
                execution_id=_new_id(),
                type="run",
                payload={},
                status=OUTBOX_SENT,
            )
        )
    await db_session.commit()

    cutoff = datetime.now(UTC) - timedelta(days=30)
    summary = await maint.cleanup_terminal_data(
        db_session, exec_settings, cutoff=cutoff
    )
    await db_session.commit()

    # only the deleted (terminal) task's outbox row is removed.
    assert summary.command_outbox == 1
    rows = (await db_session.execute(select(CommandOutbox.task_id))).all()
    assert [r[0] for r in rows] == [active.id]


async def test_cleanup_dry_run_changes_nothing(
    db_session: AsyncSession, exec_settings: Settings
):
    task, _, log = await _make_task(
        db_session, exec_settings,
        status=states.TASK_COMPLETE, age_days=40, exec_status=states.EXEC_FINISHED,
    )
    cutoff = datetime.now(UTC) - timedelta(days=30)
    summary = await maint.cleanup_terminal_data(
        db_session, exec_settings, cutoff=cutoff, dry_run=True
    )
    await db_session.commit()

    assert summary.dry_run is True
    assert summary.tasks == 1
    assert summary.log_files_removed == 0
    # nothing actually deleted.
    assert await db_session.get(Task, task.id) is not None
    assert log is not None and os.path.exists(log.storage_path)


async def test_cleanup_uses_created_at_when_no_finished_at(
    db_session: AsyncSession, exec_settings: Settings
):
    # terminal row without finished_at -> created_at is the conservative fallback.
    task, _, _ = await _make_task(
        db_session, exec_settings,
        status=states.TASK_NO_TARGET, age_days=40, exec_status=states.EXEC_FAILED,
        with_log=False, use_created_at=True,
    )
    cutoff = datetime.now(UTC) - timedelta(days=30)
    summary = await maint.cleanup_terminal_data(
        db_session, exec_settings, cutoff=cutoff
    )
    await db_session.commit()
    assert summary.tasks == 1
    assert await db_session.get(Task, task.id) is None


# ---------------------------------------------------------------------------
# stuck-task mark-lost
# ---------------------------------------------------------------------------


async def test_mark_lost_marks_active_executions_and_task(
    db_session: AsyncSession, exec_settings: Settings
):
    task, execution, _ = await _make_task(
        db_session, exec_settings,
        status=states.TASK_RUNNING, age_days=1, exec_status=states.EXEC_RUNNING,
    )
    summary = await maint.mark_task_lost(db_session, task)
    await db_session.commit()

    assert summary.executions_marked == 1
    assert summary.task_status == states.TASK_LOST
    refreshed_exec = await db_session.get(Execution, execution.id)
    assert refreshed_exec.status == states.EXEC_LOST
    assert refreshed_exec.lost_reason == maint.MANUAL_LOST_REASON
    # audit detail kept in error_detail / status_detail (not deleted).
    assert refreshed_exec.error_detail.get("reason") == maint.MANUAL_LOST_REASON
    refreshed_task = await db_session.get(Task, task.id)
    assert refreshed_task.status == states.TASK_LOST
    assert refreshed_task.status_reason == maint.MANUAL_LOST_REASON


async def test_mark_lost_rejects_terminal_task(
    db_session: AsyncSession, exec_settings: Settings
):
    task, _, _ = await _make_task(
        db_session, exec_settings,
        status=states.TASK_COMPLETE, age_days=1, exec_status=states.EXEC_FINISHED,
    )
    with pytest.raises(ApiError) as exc:
        await maint.mark_task_lost(db_session, task)
    assert exc.value.status_code == 409


async def test_mark_lost_does_not_touch_already_terminal_executions(
    db_session: AsyncSession, exec_settings: Settings
):
    # an active task with one finished + one running execution.
    task, running_exec, _ = await _make_task(
        db_session, exec_settings,
        status=states.TASK_RUNNING, age_days=1, exec_status=states.EXEC_RUNNING,
    )
    finished = Execution(
        id=_new_id(),
        task_id=task.id,
        agent_id="agent-1",
        status=states.EXEC_FINISHED,
        error_detail={},
        finished_at=datetime.now(UTC),
    )
    db_session.add(finished)
    await db_session.commit()

    summary = await maint.mark_task_lost(db_session, task)
    await db_session.commit()

    assert summary.executions_marked == 1
    assert finished.id in summary.already_terminal
    # the finished execution is preserved as finished (not hard-deleted/overwritten).
    refreshed = await db_session.get(Execution, finished.id)
    assert refreshed.status == states.EXEC_FINISHED


# ---------------------------------------------------------------------------
# API wiring
# ---------------------------------------------------------------------------


async def test_terminal_cleanup_api(
    client, db_session: AsyncSession, exec_settings: Settings
):
    await _make_task(
        db_session, exec_settings,
        status=states.TASK_COMPLETE, age_days=40, exec_status=states.EXEC_FINISHED,
        with_log=False,
    )
    resp = await client.post(
        "/api/v1/maintenance/terminal-cleanup",
        json={"older_than_days": 30, "dry_run": True},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["dry_run"] is True
    assert body["tasks"] == 1


async def test_terminal_cleanup_api_requires_cutoff(client):
    resp = await client.post("/api/v1/maintenance/terminal-cleanup", json={})
    assert resp.status_code == 400
    assert resp.json()["code"] == "maintenance.cutoff_required"


async def test_mark_lost_api(
    client, db_session: AsyncSession, exec_settings: Settings
):
    task, _, _ = await _make_task(
        db_session, exec_settings,
        status=states.TASK_RUNNING, age_days=1, exec_status=states.EXEC_RUNNING,
        with_log=False,
    )
    resp = await client.post(f"/api/v1/tasks/{task.id}/mark-lost")
    assert resp.status_code == 200
    body = resp.json()
    assert body["task_status"] == states.TASK_LOST
    assert body["executions_marked"] == 1


# --- R-04 (round 2): the manual API paths settle the shared logs-dir gauge ------------


async def test_terminal_cleanup_api_settles_shared_logs_gauge(
    client, db_session: AsyncSession, exec_settings: Settings
):
    from dopilot_server.logs.dir_gauge import LogsDirGauge, walk_size

    task, _e, log = await _make_task(
        db_session, exec_settings,
        status=states.TASK_COMPLETE, age_days=40, exec_status=states.EXEC_FINISHED,
    )
    assert log is not None and os.path.exists(log.storage_path)
    gauge = LogsDirGauge(exec_settings.logs.root_dir, budget=10**9)
    await gauge.calibrate()
    before = gauge.value
    assert before == walk_size(exec_settings.logs.root_dir) > 0
    # the real lifespan parks the gauge on app.state; the ASGI test client's app
    # gets it the same way
    client._transport.app.state.logs_gauge = gauge

    resp = await client.post(
        "/api/v1/maintenance/terminal-cleanup",
        json={"older_than_days": 30, "dry_run": False},
    )
    assert resp.status_code == 200 and resp.json()["tasks"] == 1
    assert not os.path.exists(log.storage_path)
    assert gauge.value == walk_size(exec_settings.logs.root_dir) == before - int(log.size_bytes)
    assert await db_session.get(Task, task.id) is None

    # sweep-now takes the same gauge
    task2, _e2, log2 = await _make_task(
        db_session, exec_settings,
        status=states.TASK_COMPLETE, age_days=40, exec_status=states.EXEC_FINISHED,
    )
    await gauge.calibrate()
    before = gauge.value
    resp = await client.post("/api/v1/maintenance/sweep-now")
    assert resp.status_code == 200, resp.text
    assert not os.path.exists(log2.storage_path)
    assert gauge.value == walk_size(exec_settings.logs.root_dir) == before - int(log2.size_bytes)


# ---------------------------------------------------------------------------
# TC-03/04/05/10/11/12 (fix-outbox-sent-oom): resolved-outbox retention
# ---------------------------------------------------------------------------

from dopilot_server.models.command_outbox import (  # noqa: E402
    OUTBOX_CANCELED,
    OUTBOX_DISPATCHING,
    OUTBOX_FAILED,
    OUTBOX_FAILED_RETRYABLE,
    OUTBOX_PENDING,
)


def _outbox_row(
    session: AsyncSession,
    *,
    task_id: str,
    status: str = OUTBOX_SENT,
    age_days: float = 8.0,
    type_: str = "run",
    intent: str | None = None,
    execution_id: str | None = None,
) -> CommandOutbox:
    row = CommandOutbox(
        command_id=_new_id(),
        agent_id="agent-1",
        task_id=task_id,
        execution_id=execution_id or _new_id(),
        type=type_,
        intent=intent,
        payload={},
        status=status,
        updated_at=datetime.now(UTC) - timedelta(days=age_days),
    )
    session.add(row)
    return row


async def _outbox_ids(session: AsyncSession) -> set[str]:
    return set(
        (await session.execute(select(CommandOutbox.command_id))).scalars().all()
    )


async def test_prune_resolved_outbox_deletes_in_batches(
    db_session: AsyncSession, settings: Settings
):
    """TC-03: old resolved rows of hard-terminal / missing tasks go, batched."""
    task, _, _ = await _make_task(
        db_session, settings,
        status=states.TASK_COMPLETE, age_days=40,
        exec_status=states.EXEC_FINISHED, with_log=False,
    )
    doomed = [
        _outbox_row(db_session, task_id=task.id, status=OUTBOX_SENT),
        _outbox_row(db_session, task_id=task.id, status=OUTBOX_FAILED),
        _outbox_row(db_session, task_id=task.id, status=OUTBOX_CANCELED),
        _outbox_row(db_session, task_id=_new_id()),  # orphan: task row gone
    ]
    await db_session.commit()
    settings.maintenance.outbox_delete_batch = 2  # 4 rows -> 2 batches

    deleted = await maint.prune_resolved_outbox(
        db_session, settings, now=datetime.now(UTC)
    )
    assert deleted == 4
    remaining = await _outbox_ids(db_session)
    assert not remaining.intersection({r.command_id for r in doomed})


@pytest.mark.parametrize(
    "status", [OUTBOX_PENDING, OUTBOX_DISPATCHING, OUTBOX_FAILED_RETRYABLE]
)
async def test_prune_outbox_keeps_unresolved_states(
    db_session: AsyncSession, settings: Settings, status: str
):
    """TC-04a: every OUTBOX_UNRESOLVED state survives, however old."""
    task, _, _ = await _make_task(
        db_session, settings,
        status=states.TASK_COMPLETE, age_days=40,
        exec_status=states.EXEC_FINISHED, with_log=False,
    )
    kept = _outbox_row(db_session, task_id=task.id, status=status, age_days=400)
    await db_session.commit()

    deleted = await maint.prune_resolved_outbox(
        db_session, settings, now=datetime.now(UTC)
    )
    assert deleted == 0
    assert kept.command_id in await _outbox_ids(db_session)


async def test_prune_outbox_keeps_active_fresh_and_disabled(
    db_session: AsyncSession, settings: Settings
):
    """TC-04b: active-task rows and fresh rows survive; 0 disables entirely."""
    active_task, _, _ = await _make_task(
        db_session, settings,
        status=states.TASK_RUNNING, age_days=40,
        exec_status=states.EXEC_RUNNING, with_log=False,
    )
    done_task, _, _ = await _make_task(
        db_session, settings,
        status=states.TASK_COMPLETE, age_days=40,
        exec_status=states.EXEC_FINISHED, with_log=False,
    )
    active_row = _outbox_row(db_session, task_id=active_task.id, age_days=40)
    fresh_row = _outbox_row(db_session, task_id=done_task.id, age_days=1)
    old_row = _outbox_row(db_session, task_id=done_task.id, age_days=40)
    await db_session.commit()

    deleted = await maint.prune_resolved_outbox(
        db_session, settings, now=datetime.now(UTC)
    )
    assert deleted == 1  # only the old resolved row of the settled task
    remaining = await _outbox_ids(db_session)
    assert active_row.command_id in remaining
    assert fresh_row.command_id in remaining
    assert old_row.command_id not in remaining

    # retention 0 = disabled: an eligible row is NOT touched
    another = _outbox_row(db_session, task_id=done_task.id, age_days=40)
    await db_session.commit()
    settings.maintenance.outbox_retention_days = 0
    deleted = await maint.prune_resolved_outbox(
        db_session, settings, now=datetime.now(UTC)
    )
    assert deleted == 0
    assert another.command_id in await _outbox_ids(db_session)


async def test_prune_outbox_keeps_reclaim_and_lost_rows(
    db_session: AsyncSession, settings: Settings
):
    """TC-11: reclaim rows (any status, even orphaned) and lost tasks' rows stay."""
    done_task, _, _ = await _make_task(
        db_session, settings,
        status=states.TASK_COMPLETE, age_days=40,
        exec_status=states.EXEC_FINISHED, with_log=False,
    )
    lost_task, _, _ = await _make_task(
        db_session, settings,
        status=states.TASK_LOST, age_days=40,
        exec_status=states.EXEC_LOST, with_log=False,
    )
    reclaim_sent = _outbox_row(
        db_session, task_id=done_task.id, status=OUTBOX_SENT,
        age_days=40, type_="stop", intent="reclaim",
    )
    reclaim_failed = _outbox_row(
        db_session, task_id=done_task.id, status=OUTBOX_FAILED,
        age_days=40, type_="stop", intent="reclaim",
    )
    reclaim_orphan = _outbox_row(
        db_session, task_id=_new_id(), status=OUTBOX_SENT,
        age_days=40, type_="stop", intent="reclaim",
    )
    lost_run = _outbox_row(db_session, task_id=lost_task.id, age_days=40)
    plain_old = _outbox_row(db_session, task_id=done_task.id, age_days=40)
    await db_session.commit()

    deleted = await maint.prune_resolved_outbox(
        db_session, settings, now=datetime.now(UTC)
    )
    assert deleted == 1  # ONLY the plain old row of the settled task
    remaining = await _outbox_ids(db_session)
    for row in (reclaim_sent, reclaim_failed, reclaim_orphan, lost_run):
        assert row.command_id in remaining
    assert plain_old.command_id not in remaining


async def test_prune_outbox_preserves_reclaim_invariants(
    db_session: AsyncSession, settings: Settings
):
    """TC-12: after a prune, heartbeat reclaim stays at-most-once and the
    lost-log finalize gate still opens (the persisted fact survived)."""
    import uuid as _uuid

    from dopilot_protocol import AgentEvent, AgentEventType
    from dopilot_server.redis.reconcile import finalize_drained_logs
    from dopilot_server.services.events import apply_event
    from dopilot_server.services.outbox import reclaim_ever_issued

    lost_task, execution, _ = await _make_task(
        db_session, settings,
        status=states.TASK_LOST, age_days=40,
        exec_status=states.EXEC_LOST, with_log=False,
    )
    execution.finished_at = datetime.now(UTC) - timedelta(days=39)
    reclaim_row = _outbox_row(
        db_session, task_id=lost_task.id, status=OUTBOX_SENT,
        age_days=40, type_="stop", intent="reclaim", execution_id=execution.id,
    )
    log_file = ExecutionLogFile(
        task_id=lost_task.id, execution_id=execution.id, stream="log",
        storage_path="/tmp/dopilot-tc12.log", size_bytes=0,
        last_pulled_offset=0, status=states.LOG_ACTIVE,
    )
    db_session.add(log_file)
    await db_session.commit()

    deleted = await maint.prune_resolved_outbox(
        db_session, settings, now=datetime.now(UTC)
    )
    assert deleted == 0
    assert reclaim_row.command_id in await _outbox_ids(db_session)
    assert await reclaim_ever_issued(db_session, execution.id) is True

    async def _reclaim_count() -> int:
        return len(
            (
                await db_session.execute(
                    select(CommandOutbox.command_id).where(
                        CommandOutbox.execution_id == execution.id,
                        CommandOutbox.type == "stop",
                        CommandOutbox.intent == "reclaim",
                    )
                )
            ).scalars().all()
        )

    # (a) heartbeat on the lost execution does NOT enqueue a second reclaim
    before = await _reclaim_count()
    assert before == 1
    ev = AgentEvent(
        event_id=_uuid.uuid4().hex,
        agent_id="agent-1",
        task_id=lost_task.id,
        execution_id=execution.id,
        type=AgentEventType.heartbeat,
        created_at="t",
    )
    await apply_event(db_session, ev, "m-tc12")
    await db_session.commit()
    assert await _reclaim_count() == 1

    # (b) the finalize gate still sees the reclaim fact: reclaimed-lost logs
    # ARE finalized (a pruned fact would leave the file draining forever)
    settings.logs.log_drain_timeout_seconds = 0
    exec_id = execution.id
    count = await finalize_drained_logs(db_session, settings)
    await db_session.commit()
    assert count == 1
    db_session.expire_all()
    lf = (
        await db_session.execute(
            select(ExecutionLogFile).where(
                ExecutionLogFile.execution_id == exec_id
            )
        )
    ).scalar_one()
    assert lf.status == states.LOG_COMPLETE


async def test_sweep_runs_outbox_prune(
    db_session: AsyncSession, exec_settings: Settings, test_sessionmaker
):
    """TC-05: RetentionSweepLoop.sweep_once wires the outbox prune in."""
    from dopilot_server.retention import RetentionSweepLoop

    task, _, _ = await _make_task(
        db_session, exec_settings,
        status=states.TASK_COMPLETE, age_days=5,  # young: survives step 1
        exec_status=states.EXEC_FINISHED, with_log=False,
    )
    doomed = _outbox_row(db_session, task_id=task.id, age_days=8)
    await db_session.commit()

    loop = RetentionSweepLoop(test_sessionmaker, exec_settings, None)
    await loop.sweep_once()

    assert doomed.command_id not in await _outbox_ids(db_session)
    assert await db_session.get(Task, task.id) is not None  # step 1 untouched


async def test_sweep_outbox_step_failure_isolation(
    db_session: AsyncSession, exec_settings: Settings, test_sessionmaker, monkeypatch
):
    """TC-10: the outbox step neither kills later steps nor dies with earlier ones."""
    import dopilot_server.retention as retention_mod
    from dopilot_server.retention import RetentionSweepLoop

    task, _, _ = await _make_task(
        db_session, exec_settings,
        status=states.TASK_COMPLETE, age_days=5,
        exec_status=states.EXEC_FINISHED, with_log=False,
    )
    doomed = _outbox_row(db_session, task_id=task.id, age_days=8)
    await db_session.commit()

    # (a) outbox prune raises -> later steps still run (notification prune spy)
    later_ran: list[bool] = []

    async def _boom(*a, **k):
        raise RuntimeError("outbox prune boom")

    async def _notif_spy(*a, **k):
        later_ran.append(True)
        return 0

    monkeypatch.setattr(retention_mod, "prune_resolved_outbox", _boom)
    monkeypatch.setattr(retention_mod, "prune_notifications", _notif_spy)
    loop = RetentionSweepLoop(test_sessionmaker, exec_settings, None)
    await loop.sweep_once()
    assert later_ran == [True]
    assert doomed.command_id in await _outbox_ids(db_session)  # prune really failed

    # (b) an EARLIER step raises -> the outbox prune still runs
    monkeypatch.undo()

    async def _audit_boom(*a, **k):
        raise RuntimeError("event audit boom")

    monkeypatch.setattr(retention_mod, "prune_event_audit", _audit_boom)
    loop = RetentionSweepLoop(test_sessionmaker, exec_settings, None)
    await loop.sweep_once()
    assert doomed.command_id not in await _outbox_ids(db_session)
