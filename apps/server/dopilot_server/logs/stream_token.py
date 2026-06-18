"""Short-lived, stateless SSE connect tokens.

``EventSource`` cannot send an ``Authorization`` header, so when web auth is ON
the browser POSTs (with its bearer) to exchange for a short-lived stream token
and passes it as a query param on the SSE URL. The token is a signed
``payload.signature`` (HMAC-SHA256 over the payload, keyed by the auth
``token_secret``); it is only checked at CONNECT time. Stateless: no DB row.
"""

from __future__ import annotations

import base64
import hmac
import json
import time
from hashlib import sha256


def _b64u_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64u_decode(text: str) -> bytes:
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


def _sign(secret: str, payload_b64: str) -> str:
    sig = hmac.new(
        secret.encode("utf-8"), payload_b64.encode("ascii"), sha256
    ).digest()
    return _b64u_encode(sig)


def issue_stream_token(
    secret: str, execution_id: str, ttl_seconds: int, *, now: float | None = None
) -> tuple[str, int]:
    """Return ``(token, expires_at_epoch)`` bound to ``execution_id``."""
    issued = int(now if now is not None else time.time())
    exp = issued + max(1, ttl_seconds)
    payload = {"e": execution_id, "exp": exp}
    payload_b64 = _b64u_encode(json.dumps(payload, separators=(",", ":")).encode())
    token = f"{payload_b64}.{_sign(secret, payload_b64)}"
    return token, exp


def verify_stream_token(
    secret: str, token: str, execution_id: str, *, now: float | None = None
) -> bool:
    """True iff ``token`` is well-formed, unexpired, and bound to ``execution_id``."""
    try:
        payload_b64, sig = token.split(".", 1)
    except ValueError:
        return False
    if not hmac.compare_digest(sig, _sign(secret, payload_b64)):
        return False
    try:
        payload = json.loads(_b64u_decode(payload_b64))
    except Exception:  # noqa: BLE001
        return False
    if payload.get("e") != execution_id:
        return False
    current = now if now is not None else time.time()
    return bool(payload.get("exp", 0) > current)
