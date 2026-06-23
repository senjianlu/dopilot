"""Pydantic settings models mirroring the dopilot server TOML config.

Each model maps one ``[section]`` of the config file.

Web admin auth is **fail-closed** (phase 2.2): it is enabled iff it is not
explicitly disabled AND admin_username, admin_password and token_secret are all
present and non-empty. Production startup (:func:`loader.load_settings`) refuses
to boot when auth is not disabled but a credential is missing; the only way to
run anonymously is the explicit ``auth.disabled`` flag
(``DOPILOT_AUTH_DISABLED=true``). Machine (server<->agent) auth stays
"config-present-or-off": it is enabled iff the single ``[agents].agent_token``
is non-empty after config loading or after the phase 2.2.4 server runtime
auto-generates and applies a persisted token (phase 2.2.3 collapsed the old
split tokens into one).
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ServerSettings(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8000
    public_url: str | None = None
    # Server-owned data root (phase 2.2.4). The persistence anchor for
    # server-side secrets — specifically the auto-generated server<->agent token
    # at ``<data_dir>/secrets/agent-token``. This is intentionally distinct from
    # ``logs.root_dir`` / ``artifacts.root_dir`` (those stay independent and are
    # NOT the token anchor). Override with ``DOPILOT_SERVER_DATA_DIR``.
    data_dir: str = "/server-data"


class DatabaseSettings(BaseModel):
    url: str = "postgresql+psycopg://dopilot:dopilot@localhost:5432/dopilot"


class AuthSettings(BaseModel):
    # Explicit dev/anonymous escape hatch (phase 2.2). When true the platform
    # runs as an anonymous admin and protected endpoints are open. Set via
    # ``DOPILOT_AUTH_DISABLED=true``. Anonymous mode is NEVER entered silently:
    # it requires this flag, so production startup fail-closes otherwise.
    disabled: bool = False
    admin_username: str | None = None
    admin_password: str | None = None
    # Internal HMAC signing key for login access tokens and SSE stream tokens.
    # TOML-only (phase 2.2.2): it has NO env override and is never the machine
    # token fallback source.
    token_secret: str | None = None
    # Externally supplied static admin API token (phase 2.2.2). When non-empty it
    # may be presented directly as ``Authorization: Bearer <admin_api_token>`` to
    # authenticate as admin (no login round-trip). Set via ``DOPILOT_ADMIN_API_TOKEN``
    # or TOML. It is an ADDITIONAL automation credential and does NOT participate
    # in :attr:`enabled` (interactive web login still needs the three creds).
    # Admin-only (phase 2.2.3): it is NEVER a source for the server<->agent
    # machine token — those are separate secrets with no fallback between them.
    admin_api_token: str | None = None
    access_token_ttl_minutes: int = 720
    stream_token_ttl_seconds: int = 3600

    @property
    def enabled(self) -> bool:
        """Web auth is ON iff not disabled AND all three creds are non-empty.

        ``admin_api_token`` is intentionally excluded: it is an additional
        automation credential, not a substitute for interactive login.
        """
        return not self.disabled and bool(
            self.admin_username
            and self.admin_password
            and self.token_secret
        )


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
    """``[agents]`` — agent-fleet behavior + the single server<->agent token.

    ``agent_token`` (phase 2.2.3) is the ONE machine secret. The agent presents
    it on its outbound calls — agent -> server heartbeat and artifact/wheel
    fetches — and the server validates them against this value. After phase 2.2.7
    the agent is outbound-only, so there is no server -> agent HTTP direction to
    authenticate. It replaced the old split ``[agent_auth].shared_token`` +
    ``[agents].server_shared_token`` pair; there is no fallback from the admin API
    token. Machine auth is ON iff ``agent_token`` is set; this is distinct from
    Web admin auth, which is fail-closed (see the module docstring).

    Phase 2.2.4 relaxed the strict "config-present-or-off" rule at the SERVER
    runtime boundary only: when no ``agent_token`` is configured, the server
    runtime/CLI auto-generates and persists one under ``server.data_dir`` and
    sets it on this field before startup, so machine auth ends up ON. The
    generation is a runtime step (:mod:`dopilot_server.agent_token`), never a
    side effect of :func:`loader.load_settings` — loading stays pure.
    """

    heartbeat_timeout_seconds: int = 30
    stalled_attempt_seconds: int = 300
    lost_after_stalled_seconds: int = 900
    agent_token: str | None = None

    @property
    def machine_auth_enabled(self) -> bool:
        """server<->agent machine auth is ON iff ``agent_token`` is set."""
        return bool(self.agent_token)


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
    redis: RedisSettings = Field(default_factory=RedisSettings)
    agents: AgentsSettings = Field(default_factory=AgentsSettings)
    nodes: NodesSettings = Field(default_factory=NodesSettings)
    scheduler: SchedulerSettings = Field(default_factory=SchedulerSettings)
    logs: LogsSettings = Field(default_factory=LogsSettings)
    artifacts: ArtifactsSettings = Field(default_factory=ArtifactsSettings)
    i18n: I18nSettings = Field(default_factory=I18nSettings)
