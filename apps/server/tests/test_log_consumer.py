"""Server log-consumer / log-apply tests (phase 1.5)."""

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
    ExecutionAttempt,
    ExecutionLogFile,
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

    execution = Execution(
        id=new_id(), task_type="scrapy", target="demo:phase1",
        status=states.EXEC_RUNNING, params={},
    )
    session.add(execution)
    attempt = ExecutionAttempt(
        id=new_id(), execution_id=execution.id, agent_id=agent_id,
        status=states.ATTEMPT_RUNNING, error_detail={},
    )
    session.add(attempt)
    log_file = svc.create_log_file(session, settings, execution, attempt)
    await session.commit()
    return execution, attempt, log_file


def _log_event(attempt, offset, content: bytes, *, eof=False):
    return AgentLogEvent(
        agent_id=attempt.agent_id,
        execution_id=attempt.execution_id,
        attempt_id=attempt.id,
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
                ExecutionLogFile.execution_id == log_file.execution_id,
                ExecutionLogFile.attempt_id == log_file.attempt_id,
            )
        )
    ).scalar_one()


async def _lf_by_attempt(session, attempt_id):
    res = await session.execute(
        select(ExecutionLogFile).where(ExecutionLogFile.attempt_id == attempt_id)
    )
    return res.scalar_one()


async def _exec(session, execution_id):
    res = await session.execute(select(Execution).where(Execution.id == execution_id))
    return res.scalar_one()


async def _apply(session, settings, attempt, offset, content, *, mgr=None, eof=False):
    return await apply_log_event(
        session, settings, _log_event(attempt, offset, content, eof=eof), mgr
    )


async def test_contiguous_appends_and_publishes_sse(db_session, exec_settings):
    _e, attempt, lf = await _seed(db_session, exec_settings)
    manager = SubscriptionManager()
    q = manager.subscribe(attempt.execution_id)

    out1 = await _apply(db_session, exec_settings, attempt, 0, b"hello\n", mgr=manager)
    out2 = await _apply(db_session, exec_settings, attempt, 6, b"world\n", mgr=manager)
    await db_session.commit()

    assert out1 == OUTCOME_APPENDED and out2 == OUTCOME_APPENDED
    lf = await _reload_lf(db_session, lf)
    assert lf.last_pulled_offset == 12
    assert lf.log_integrity == "complete"
    assert Path(lf.storage_path).read_bytes() == b"hello\nworld\n"
    # SSE got two log events
    assert q.qsize() == 2


async def test_duplicate_slice_dropped(db_session, exec_settings):
    _e, attempt, lf = await _seed(db_session, exec_settings)
    await _apply(db_session, exec_settings, attempt, 0, b"abc")
    out = await _apply(db_session, exec_settings, attempt, 0, b"abc")
    await db_session.commit()
    assert out == OUTCOME_DROPPED_DUP
    lf = await _reload_lf(db_session, lf)
    assert lf.last_pulled_offset == 3
    assert Path(lf.storage_path).read_bytes() == b"abc"  # not doubled


async def test_gap_marks_sticky_partial(db_session, exec_settings):
    _e, attempt, lf = await _seed(db_session, exec_settings)
    await _apply(db_session, exec_settings, attempt, 0, b"head\n")
    # jump forward (a window was trimmed/lost): offset 100 > last_pulled 5
    out = await _apply(db_session, exec_settings, attempt, 100, b"tail\n")
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
    _e, attempt, lf = await _seed(db_session, exec_settings)
    await _apply(db_session, exec_settings, attempt, 0, b"a")
    await _apply(db_session, exec_settings, attempt, 50, b"b")  # gap
    # contiguous after the gap (offset == last_pulled = 51)
    out = await _apply(db_session, exec_settings, attempt, 51, b"c")
    await db_session.commit()
    assert out == OUTCOME_APPENDED
    lf = await _reload_lf(db_session, lf)
    assert lf.log_integrity == "partial"  # sticky: never reverts to complete
    assert lf.last_pulled_offset == 52


async def test_gap_does_not_block_execution_terminal(db_session, exec_settings):
    from dopilot_protocol import AgentEvent, AgentEventType
    from dopilot_server.services.events import apply_event

    execution, attempt, _lf = await _seed(db_session, exec_settings)
    await _apply(db_session, exec_settings, attempt, 200, b"partial\n")
    # a finished event still rolls the execution up despite the partial log
    ev = AgentEvent(
        event_id="ev1", agent_id="agent-1", execution_id=execution.id,
        attempt_id=attempt.id, type=AgentEventType.finished, exit_code=0, created_at="t",
    )
    await apply_event(db_session, ev, "m1")
    await db_session.commit()
    e = await _exec(db_session, execution.id)
    assert e.status == states.EXEC_COMPLETE


async def test_eof_event_is_noop(db_session, exec_settings):
    _e, attempt, lf = await _seed(db_session, exec_settings)
    out = await _apply(db_session, exec_settings, attempt, 0, b"", eof=True)
    await db_session.commit()
    assert out == OUTCOME_EOF
    lf = await _reload_lf(db_session, lf)
    assert lf.last_pulled_offset == 0 and lf.status == states.LOG_ACTIVE


async def test_finalize_drained_logs_enqueues_cleanup(db_session, exec_settings):
    exec_settings.logs.log_drain_timeout_seconds = 5
    now = datetime.now(UTC)
    _e, attempt, lf = await _seed(db_session, exec_settings)
    # attempt is an agent-authoritative terminal, finished beyond the drain window
    attempt.status = states.ATTEMPT_FINISHED
    attempt.finished_at = now - timedelta(seconds=30)
    await db_session.commit()

    count = await finalize_drained_logs(db_session, exec_settings, now=now)
    await db_session.commit()
    assert count == 1
    lf = await _reload_lf(db_session, lf)
    assert lf.status == states.LOG_COMPLETE
    cleanups = (
        await db_session.execute(
            select(CommandOutbox).where(
                CommandOutbox.attempt_id == attempt.id,
                CommandOutbox.type == "cleanup_logs",
            )
        )
    ).scalars().all()
    assert len(cleanups) == 1


async def test_finalize_skips_pure_server_lost(db_session, exec_settings):
    exec_settings.logs.log_drain_timeout_seconds = 0
    now = datetime.now(UTC)
    _e, attempt, lf = await _seed(db_session, exec_settings)
    # pure server-lost (process maybe alive) -> must NOT auto-cleanup
    attempt.status = states.ATTEMPT_LOST
    attempt.finished_at = now - timedelta(seconds=30)
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
    # a lost attempt for which a stop(reclaim) was issued (agent recovered ->
    # reclaim sent) IS cleaned up after the drain window.
    from dopilot_protocol import StopIntent
    from dopilot_server.services.outbox import create_stop_outbox

    exec_settings.logs.log_drain_timeout_seconds = 0
    now = datetime.now(UTC)
    _e, attempt, lf = await _seed(db_session, exec_settings)
    attempt.status = states.ATTEMPT_LOST
    attempt.finished_at = now - timedelta(seconds=30)
    lf.status = states.LOG_FINALIZING
    create_stop_outbox(
        db_session, execution_id=attempt.execution_id, attempt_id=attempt.id,
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
                CommandOutbox.attempt_id == attempt.id,
                CommandOutbox.type == "cleanup_logs",
            )
        )
    ).scalars().all()
    assert len(cleanups) == 1


async def test_log_consumer_drains_stream(db_session, exec_settings, fake_redis, test_sessionmaker):
    fake = fake_redis()
    _e, attempt, lf = await _seed(db_session, exec_settings)
    manager = SubscriptionManager()
    consumer = LogConsumer(test_sessionmaker, fake, exec_settings, manager)
    await consumer.setup()

    await fake.xadd(LOG_STREAM, to_stream_entry(_log_event(attempt, 0, b"one\n")))
    await fake.xadd(LOG_STREAM, to_stream_entry(_log_event(attempt, 4, b"two\n")))
    n = await consumer.drain_once()
    assert n == 2

    async with test_sessionmaker() as s:
        lf2 = await _lf_by_attempt(s, attempt.id)
        assert lf2.last_pulled_offset == 8
        assert Path(lf2.storage_path).read_bytes() == b"one\ntwo\n"
