"""Runtime wiring for the agent worker daemon.

The agent holds two long-lived runtime objects: the
:class:`~dopilot_agent.scrapyd.client.ScrapydClient` (talks to local scrapyd)
and the :class:`~dopilot_agent.runners.scrapyd.ScrapyRunner` (run/stop/status +
state). :func:`build_runtime` constructs them — plus the optional managed scrapyd
subprocess, the artifact/wheel caches, and the heartbeat worker — from settings.

Phase 2.2.7: the agent is outbound-only with no FastAPI app, so there are no
request-scoped dependencies; :func:`build_runtime` is called directly from
``run_agent`` (see :mod:`dopilot_agent.main`). The Scrapy runner is driven by the
Redis command consumer, not by HTTP endpoints.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import __version__
from .artifacts.cache import ScrapyArtifactCache
from .artifacts.wheel_cache import PythonWheelCache
from .config.settings import Settings
from .disk_status import DiskStatus
from .redis.heartbeat import HeartbeatWorker
from .redis.status import RedisRuntimeStatus
from .runners.python_wheel import PythonWheelRunner
from .runners.scrapyd import ScrapyRunner
from .scrapyd.client import ScrapydClient
from .scrapyd.process import ScrapydProcess
from .state.store import StateStore


@dataclass
class AgentRuntime:
    """Long-lived runtime objects owned by the agent daemon."""

    settings: Settings
    process: ScrapydProcess | None
    client: ScrapydClient
    store: StateStore
    runner: ScrapyRunner
    redis_status: RedisRuntimeStatus | None = None
    disk_status: DiskStatus | None = None
    artifact_cache: ScrapyArtifactCache | None = None
    wheel_cache: PythonWheelCache | None = None
    wheel_runner: PythonWheelRunner | None = None
    heartbeat: HeartbeatWorker | None = None


def state_dir(workdir: str | Path) -> Path:
    """Directory holding per-attempt state files."""
    return Path(workdir) / "state" / "executions"


def scrapyd_logs_dir(workdir: str | Path) -> Path:
    """Directory scrapyd writes job logs into."""
    return Path(workdir) / "scrapyd" / "logs"


def wheel_workspace_dir(workdir: str | Path) -> Path:
    """Root for per-execution Python-wheel workspaces (cwd + merged job.log)."""
    return Path(workdir) / "python_wheel" / "workspaces"


def build_runtime(settings: Settings) -> AgentRuntime:
    """Construct the agent's runtime objects from settings.

    A :class:`ScrapydProcess` is created when ``[scrapyd].start`` is true so the
    daemon can start/stop it; the client/runner are always built so the Redis
    command consumer can drive local execution.
    """
    workdir = settings.agent.workdir
    base_url = f"http://{settings.scrapyd.host}:{settings.scrapyd.port}"

    process: ScrapydProcess | None = None
    if settings.scrapyd.start:
        process = ScrapydProcess(
            workdir=workdir,
            host=settings.scrapyd.host,
            port=settings.scrapyd.port,
            jobs_to_keep=settings.scrapyd.jobs_to_keep,
            finished_to_keep=settings.scrapyd.finished_to_keep,
        )

    client = ScrapydClient(base_url=base_url)
    store = StateStore(state_dir(workdir))
    runner = ScrapyRunner(
        client=client,
        store=store,
        logs_dir=scrapyd_logs_dir(workdir),
        max_job_log_bytes=settings.agent.max_job_log_bytes,
    )
    redis_status = RedisRuntimeStatus() if settings.redis.url else None
    # Shared disk-usage sample: the janitor publishes it, the heartbeat reads it.
    disk_status = DiskStatus()
    artifact_cache: ScrapyArtifactCache | None = None
    wheel_cache: PythonWheelCache | None = None
    if settings.agent.server_url:
        artifact_cache = ScrapyArtifactCache(
            root_dir=Path(workdir) / "artifacts",
            server_url=settings.agent.server_url,
            agent_token=settings.agent.agent_token,
            scrapyd=client,
        )
        wheel_cache = PythonWheelCache(
            root_dir=Path(workdir) / "artifacts",
            server_url=settings.agent.server_url,
            agent_token=settings.agent.agent_token,
        )
    # The Python-wheel runner needs no server URL (it spawns local shell
    # commands); the cache that fetches the wheel does.
    wheel_runner = PythonWheelRunner(
        workspace_root=wheel_workspace_dir(workdir),
        max_job_log_bytes=settings.agent.max_job_log_bytes,
    )
    # Heartbeat worker is built only when a server_url is configured; run_agent
    # starts/stops the background task.
    heartbeat: HeartbeatWorker | None = None
    if settings.agent.server_url:
        heartbeat = HeartbeatWorker(
            settings=settings,
            store=store,
            version=__version__,
            redis_status=redis_status,
            disk_status=disk_status,
        )
    return AgentRuntime(
        settings=settings,
        process=process,
        client=client,
        store=store,
        runner=runner,
        redis_status=redis_status,
        disk_status=disk_status,
        artifact_cache=artifact_cache,
        wheel_cache=wheel_cache,
        wheel_runner=wheel_runner,
        heartbeat=heartbeat,
    )
