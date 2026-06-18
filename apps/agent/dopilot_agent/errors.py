"""Agent error type and the universal error envelope mapping.

``AgentError`` carries everything needed to render the frozen ``ErrorResponse``
envelope ``{code, message_key, detail}`` plus the HTTP status code. A global
exception handler (see :mod:`dopilot_agent.main`) turns it into that envelope.
"""

from __future__ import annotations

from typing import Any


class AgentError(Exception):
    """An error that maps directly to the ``ErrorResponse`` envelope.

    Attributes:
        status_code: HTTP status code to return.
        code: machine-readable error code (e.g. ``"agent.unauthorized"``).
        message_key: i18n key the web frontend resolves (e.g. ``"errors.unauthorized"``).
        detail: structured, machine-readable context.
    """

    def __init__(
        self,
        status_code: int,
        code: str,
        message_key: str,
        detail: dict[str, Any] | None = None,
    ) -> None:
        self.status_code = status_code
        self.code = code
        self.message_key = message_key
        self.detail: dict[str, Any] = detail if detail is not None else {}
        super().__init__(f"{code}: {message_key}")


def not_implemented(
    code: str,
    message_key: str = "errors.notImplemented",
    detail: dict[str, Any] | None = None,
) -> AgentError:
    """Build a 501 ``AgentError`` for endpoints that are phase-1+ stubs."""
    return AgentError(501, code, message_key, detail)


def not_found(
    code: str,
    message_key: str = "errors.notFound",
    detail: dict[str, Any] | None = None,
) -> AgentError:
    """Build a 404 ``AgentError`` (e.g. no state mapping for an attempt)."""
    return AgentError(404, code, message_key, detail)


def upstream_error(
    code: str,
    message_key: str = "errors.upstream",
    detail: dict[str, Any] | None = None,
) -> AgentError:
    """Build a 502 ``AgentError`` for a failed local-scrapyd call."""
    return AgentError(502, code, message_key, detail)
