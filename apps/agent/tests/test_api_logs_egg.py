"""Contract tests for /logs/tail, cleanup, and egg deploy."""

from __future__ import annotations

from pathlib import Path

from .conftest import (
    FakeScrapyd,
    app_with_fake_scrapyd,
    client_for_app,
    read_state,
    write_log,
)

RUN_BODY = {
    "execution_id": "exec-1",
    "attempt_id": "a1",
    "project": "demo",
    "spider": "phase1",
}


async def _run_and_log(workdir: Path, fake: FakeScrapyd, body: str) -> tuple[str, Path]:
    """Run an attempt and write a job.log matching its scrapyd job id."""
    app = app_with_fake_scrapyd(workdir, fake)
    async with client_for_app(app) as client:
        run = await client.post("/run", json=RUN_BODY)
    job_id = run.json()["remote_job_id"]
    log = write_log(workdir, "demo", "phase1", job_id, body)
    return job_id, log


async def test_tail_offset_semantics_over_real_file(workdir: Path) -> None:
    fake = FakeScrapyd()
    job_id, _ = await _run_and_log(workdir, fake, "phase1 demo started\n")

    app = app_with_fake_scrapyd(workdir, fake)
    async with client_for_app(app) as client:
        # Read from zero.
        r1 = await client.get(
            "/logs/tail?execution_id=exec-1&attempt_id=a1&offset=0&max_bytes=1024"
        )
        b1 = r1.json()
        assert b1["start_offset"] == 0
        assert b1["content"] == "phase1 demo started\n"
        assert b1["eof"] is True
        # running => not finished.
        assert b1["finished"] is False

        # Append, then tail from previous end_offset.
        with (workdir / "scrapyd" / "logs" / "demo" / "phase1" / f"{job_id}.log").open(
            "a", encoding="utf-8"
        ) as fh:
            fh.write("phase1 demo done\n")
        r2 = await client.get(
            f"/logs/tail?execution_id=exec-1&attempt_id=a1&offset={b1['end_offset']}"
        )
        b2 = r2.json()
        assert b2["content"] == "phase1 demo done\n"


async def test_tail_offset_past_eof_clamps(workdir: Path) -> None:
    fake = FakeScrapyd()
    await _run_and_log(workdir, fake, "hello\n")
    app = app_with_fake_scrapyd(workdir, fake)
    async with client_for_app(app) as client:
        r = await client.get(
            "/logs/tail?execution_id=exec-1&attempt_id=a1&offset=9999"
        )
    b = r.json()
    assert b["start_offset"] == b["end_offset"]
    assert b["content"] == ""
    assert b["eof"] is True


async def test_tail_finished_flag_when_terminal(workdir: Path) -> None:
    fake = FakeScrapyd()
    job_id, _ = await _run_and_log(workdir, fake, "done\n")
    fake.move_to_finished(job_id)
    app = app_with_fake_scrapyd(workdir, fake)
    async with client_for_app(app) as client:
        r = await client.get(
            "/logs/tail?execution_id=exec-1&attempt_id=a1&offset=0"
        )
    assert r.json()["finished"] is True


async def test_tail_missing_log_file_but_state_present(workdir: Path) -> None:
    # State exists but no job.log on disk => content empty, eof True.
    fake = FakeScrapyd()
    app = app_with_fake_scrapyd(workdir, fake)
    async with client_for_app(app) as client:
        await client.post("/run", json=RUN_BODY)
        r = await client.get(
            "/logs/tail?execution_id=exec-1&attempt_id=a1&offset=0"
        )
    b = r.json()
    assert b["content"] == ""
    assert b["eof"] is True


async def test_tail_no_state_404(workdir: Path) -> None:
    fake = FakeScrapyd()
    app = app_with_fake_scrapyd(workdir, fake)
    async with client_for_app(app) as client:
        r = await client.get(
            "/logs/tail?execution_id=exec-1&attempt_id=ghost&offset=0"
        )
    assert r.status_code == 404
    assert r.json()["code"] == "agent.attempt_not_found"


async def test_cleanup_removes_then_idempotent(workdir: Path) -> None:
    fake = FakeScrapyd()
    job_id, log = await _run_and_log(workdir, fake, "data\n")
    assert log.exists()
    state = read_state(workdir, "a1")
    assert state["scrapyd_job_id"] == job_id

    app = app_with_fake_scrapyd(workdir, fake)
    async with client_for_app(app) as client:
        first = await client.post("/executions/a1/logs/cleanup")
        assert first.status_code == 200
        assert first.json()["removed"] is True
        assert not log.exists()
        assert not (workdir / "state" / "executions" / "a1.json").exists()

        # Idempotent re-call: nothing left to remove.
        second = await client.post("/executions/a1/logs/cleanup")
        assert second.json()["removed"] is False

        # Tail after cleanup => 404 (state gone).
        tail = await client.get(
            "/logs/tail?execution_id=exec-1&attempt_id=a1&offset=0"
        )
        assert tail.status_code == 404
        assert tail.json()["code"] == "agent.attempt_not_found"


async def test_egg_deploy_returns_spiders(workdir: Path) -> None:
    fake = FakeScrapyd()
    fake.spiders = ["phase1", "another"]
    app = app_with_fake_scrapyd(workdir, fake)
    async with client_for_app(app) as client:
        resp = await client.post(
            "/artifacts/scrapy/egg",
            data={"project": "demo", "version": "1"},
            files={"file": ("demo.egg", b"PK\x03\x04egg-bytes", "application/octet-stream")},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["project"] == "demo"
    assert body["version"] == "1"
    assert body["spiders"] == ["phase1", "another"]


async def test_egg_deploy_failure_envelope(workdir: Path) -> None:
    fake = FakeScrapyd()
    fake.fail_addversion = True
    app = app_with_fake_scrapyd(workdir, fake)
    async with client_for_app(app) as client:
        resp = await client.post(
            "/artifacts/scrapy/egg",
            data={"project": "demo", "version": "1"},
            files={"file": ("demo.egg", b"bad", "application/octet-stream")},
        )
    assert resp.status_code == 502
    assert resp.json()["code"] == "agent.addversion_failed"
