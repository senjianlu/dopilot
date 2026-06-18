"""Config loading.

Reads a TOML file (path argument or ``DOPILOT_CONFIG`` env), applies the
``DOPILOT_DATABASE_URL`` env override, and returns a :class:`Settings`.

dopilot uses its own TOML loader under ``configs/`` — it does NOT inherit the
scrapydweb ``scrapydweb_settings_v11.py`` / ``os.getcwd()`` form.
"""

from __future__ import annotations

import os
import tomllib
from functools import lru_cache
from pathlib import Path
from typing import Any

from .settings import Settings


class ConfigError(Exception):
    """Raised when no config can be located or the file is unreadable."""


def _read_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as fh:
        return tomllib.load(fh)


def load_settings(path: str | None = None) -> Settings:
    """Load :class:`Settings` from a TOML file.

    Resolution order for the file path: explicit ``path`` argument, else the
    ``DOPILOT_CONFIG`` environment variable. If neither is set, or the file is
    missing, a :class:`ConfigError` is raised.

    The ``DOPILOT_DATABASE_URL`` env var, if set, overrides ``[database].url``.
    """
    resolved = path or os.environ.get("DOPILOT_CONFIG")
    if not resolved:
        raise ConfigError(
            "No config provided: pass a path or set the DOPILOT_CONFIG "
            "environment variable."
        )

    config_path = Path(resolved)
    if not config_path.is_file():
        raise ConfigError(f"Config file not found: {config_path}")

    try:
        raw = _read_toml(config_path)
    except (OSError, tomllib.TOMLDecodeError) as exc:  # pragma: no cover
        raise ConfigError(f"Failed to read config {config_path}: {exc}") from exc

    settings = Settings.model_validate(raw)

    db_override = os.environ.get("DOPILOT_DATABASE_URL")
    if db_override:
        settings.database.url = db_override

    return settings


@lru_cache(maxsize=1)
def _cached_settings() -> Settings:
    return load_settings()


def get_settings() -> Settings:
    """FastAPI dependency returning a cached singleton :class:`Settings`.

    Tests override this via ``app.dependency_overrides[get_settings]`` so the
    lru_cache is never exercised in the test client path.
    """
    return _cached_settings()


def reset_settings_cache() -> None:
    """Clear the cached settings (useful in tests / config reloads)."""
    _cached_settings.cache_clear()
