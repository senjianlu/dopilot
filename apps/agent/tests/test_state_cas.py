"""Two-phase state-file CAS tests (phase 1.5)."""

from __future__ import annotations

from pathlib import Path

from dopilot_agent.deps import state_dir
from dopilot_agent.state.store import StateStore


def _store(workdir: Path) -> StateStore:
    return StateStore(state_dir(workdir))


def test_create_reserved_is_exclusive(workdir: Path) -> None:
    store = _store(workdir)
    first = store.create_reserved(
        task_id="e1", execution_id="a1", project="demo", spider="phase1"
    )
    assert first is not None
    assert first.phase == "reserved"
    assert first.scrapyd_job_id == ""
    # a second reserve of the same attempt must fail (O_EXCL) -> None
    second = store.create_reserved(
        task_id="e1", execution_id="a1", project="demo", spider="phase1"
    )
    assert second is None
    # the on-disk state is still the reserved one
    assert store.read("a1").phase == "reserved"


def test_promote_started_flips_phase(workdir: Path) -> None:
    store = _store(workdir)
    store.create_reserved(
        task_id="e1", execution_id="a1", project="demo", spider="phase1"
    )
    promoted = store.promote_started(
        "a1", scrapyd_job_id="job-1", log_path="/logs/a1.log"
    )
    assert promoted is not None
    assert promoted.phase == "started"
    assert promoted.scrapyd_job_id == "job-1"
    reread = store.read("a1")
    assert reread.phase == "started" and reread.log_path == "/logs/a1.log"


def test_promote_started_missing_returns_none(workdir: Path) -> None:
    store = _store(workdir)
    assert store.promote_started("nope", scrapyd_job_id="x", log_path="y") is None


def test_mark_done_records_terminal(workdir: Path) -> None:
    store = _store(workdir)
    store.create_reserved(
        task_id="e1", execution_id="a1", project="demo", spider="phase1"
    )
    done = store.mark_done(
        "a1", result="failed", error_code="spawn_aborted", lost_reason="spawn_aborted"
    )
    assert done.phase == "done"
    assert done.result == "failed"
    assert done.lost_reason == "spawn_aborted"


def test_mark_done_canceled_sets_canceled_flag(workdir: Path) -> None:
    store = _store(workdir)
    store.create_reserved(
        task_id="e1", execution_id="a1", project="demo", spider="phase1"
    )
    done = store.mark_done("a1", result="canceled")
    assert done.phase == "done" and done.result == "canceled"
    assert done.canceled is True
