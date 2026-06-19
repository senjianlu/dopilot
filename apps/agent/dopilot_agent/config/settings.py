"""Agent settings models (Pydantic v2).

These mirror the agent-side TOML config. The agent never connects to a
database; it only knows about itself (id/host/port/workdir), its shared-token
auth, and which capabilities it advertises.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class AgentSettings(BaseModel):
    """Identity and HTTP bind settings for this agent.

    Phase 1.5 adds the agent -> server contact details: ``server_url`` (where the
    agent POSTs heartbeats), ``heartbeat_interval_seconds``, and
    ``server_shared_token`` (the agent -> server token, distinct from the
    server -> agent :class:`AuthSettings.shared_token`).
    """

    agent_id: str
    host: str = "0.0.0.0"
    port: int = 6800
    workdir: str = "/agent-data"
    server_url: str = ""
    heartbeat_interval_seconds: int = 10
    server_shared_token: str = ""
    # The server-reachable base endpoint this agent advertises in its heartbeat
    # (e.g. "agent:6800" in compose). Used by the surviving egg-deploy HTTP path;
    # empty => not advertised (the server keeps any previously-known endpoint).
    advertise_endpoint: str = ""


class AuthSettings(BaseModel):
    """Server->agent shared-token auth (used by the surviving egg-deploy path).

    Auth is enabled iff ``shared_token`` is non-empty.
    """

    shared_token: str = ""

    @property
    def enabled(self) -> bool:
        return bool(self.shared_token)


class RedisSettings(BaseModel):
    """``[redis]`` — agent-side Redis Streams transport (phase 1.5).

    The agent consumes its command stream and publishes status/log events; it
    never connects to PostgreSQL. ``event_outbox_dir`` holds the durable local
    event outbox replayed on restart.
    """

    url: str = "redis://redis:6379/0"
    command_block_ms: int = 5000
    pending_idle_ms: int = 30000
    event_outbox_dir: str = "/agent-data/outbox"

    @property
    def enabled(self) -> bool:
        return bool(self.url)


class Capabilities(BaseModel):
    """Which scheduled-object types this agent can execute.

    Field shape matches the frozen ``CapabilitySet`` protocol contract.
    """

    scrapy: bool = False
    script: bool = False
    docker: bool = False


class ScrapydSettings(BaseModel):
    """Local scrapyd subprocess settings.

    The agent owns a scrapyd child bound to ``host:port`` on a container-internal
    address (never exposed to the host). Its data dirs live under
    ``{workdir}/scrapyd``. ``start=False`` lets a deployment point the agent at an
    externally managed scrapyd (and skips spawning a child) — the default is to
    spawn one.
    """

    start: bool = True
    host: str = "127.0.0.1"
    port: int = 6801


class Settings(BaseModel):
    """Top-level agent settings."""

    agent: AgentSettings
    auth: AuthSettings = Field(default_factory=AuthSettings)
    capabilities: Capabilities = Field(default_factory=Capabilities)
    scrapyd: ScrapydSettings = Field(default_factory=ScrapydSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
