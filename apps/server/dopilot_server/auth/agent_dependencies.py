"""Agent -> server auth dependency (phase 1.5).

Authenticates agent-initiated calls (heartbeat) with the dedicated
``[agents].server_shared_token``. This is a SEPARATE secret from the web admin
token and from the server -> agent ``[agent_auth].shared_token`` (egg deploy):
auth is split in phase 1.5 (decision #12).

Follows the repo's "config-present-or-off" idiom: when ``server_shared_token``
is unset, inbound agent auth is OFF (dev convenience); when set, a matching
Bearer token is required.
"""

from __future__ import annotations

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
    """Reject the request with 401 when inbound agent auth is ON and invalid."""
    if not settings.agents.inbound_auth_enabled:
        return
    token = _extract_bearer(request)
    if not token or token != settings.agents.server_shared_token:
        raise ApiError(401, "auth.unauthorized", "errors.unauthorized", {})
