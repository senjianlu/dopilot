"""Application error type and the universal error envelope.

Every API failure surfaces as an ``ApiError`` which the global exception
handler in :mod:`dopilot_server.app` renders as the frozen error envelope
``{code, message_key, detail}`` (see :class:`dopilot_protocol.ErrorResponse`).
"""

from __future__ import annotations

from typing import Any


class ApiError(Exception):
    """Domain error mapped to the ``{code, message_key, detail}`` envelope.

    Attributes:
        status_code: HTTP status to return.
        code: machine-readable error code (e.g. ``"auth.unauthorized"``).
        message_key: i18n key the web layer resolves (e.g. ``"errors.unauthorized"``).
        detail: extra structured context, JSON-serializable.
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
        self.detail: dict[str, Any] = detail or {}
        super().__init__(f"{code}: {message_key}")


def not_implemented(
    code: str,
    message_key: str,
    detail: dict[str, Any] | None = None,
) -> ApiError:
    """Build a 501 ``ApiError`` for phase-deferred features."""
    return ApiError(501, code, message_key, detail or {})
