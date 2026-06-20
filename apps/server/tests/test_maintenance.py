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
            execution_id=task.id,
            attempt_id=execution.id,
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
                ExecutionLogFile.execution_id == task.id
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
    # one resolved outbox row per task (seam execution_id == task id).
    for tid in (old_done.id, active.id):
        db_session.add(
            CommandOutbox(
                command_id=_new_id(),
                agent_id="agent-1",
                execution_id=tid,
                attempt_id=_new_id(),
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
    rows = (await db_session.execute(select(CommandOutbox.execution_id))).all()
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
