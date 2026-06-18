"""Contract tests for /run, /stop, /status over the ASGI app + fake scrapyd."""

from __future__ import annotations

from pathlib import Path

from .conftest import (
    FakeScrapyd,
    app_with_fake_scrapyd,
    client_for_app,
    write_log,
)

RUN_BODY = {
    "execution_id": "exec-1",
    "attempt_id": "a1",
    "project": "demo",
    "spider": "phase1",
    "version": "1",
    "settings": {"LOG_LEVEL": "INFO"},
    "args": {"start": "0"},
}


async def test_run_returns_remote_job_id_and_writes_state(
    workdir: Path,
) -> None:
    fake = FakeScrapyd()
    app = app_with_fake_scrapyd(workdir, fake)
    async with client_for_app(app) as client:
        resp = await client.post("/run", json=RUN_BODY)

    assert resp.status_code == 200
    body = resp.json()
    assert body["execution_id"] == "exec-1"
    assert body["attempt_id"] == "a1"
    assert body["remote_job_id"].startswith("job-")
    assert body["status"] == "running"
    # State file persisted on disk.
    assert (workdir / "state" / "executions" / "a1.json").exists()


async def test_run_schedule_failure_returns_error_envelope(workdir: Path) -> None:
    fake = FakeScrapyd()
    fake.fail_schedule = True
    app = app_with_fake_scrapyd(workdir, fake)
    async with client_for_app(app) as client:
        resp = await client.post("/run", json=RUN_BODY)

    assert resp.status_code == 502
    body = resp.json()
    assert body["code"] == "agent.schedule_failed"
    assert "message_key" in body


async def test_status_running_then_finished(workdir: Path) -> None:
    fake = FakeScrapyd()
    app = app_with_fake_scrapyd(workdir, fake)
    async with client_for_app(app) as client:
        run = await client.post("/run", json=RUN_BODY)
        job_id = run.json()["remote_job_id"]

        status = await client.get("/status?execution_id=exec-1&attempt_id=a1")
        assert status.json()["status"] == "running"

        fake.move_to_finished(job_id)
        status2 = await client.get("/status?execution_id=exec-1&attempt_id=a1")
        body = status2.json()
        assert body["status"] == "finished"
        assert body["remote_job_id"] == job_id


async def test_status_and_tail_not_finished_when_scrapyd_unreachable(
    workdir: Path,
) -> None:
    # P1 regression at the HTTP layer: if scrapyd is unreachable (listjobs
    # transport error), GET /status must be 'unknown' and GET /logs/tail must
    # report finished=False even though a job.log exists on disk.
    fake = FakeScrapyd()
    app = app_with_fake_scrapyd(workdir, fake)
    async with client_for_app(app) as client:
        run = await client.post("/run", json=RUN_BODY)
        job_id = run.json()["remote_job_id"]
        write_log(workdir, "demo", "phase1", job_id, "phase1 demo running\n")

        fake.fail_listjobs = True  # scrapyd goes unreachable while job runs

        status = await client.get("/status?execution_id=exec-1&attempt_id=a1")
        assert status.json()["status"] == "unknown"

        tail = await client.get(
            "/logs/tail?execution_id=exec-1&attempt_id=a1&offset=0&max_bytes=1024"
        )
        body = tail.json()
        assert body["finished"] is False
        assert "phase1 demo running" in body["content"]


async def test_stop_marks_canceled(workdir: Path) -> None:
    fake = FakeScrapyd()
    app = app_with_fake_scrapyd(workdir, fake)
    async with client_for_app(app) as client:
        await client.post("/run", json=RUN_BODY)
        stop = await client.post(
            "/stop", json={"execution_id": "exec-1", "attempt_id": "a1"}
        )
        assert stop.status_code == 200
        body = stop.json()
        assert body["stopped"] is True
        assert body["status"] == "canceled"

        status = await client.get("/status?execution_id=exec-1&attempt_id=a1")
        assert status.json()["status"] == "canceled"


async def test_stop_unknown_attempt_idempotent(workdir: Path) -> None:
    fake = FakeScrapyd()
    app = app_with_fake_scrapyd(workdir, fake)
    async with client_for_app(app) as client:
        stop = await client.post(
            "/stop", json={"execution_id": "exec-1", "attempt_id": "ghost"}
        )
    assert stop.status_code == 200
    body = stop.json()
    assert body["stopped"] is False
    assert body["status"] == "unknown"


async def test_restart_recovery_status_from_state_file(workdir: Path) -> None:
    # Run on one app instance, then a fresh app instance (same workdir) resolves
    # status from the persisted state file.
    fake = FakeScrapyd()
    app1 = app_with_fake_scrapyd(workdir, fake)
    async with client_for_app(app1) as client:
        run = await client.post("/run", json=RUN_BODY)
        job_id = run.json()["remote_job_id"]

    # Simulate restart + job finished + log on disk.
    fake.move_to_finished(job_id)
    write_log(workdir, "demo", "phase1", job_id, "phase1 demo started\ndone\n")

    app2 = app_with_fake_scrapyd(workdir, fake)
    async with client_for_app(app2) as client:
        status = await client.get("/status?execution_id=exec-1&attempt_id=a1")
        body = status.json()
    assert body["status"] == "finished"
    assert body["remote_job_id"] == job_id
