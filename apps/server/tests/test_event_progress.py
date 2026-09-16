"""Heartbeat progress semantics: telling "alive" apart from "doing something".

scrapyd keeps listing a spider that is wedged in its close phase, so a plain
heartbeat stays true indefinitely for a stuck job. The only progress evidence we
have is the job log growing, which the agent now attaches to each heartbeat. The
liveness clock (``last_event_at``, which drives lost/reclaim) must keep behaving
exactly as before — these tests pin that boundary.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from dopilot_protocol import AgentEvent, AgentEventType
from dopilot_server.models.execution import Execution, Task
from dopilot_server.services import states
from dopilot_server.services.events import apply_event
from dopilot_server.services.executions import new_id
from sqlalchemy import select


async def _seed(session, *, log_bytes=100, progress_age=600.0):
    now = datetime.now(UTC)
    task = Task(
        id=new_id(), artifact_type="scrapy", target="demo:phase1",
        status=states.TASK_RUNNING, params={},
    )
    session.add(task)
    execution = Execution(
        id=new_id(), task_id=task.id, agent_id="agent-1",
        status=states.EXEC_RUNNING, error_detail={},
        started_at=now - timedelta(seconds=progress_age),
        last_event_at=now - timedelta(seconds=progress_age),
        stalled_at=now - timedelta(seconds=progress_age),
        log_bytes=log_bytes,
        last_progress_at=now - timedelta(seconds=progress_age),
        last_progress_sample_at=now - timedelta(seconds=progress_age),
        no_progress_at=now - timedelta(seconds=progress_age),
    )
    session.add(execution)
    await session.commit()
    return task, execution


def _event(type_, execution, **kw) -> AgentEvent:
    return AgentEvent(
        event_id=uuid.uuid4().hex,
        agent_id="agent-1",
        task_id=execution.task_id,
        execution_id=execution.id,
        type=type_,
        created_at="t",
        **kw,
    )


async def _reload(session, execution):
    return (
        await session.execute(select(Execution).where(Execution.id == execution.id))
    ).scalar_one()


def _aware(dt):
    return dt if dt is None or dt.tzinfo else dt.replace(tzinfo=UTC)


async def test_growing_log_advances_both_clocks(db_session):
    # TC-01
    _task, execution = await _seed(db_session, log_bytes=100)
    before = _aware(execution.last_progress_at)

    await apply_event(
        db_session, _event(AgentEventType.heartbeat, execution, log_bytes=500), "m1"
    )
    await db_session.commit()

    e = await _reload(db_session, execution)
    assert e.log_bytes == 500
    assert _aware(e.last_progress_at) > before
    assert _aware(e.last_progress_sample_at) > before
    assert _aware(e.last_event_at) > before
    assert e.no_progress_at is None  # real progress clears the alert latch


async def test_flat_log_keeps_liveness_but_not_progress(db_session):
    # TC-02: the whole point. The attempt is alive (so lost/reclaim must stay
    # exactly as before) but it is not advancing.
    _task, execution = await _seed(db_session, log_bytes=100)
    progress_before = _aware(execution.last_progress_at)
    event_before = _aware(execution.last_event_at)

    await apply_event(
        db_session, _event(AgentEventType.heartbeat, execution, log_bytes=100), "m1"
    )
    await db_session.commit()

    e = await _reload(db_session, execution)
    # liveness side: untouched behaviour
    assert _aware(e.last_event_at) > event_before
    assert e.stalled_at is None
    # progress side: we saw a reading, but nothing moved
    assert _aware(e.last_progress_sample_at) > progress_before
    assert _aware(e.last_progress_at) == progress_before
    assert e.log_bytes == 100
    assert e.no_progress_at is not None  # latch survives a heartbeat


async def test_missing_reading_freezes_nothing(db_session):
    # TC-03: "could not sample" is not "no progress". Advancing the sample clock
    # here would let a blind server keep judging; overwriting log_bytes with
    # None would lose the last known size.
    _task, execution = await _seed(db_session, log_bytes=100)
    progress_before = _aware(execution.last_progress_at)
    sample_before = _aware(execution.last_progress_sample_at)

    await apply_event(
        db_session, _event(AgentEventType.heartbeat, execution), "m1"
    )
    await db_session.commit()

    e = await _reload(db_session, execution)
    assert _aware(e.last_progress_sample_at) == sample_before
    assert _aware(e.last_progress_at) == progress_before
    assert e.log_bytes == 100
    assert _aware(e.last_event_at) > progress_before  # still alive


async def test_lifecycle_event_counts_as_progress(db_session):
    # TC-04
    _task, execution = await _seed(db_session)
    before = _aware(execution.last_progress_at)

    await apply_event(
        db_session, _event(AgentEventType.running, execution), "m1"
    )
    await db_session.commit()

    e = await _reload(db_session, execution)
    assert _aware(e.last_progress_at) > before
    assert e.no_progress_at is None
