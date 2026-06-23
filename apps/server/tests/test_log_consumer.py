"""Server log-consumer / log-apply tests (phase 1.5; phase-1.7 naming).

A parent run is a :class:`Task`; an atomic unit is an :class:`Execution`. On the
agent wire (``AgentLogEvent``) and the ``execution_log_files`` index the parent
id is ``task_id`` and the atomic id is ``execution_id`` (phase 2a clean-cut).
"""

from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta
from pathlib import Path

from dopilot_protocol import (
    LOG_STREAM,
    AgentLogEvent,
    to_stream_entry,
)
from dopilot_server.logs.sse import SubscriptionManager
from dopilot_server.models.command_outbox import CommandOutbox
from dopilot_server.models.execution import (
    Execution,
    ExecutionLogFile,
    Task,
)
from dopilot_server.redis.consumers import LogConsumer
from dopilot_server.redis.reconcile import finalize_drained_logs
from dopilot_server.services import states
from dopilot_server.services.executions import new_id
from dopilot_server.services.logs import (
    OUTCOME_APPENDED,
    OUTCOME_DROPPED_DUP,
    OUTCOME_EOF,
    OUTCOME_GAP_PARTIAL,
    apply_log_event,
)
from sqlalchemy import select


async def _seed(session, settings, *, agent_id="agent-1"):
    from dopilot_server.services import executions as svc

    task = Task(
        id=new_id(), artifact_type="scrapy", target="demo:phase1",
        status=states.TASK_RUNNING, params={},
    )
    session.add(task)
    execution = Execution(
        id=new_id(), task_id=task.id, agent_id=agent_id,
        status=states.EXEC_RUNNING, error_detail={},
    )
    session.add(execution)
    log_file = svc.create_log_file(session, settings, task, execution)
    await session.commit()
    return task, execution, log_file


def _log_event(execution, offset, content: bytes, *, eof=False):
    return AgentLogEvent(
        agent_id=execution.agent_id,
        task_id=execution.task_id,
        execution_id=execution.id,
        offset=offset,
        content_b64=base64.b64encode(content).decode("ascii"),
        size_bytes=len(content),
        eof=eof,
        created_at="t",
    )


async def _reload_lf(session, log_file):
    return (
        await session.execute(
            select(ExecutionLogFile).where(
                ExecutionLogFile.task_id == log_file.task_id,
                ExecutionLogFile.execution_id == log_file.execution_id,
            )
        )
    ).scalar_one()


async def _lf_by_execution(session, execution_id):
    res = await session.execute(
        select(ExecutionLogFile).where(ExecutionLogFile.execution_id == execution_id)
    )
    return res.scalar_one()


async def _task(session, task_id):
    res = await session.execute(select(Task).where(Task.id == task_id))
    return res.scalar_one()


async def _apply(session, settings, execution, offset, content, *, mgr=None, eof=False):
    return await apply_log_event(
        session, settings, _log_event(execution, offset, content, eof=eof), mgr
    )


async def test_contiguous_appends_and_publishes_sse(db_session, exec_settings):
    _t, execution, lf = await _seed(db_session, exec_settings)
    manager = SubscriptionManager()
    q = manager.subscribe(execution.id)

    out1 = await _apply(db_session, exec_settings, execution, 0, b"hello\n", mgr=manager)
    out2 = await _apply(db_session, exec_settings, execution, 6, b"world\n", mgr=manager)
    await db_session.commit()

    assert out1 == OUTCOME_APPENDED and out2 == OUTCOME_APPENDED
    lf = await _reload_lf(db_session, lf)
    assert lf.last_pulled_offset == 12
    assert lf.log_integrity == "complete"
    assert Path(lf.storage_path).read_bytes() == b"hello\nworld\n"
    # SSE got two log events
    assert q.qsize() == 2


async def test_duplicate_slice_dropped(db_session, exec_settings):
    _t, execution, lf = await _seed(db_session, exec_settings)
    await _apply(db_session, exec_settings, execution, 0, b"abc")
    out = await _apply(db_session, exec_settings, execution, 0, b"abc")
    await db_session.commit()
    assert out == OUTCOME_DROPPED_DUP
    lf = await _reload_lf(db_session, lf)
    assert lf.last_pulled_offset == 3
    assert Path(lf.storage_path).read_bytes() == b"abc"  # not doubled


async def test_gap_marks_sticky_partial(db_session, exec_settings):
    _t, execution, lf = await _seed(db_session, exec_settings)
    await _apply(db_session, exec_settings, execution, 0, b"head\n")
    # jump forward (a window was trimmed/lost): offset 100 > last_pulled 5
    out = await _apply(db_session, exec_settings, execution, 100, b"tail\n")
    await db_session.commit()

    assert out == OUTCOME_GAP_PARTIAL
    lf = await _reload_lf(db_session, lf)
    assert lf.log_integrity == "partial"
    assert lf.gap_count == 1
    assert lf.first_gap_expected_offset == 5 and lf.first_gap_actual_offset == 100
    # last_pulled jumped to agent logical end (100 + 5)
    assert lf.last_pulled_offset == 105
    body = Path(lf.storage_path).read_bytes()
    assert b"head\n" in body and b"tail\n" in body and b"log-gap" in body
    # final_offset = physical size (incl marker) >= logical bytes received
    assert lf.final_offset == lf.size_bytes == len(body)


async def test_gap_then_contiguous_stays_partial(db_session, exec_settings):
    _t, execution, lf = await _seed(db_session, exec_settings)
    await _apply(db_session, exec_settings, execution, 0, b"a")
    await _apply(db_session, exec_settings, execution, 50, b"b")  # gap
    # contiguous after the gap (offset == last_pulled = 51)
    out = await _apply(db_session, exec_settings, execution, 51, b"c")
    await db_session.commit()
    assert out == OUTCOME_APPENDED
    lf = await _reload_lf(db_session, lf)
    assert lf.log_integrity == "partial"  # sticky: never reverts to complete
    assert lf.last_pulled_offset == 52


async def test_gap_does_not_block_task_terminal(db_session, exec_settings):
    from dopilot_protocol import AgentEvent, AgentEventType
    from dopilot_server.services.events import apply_event

    task, execution, _lf = await _seed(db_session, exec_settings)
    await _apply(db_session, exec_settings, execution, 200, b"partial\n")
    # a finished event still rolls the task up despite the partial log
    ev = AgentEvent(
        event_id="ev1", agent_id="agent-1", task_id=task.id,
        execution_id=execution.id, type=AgentEventType.finished, exit_code=0, created_at="t",
    )
    await apply_event(db_session, ev, "m1")
    await db_session.commit()
    t = await _task(db_session, task.id)
    assert t.status == states.TASK_COMPLETE


async def test_eof_event_is_noop(db_session, exec_settings):
    _t, execution, lf = await _seed(db_session, exec_settings)
    out = await _apply(db_session, exec_settings, execution, 0, b"", eof=True)
    await db_session.commit()
    assert out == OUTCOME_EOF
    lf = await _reload_lf(db_session, lf)
    assert lf.last_pulled_offset == 0 and lf.status == states.LOG_ACTIVE


async def test_finalize_drained_logs_enqueues_cleanup(db_session, exec_settings):
    exec_settings.logs.log_drain_timeout_seconds = 5
    now = datetime.now(UTC)
    _t, execution, lf = await _seed(db_session, exec_settings)
    # execution is an agent-authoritative terminal, finished beyond the drain window
    execution.status = states.EXEC_FINISHED
    execution.finished_at = now - timedelta(seconds=30)
    await db_session.commit()

    count = await finalize_drained_logs(db_session, exec_settings, now=now)
    await db_session.commit()
    assert count == 1
    lf = await _reload_lf(db_session, lf)
    assert lf.status == states.LOG_COMPLETE
    cleanups = (
        await db_session.execute(
            select(CommandOutbox).where(
                CommandOutbox.execution_id == execution.id,
                CommandOutbox.type == "cleanup_logs",
            )
        )
    ).scalars().all()
    assert len(cleanups) == 1


async def test_finalize_skips_pure_server_lost(db_session, exec_settings):
    exec_settings.logs.log_drain_timeout_seconds = 0
    now = datetime.now(UTC)
    _t, execution, lf = await _seed(db_session, exec_settings)
    # pure server-lost (process maybe alive) -> must NOT auto-cleanup
    execution.status = states.EXEC_LOST
    execution.finished_at = now - timedelta(seconds=30)
    await db_session.commit()
    count = await finalize_drained_logs(db_session, exec_settings, now=now)
    await db_session.commit()
    assert count == 0
    cleanups = (
        await db_session.execute(
            select(CommandOutbox).where(CommandOutbox.type == "cleanup_logs")
        )
    ).scalars().all()
    assert cleanups == []


async def test_finalize_cleans_reclaimed_lost(db_session, exec_settings):
    # a lost execution for which a stop(reclaim) was issued (agent recovered ->
    # reclaim sent) IS cleaned up after the drain window.
    from dopilot_protocol import StopIntent
    from dopilot_server.services.outbox import create_stop_outbox

    exec_settings.logs.log_drain_timeout_seconds = 0
    now = datetime.now(UTC)
    _t, execution, lf = await _seed(db_session, exec_settings)
    execution.status = states.EXEC_LOST
    execution.finished_at = now - timedelta(seconds=30)
    lf.status = states.LOG_FINALIZING
    create_stop_outbox(
        db_session, task_id=execution.task_id, execution_id=execution.id,
        agent_id="agent-1", intent=StopIntent.reclaim,
    )
    await db_session.commit()

    count = await finalize_drained_logs(db_session, exec_settings, now=now)
    await db_session.commit()
    assert count == 1
    lf = await _reload_lf(db_session, lf)
    assert lf.status == states.LOG_COMPLETE
    cleanups = (
        await db_session.execute(
            select(CommandOutbox).where(
                CommandOutbox.execution_id == execution.id,
                CommandOutbox.type == "cleanup_logs",
            )
        )
    ).scalars().all()
    assert len(cleanups) == 1


async def test_apply_log_event_uses_async_file_boundary(
    db_session, exec_settings, monkeypatch
):
    """Regression: ``apply_log_event`` (an async path) must reach disk through
    the named async boundary ``files.aappend_increment`` (offloaded to a thread),
    never via a direct synchronous ``files.append`` call on the event loop."""
    from dopilot_server.logs import files as files_mod
    from dopilot_server.services import logs as logs_mod

    calls: list[tuple[bytes, bytes]] = []
    real = files_mod.aappend_increment

    async def spy(path, marker, raw):
        calls.append((marker, raw))
        return await real(path, marker, raw)

    # Patch the symbol the service module resolves at call time.
    monkeypatch.setattr(logs_mod.files, "aappend_increment", spy)

    _t, execution, lf = await _seed(db_session, exec_settings)
    out = await _apply(db_session, exec_settings, execution, 0, b"hi\n")
    await db_session.commit()

    assert out == OUTCOME_APPENDED
    assert calls == [(b"", b"hi\n")]  # one offloaded write, no marker
    lf = await _reload_lf(db_session, lf)
    assert lf.last_pulled_offset == 3
    assert Path(lf.storage_path).read_bytes() == b"hi\n"


async def test_log_consumer_drains_stream(db_session, exec_settings, fake_redis, test_sessionmaker):
    fake = fake_redis()
    _t, execution, lf = await _seed(db_session, exec_settings)
    manager = SubscriptionManager()
    consumer = LogConsumer(test_sessionmaker, fake, exec_settings, manager)
    await consumer.setup()

    await fake.xadd(LOG_STREAM, to_stream_entry(_log_event(execution, 0, b"one\n")))
    await fake.xadd(LOG_STREAM, to_stream_entry(_log_event(execution, 4, b"two\n")))
    n = await consumer.drain_once()
    assert n == 2

    async with test_sessionmaker() as s:
        lf2 = await _lf_by_execution(s, execution.id)
        assert lf2.last_pulled_offset == 8
        assert Path(lf2.storage_path).read_bytes() == b"one\ntwo\n"
