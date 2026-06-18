"""Tests for the reconcile loop's lost-escalation timer.

Regression: a successful drain must NOT reset the unreachable/unknown timer, so
an attempt whose agent stays status=unknown still escalates to ``lost`` within
``unreachable_lost_seconds`` (decision #11: never stuck running forever).
"""

from __future__ import annotations

from dopilot_protocol import AttemptStatus
from dopilot_server.logs import loop as loop_mod
from dopilot_server.services import states


async def test_status_unknown_escalates_to_lost_despite_drains(
    seeder, db_session, fake_agent, subscriptions, exec_settings, monkeypatch
):
    exec_settings.logs.unreachable_lost_seconds = 5
    exec_settings.logs.status_poll_interval_seconds = 5
    execution, attempt, _log = await seeder.running_execution()
    fake_agent.default_status = AttemptStatus.unknown  # /status -> unknown

    clock = {"t": 1000.0}
    monkeypatch.setattr(loop_mod.time, "monotonic", lambda: clock["t"])

    rl = loop_mod.ReconcileLoop(
        None, exec_settings, fake_agent, subscriptions, refresh_nodes_enabled=False
    )
    hot = {execution.id}  # hot -> 1s drain interval, so drains run between polls

    # t=1000: drain (ok) + poll(unknown) -> start the lost timer.
    await rl._process(db_session, attempt, hot, 0.0)
    assert attempt.status == states.ATTEMPT_RUNNING

    # t=1002: only a drain is due (poll interval 5s). A successful drain must
    # NOT reset the lost timer.
    clock["t"] = 1002.0
    await rl._process(db_session, attempt, hot, 0.0)
    assert attempt.status == states.ATTEMPT_RUNNING

    # t=1006: poll again -> 6s since first unknown >= 5s -> lost.
    clock["t"] = 1006.0
    await rl._process(db_session, attempt, hot, 0.0)
    assert attempt.status == states.ATTEMPT_LOST
    assert execution.status == states.EXEC_LOST


async def test_status_running_clears_lost_timer(
    seeder, db_session, fake_agent, subscriptions, exec_settings, monkeypatch
):
    """A positive /status (running) clears the timer so it never escalates."""
    exec_settings.logs.unreachable_lost_seconds = 5
    exec_settings.logs.status_poll_interval_seconds = 1
    execution, attempt, _log = await seeder.running_execution()

    clock = {"t": 1000.0}
    monkeypatch.setattr(loop_mod.time, "monotonic", lambda: clock["t"])
    rl = loop_mod.ReconcileLoop(
        None, exec_settings, fake_agent, subscriptions, refresh_nodes_enabled=False
    )
    hot = {execution.id}

    fake_agent.default_status = AttemptStatus.unknown
    await rl._process(db_session, attempt, hot, 0.0)  # t=1000: timer starts
    clock["t"] = 1003.0
    fake_agent.default_status = AttemptStatus.running  # agent recovers
    await rl._process(db_session, attempt, hot, 0.0)  # clears timer
    clock["t"] = 1010.0
    fake_agent.default_status = AttemptStatus.unknown
    await rl._process(db_session, attempt, hot, 0.0)  # timer restarts here
    assert attempt.status == states.ATTEMPT_RUNNING  # not lost (timer reset)
