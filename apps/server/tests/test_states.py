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


def test_agent_to_attempt_mapping():
    from dopilot_protocol import AttemptStatus

    assert states.AGENT_TO_ATTEMPT[AttemptStatus.finished] == states.ATTEMPT_FINISHED
    assert states.AGENT_TO_ATTEMPT[AttemptStatus.running] == states.ATTEMPT_RUNNING
    assert states.AGENT_TO_ATTEMPT[AttemptStatus.unknown] is None
