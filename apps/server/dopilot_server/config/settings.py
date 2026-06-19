"""Pydantic settings models mirroring the dopilot server TOML config.

Each model maps one ``[section]`` of the config file. Auth is
"config-present-or-off": web auth is enabled iff admin_username,
admin_password and token_secret are all present and non-empty; agent auth is
enabled iff shared_token is non-empty.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ServerSettings(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8000
    public_url: str | None = None


class DatabaseSettings(BaseModel):
    url: str = "postgresql+psycopg://dopilot:dopilot@localhost:5432/dopilot"


class AuthSettings(BaseModel):
    admin_username: str | None = None
    admin_password: str | None = None
    token_secret: str | None = None
    access_token_ttl_minutes: int = 720
    stream_token_ttl_seconds: int = 3600

    @property
    def enabled(self) -> bool:
        """Web auth is ON iff all three credentials are present and non-empty."""
        return bool(
            self.admin_username
            and self.admin_password
            and self.token_secret
        )


class AgentAuthSettings(BaseModel):
    """server -> agent shared-token auth (used by the surviving egg-deploy
    HTTP path). Distinct from the agent -> server token in :class:`AgentsSettings`
    (auth is split in phase 1.5, decision #12)."""

    shared_token: str | None = None

    @property
    def enabled(self) -> bool:
        """Agent auth is ON iff the shared token is present and non-empty."""
        return bool(self.shared_token)


class RedisSettings(BaseModel):
    """``[redis]`` — server-side Redis Streams transport (phase 1.5).

    Redis is a message bus / transient transport, never a dopilot database;
    PostgreSQL remains the business-state authority.
    """

    url: str = "redis://localhost:6379/0"
    stream_maxlen_commands: int = 100000
    stream_maxlen_events: int = 100000
    stream_maxlen_logs: int = 1000000
    log_retention_seconds: int = 86400
    consumer_name: str = "server-1"
    require_aof: bool = True

    @property
    def enabled(self) -> bool:
        return bool(self.url)


class AgentsSettings(BaseModel):
    """``[agents]`` — agent-fleet behavior + the agent -> server inbound token.

    ``server_shared_token`` authenticates agent-initiated calls (heartbeat) TO
    the server; it is a *different* secret from
    :attr:`AgentAuthSettings.shared_token` (server -> agent). Inbound agent auth
    follows the same "config-present-or-off" idiom as web/agent auth.
    """

    heartbeat_timeout_seconds: int = 30
    stalled_attempt_seconds: int = 300
    lost_after_stalled_seconds: int = 900
    server_shared_token: str | None = None

    @property
    def inbound_auth_enabled(self) -> bool:
        """Agent -> server auth is ON iff ``server_shared_token`` is set."""
        return bool(self.server_shared_token)


class NodesSettings(BaseModel):
    agents: list[str] = Field(default_factory=list)


class SchedulerSettings(BaseModel):
    enabled: bool = False
    timezone: str = "UTC"


class LogsSettings(BaseModel):
    root_dir: str = "/server-data/logs"
    background_drain_interval_seconds: int = 30
    realtime_drain_interval_seconds: int = 1
    # How often the reconcile loop polls each active attempt's agent /status.
    status_poll_interval_seconds: int = 5
    max_tail_bytes_per_pull: int = 262144
    eof_stable_seconds: int = 5
    final_drain_hard_timeout_seconds: int = 60
    # Phase 1.5: bounded drain window after a terminal event before the server
    # finalizes the log file and issues cleanup_logs (decoupled from lossy eof).
    log_drain_timeout_seconds: int = 30
    # How long an attempt may stay unreachable (agent down) before it is
    # declared "lost" rather than left running forever.
    unreachable_lost_seconds: int = 120
    retention_days: int = 14
    # First-screen tail when a web log window opens: last N lines or M bytes,
    # whichever boundary is reached first.
    first_screen_max_lines: int = 2000
    first_screen_max_bytes: int = 1048576


class ArtifactsSettings(BaseModel):
    root_dir: str = "/server-data/artifacts"


class I18nSettings(BaseModel):
    locale: str = "en"
    timezone: str = "UTC"


class Settings(BaseModel):
    """Aggregate of all config sections."""

    server: ServerSettings = Field(default_factory=ServerSettings)
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    auth: AuthSettings = Field(default_factory=AuthSettings)
    agent_auth: AgentAuthSettings = Field(default_factory=AgentAuthSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
    agents: AgentsSettings = Field(default_factory=AgentsSettings)
    nodes: NodesSettings = Field(default_factory=NodesSettings)
    scheduler: SchedulerSettings = Field(default_factory=SchedulerSettings)
    logs: LogsSettings = Field(default_factory=LogsSettings)
    artifacts: ArtifactsSettings = Field(default_factory=ArtifactsSettings)
    i18n: I18nSettings = Field(default_factory=I18nSettings)
