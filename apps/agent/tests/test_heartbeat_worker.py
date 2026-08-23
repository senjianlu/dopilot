"""Agent heartbeat worker tests (phase 1.5)."""

from __future__ import annotations

from pathlib import Path

import httpx
from dopilot_agent.config.settings import (
    AgentSettings,
    Capabilities,
    ScrapydSettings,
    Settings,
)
from dopilot_agent.deps import state_dir
from dopilot_agent.redis.heartbeat import HeartbeatWorker
from dopilot_agent.redis.status import RedisRuntimeStatus
from dopilot_agent.state.store import AttemptState, StateStore


def _settings(workdir: Path) -> Settings:
    return Settings(
        agent=AgentSettings(
            agent_id="agent-test-1",
            workdir=str(workdir),
            server_url="http://server:5000/",
            agent_token="agent-machine-token",
            heartbeat_interval_seconds=1,
        ),
        capabilities=Capabilities(scrapy=True, script=True, docker=False),
        scrapyd=ScrapydSettings(start=False, port=6801),
    )


def _store_with_attempts(workdir: Path, n: int) -> StateStore:
    store = StateStore(state_dir(workdir))
    for i in range(n):
        store.write(
            AttemptState(
                task_id=f"e{i}",
                execution_id=f"a{i}",
                scrapyd_job_id=f"job-{i}",
                project="demo",
                spider="phase1",
                log_path=str(workdir / f"{i}.log"),
            )
        )
    return store


def test_build_request_reflects_settings_and_load(workdir: Path) -> None:
    store = _store_with_attempts(workdir, 2)
    worker = HeartbeatWorker(settings=_settings(workdir), store=store, version="9.9.9")
    req = worker.build_request()
    assert req.agent_id == "agent-test-1"
    assert req.version == "9.9.9"
    assert req.capabilities.scrapy is True and req.capabilities.docker is False
    assert req.load == {"running_attempts": 2}
    assert req.detail["scrapyd"]["port"] == 6801
    # Phase 2.2.7: the outbound-only agent advertises no network endpoint.
    assert req.endpoint is None


def test_build_request_includes_redis_status(workdir: Path) -> None:
    store = _store_with_attempts(workdir, 0)
    redis_status = RedisRuntimeStatus()
    redis_status.mark_command_running(True)
    redis_status.mark_ok()
    worker = HeartbeatWorker(
        settings=_settings(workdir),
        store=store,
        version="9.9.9",
        redis_status=redis_status,
    )

    req = worker.build_request()

    assert req.detail["redis"]["connected"] is True
    assert req.detail["redis"]["command_consumer"]["running"] is True
    assert req.detail["redis"]["event_outbox"]["pending"] == 0


async def test_send_once_posts_with_token(workdir: Path) -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("authorization")
        captured["body"] = request.read().decode()
        return httpx.Response(200, json={"ok": True, "server_time": "t"})

    store = _store_with_attempts(workdir, 0)
    worker = HeartbeatWorker(settings=_settings(workdir), store=store, version="0.1.0")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        ok = await worker.send_once(http)

    assert ok is True
    assert captured["url"] == "http://server:5000/api/v1/agents/agent-test-1/heartbeat"
    assert captured["auth"] == "Bearer agent-machine-token"
    assert '"agent_id":"agent-test-1"' in captured["body"]


async def test_send_once_returns_false_on_5xx(workdir: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="unavailable")

    store = _store_with_attempts(workdir, 0)
    worker = HeartbeatWorker(settings=_settings(workdir), store=store, version="0.1.0")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        ok = await worker.send_once(http)
    assert ok is False


async def test_send_once_no_token_omits_auth_header(workdir: Path) -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"ok": True, "server_time": "t"})

    settings = _settings(workdir)
    settings.agent.agent_token = ""
    store = _store_with_attempts(workdir, 0)
    worker = HeartbeatWorker(settings=settings, store=store, version="0.1.0")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        await worker.send_once(http)
    assert captured["auth"] is None


def test_build_request_includes_disk_sample(workdir: Path) -> None:
    """TC-10: when a disk sample exists it is attached under detail["disk"];
    reading it never touches the filesystem (a stub sampler proves zero walks)."""
    from dopilot_agent.disk_status import DiskStatus

    store = _store_with_attempts(workdir, 0)
    disk = DiskStatus()
    sample = {"sampled_at": "2026-07-24T12:00:00+00:00", "interval_seconds": 600,
              "workspaces": {"count": 1, "bytes": 42}}
    disk.update(sample)
    worker = HeartbeatWorker(
        settings=_settings(workdir), store=store, version="9.9.9",
        disk_status=disk,
    )
    req = worker.build_request()
    assert req.detail["disk"] == sample
    # scrapyd detail still present (disk is additive).
    assert req.detail["scrapyd"]["port"] == 6801


def test_build_request_omits_disk_when_no_sample(workdir: Path) -> None:
    """TC-10: with no cached sample yet, detail has no "disk" key."""
    from dopilot_agent.disk_status import DiskStatus

    store = _store_with_attempts(workdir, 0)
    worker = HeartbeatWorker(
        settings=_settings(workdir), store=store, version="9.9.9",
        disk_status=DiskStatus(),
    )
    req = worker.build_request()
    assert "disk" not in req.detail
    assert req.detail["scrapyd"]["port"] == 6801


def test_build_request_reads_cache_never_walks_fs(workdir: Path, monkeypatch) -> None:
    """TC-10: build_request only READS the cached sample (snapshot() once) and
    NEVER samples/walks the filesystem — os.walk is asserted uncalled."""
    import os as _os

    from dopilot_agent.disk_status import DiskStatus

    store = _store_with_attempts(workdir, 0)
    sample = {"sampled_at": "2026-07-24T12:00:00+00:00", "interval_seconds": 600,
              "workspaces": {"count": 1, "bytes": 42}}
    calls = {"snapshot": 0, "walk": 0}

    class CountingDisk(DiskStatus):
        def snapshot(self):  # type: ignore[override]
            calls["snapshot"] += 1
            return sample

    real_walk = _os.walk

    def _tracking_walk(*a, **k):
        calls["walk"] += 1
        return real_walk(*a, **k)

    monkeypatch.setattr(_os, "walk", _tracking_walk)
    worker = HeartbeatWorker(
        settings=_settings(workdir), store=store, version="9.9.9",
        disk_status=CountingDisk(),
    )
    req = worker.build_request()
    assert req.detail["disk"] == sample
    assert calls["snapshot"] == 1  # cache read exactly once
    assert calls["walk"] == 0  # zero filesystem traversal in the heartbeat path


# --- TC-01h: log-cap mode is reported in the heartbeat detail ----------------------


def test_build_request_reports_log_cap_mode(workdir: Path) -> None:
    store = _store_with_attempts(workdir, 0)
    external = _settings(workdir)
    assert external.scrapyd.start is False
    req = HeartbeatWorker(settings=external, store=store, version="1").build_request()
    assert req.detail["scrapyd"]["log_cap"] == "external"
    assert req.detail["scrapyd"]["log_cap_bytes"] == external.agent.max_job_log_bytes

    managed = external.model_copy(
        update={"scrapyd": external.scrapyd.model_copy(update={"start": True})}
    )
    req = HeartbeatWorker(settings=managed, store=store, version="1").build_request()
    assert req.detail["scrapyd"]["log_cap"] == "managed"
