"""Unit tests for the execution/attempt state machine + roll-up."""

from __future__ import annotations

from dopilot_server.services import states


def test_rollup_pending_while_active():
    assert states.rollup_execution_status(["running", "finished"]) is None
    assert states.rollup_execution_status([]) is None


def test_rollup_all_finished_is_complete():
    assert (
        states.rollup_execution_status(["finished", "finished"])
        == states.EXEC_COMPLETE
    )


def test_rollup_precedence_failed_over_lost_over_canceled():
    assert (
        states.rollup_execution_status(["finished", "failed", "lost", "canceled"])
        == states.EXEC_FAILED
    )
    assert (
        states.rollup_execution_status(["finished", "lost", "canceled"])
        == states.EXEC_LOST
    )
    assert (
        states.rollup_execution_status(["finished", "canceled"])
        == states.EXEC_CANCELED
    )


def test_execution_transitions():
    assert states.is_valid_execution_transition("queued", "running")
    assert states.is_valid_execution_transition("running", "finalizing")
    assert states.is_valid_execution_transition("finalizing", "complete")
    assert states.is_valid_execution_transition("running", "running")  # idempotent
    # no resurrection from terminal
    assert not states.is_valid_execution_transition("complete", "running")
    assert states.is_valid_execution_transition("complete", "complete")
    # cannot jump queued -> finalizing
    assert not states.is_valid_execution_transition("queued", "finalizing")


def test_attempt_transitions():
    assert states.is_valid_attempt_transition("pending", "running")
    assert states.is_valid_attempt_transition("running", "finished")
    assert states.is_valid_attempt_transition("running", "lost")
    assert not states.is_valid_attempt_transition("finished", "running")


def test_attempt_lost_is_soft_terminal_overridable():
    # phase 1.5: an agent-authoritative terminal may override a server-lost
    for new in ("finished", "failed", "canceled"):
        assert states.is_valid_attempt_transition("lost", new), new
    # idempotent same->same still allowed
    assert states.is_valid_attempt_transition("lost", "lost")
    # but lost cannot regress to a non-terminal
    assert not states.is_valid_attempt_transition("lost", "running")
    assert not states.is_valid_attempt_transition("lost", "pending")


def test_execution_lost_is_soft_terminal_overridable():
    # phase 1.5: execution `lost` re-rolls when its attempt is reconciled
    for new in ("complete", "failed", "canceled"):
        assert states.is_valid_execution_transition("lost", new), new
    assert states.is_valid_execution_transition("lost", "lost")
    assert not states.is_valid_execution_transition("lost", "running")
    # other execution terminals stay frozen
    assert not states.is_valid_execution_transition("complete", "failed")
    assert states.is_valid_execution_transition("complete", "complete")


def test_hard_terminals_remain_mutually_non_transitionable():
    for old in ("finished", "failed", "canceled"):
        for new in ("finished", "failed", "canceled", "lost", "running"):
            if old == new:
                assert states.is_valid_attempt_transition(old, new)
            else:
                assert not states.is_valid_attempt_transition(old, new), (old, new)


def test_agent_to_attempt_mapping():
    from dopilot_protocol import AttemptStatus

    assert states.AGENT_TO_ATTEMPT[AttemptStatus.finished] == states.ATTEMPT_FINISHED
    assert states.AGENT_TO_ATTEMPT[AttemptStatus.running] == states.ATTEMPT_RUNNING
    assert states.AGENT_TO_ATTEMPT[AttemptStatus.unknown] is None
