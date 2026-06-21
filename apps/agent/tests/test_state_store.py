"""Unit tests for the atomic per-execution state store."""

from __future__ import annotations

from pathlib import Path

from dopilot_agent.state.store import AttemptState, StateStore


def _state(execution_id: str = "a1", job_id: str = "job-1") -> AttemptState:
    return AttemptState(
        task_id="exec-1",
        execution_id=execution_id,
        scrapyd_job_id=job_id,
        project="demo",
        version="1",
        spider="phase1",
        log_path="/agent-data/scrapyd/logs/demo/phase1/job-1.log",
    )


def test_write_then_read_roundtrip(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state")
    store.write(_state())

    got = store.read("a1")
    assert got is not None
    assert got.task_id == "exec-1"
    assert got.scrapyd_job_id == "job-1"
    assert got.spider == "phase1"
    assert got.canceled is False
    # Timestamps are populated.
    assert got.created_at
    assert got.updated_at


def test_write_is_atomic_no_tmp_left(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state")
    store.write(_state())
    leftovers = list((tmp_path / "state").glob("*.tmp"))
    assert leftovers == []
    assert store.path_for("a1").exists()


def test_read_missing_returns_none(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state")
    assert store.read("nope") is None


def test_read_corrupt_half_json_returns_none(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state")
    store.dir.mkdir(parents=True, exist_ok=True)
    # Simulate a crash mid-write: truncated JSON.
    store.path_for("a1").write_text('{"task_id": "exec-1", "exe', encoding="utf-8")
    assert store.read("a1") is None


def test_read_valid_json_wrong_shape_returns_none(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state")
    store.dir.mkdir(parents=True, exist_ok=True)
    # Valid JSON but missing required fields.
    store.path_for("a1").write_text('{"foo": "bar"}', encoding="utf-8")
    assert store.read("a1") is None


def test_delete_idempotent(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state")
    store.write(_state())
    assert store.delete("a1") is True
    assert store.delete("a1") is False
    assert store.read("a1") is None


def test_list_execution_ids(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state")
    assert store.list_execution_ids() == []
    store.write(_state(execution_id="a1"))
    store.write(_state(execution_id="a2"))
    assert store.list_execution_ids() == ["a1", "a2"]


def test_updated_at_refreshed_on_rewrite(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state")
    s = store.write(_state())
    first = s.updated_at
    s.canceled = True
    # Force a distinct timestamp; isoformat has microsecond resolution.
    store.write(s)
    again = store.read("a1")
    assert again is not None
    assert again.canceled is True
    assert again.updated_at >= first


# --- phase 2b: additive runner/process fields -----------------------------
def test_legacy_scrapy_state_loads_with_default_runner_type(tmp_path: Path) -> None:
    """A pre-2b state file (no runner fields) still loads as a Scrapy attempt."""
    store = StateStore(tmp_path / "state")
    store.dir.mkdir(parents=True, exist_ok=True)
    legacy = (
        '{"task_id": "e1", "execution_id": "a1", "scrapyd_job_id": "job-1", '
        '"project": "demo", "spider": "phase1", "phase": "started"}'
    )
    store.path_for("a1").write_text(legacy, encoding="utf-8")
    state = store.read("a1")
    assert state is not None
    assert state.runner_type == "scrapy"
    assert state.pid is None and state.pgid is None
    assert state.workspace_path == "" and state.install_path == ""


def test_create_reserved_wheel_records_runner_type(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state")
    reserved = store.create_reserved(
        task_id="e1",
        execution_id="a1",
        runner_type="python_wheel",
        shell_command="python -m main",
    )
    assert reserved is not None
    state = store.read("a1")
    assert state.runner_type == "python_wheel"
    assert state.shell_command == "python -m main"
    assert state.phase == "reserved"
    assert state.project == "" and state.spider == ""


def test_promote_started_wheel_records_process_fields(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state")
    store.create_reserved(
        task_id="e1", execution_id="a1", runner_type="python_wheel"
    )
    promoted = store.promote_started_wheel(
        "a1",
        pid=4242,
        pgid=4242,
        workspace_path="/wd/a1",
        install_path="/cache/python_wheel/abc/site",
        log_path="/wd/a1/job.log",
    )
    assert promoted is not None
    state = store.read("a1")
    assert state.phase == "started"
    assert state.pid == 4242 and state.pgid == 4242
    assert state.workspace_path == "/wd/a1"
    assert state.install_path == "/cache/python_wheel/abc/site"
    assert state.log_path == "/wd/a1/job.log"
