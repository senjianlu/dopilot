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
            advertise_endpoint="agent:6800",
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
    assert req.endpoint == "agent:6800"


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
