"""No-progress detection: alert on an attempt that is alive but not working.

A heartbeat only proves scrapyd still lists the job, which stays true for a
spider wedged in its close phase — that is how a stuck job held a schedule's
only concurrency slot for two hours. Progress is therefore tracked on its own
clocks and, crucially, never feeds the lost/reclaim path: the worst a false
positive can do is post a notification.

The state transitions here are driven through the real ``apply_event`` heartbeat
path rather than by poking columns, so the tests exercise the same code the
agent actually reaches.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from dopilot_protocol import AgentEvent, AgentEventType
from dopilot_server.models.command_outbox import CommandOutbox
from dopilot_server.models.execution import Execution, ExecutionLogFile, Task
from dopilot_server.models.node import Node
from dopilot_server.models.notification import (
    TYPE_ATTEMPT_NO_PROGRESS,
    Notification,
)
from dopilot_server.redis.reconcile import reconcile_once
from dopilot_server.services import events as events_module
from dopilot_server.services import states
from dopilot_server.services.events import apply_event
from dopilot_server.services.executions import new_id
from sqlalchemy import select


class Clock:
    """One clock for both sides of the test.

    ``apply_event`` stamps its own ``datetime.now(UTC)``, so without pinning it
    a test cannot make a sample go stale through real heartbeats -- it would
    have to reach in and rewrite the very columns under test.
    """

    def __init__(self, start: datetime) -> None:
        self.now = start

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


@pytest.fixture
def clock(monkeypatch):
    c = Clock(datetime(2026, 9, 16, 12, 0, 0, tzinfo=UTC))

    class _FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):  # noqa: ARG003 - signature parity
            return c.now

    monkeypatch.setattr(events_module, "datetime", _FrozenDatetime)
    return c


def _settings(
    s,
    *,
    stall_after=1800,
    sample_max_age=300,
    auto_stop=False,
    hb_timeout=30,
    stall=300,
    lost_after=3600,
):
    s.agents.heartbeat_timeout_seconds = hb_timeout
    s.agents.stalled_attempt_seconds = stall
    s.agents.lost_after_stalled_seconds = lost_after
    s.agents.no_progress_stall_seconds = stall_after
    s.agents.no_progress_sample_max_age_seconds = sample_max_age
    s.agents.auto_stop_on_no_progress = auto_stop
    return s


async def _seed(
    session,
    now,
    *,
    agent_id="agent-1",
    progress_age=3600.0,
    log_bytes=4096,
):
    """An attempt that started a while ago and has a log size on record."""
    session.add(
        Node(
            id=uuid.uuid4(),
            agent_id=agent_id,
            endpoint=f"http://{agent_id}:6800",
            status="healthy",
            capabilities={"scrapy": True},
            health={},
            last_seen_at=now,
        )
    )
    task = Task(
        id=new_id(), artifact_type="scrapy", target="demo:phase1",
        status=states.TASK_RUNNING, params={},
    )
    session.add(task)
    execution = Execution(
        id=new_id(), task_id=task.id, agent_id=agent_id,
        status=states.EXEC_RUNNING, error_detail={},
        started_at=now - timedelta(seconds=progress_age),
        last_event_at=now - timedelta(seconds=progress_age),
        log_bytes=log_bytes,
        last_progress_at=now - timedelta(seconds=progress_age),
        last_progress_sample_at=None,
        no_progress_at=None,
    )
    session.add(execution)
    session.add(
        ExecutionLogFile(
            task_id=task.id, execution_id=execution.id, stream="log",
            storage_path="/tmp/x.log", size_bytes=0, last_pulled_offset=0,
            status=states.LOG_ACTIVE,
        )
    )
    await session.commit()
    return task, execution


async def _heartbeat(session, execution, *, log_bytes=None):
    """Apply a real agent heartbeat (the only way the clocks should move)."""
    await apply_event(
        session,
        AgentEvent(
            event_id=uuid.uuid4().hex,
            agent_id=execution.agent_id or "agent-1",
            task_id=execution.task_id,
            execution_id=execution.id,
            type=AgentEventType.heartbeat,
            created_at="t",
            log_bytes=log_bytes,
        ),
        uuid.uuid4().hex,
    )
    await session.commit()


async def _keep_agent_fresh(session, at):
    """Advance the node heartbeat alongside simulated time.

    Without it a test that moves ``now`` forward trips the agent-unreachable
    branch first and the execution is judged lost long before the no-progress
    check runs.
    """
    for node in (await session.execute(select(Node))).scalars().all():
        node.last_seen_at = at
    await session.commit()


async def _notifications(session):
    return (
        (
            await session.execute(
                select(Notification).where(
                    Notification.type == TYPE_ATTEMPT_NO_PROGRESS
                )
            )
        )
        .scalars()
        .all()
    )


async def _stops(session, execution_id):
    return (
        (
            await session.execute(
                select(CommandOutbox).where(
                    CommandOutbox.execution_id == execution_id,
                    CommandOutbox.type == "stop",
                )
            )
        )
        .scalars()
        .all()
    )


async def _execution(session, execution_id):
    return (
        await session.execute(select(Execution).where(Execution.id == execution_id))
    ).scalar_one()


async def test_alerts_once_without_touching_the_execution(db_session, settings):
    # TC-05: alive (fresh heartbeat), sample fresh, log idle past the threshold.
    _settings(settings, stall_after=600)
    now = datetime.now(UTC)
    _task, execution = await _seed(db_session, now, progress_age=1200)
    await _heartbeat(db_session, execution, log_bytes=4096)  # flat log

    report = await reconcile_once(db_session, settings, now=now)
    await db_session.commit()

    assert report.no_progress == 1
    notes = await _notifications(db_session)
    assert len(notes) == 1
    assert notes[0].payload["execution_id"] == execution.id
    assert notes[0].payload["auto_stopped"] is False
    e = await _execution(db_session, execution.id)
    # alerting only: still running, never judged lost, nothing was stopped
    assert e.status == states.EXEC_RUNNING
    assert e.no_progress_at is not None
    assert await _stops(db_session, execution.id) == []


async def test_repeated_passes_do_not_re_alert(db_session, settings):
    # TC-06: the latch makes it one-shot.
    _settings(settings, stall_after=600)
    now = datetime.now(UTC)
    _task, execution = await _seed(db_session, now, progress_age=1200)
    await _heartbeat(db_session, execution, log_bytes=4096)

    first = await reconcile_once(db_session, settings, now=now)
    await db_session.commit()
    stamped = (await _execution(db_session, execution.id)).no_progress_at

    for _ in range(2):
        again = await reconcile_once(db_session, settings, now=now)
        await db_session.commit()
        assert again.no_progress == 0

    assert first.no_progress == 1
    assert len(await _notifications(db_session)) == 1
    assert (await _execution(db_session, execution.id)).no_progress_at == stamped


async def test_reading_the_alert_does_not_unlatch_it(db_session, settings):
    # TC-07: notify() de-dupes only among UNREAD rows, so reading the alert
    # would let the next pass insert a second one. The latch lives on the
    # execution precisely so that cannot happen — and a real heartbeat (which
    # clears stalled_at) must not disturb it either.
    _settings(settings, stall_after=600)
    now = datetime.now(UTC)
    _task, execution = await _seed(db_session, now, progress_age=1200)
    await _heartbeat(db_session, execution, log_bytes=4096)
    await reconcile_once(db_session, settings, now=now)
    await db_session.commit()

    notes = await _notifications(db_session)
    assert len(notes) == 1
    notes[0].read_at = now
    await db_session.commit()

    # a genuine flat heartbeat arrives after the operator read the alert
    await _heartbeat(db_session, execution, log_bytes=4096)
    e = await _execution(db_session, execution.id)
    assert e.stalled_at is None  # the heartbeat really did clear that one
    assert e.no_progress_at is not None  # ...but not the latch

    report = await reconcile_once(db_session, settings, now=now)
    await db_session.commit()

    assert report.no_progress == 0
    assert len(await _notifications(db_session)) == 1


async def test_idle_below_threshold_is_quiet(db_session, settings):
    # TC-08
    _settings(settings, stall_after=1800)
    now = datetime.now(UTC)
    _task, execution = await _seed(db_session, now, progress_age=60)
    await _heartbeat(db_session, execution, log_bytes=4096)

    report = await reconcile_once(db_session, settings, now=now)
    await db_session.commit()

    assert report.no_progress == 0
    assert await _notifications(db_session) == []
    assert (await _execution(db_session, execution.id)).no_progress_at is None


async def test_stale_sample_is_never_judged(db_session, settings):
    # TC-09: a reading arrives, then the agent can only send bare heartbeats
    # (unreadable log / older agent). We are blind, not watching a stall. Both
    # auto-stop settings must stay silent — with it on, judging would kill
    # healthy work.
    for i, auto_stop in enumerate((False, True)):
        _settings(
            settings, stall_after=600, sample_max_age=300, auto_stop=auto_stop
        )
        now = datetime.now(UTC)
        _task, execution = await _seed(
            db_session, now, progress_age=1200, agent_id=f"agent-{i}"
        )
        await _heartbeat(db_session, execution, log_bytes=4096)  # last reading

        # bare heartbeats keep arriving: they prove liveness but carry no size,
        # so the sample clock stands still while wall time moves on
        for _ in range(3):
            await _heartbeat(db_session, execution, log_bytes=None)
        later = now + timedelta(seconds=900)
        await _keep_agent_fresh(db_session, later)  # all nodes stay reachable

        report = await reconcile_once(db_session, settings, now=later)
        await db_session.commit()

        assert report.no_progress == 0
        assert await _notifications(db_session) == []
        assert await _stops(db_session, execution.id) == []
        assert (await _execution(db_session, execution.id)).no_progress_at is None


async def test_recovered_sample_restarts_the_clock(db_session, settings, clock):
    # TC-10: readings stop, then come back WITH growth, then it goes quiet
    # again -> exactly one fresh alert, and not before the new idle stretch
    # passes the bar. Everything here moves through real heartbeats on a single
    # pinned clock; no progress column is written by the test itself.
    _settings(settings, stall_after=600, sample_max_age=300)
    now = clock.now
    _task, execution = await _seed(db_session, now, progress_age=1200)
    await _heartbeat(db_session, execution, log_bytes=4096)

    # the agent loses its reading and can only send bare heartbeats
    for _ in range(3):
        clock.advance(60)
        await _heartbeat(db_session, execution, log_bytes=None)
    clock.advance(600)  # the last real sample is now well past sample_max_age
    await _keep_agent_fresh(db_session, clock.now)
    assert (
        await reconcile_once(db_session, settings, now=clock.now)
    ).no_progress == 0
    await db_session.commit()

    # the log becomes readable again AND it grew -> real progress
    clock.advance(60)
    await _heartbeat(db_session, execution, log_bytes=9000)
    e = await _execution(db_session, execution.id)
    assert e.log_bytes == 9000
    assert e.no_progress_at is None

    # shortly after: sample is fresh, but it has not been idle long enough
    clock.advance(120)
    await _heartbeat(db_session, execution, log_bytes=9000)
    await _keep_agent_fresh(db_session, clock.now)
    assert (
        await reconcile_once(db_session, settings, now=clock.now)
    ).no_progress == 0
    await db_session.commit()

    # it stays flat past the threshold while still being sampled
    for _ in range(9):
        clock.advance(60)
        await _heartbeat(db_session, execution, log_bytes=9000)
    await _keep_agent_fresh(db_session, clock.now)

    report = await reconcile_once(db_session, settings, now=clock.now)
    await db_session.commit()

    assert report.no_progress == 1
    assert len(await _notifications(db_session)) == 1


async def test_zero_threshold_disables_the_feature(db_session, settings):
    # TC-11
    _settings(settings, stall_after=0)
    now = datetime.now(UTC)
    _task, execution = await _seed(db_session, now, progress_age=99999)
    await _heartbeat(db_session, execution, log_bytes=4096)

    report = await reconcile_once(db_session, settings, now=now)
    await db_session.commit()

    assert report.no_progress == 0
    assert await _notifications(db_session) == []
    assert (await _execution(db_session, execution.id)).no_progress_at is None


async def test_auto_stop_off_by_default_only_notifies(db_session, settings):
    # TC-12: the shipped default must never kill anything.
    _settings(settings, stall_after=600)
    assert settings.agents.auto_stop_on_no_progress is False
    now = datetime.now(UTC)
    _task, execution = await _seed(db_session, now, progress_age=1200)
    await _heartbeat(db_session, execution, log_bytes=4096)

    await reconcile_once(db_session, settings, now=now)
    await db_session.commit()

    assert len(await _notifications(db_session)) == 1
    assert await _stops(db_session, execution.id) == []


async def test_auto_stop_enqueues_exactly_one_cancel(db_session, settings):
    # TC-13: enqueue once on the latch transition. Redelivery belongs to the
    # outbox dispatcher; re-enqueueing every pass would pile up cancels while
    # the first is still being confirmed (confirmation takes tens of seconds,
    # reconcile runs every few).
    _settings(settings, stall_after=600, auto_stop=True)
    now = datetime.now(UTC)
    _task, execution = await _seed(db_session, now, progress_age=1200)
    await _heartbeat(db_session, execution, log_bytes=4096)

    await reconcile_once(db_session, settings, now=now)
    await db_session.commit()

    # more real heartbeats land (each clears stalled_at, none clears the latch)
    for _ in range(2):
        await _heartbeat(db_session, execution, log_bytes=4096)
        await reconcile_once(db_session, settings, now=now)
        await db_session.commit()

    stops = await _stops(db_session, execution.id)
    assert len(stops) == 1
    assert stops[0].intent == "cancel"
    notes = await _notifications(db_session)
    assert len(notes) == 1
    assert notes[0].payload["auto_stopped"] is True


async def test_lost_execution_never_also_gets_a_no_progress_cancel(
    db_session, settings
):
    # Regression for round-01 R-02: with lost_after_stalled_seconds SHORTER than
    # the sample window (a legal configuration), one pass could judge the
    # attempt lost, enqueue a reclaim, then fall through and enqueue a
    # no-progress cancel for the same execution — whose terminal would overwrite
    # the lost verdict.
    _settings(
        settings, stall_after=600, sample_max_age=3600, lost_after=300,
        stall=60, auto_stop=True,
    )
    now = datetime.now(UTC)
    _task, execution = await _seed(db_session, now, progress_age=1200)
    await _heartbeat(db_session, execution, log_bytes=4096)
    # event stall well past lost_after, while the sample is still "fresh"
    e = await _execution(db_session, execution.id)
    e.last_event_at = now - timedelta(seconds=900)
    await db_session.commit()

    report = await reconcile_once(db_session, settings, now=now)
    await db_session.commit()

    assert report.event_stall_lost == 1
    assert report.no_progress == 0
    stops = await _stops(db_session, execution.id)
    assert [s.intent for s in stops] == ["reclaim"]  # reclaim only, no cancel
    assert await _notifications(db_session) == []
    assert (await _execution(db_session, execution.id)).status == states.EXEC_LOST
