"""TOML config loader for the agent.

Loads settings from the path given by ``DOPILOT_CONFIG`` (or an explicit path).
Supports a small set of environment overrides used by container deployments.
``get_settings()`` is a cached singleton helper retained for direct callers.
"""

from __future__ import annotations

import os
import tomllib
from functools import lru_cache
from pathlib import Path
from typing import Any

from .settings import (
    AgentSettings,
    Capabilities,
    RedisSettings,
    ScrapydSettings,
    Settings,
)

# Minimum length for a non-empty server<->agent ``agent_token`` (phase 2.2.3),
# matching the server-side check.
_AGENT_TOKEN_MIN_LEN = 16

# Role-specific baked default config path. ``main()`` passes this as
# ``default_path`` so the unified image runs agent mode without an explicit
# ``DOPILOT_CONFIG`` (precedence: explicit path > DOPILOT_CONFIG > this default).
DEFAULT_CONFIG_PATH = "/app/configs/agent.toml"


class ConfigError(Exception):
    """Raised when the agent config is missing or unreadable."""


def _read_toml(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as fh:
            return tomllib.load(fh)
    except FileNotFoundError as exc:
        raise ConfigError(f"config file not found: {path}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"invalid TOML in config file {path}: {exc}") from exc


def load_settings(
    path: str | os.PathLike[str] | None = None,
    *,
    default_path: str | None = None,
) -> Settings:
    """Load agent settings from TOML.

    Resolution order for the path: explicit ``path`` argument, then the
    ``DOPILOT_CONFIG`` environment variable, then ``default_path`` (``main()``
    passes the baked agent default so the image runs without an explicit
    ``DOPILOT_CONFIG``). Environment overrides applied after parsing:
    ``DOPILOT_AGENT_ID`` -> ``[agent].agent_id``, ``DOPILOT_AGENT_WORKDIR`` ->
    ``[agent].workdir``,
    ``DOPILOT_SERVER_URL`` -> ``[agent].server_url`` (the server HTTP base URL the
    agent uses for heartbeat and artifact/wheel fetch; needed by agent-only / K3s
    deployments where the baked ``http://server:5000`` does not resolve),
    ``DOPILOT_REDIS_URL`` -> ``[redis].url``, ``DOPILOT_AGENT_TOKEN`` ->
    ``[agent].agent_token`` (the single server<->agent machine token).

    Phase 2.2.3 collapsed the split machine tokens into one. The old envs
    ``DOPILOT_AGENT_SHARED_TOKEN`` / ``DOPILOT_SERVER_SHARED_TOKEN`` and the
    admin-token fallback (``DOPILOT_ADMIN_API_TOKEN``) no longer fill any agent
    machine token and have no effect: agents are never given or derive from the
    admin API token. A non-empty ``agent_token`` shorter than 16 characters
    raises :class:`ConfigError`; empty/missing keeps machine auth OFF.
    """
    raw_path = (
        path if path is not None else os.environ.get("DOPILOT_CONFIG")
    ) or default_path
    if not raw_path:
        raise ConfigError(
            "no config path provided; set DOPILOT_CONFIG or pass path explicitly"
        )

    data = _read_toml(Path(raw_path))

    agent_section: dict[str, Any] = dict(data.get("agent") or {})
    cap_section: dict[str, Any] = dict(data.get("capabilities") or {})
    scrapyd_section: dict[str, Any] = dict(data.get("scrapyd") or {})
    redis_section: dict[str, Any] = dict(data.get("redis") or {})

    # Every deployment env override is DOPILOT_-prefixed (no bare AGENT_ID /
    # AGENT_WORKDIR): unprefixed generic names are silently inherited from an
    # unrelated service on the same host / sidecar and would then rewrite this
    # agent's identity or working set.
    #
    # ``DOPILOT_AGENT_ID`` deliberately reuses the name that
    # dopilot_protocol.execution exposes to user workloads as the runtime-context
    # agent id: both carry the SAME fact ("the id of this agent"), and they agree
    # by construction because an agent only consumes the command stream addressed
    # to its own id. Job children still take the runtime-context value — the
    # wheel runner overlays it last over the inherited process env.
    env_agent_id = os.environ.get("DOPILOT_AGENT_ID")
    if env_agent_id:
        agent_section["agent_id"] = env_agent_id
    env_workdir = os.environ.get("DOPILOT_AGENT_WORKDIR")
    if env_workdir:
        agent_section["workdir"] = env_workdir
    # Server HTTP base URL (heartbeat + artifact/wheel fetch): env wins over TOML.
    # Agent-only / K3s deployments set this because the baked compose default
    # ``http://server:5000`` only resolves inside the all-in-one compose network.
    env_server_url = os.environ.get("DOPILOT_SERVER_URL")
    if env_server_url:
        agent_section["server_url"] = env_server_url
    env_redis_url = os.environ.get("DOPILOT_REDIS_URL")
    if env_redis_url:
        redis_section["url"] = env_redis_url

    # Resource caps (C7): env overrides for every new numeric knob (TOML + env
    # dual channel), so a deployment can retune them without editing TOML.
    for env_var, section, key in (
        ("DOPILOT_REDIS_STREAM_MAXLEN_LOGS", redis_section, "maxlen_logs"),
        ("DOPILOT_REDIS_STREAM_MAXLEN_EVENTS", redis_section, "maxlen_events"),
        ("DOPILOT_REDIS_EVENT_OUTBOX_MAX_FILES", redis_section,
         "event_outbox_max_files"),
        ("DOPILOT_AGENT_JANITOR_INTERVAL_SECONDS", agent_section,
         "janitor_interval_seconds"),
        ("DOPILOT_AGENT_COMPLETED_LOG_TTL_DAYS", agent_section,
         "completed_log_ttl_days"),
        ("DOPILOT_AGENT_ORPHAN_LOG_TTL_DAYS", agent_section,
         "orphan_log_ttl_days"),
        ("DOPILOT_AGENT_MAX_JOB_LOG_BYTES", agent_section, "max_job_log_bytes"),
        ("DOPILOT_AGENT_ARTIFACT_CACHE_MAX_BYTES", agent_section,
         "artifact_cache_max_bytes"),
        ("DOPILOT_SCRAPYD_JOBS_TO_KEEP", scrapyd_section, "jobs_to_keep"),
        ("DOPILOT_SCRAPYD_FINISHED_TO_KEEP", scrapyd_section,
         "finished_to_keep"),
    ):
        raw = os.environ.get(env_var)
        if raw is not None:
            try:
                section[key] = int(raw.strip())
            except ValueError as exc:
                raise ConfigError(
                    f"invalid integer for {env_var}: {raw!r}"
                ) from exc

    # Single server<->agent machine token (phase 2.2.3): env wins over TOML.
    # The old split envs and the admin-token fallback were removed and have no
    # effect — agents never receive or derive from the admin API token.
    env_agent_token = os.environ.get("DOPILOT_AGENT_TOKEN")
    if env_agent_token is not None:
        agent_section["agent_token"] = env_agent_token

    if not agent_section.get("agent_id"):
        raise ConfigError("missing required setting: [agent].agent_id")

    token = str(agent_section.get("agent_token") or "").strip()
    if token and len(token) < _AGENT_TOKEN_MIN_LEN:
        raise ConfigError(
            "agent.agent_token is too short: a non-empty server<->agent token "
            f"must be at least {_AGENT_TOKEN_MIN_LEN} characters "
            "(set DOPILOT_AGENT_TOKEN or [agent].agent_token, or leave it empty)."
        )

    return Settings(
        agent=AgentSettings(**agent_section),
        capabilities=Capabilities(**cap_section),
        scrapyd=ScrapydSettings(**scrapyd_section),
        redis=RedisSettings(**redis_section),
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Singleton settings helper for direct library callers."""
    return load_settings()
