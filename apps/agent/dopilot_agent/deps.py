"""Runtime wiring + FastAPI dependencies for the agent.

The agent holds two long-lived runtime objects: the
:class:`~dopilot_agent.scrapyd.client.ScrapydClient` (talks to local scrapyd)
and the :class:`~dopilot_agent.runners.scrapyd.ScrapyRunner` (run/stop/status +
state). :func:`build_runtime` constructs them from settings and is called in
``create_app`` so they live on ``app.state`` regardless of whether the lifespan
ran — important because tests drive the app over httpx ``ASGITransport``, which
does NOT run the lifespan.

The endpoint dependencies (:func:`get_scrapyd_client`, :func:`get_scrapy_runner`,
:func:`get_scrapyd_process`) are thin: they read from ``request.app.state``. Tests
override them via ``app.dependency_overrides`` (mirroring how the server overrides
``get_session``) to inject a fake-scrapyd-backed client/runner.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from fastapi import Request

from . import __version__
from .config.settings import Settings
from .redis.heartbeat import HeartbeatWorker
from .runners.scrapyd import ScrapyRunner
from .scrapyd.client import ScrapydClient
from .scrapyd.process import ScrapydProcess
from .state.store import StateStore


@dataclass
class AgentRuntime:
    """Long-lived runtime objects stored on ``app.state.runtime``."""

    settings: Settings
    process: ScrapydProcess | None
    client: ScrapydClient
    store: StateStore
    runner: ScrapyRunner
    heartbeat: HeartbeatWorker | None = None


def state_dir(workdir: str | Path) -> Path:
    """Directory holding per-attempt state files."""
    return Path(workdir) / "state" / "executions"


def scrapyd_logs_dir(workdir: str | Path) -> Path:
    """Directory scrapyd writes job logs into."""
    return Path(workdir) / "scrapyd" / "logs"


def build_runtime(settings: Settings) -> AgentRuntime:
    """Construct the agent's runtime objects from settings.

    A :class:`ScrapydProcess` is created when ``[scrapyd].start`` is true so the
    lifespan can start/stop it; the client/runner are always built so the API
    works under both the real lifespan and the test ASGI transport.
    """
    workdir = settings.agent.workdir
    base_url = f"http://{settings.scrapyd.host}:{settings.scrapyd.port}"

    process: ScrapydProcess | None = None
    if settings.scrapyd.start:
        process = ScrapydProcess(
            workdir=workdir,
            host=settings.scrapyd.host,
            port=settings.scrapyd.port,
        )

    client = ScrapydClient(base_url=base_url)
    store = StateStore(state_dir(workdir))
    runner = ScrapyRunner(
        client=client,
        store=store,
        logs_dir=scrapyd_logs_dir(workdir),
    )
    # Heartbeat worker is built only when a server_url is configured; the task
    # itself is started by the lifespan (not under the test ASGI transport).
    heartbeat: HeartbeatWorker | None = None
    if settings.agent.server_url:
        heartbeat = HeartbeatWorker(
            settings=settings, store=store, version=__version__
        )
    return AgentRuntime(
        settings=settings,
        process=process,
        client=client,
        store=store,
        runner=runner,
        heartbeat=heartbeat,
    )


def _runtime(request: Request) -> AgentRuntime:
    runtime = getattr(request.app.state, "runtime", None)
    if runtime is None:  # pragma: no cover - create_app always sets this.
        raise RuntimeError("agent runtime not initialized on app.state")
    return runtime


def get_runtime(request: Request) -> AgentRuntime:
    """Dependency: the whole runtime (overridable in tests)."""
    return _runtime(request)


def get_scrapyd_client(request: Request) -> ScrapydClient:
    """Dependency: the scrapyd client (overridable in tests)."""
    return _runtime(request).client


def get_scrapy_runner(request: Request) -> ScrapyRunner:
    """Dependency: the Scrapy runner (overridable in tests)."""
    return _runtime(request).runner


def get_state_store(request: Request) -> StateStore:
    """Dependency: the attempt state store (overridable in tests)."""
    return _runtime(request).store


def get_scrapyd_process(request: Request) -> ScrapydProcess | None:
    """Dependency: the scrapyd subprocess manager (None when not managed)."""
    return _runtime(request).process
