"""Tests for the reconcile engine: drain, finalize, lost, cancel."""

from __future__ import annotations

from dopilot_server.clients.agent import AgentResponseError, AgentUnreachableError
from dopilot_server.logs import files, reconcile
from dopilot_server.services import states


async def test_drain_writes_advances_offset_and_publishes(
    seeder, db_session, fake_agent, subscriptions, exec_settings
):
    execution, attempt, log_file = await seeder.running_execution()
    fake_agent.tail_script[attempt.id] = ["hello\n"]
    queue = subscriptions.subscribe(execution.id)

    written, eof, finished = await reconcile.drain_attempt(
        db_session, exec_settings, fake_agent, subscriptions, attempt, log_file
    )

    assert written == 6
    assert log_file.size_bytes == 6
    assert log_file.last_pulled_offset == 6  # advanced to agent end_offset
    assert files.read_slice(log_file.storage_path, 0, 99)[2] == "hello\n"
    event = queue.get_nowait()
    assert event["type"] == "log"
    assert event["content"] == "hello\n"
    assert event["start_offset"] == 0 and event["end_offset"] == 6


async def test_drain_is_idempotent_on_lost_commit_replay(
    seeder, db_session, fake_agent, subscriptions, exec_settings
):
    """Crash after file write but before DB commit: bytes are on disk while the
    DB offsets are still 0. Re-draining the same agent range must NOT duplicate
    the bytes (write_increment short-circuits)."""
    execution, attempt, log_file = await seeder.running_execution()
    # simulate the pre-commit state: 6 bytes already on disk, DB offsets at 0.
    files.append(log_file.storage_path, b"hello\n")
    assert log_file.size_bytes == 0 and log_file.last_pulled_offset == 0
    fake_agent.tail_script[attempt.id] = ["hello\n"]  # agent re-serves [0,6]

    written, _eof, _finished = await reconcile.drain_attempt(
        db_session, exec_settings, fake_agent, subscriptions, attempt, log_file
    )

    assert files.size(log_file.storage_path) == 6  # not duplicated to 12
    assert log_file.size_bytes == 6
    assert log_file.last_pulled_offset == 6


async def test_drain_attempt_not_found_marks_missing(
    seeder, db_session, fake_agent, subscriptions, exec_settings
):
    execution, attempt, log_file = await seeder.running_execution()
    fake_agent.raises["tail"] = AgentResponseError(
        "http://agent:6800", 404, {"code": "agent.attempt_not_found"}
    )
    written, eof, finished = await reconcile.drain_attempt(
        db_session, exec_settings, fake_agent, subscriptions, attempt, log_file
    )
    assert written == 0
    assert log_file.status == states.LOG_MISSING


async def test_drain_unreachable_propagates(
    seeder, db_session, fake_agent, subscriptions, exec_settings
):
    _execution, attempt, log_file = await seeder.running_execution()
    fake_agent.raises["tail"] = AgentUnreachableError("http://agent:6800", "down")
    try:
        await reconcile.drain_attempt(
            db_session, exec_settings, fake_agent, subscriptions, attempt, log_file
        )
        raise AssertionError("expected AgentUnreachableError")
    except AgentUnreachableError:
        pass


async def test_finalize_completes_and_cleans_up(
    seeder, db_session, fake_agent, subscriptions, exec_settings
):
    execution, attempt, log_file = await seeder.running_execution()
    fake_agent.tail_script[attempt.id] = ["done\n"]
    queue = subscriptions.subscribe(execution.id)

    await reconcile.finalize_attempt(
        db_session,
        exec_settings,
        fake_agent,
        subscriptions,
        attempt,
        states.ATTEMPT_FINISHED,
        exit_code=0,
        poll_step=0.001,
    )

    assert attempt.status == states.ATTEMPT_FINISHED
    assert attempt.exit_code == 0
    assert attempt.finished_at is not None
    assert log_file.status == states.LOG_COMPLETE
    assert log_file.final_offset == log_file.size_bytes
    assert execution.status == states.EXEC_COMPLETE
    assert attempt.id in fake_agent.cleaned
    # a complete event was published
    events = [queue.get_nowait() for _ in range(queue.qsize())]
    assert any(e.get("type") == "complete" for e in events)


async def test_mark_attempt_lost(
    seeder, db_session, subscriptions
):
    execution, attempt, log_file = await seeder.running_execution()
    await reconcile.mark_attempt_lost(
        db_session, subscriptions, attempt, "unreachable"
    )
    assert attempt.status == states.ATTEMPT_LOST
    assert attempt.error_code == "agent.lost"
    assert log_file.status == states.LOG_MISSING
    assert execution.status == states.EXEC_LOST


async def test_cancel_execution(
    seeder, db_session, fake_agent, subscriptions, exec_settings
):
    execution, attempt, _log_file = await seeder.running_execution()
    fake_agent.tail_script[attempt.id] = []  # no remaining logs

    await reconcile.cancel_execution(
        db_session,
        exec_settings,
        fake_agent,
        subscriptions,
        execution,
        poll_step=0.001,
    )

    assert "stop" in fake_agent.call_names()
    assert attempt.status == states.ATTEMPT_CANCELED
    assert execution.status == states.EXEC_CANCELED
