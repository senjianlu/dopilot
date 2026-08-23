"""Tests for the outbound-only agent worker daemon (phase 2.2.7).

These replace the old FastAPI lifespan coverage: ``run_agent`` is now the single
source of truth for runtime start/stop ordering. The agent opens no inbound HTTP
listener, so the tests drive the runtime directly (no ASGI client).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import dopilot_agent.main as main_mod
from dopilot_agent.config.settings import (
    AgentSettings,
    Capabilities,
    RedisSettings,
    ScrapydSettings,
    Settings,
)
from dopilot_agent.main import run_agent


def _settings(workdir: Path, *, redis_url: str = "", server_url: str = "") -> Settings:
    return Settings(
        agent=AgentSettings(
            agent_id="agent-test-1",
            workdir=str(workdir),
            server_url=server_url,
        ),
        capabilities=Capabilities(scrapy=True, script=True, docker=False),
        # No real scrapyd subprocess in tests.
        scrapyd=ScrapydSettings(start=False, host="127.0.0.1", port=6801),
        # Short block so the consumer's blocking read is promptly cancellable on
        # shutdown (fakeredis honors the XREADGROUP block timeout).
        redis=RedisSettings(url=redis_url, command_block_ms=50, pending_idle_ms=1000),
    )


async def test_run_agent_starts_and_stops_cleanly(workdir: Path) -> None:
    # With no redis/server configured the daemon has no background workers; it
    # must still block until stopped and then return promptly (graceful exit).
    stop = asyncio.Event()
    task = asyncio.create_task(run_agent(_settings(workdir), stop=stop))
    await asyncio.sleep(0.05)
    assert not task.done()  # blocks on the stop event

    stop.set()
    await asyncio.wait_for(task, timeout=5)
    assert task.exception() is None


async def test_run_agent_starts_and_stops_redis_workers(
    workdir: Path, fake_redis: Any, monkeypatch: Any
) -> None:
    # When redis is configured, run_agent must BUILD the command consumer + log
    # publisher, START them after starting redis, and STOP them (log publisher
    # before consumer) on shutdown. We inject an in-memory Redis double via
    # build_redis and stub the workers' start/stop with recorders, so the wiring
    # + ordering are asserted without running the blocking consumer loop.
    fake = fake_redis()
    monkeypatch.setattr(main_mod, "build_redis", lambda _url: fake)

    events: list[str] = []

    def _rec(label: str) -> Any:
        def _start(self: Any) -> None:
            events.append(f"start:{label}")

        return _start

    monkeypatch.setattr(main_mod.CommandConsumer, "start", _rec("consumer"))
    monkeypatch.setattr(main_mod.LogPublisher, "start", _rec("log_publisher"))

    async def _consumer_stop(self: Any) -> None:
        events.append("stop:consumer")

    async def _publisher_stop(self: Any) -> None:
        events.append("stop:log_publisher")

    monkeypatch.setattr(main_mod.CommandConsumer, "stop", _consumer_stop)
    monkeypatch.setattr(main_mod.LogPublisher, "stop", _publisher_stop)

    stop = asyncio.Event()
    settings = _settings(workdir, redis_url="redis://fake:6379/0")
    task = asyncio.create_task(run_agent(settings, stop=stop))
    await asyncio.sleep(0.05)  # let run_agent build + start the workers

    assert "start:consumer" in events
    assert "start:log_publisher" in events

    stop.set()
    await asyncio.wait_for(task, timeout=5)
    assert task.exception() is None
    # Teardown order: log publisher stops before the command consumer.
    assert events.index("stop:log_publisher") < events.index("stop:consumer")


async def test_startup_janitor_sweep_runs_before_workers_start(
    workdir: Path, fake_redis: Any, monkeypatch: Any, caplog: Any
) -> None:
    # TC-33 / TC-01h: one full janitor sweep (incl. the oversized-log step C8)
    # completes BEFORE the command consumer / log publisher start; the periodic
    # janitor task is then started; external-scrapyd mode logs the log-cap warning.
    fake = fake_redis()
    monkeypatch.setattr(main_mod, "build_redis", lambda _url: fake)
    events: list[str] = []

    async def _sweep(self: Any, *, now: Any = None) -> None:
        events.append("janitor.sweep_once")
        await asyncio.sleep(0)

    def _janitor_start(self: Any) -> None:
        events.append("janitor.start")

    async def _janitor_stop(self: Any) -> None:
        events.append("janitor.stop")

    monkeypatch.setattr(main_mod.AgentJanitor, "sweep_once", _sweep)
    monkeypatch.setattr(main_mod.AgentJanitor, "start", _janitor_start)
    monkeypatch.setattr(main_mod.AgentJanitor, "stop", _janitor_stop)
    monkeypatch.setattr(
        main_mod.CommandConsumer, "start", lambda self: events.append("consumer.start")
    )
    monkeypatch.setattr(
        main_mod.LogPublisher, "start", lambda self: events.append("log_publisher.start")
    )

    async def _noop_stop(self: Any) -> None:
        return None

    monkeypatch.setattr(main_mod.CommandConsumer, "stop", _noop_stop)
    monkeypatch.setattr(main_mod.LogPublisher, "stop", _noop_stop)

    stop = asyncio.Event()
    settings = _settings(workdir, redis_url="redis://fake:6379/0")
    with caplog.at_level("WARNING"):
        task = asyncio.create_task(run_agent(settings, stop=stop))
        await asyncio.sleep(0.05)
        stop.set()
        await asyncio.wait_for(task, timeout=5)
    assert task.exception() is None
    assert events.index("janitor.sweep_once") < events.index("consumer.start")
    assert events.index("janitor.sweep_once") < events.index("log_publisher.start")
    assert "janitor.start" in events
    assert any("scrapyd.start=false" in r.getMessage() for r in caplog.records)
