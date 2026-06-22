"""Single-token bearer auth dependency for protected agent endpoints.

When the agent's ``[agent].agent_token`` is empty, machine auth is OFF and every
request is allowed (the server simply doesn't send a token). When it is
non-empty, the incoming ``Authorization: Bearer <token>`` header must match
exactly, otherwise a 401 envelope is raised. This is the same single
server<->agent token the agent presents on heartbeat / artifact fetches
(phase 2.2.3).
"""

from __future__ import annotations

import secrets

from fastapi import Depends, Header

from ..config.loader import get_settings
from ..config.settings import Settings
from ..errors import AgentError


def require_agent_token(
    authorization: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> None:
    """Enforce the server<->agent token when configured."""
    token = settings.agent.agent_token
    if not token:
        # Auth OFF: allow.
        return

    expected = f"Bearer {token}"
    if authorization is None or not secrets.compare_digest(authorization, expected):
        raise AgentError(401, "agent.unauthorized", "errors.unauthorized", {})
