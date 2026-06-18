"""Unit tests for the Scrapy runner over a fake scrapyd."""

from __future__ import annotations

from pathlib import Path

import pytest
from dopilot_agent.runners.scrapyd import RunnerError, ScrapyRunner
from dopilot_protocol import AgentRunRequest, AttemptStatus

from .conftest import FakeScrapyd, make_runner, write_log


def _req(**overrides: object) -> AgentRunRequest:
    base = {
        "execution_id": "exec-1",
        "attempt_id": "a1",
        "project": "demo",
        "spider": "phase1",
        "version": "1",
        "settings": {"LOG_LEVEL": "INFO"},
        "args": {"start": "0"},
    }
    base.update(overrides)
    return AgentRunRequest(**base)


async def test_run_schedules_and_persists_state(tmp_path: Path) -> None:
    fake = FakeScrapyd()
    runner = make_runner(tmp_path, fake)

    resp = await runner.run(_req())

    assert resp.remote_job_id.startswith("job-")
    assert resp.status == AttemptStatus.running
    # State persisted with the scrapyd job id and a resolved log path.
    state = runner._store.read("a1")
    assert state is not None
    assert state.scrapyd_job_id == resp.remote_job_id
    assert state.project == "demo"
    assert state.spider == "phase1"
    assert state.log_path.endswith(f"demo/phase1/{resp.remote_job_id}.log")
    assert state.canceled is False


async def test_run_schedule_failure_raises_runner_error(tmp_path: Path) -> None:
    fake = FakeScrapyd()
    fake.fail_schedule = True
    runner = make_runner(tmp_path, fake)

    with pytest.raises(RunnerError):
        await runner.run(_req())
    # No state file written on failure.
    assert runner._store.read("a1") is None


async def test_status_running(tmp_path: Path) -> None:
    fake = FakeScrapyd()
    runner = make_runner(tmp_path, fake)
    await runner.run(_req())

    status = await runner.status("a1", "exec-1")
    assert status.status == AttemptStatus.running


async def test_status_finished(tmp_path: Path) -> None:
    fake = FakeScrapyd()
    runner = make_runner(tmp_path, fake)
    resp = await runner.run(_req())
    fake.move_to_finished(resp.remote_job_id)

    status = await runner.status("a1", "exec-1")
    assert status.status == AttemptStatus.finished
    assert status.exit_code is None


async def test_status_canceled_after_stop(tmp_path: Path) -> None:
    fake = FakeScrapyd()
    runner = make_runner(tmp_path, fake)
    await runner.run(_req())

    stop = await runner.stop("a1", "exec-1")
    assert stop.stopped is True
    assert stop.status == AttemptStatus.canceled

    # cancel moved the job to finished; state.canceled => report canceled.
    status = await runner.status("a1", "exec-1")
    assert status.status == AttemptStatus.canceled


async def test_status_unknown_no_state(tmp_path: Path) -> None:
    fake = FakeScrapyd()
    runner = make_runner(tmp_path, fake)
    status = await runner.status("missing", "exec-1")
    assert status.status == AttemptStatus.unknown
    assert status.remote_job_id is None


async def test_status_finished_when_log_exists_but_not_in_lists(tmp_path: Path) -> None:
    # Restart scenario: state exists, scrapyd no longer lists the job, but the
    # log is on disk => finished.
    fake = FakeScrapyd()
    runner = make_runner(tmp_path, fake)
    resp = await runner.run(_req())
    # Remove from running without adding to finished.
    fake.running = []
    write_log(tmp_path, "demo", "phase1", resp.remote_job_id, "phase1 demo done\n")

    status = await runner.status("a1", "exec-1")
    assert status.status == AttemptStatus.finished


async def test_status_unknown_when_scrapyd_unreachable_even_with_log(
    tmp_path: Path,
) -> None:
    # P1 regression: scrapyd unreachable (listjobs transport error) must NOT be
    # inferred as "finished" just because a log file exists -- the job may still
    # be running. Report unknown so the server applies its lost/timeout policy.
    fake = FakeScrapyd()
    runner = make_runner(tmp_path, fake)
    resp = await runner.run(_req())
    write_log(tmp_path, "demo", "phase1", resp.remote_job_id, "phase1 demo running\n")
    fake.fail_listjobs = True

    status = await runner.status("a1", "exec-1")
    assert status.status == AttemptStatus.unknown


async def test_status_unknown_when_no_log_and_not_listed(tmp_path: Path) -> None:
    fake = FakeScrapyd()
    runner = make_runner(tmp_path, fake)
    await runner.run(_req())
    fake.running = []  # vanished, no log written
    status = await runner.status("a1", "exec-1")
    assert status.status == AttemptStatus.unknown


async def test_stop_unknown_attempt_idempotent(tmp_path: Path) -> None:
    fake = FakeScrapyd()
    runner = make_runner(tmp_path, fake)
    stop = await runner.stop("nope", "exec-1")
    assert stop.stopped is False
    assert stop.status == AttemptStatus.unknown


async def test_stop_already_finished_idempotent(tmp_path: Path) -> None:
    fake = FakeScrapyd()
    runner = make_runner(tmp_path, fake)
    resp = await runner.run(_req())
    fake.move_to_finished(resp.remote_job_id)

    stop = await runner.stop("a1", "exec-1")
    # Job was no longer running => not stopped, but resolved status, no error.
    assert stop.stopped is False
    assert stop.status == AttemptStatus.finished


async def test_run_restart_recovery_via_state_file(tmp_path: Path) -> None:
    # State file is the source of truth: a fresh runner instance (same workdir)
    # resolves status purely from the persisted state file.
    fake = FakeScrapyd()
    runner1 = make_runner(tmp_path, fake)
    resp = await runner1.run(_req())

    runner2 = ScrapyRunner(
        client=runner1._client, store=runner1._store, logs_dir=runner1._logs_dir
    )
    status = await runner2.status("a1", "exec-1")
    assert status.remote_job_id == resp.remote_job_id
    assert status.status == AttemptStatus.running
