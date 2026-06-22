"""Agent -> server auth dependency (phase 1.5; single token in phase 2.2.3).

Authenticates agent-initiated calls (heartbeat) with the single server<->agent
``[agents].agent_token``. This is a SEPARATE secret from the web admin token;
it is the SAME secret used by the server -> agent egg-deploy path (the split
tokens were collapsed into one in phase 2.2.3).

Follows the repo's "config-present-or-off" idiom: when ``agent_token`` is unset,
machine auth is OFF (dev convenience); when set, a matching Bearer token is
required.
"""

from __future__ import annotations

import secrets

from fastapi import Depends, Request

from ..config.loader import get_settings
from ..config.settings import Settings
from ..errors import ApiError


def _extract_bearer(request: Request) -> str | None:
    header = request.headers.get("authorization")
    if not header:
        return None
    scheme, _, value = header.partition(" ")
    if scheme.lower() != "bearer" or not value:
        return None
    return value.strip()


async def require_server_token(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> None:
    """Reject the request with 401 when machine auth is ON and invalid."""
    if not settings.agents.machine_auth_enabled:
        return
    token = _extract_bearer(request)
    expected = settings.agents.agent_token or ""
    if not token or not secrets.compare_digest(token, expected):
        raise ApiError(401, "auth.unauthorized", "errors.unauthorized", {})
