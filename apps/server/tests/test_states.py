"""Unit tests for the task/execution state machine + roll-up (phase 1.7)."""

from __future__ import annotations

from dopilot_server.services import states


def test_rollup_pending_while_active():
    # any active execution -> task not yet terminal
    assert states.rollup_task_status(["running", "finished"]) is None
    # empty set -> None (a zero-execution task is set to no_target at creation,
    # never rolled up)
    assert states.rollup_task_status([]) is None


def test_rollup_all_finished_is_complete():
    assert (
        states.rollup_task_status(["finished", "finished"])
        == states.TASK_COMPLETE
    )


def test_rollup_precedence_failed_over_lost_over_canceled():
    assert (
        states.rollup_task_status(["finished", "failed", "lost", "canceled"])
        == states.TASK_FAILED
    )
    assert (
        states.rollup_task_status(["finished", "lost", "canceled"])
        == states.TASK_LOST
    )
    assert (
        states.rollup_task_status(["finished", "canceled"])
        == states.TASK_CANCELED
    )


def test_task_transitions():
    assert states.is_valid_task_transition("queued", "running")
    assert states.is_valid_task_transition("running", "finalizing")
    assert states.is_valid_task_transition("finalizing", "complete")
    assert states.is_valid_task_transition("running", "running")  # idempotent
    # no resurrection from terminal
    assert not states.is_valid_task_transition("complete", "running")
    assert states.is_valid_task_transition("complete", "complete")
    # cannot jump queued -> finalizing
    assert not states.is_valid_task_transition("queued", "finalizing")


def test_no_target_is_terminal():
    assert states.TASK_NO_TARGET in states.TASK_TERMINAL
    # terminal with no out-edges (not even back to queued)
    assert states.is_valid_task_transition("no_target", "no_target")
    assert not states.is_valid_task_transition("no_target", "queued")
    assert not states.is_valid_task_transition("no_target", "running")
    # and a roll-up can never produce it (creation-time only)
    assert "no_target" not in {
        states.rollup_task_status(["finished"]),
        states.rollup_task_status(["failed"]),
        states.rollup_task_status([]),
    }


def test_execution_transitions():
    assert states.is_valid_execution_transition("pending", "running")
    assert states.is_valid_execution_transition("running", "finished")
    assert states.is_valid_execution_transition("running", "lost")
    assert not states.is_valid_execution_transition("finished", "running")


def test_execution_lost_is_soft_terminal_overridable():
    # phase 1.5: an agent-authoritative terminal may override a server-lost
    for new in ("finished", "failed", "canceled"):
        assert states.is_valid_execution_transition("lost", new), new
    # idempotent same->same still allowed
    assert states.is_valid_execution_transition("lost", "lost")
    # but lost cannot regress to a non-terminal
    assert not states.is_valid_execution_transition("lost", "running")
    assert not states.is_valid_execution_transition("lost", "pending")


def test_task_lost_is_soft_terminal_overridable():
    # phase 1.5: task `lost` re-rolls when its execution is reconciled
    for new in ("complete", "failed", "canceled"):
        assert states.is_valid_task_transition("lost", new), new
    assert states.is_valid_task_transition("lost", "lost")
    assert not states.is_valid_task_transition("lost", "running")
    # other task terminals stay frozen
    assert not states.is_valid_task_transition("complete", "failed")
    assert states.is_valid_task_transition("complete", "complete")


def test_hard_terminals_remain_mutually_non_transitionable():
    for old in ("finished", "failed", "canceled"):
        for new in ("finished", "failed", "canceled", "lost", "running"):
            if old == new:
                assert states.is_valid_execution_transition(old, new)
            else:
                assert not states.is_valid_execution_transition(old, new), (old, new)


def test_agent_to_exec_mapping():
    from dopilot_protocol import AttemptStatus

    assert states.AGENT_TO_EXEC[AttemptStatus.finished] == states.EXEC_FINISHED
    assert states.AGENT_TO_EXEC[AttemptStatus.running] == states.EXEC_RUNNING
    assert states.AGENT_TO_EXEC[AttemptStatus.unknown] is None
