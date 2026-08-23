"""Agent settings models (Pydantic v2).

These mirror the agent-side TOML config. The agent never connects to a
database; it only knows about itself (id/workdir), where to reach the server,
its single server<->agent token, and which capabilities it advertises.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

# Smallest non-zero log publish rate: the 2-second bucket (2 * rate) must hold
# one truncation marker (<= 160 bytes for any cap value).
LOG_PUBLISH_RATE_MIN = 128


class AgentSettings(BaseModel):
    """Identity and outbound-contact settings for this agent.

    The agent is **outbound-only** (phase 2.2.7): it opens no inbound HTTP
    listener and binds no port. ``server_url`` is the server HTTP base URL the
    agent uses for heartbeat and artifact/wheel fetch; ``heartbeat_interval_seconds``
    paces the heartbeat loop.

    Phase 2.2.3 collapsed the old split machine tokens into a single
    ``agent_token``. After phase 2.2.7 it authenticates only the agent -> server
    direction (heartbeat + artifact/wheel fetch); there is no server -> agent
    HTTP path left to guard. Machine auth is ON iff ``agent_token`` is non-empty.
    """

    agent_id: str
    workdir: str = "/agent-data"
    server_url: str = ""
    heartbeat_interval_seconds: int = 10
    # Per-ATTEMPT liveness heartbeat pacing (distinct from the node-level
    # heartbeat above): while the command consumer confirms an attempt's process
    # alive (scrapyd lists the job / the wheel child has no returncode), it
    # re-emits ``attempt.heartbeat`` at most once per this many seconds so the
    # server's event-stall clock measures liveness, not time-since-transition.
    # Must stay well below the server's ``stalled_attempt_seconds`` (default
    # 300). 0 disables attempt heartbeats.
    attempt_heartbeat_interval_seconds: int = 60
    agent_token: str = ""
    # Resource caps (C1/C2): local-disk janitor + per-job log size cap.
    # How often the janitor sweeps (seconds); it also runs once at startup.
    janitor_interval_seconds: int = 600
    # A TERMINAL execution's workspace/logs/state are removed once older than this
    # many days (the server normally cleans them via cleanup_logs; this is the TTL
    # fallback when that never arrives).
    completed_log_ttl_days: int = 3
    # An ORPHAN workspace (no readable state, no live process, quiet on disk) is
    # removed once older than this many days — longer than completed, since we are
    # less certain about it.
    orphan_log_ttl_days: int = 7
    # Per-execution job-log size hard cap in bytes, for EVERY runner (log-flood
    # guard). Python wheel jobs: the drain writes one truncation marker and drops
    # further output; the subprocess keeps running. Scrapyd jobs: the cap is
    # injected into the crawler as ``-s DOPILOT_JOB_LOG_CAP_BYTES`` (the in-process
    # ``logcap`` hook stops writing + SIGTERMs the crawler at the cap), the agent
    # watchdog cancels + truncates a job whose log still reaches the cap, and the
    # log publisher stops tailing past it. Default 32MiB. 0 disables all of it.
    max_job_log_bytes: int = 33554432
    # Log-flood watchdog escalation: seconds after the first scrapyd cancel before
    # the watchdog re-cancels with ``signal=KILL``; after twice this the agent
    # kills the single crawler PID it can prove belongs to the managed scrapyd.
    log_flood_kill_after_seconds: int = 30
    # Janitor: an oversized job.log with NO readable state is only truncated when
    # scrapyd does not list the job AND the file has been quiet (mtime) for at
    # least this many seconds — never a possibly-running job's log.
    janitor_quiet_seconds: int = 3600
    # Aggregate artifact/wheel cache size cap in bytes under
    # ``{workdir}/artifacts``. The janitor evicts least-recently-used sha entries
    # above this, never evicting one referenced by a running execution. Default
    # 2GiB. 0 disables cache eviction.
    artifact_cache_max_bytes: int = 2147483648

    @property
    def machine_auth_enabled(self) -> bool:
        """server<->agent machine auth is ON iff ``agent_token`` is set."""
        return bool(self.agent_token)


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
    # Resource caps (C7): approximate MAXLEN the agent passes on XADD, now
    # config-driven (were hard-coded constructor defaults). Match the server
    # defaults so the log stream working set stays bounded (see the 2.11GB Redis
    # volume incident).
    maxlen_logs: int = 100000
    maxlen_events: int = 100000
    # Log-flood guard: agent-wide token-bucket cap on log bytes published to the
    # shared log stream (bucket = 2s of quota). Bounds how fast one agent can fill
    # Redis regardless of how many executions are talkative. 0 = unlimited;
    # otherwise at least LOG_PUBLISH_RATE_MIN so the 2s bucket can always hold
    # one truncation marker (the marker is bucket-accounted like content and is
    # never allowed to overshoot the bucket).
    log_publish_rate_bytes_per_second: int = 2097152
    # Resource caps (C5): hard cap on the durable event-outbox file count. During
    # a long Redis outage the outbox would otherwise grow without bound; above the
    # cap the OLDEST files are dropped (logged) so the agent never fills its disk.
    # 0 disables the cap.
    event_outbox_max_files: int = 100000

    @field_validator("log_publish_rate_bytes_per_second")
    @classmethod
    def _rate_can_carry_a_marker(cls, value: int) -> int:
        if value < 0 or (0 < value < LOG_PUBLISH_RATE_MIN):
            raise ValueError(
                "log_publish_rate_bytes_per_second must be 0 (unlimited) or "
                f">= {LOG_PUBLISH_RATE_MIN}"
            )
        return value

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
    # Resource caps (C3): scrapyd's own retention, now explicit + tunable instead
    # of relying on scrapyd's built-in defaults. Written into the generated
    # scrapyd.conf. jobs_to_keep bounds finished job logs/items per spider;
    # finished_to_keep bounds the in-memory finished-job list.
    jobs_to_keep: int = 5
    finished_to_keep: int = 100


class Settings(BaseModel):
    """Top-level agent settings."""

    agent: AgentSettings
    capabilities: Capabilities = Field(default_factory=Capabilities)
    scrapyd: ScrapydSettings = Field(default_factory=ScrapydSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
