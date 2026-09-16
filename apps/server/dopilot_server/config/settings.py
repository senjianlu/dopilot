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
    # Resource caps: the log stream is the dominant Redis memory consumer. At
    # ~1-2KB/entry a 1_000_000 cap holds a 1-2GB working set (observed 2.11GB
    # Redis volume in production), so the default is 100_000. This MAXLEN on XADD
    # is the primary bound; the time-based XTRIM MINID sweep (see
    # ``log_retention_seconds``) is the secondary bound.
    stream_maxlen_logs: int = 100000
    # Log-flood guard: BYTE budget for the log stream (the count-based MAXLEN
    # above is meaningless at 256KB entries). ``StreamGuardLoop`` measures
    # ``MEMORY USAGE`` every ``stream_guard_interval_seconds`` and trims the
    # stream (exact XTRIM, iterative) back under this budget; a stream that
    # will not converge is cleared. Default 256MB. 0 disables the guard.
    stream_max_bytes_logs: int = 268435456
    stream_guard_interval_seconds: int = 30
    # Log-flood guard: ``sent`` outbox rows whose command message is no longer
    # in the agent's command stream (stream cleared / trimmed / volume wiped)
    # are reset to ``pending`` for re-dispatch (at-least-once, decision 0008).
    # Checked at dispatcher start and every ``sent_reconcile_interval_seconds``;
    # only rows whose ``updated_at`` is older than ``sent_reconcile_min_age_seconds``
    # (so an in-flight XADD is never mistaken for a lost one). 0 interval = off.
    sent_reconcile_interval_seconds: int = 300
    sent_reconcile_min_age_seconds: int = 60
    # OOM guard (2026-08-26 incident): max ``sent`` rows examined per reconcile
    # call. The scan is keyset-paged with a per-sweep frozen boundary, so any
    # lost message is still checked within ``2*ceil(N/batch)+1`` intervals —
    # memory use no longer scales with the outbox table.
    sent_reconcile_batch_limit: int = 500
    # Time bound for the log stream, enforced by the retention sweep as a periodic
    # ``XTRIM <stream> MINID ~ <now - log_retention_seconds>``. Entries older than
    # this window are trimmed regardless of MAXLEN. 0 disables the time-based
    # trim (MAXLEN still applies).
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
    # With per-attempt heartbeats (~60s while confirmed alive) a healthy attempt
    # never idles anywhere near this; it now bounds "agent online but liveness
    # unconfirmable" before reclaim, so it errs toward not killing healthy work
    # (900 used to act as a hard task-runtime cap for pre-heartbeat agents).
    lost_after_stalled_seconds: int = 3600
    # No-progress detection. Strictly an ALERTING path: it never marks an
    # attempt lost and never touches the reclaim chain above, because a long
    # quiet stretch is not proof of death -- killing on that signal is exactly
    # what made a hard spider-side timeout unusable.
    #
    # ``no_progress_stall_seconds``: how long a confirmed-alive attempt may go
    #   without its log growing before we alert. 0 disables the feature. The
    #   default is deliberately far wider than any known healthy run.
    # ``no_progress_sample_max_age_seconds``: how fresh the agent's last
    #   log-size reading must be for the verdict to mean anything. Without a
    #   current reading we are blind, not looking at a stalled job, so we say
    #   nothing. ~5x the agent's 60s heartbeat leaves room for jitter.
    # ``auto_stop_on_no_progress``: opt-in. False means dopilot only tells you;
    #   turning it on makes a no-progress verdict actually cancel the task.
    no_progress_stall_seconds: int = 1800
    no_progress_sample_max_age_seconds: int = 300
    auto_stop_on_no_progress: bool = False
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
    # Log-flood guard / auto-disable: a schedule whose last N recorded task
    # outcomes (current generation, ordered by finished_at) are ALL erroneous is
    # switched off (``enabled=false``) and a notification is raised. 0 disables
    # the feature. "Erroneous" = failed/lost, or finished with scrapy
    # ``log_count/ERROR > 0`` / abnormal ``finish_reason``, or a log-flood /
    # size-cap truncation (see ``states.execution_is_erroneous``).
    auto_disable_after_errors: int = 5
    # A ``lost`` task is a soft terminal the agent may still override; it is
    # only recorded as an outcome once its executions were reclaimed and the
    # drain window passed, or after this many seconds as a bounded fallback.
    lost_outcome_grace_seconds: int = 86400


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
    # How many days a terminal task's log files + rows are retained before the
    # automatic retention sweep deletes them (see [maintenance]). Also the cutoff
    # the manual maintenance API uses by default. Default 30 (matches the docker
    # config and the documented retention policy).
    retention_days: int = 30
    # Per-execution log-file size hard cap (resource caps). Once a single
    # execution's on-disk log reaches this size the consumer stops appending body
    # bytes but keeps consuming + ACKing the stream (never stalls), writes one
    # visible truncation marker, sets ``log_integrity='truncated'`` and sends the
    # agent a ``stop_logs`` backpressure command. Default 32MiB (log-flood guard;
    # matches the agent's ``max_job_log_bytes``). 0 disables the cap.
    max_file_bytes: int = 33554432
    # Aggregate logs-directory budget (log-flood guard, disk hard limit). The
    # log consumer admits an increment only if ``LogsDirGauge`` + the planned
    # bytes stay under this; otherwise nothing is written (DB state only). The
    # retention sweep evicts the oldest SEALED terminal tasks' logs to make room.
    # Default 20GB. 0 disables the budget.
    max_total_bytes: int = 21474836480
    # First-screen tail when a web log window opens: last N lines or M bytes,
    # whichever boundary is reached first.
    first_screen_max_lines: int = 2000
    first_screen_max_bytes: int = 1048576


class MaintenanceSettings(BaseModel):
    """``[maintenance]`` — automatic retention sweep (resource caps).

    A single always-on background loop (``RetentionSweepLoop``) enforces the
    time-based retention that was previously only reachable via the manual
    maintenance API. It deletes terminal task data older than
    ``logs.retention_days``, prunes ``event_audit`` rows, and issues the periodic
    Redis stream ``XTRIM MINID`` (see ``redis.log_retention_seconds``).
    """

    # Whether the automatic sweep runs. On by default: the whole point of the
    # resource caps is that limits hold without operator action. Set false to
    # fall back to the manual maintenance API only.
    enabled: bool = True
    # How often the sweep runs, in seconds. Default hourly.
    sweep_interval_seconds: int = 3600
    # How many days ``event_audit`` rows are retained (one row per consumed agent
    # status event — the fastest-growing table). 0 disables event_audit pruning.
    event_audit_retention_days: int = 30
    # Batch size for the ``event_audit`` delete, to avoid long table locks.
    event_audit_delete_batch: int = 5000
    # How many days RESOLVED command-outbox rows (sent / failed / canceled) are
    # retained after they settle (OOM guard, 2026-08-26 incident: ``sent`` rows
    # used to live forever and grew unbounded). Rows of ACTIVE or ``lost``
    # (soft-terminal) tasks and ``stop(intent=reclaim)`` rows — the persistent
    # at-most-once reclaim fact — are NEVER pruned here; they go with their
    # task (``cleanup_terminal_data``). 0 disables outbox pruning.
    outbox_retention_days: int = 7
    # Batch size for the outbox delete, to avoid long table locks.
    outbox_delete_batch: int = 5000
    # Log-flood guard: per-agent command streams left behind by retired agent
    # ids (no node row, soft-deleted node, or heartbeat older than this) are
    # deleted once this many days old AND nothing non-terminal / undelivered
    # references that agent. 0 disables.
    stale_command_stream_days: int = 7
    # Notification center bounds (resource hard limits, 0019): read rows older
    # than ``notification_retention_days`` are pruned; UNREAD rows older than
    # ``notification_unread_max_days`` are pruned too; and the table never
    # exceeds ``notification_max_rows`` (oldest evicted first, read before
    # unread). 0 disables the respective bound.
    notification_retention_days: int = 30
    notification_unread_max_days: int = 90
    notification_max_rows: int = 2000
    # How often the resource-stats sampler (``ResourceStatsLoop``) snapshots
    # server disk / PostgreSQL / Redis usage for the /maintenance dashboard, in
    # seconds. The snapshot is served from memory (the endpoint never samples on
    # the request path). 0 disables the sampler loop entirely — the endpoint then
    # returns an empty "not yet sampled" response instead of walking the FS.
    stats_interval_seconds: int = 60


class ArtifactsSettings(BaseModel):
    root_dir: str = "/server-data/artifacts"
    # Per-upload size hard cap (resource caps). Uploads are read in bounded
    # chunks and rejected with HTTP 413 once this many bytes have been read, so a
    # single upload can never exhaust RAM or disk. Default 200MiB. 0 disables.
    max_upload_bytes: int = 209715200
    # Aggregate artifact-store size hard cap (resource caps). Before accepting a
    # new upload the server checks the current stored total (sum of stored
    # artifact ``size_bytes``) plus in-flight reservations plus this upload; over
    # the quota it returns HTTP 507. Archived artifacts are never auto-deleted
    # (product decision), so the quota bounds growth by refusing new uploads.
    # Default 20GiB. 0 disables the aggregate quota.
    max_total_bytes: int = 21474836480


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
    maintenance: MaintenanceSettings = Field(
        default_factory=MaintenanceSettings
    )
    artifacts: ArtifactsSettings = Field(default_factory=ArtifactsSettings)
    i18n: I18nSettings = Field(default_factory=I18nSettings)
