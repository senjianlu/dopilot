"""Server-side resolution + persistence of the single server<->agent token.

Phase 2.2.4: reduce server-first deployment friction. The single
``[agents].agent_token`` (phase 2.2.3) authenticates BOTH directions
(server -> agent egg deploy, agent -> server heartbeat). When an operator does
NOT supply one, the **server** can generate and persist a strong token under its
data volume and reuse it on every restart; operators retrieve it with
``dopilot-server agent-token print``.

This is a RUNTIME concern, not a config-load concern: :func:`loader.load_settings`
stays pure (no file creation, no token generation). Generation/persistence lives
here and is invoked from the server runtime (:func:`dopilot_server.app.run`) and
the ``agent-token`` CLI.

Resolution rules (:func:`resolve_agent_token`):

- a configured (non-empty) ``[agents].agent_token`` / ``DOPILOT_AGENT_TOKEN``
  wins: it is returned as-is and the generated-token file is NEVER read or
  written;
- otherwise the persisted token at ``<server.data_dir>/secrets/agent-token`` is
  read if present;
- otherwise a new ``secrets.token_urlsafe(32)`` token is generated, its parent
  directory is created, it is written atomically, and (where supported) its file
  mode is set to ``0600``.

Token generation is server-only — agents never generate tokens.
"""

from __future__ import annotations

import os
import secrets
import stat
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from .config.settings import Settings

try:  # pragma: no cover - fcntl is POSIX-only
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX fallback
    fcntl = None

# Generated tokens use 32 random bytes (~43 url-safe chars), comfortably above
# the loader's 16-char minimum for configured tokens.
_GENERATED_TOKEN_NBYTES = 32

# Persisted under the server data dir so it survives restarts on the data volume.
_SECRETS_SUBDIR = "secrets"
_TOKEN_FILENAME = "agent-token"


@dataclass(frozen=True)
class AgentTokenResult:
    """Outcome of resolving the active server<->agent token.

    ``source`` is one of:

    - ``"configured"`` — taken from ``[agents].agent_token`` / the env override;
      the generated-token file was not touched;
    - ``"disk"`` — read from a previously persisted generated-token file;
    - ``"generated"`` — freshly generated and persisted this call.
    """

    token: str
    source: str
    # The generated-token file path, or ``None`` when the token was configured.
    path: Path | None

    @property
    def is_generated_path(self) -> bool:
        """True when the active token came from the persisted generated-token
        file (freshly generated or read from disk) rather than config."""
        return self.source in ("disk", "generated")


def token_file_path(settings: Settings) -> Path:
    """Return ``<server.data_dir>/secrets/agent-token`` (not necessarily existing)."""
    return Path(settings.server.data_dir) / _SECRETS_SUBDIR / _TOKEN_FILENAME


def _read_existing(path: Path) -> str | None:
    try:
        token = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None
    return token or None


def _write_atomic(path: Path, token: str) -> None:
    """Write ``token`` to ``path`` atomically with owner-only perms where supported.

    A temp file in the same directory is written, ``0600`` is applied to it, then
    it is ``os.replace``-d over the target so a concurrent reader never sees a
    truncated file.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".agent-token-")
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(token + "\n")
        # Best-effort owner-only mode; harmless/no-op where unsupported.
        try:
            os.chmod(tmp_path, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:  # pragma: no cover - platform dependent
            pass
        os.replace(tmp_path, path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


@contextmanager
def _token_file_lock(path: Path):
    """Serialize first-time generation against concurrent CLI/server starts.

    The project deploys on Linux containers, where ``fcntl.flock`` is available.
    On non-POSIX platforms this degrades to no lock, while the atomic write still
    prevents truncated files.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(f".{path.name}.lock")
    with lock_path.open("w", encoding="utf-8") as lock_file:
        if fcntl is not None:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def resolve_agent_token(settings: Settings) -> AgentTokenResult:
    """Resolve the active server<->agent token (configured > disk > generated).

    Does NOT mutate ``settings``; callers apply the result. Reads/writes the
    persisted token file ONLY when no token is configured.
    """
    configured = (settings.agents.agent_token or "").strip()
    if configured:
        return AgentTokenResult(token=configured, source="configured", path=None)

    path = token_file_path(settings)
    with _token_file_lock(path):
        existing = _read_existing(path)
        if existing is not None:
            return AgentTokenResult(token=existing, source="disk", path=path)

        token = secrets.token_urlsafe(_GENERATED_TOKEN_NBYTES)
        _write_atomic(path, token)
        return AgentTokenResult(token=token, source="generated", path=path)


def ensure_runtime_agent_token(settings: Settings) -> AgentTokenResult:
    """Resolve the token and apply it to ``settings.agents.agent_token`` in place.

    Returns the :class:`AgentTokenResult` so the caller can log a join hint. When
    the token is read-from-disk or newly generated, machine auth becomes ON
    (``settings.agents.machine_auth_enabled`` is then true).
    """
    result = resolve_agent_token(settings)
    settings.agents.agent_token = result.token
    return result
