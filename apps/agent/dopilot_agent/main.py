"""Agent worker daemon entrypoint (phase 2.2.7).

The agent is an **outbound-only** worker: it consumes commands from its Redis
command stream, publishes status events / log increments to the server's Redis
streams, and POSTs heartbeats to the server. It exposes **no** inbound HTTP API
and binds no listening port (port ``6800`` is gone). Scrapy eggs are fetched
from the server during Redis command execution via ``ScrapyArtifactCache``.

``run_agent(settings)`` is the single source of truth for the runtime start/stop
ordering (it replaces the old FastAPI lifespan):

1. build the runtime (scrapyd client + runner + state store, and the managed
   scrapyd subprocess when ``[scrapyd].start``);
2. start the managed scrapyd subprocess when configured;
3. when Redis is configured, build the Redis client + command consumer + event
   publisher + log publisher and start the consumer/publisher;
4. start the heartbeat worker when ``server_url`` is configured;
5. block until SIGTERM/SIGINT;
6. stop, in reverse order, the log publisher, command consumer, Redis client,
   heartbeat worker, and scrapyd subprocess.

``main()`` loads settings from ``DOPILOT_CONFIG`` (falling back to the baked
``DEFAULT_CONFIG_PATH``) and runs the daemon with ``asyncio.run``.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
from pathlib import Path

from .config.loader import DEFAULT_CONFIG_PATH, load_settings
from .config.settings import Settings
from .deps import build_runtime
from .janitor import AgentJanitor
from .redis.client import build_redis
from .redis.commands import CommandConsumer
from .redis.events import EventPublisher
from .redis.logs import LogPublisher

logger = logging.getLogger("dopilot_agent")


async def run_agent(settings: Settings, *, stop: asyncio.Event | None = None) -> None:
    """Run the agent worker daemon until ``stop`` is set (or SIGTERM/SIGINT).

    This is the non-HTTP replacement for the old ASGI lifespan: it starts the
    same set of background workers, in the same order, and tears them down in
    reverse order. When ``stop`` is not provided, SIGTERM/SIGINT handlers are
    installed to set an internal stop event; pass an explicit ``stop`` event in
    tests to drive shutdown without signals.
    """
    runtime = build_runtime(settings)
    s = runtime.settings

    own_stop = stop is None
    stop_event = stop if stop is not None else asyncio.Event()
    if own_stop:
        _install_signal_handlers(stop_event)

    if runtime.process is not None:
        runtime.process.start()

    redis_client = None
    consumer: CommandConsumer | None = None
    log_publisher: LogPublisher | None = None
    if s.redis.url:
        redis_client = build_redis(s.redis.url)
        publisher = EventPublisher(
            redis=redis_client,
            agent_id=s.agent.agent_id,
            runner=runtime.runner,
            store=runtime.store,
            maxlen_events=s.redis.maxlen_events,
            outbox_dir=s.redis.event_outbox_dir or None,
            max_outbox_files=s.redis.event_outbox_max_files,
            status=runtime.redis_status,
        )
        consumer = CommandConsumer(
            redis=redis_client,
            agent_id=s.agent.agent_id,
            runner=runtime.runner,
            store=runtime.store,
            events=publisher,
            pending_idle_ms=s.redis.pending_idle_ms,
            command_block_ms=s.redis.command_block_ms,
            status=runtime.redis_status,
            artifact_cache=runtime.artifact_cache,
            wheel_runner=runtime.wheel_runner,
            wheel_cache=runtime.wheel_cache,
        )
        log_publisher = LogPublisher(
            redis=redis_client,
            agent_id=s.agent.agent_id,
            store=runtime.store,
            cursor_dir=str(runtime.store.dir / "logpos"),
            maxlen_logs=s.redis.maxlen_logs,
            status=runtime.redis_status,
            # Resource caps (C6): release EOF-safe bookkeeping the moment EOF is
            # published for a terminal execution.
            on_eof=consumer.on_execution_eof,
        )
        # Let cleanup release the publisher's per-execution cursor/EOF state (C6).
        consumer.set_log_publisher(log_publisher)
        consumer.start()
        log_publisher.start()

    # Resource caps (C1/C4): local-disk janitor. Runs regardless of Redis (it only
    # touches local files); when a consumer exists its cleanup callback is wired so
    # GC also releases in-memory bookkeeping. Starts with an immediate sweep.
    janitor = AgentJanitor(
        settings=s,
        store=runtime.store,
        wheel_runner=runtime.wheel_runner,
        cursor_dir=str(runtime.store.dir / "logpos"),
        artifacts_root=str(Path(s.agent.workdir) / "artifacts"),
        release=consumer._release_execution if consumer is not None else None,
        # Resource caps (R-04): full active set (runner ∪ consumer in-flight) +
        # the consumer's per-execution lock, so GC never races a mid-flight run.
        active_ids=(
            (lambda: runtime.wheel_runner.active_execution_ids()
             | consumer.active_execution_ids())
            if consumer is not None
            else None
        ),
        lock_for=consumer.execution_lock if consumer is not None else None,
    )
    janitor.start()
    if runtime.heartbeat is not None:
        runtime.heartbeat.start()

    logger.info(
        "dopilot-agent worker started (agent_id=%s, redis=%s, server_url=%s); "
        "no inbound HTTP listener",
        s.agent.agent_id,
        bool(s.redis.url),
        bool(s.agent.server_url),
    )
    try:
        await stop_event.wait()
    finally:
        await janitor.stop()
        if log_publisher is not None:
            await log_publisher.stop()
        if consumer is not None:
            await consumer.stop()
        if redis_client is not None:
            await redis_client.aclose()
        if runtime.heartbeat is not None:
            await runtime.heartbeat.stop()
        if runtime.process is not None:
            runtime.process.stop()
        logger.info("dopilot-agent worker stopped")


def _install_signal_handlers(stop_event: asyncio.Event) -> None:
    """Set ``stop_event`` on SIGTERM/SIGINT (graceful container shutdown)."""
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:  # pragma: no cover - non-Unix fallback
            signal.signal(sig, lambda *_: stop_event.set())


def main() -> None:
    # No bind/port flags: the agent is outbound-only and opens no HTTP listener.
    argparse.ArgumentParser(prog="dopilot-agent").parse_args()

    # load_settings reads DOPILOT_CONFIG itself when no path is passed, then
    # falls back to the baked agent default so the image needs no DOPILOT_CONFIG.
    settings = load_settings(default_path=DEFAULT_CONFIG_PATH)
    asyncio.run(run_agent(settings))


if __name__ == "__main__":
    main()
