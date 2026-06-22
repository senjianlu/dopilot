"""Auth endpoint tests: off mode, login, token lifecycle (expired/revoked),
and the phase 2.2.2 static admin API token."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest_asyncio
from dopilot_server.auth.tokens import hash_token
from dopilot_server.config.settings import Settings
from dopilot_server.models.auth_token import AuthToken
from httpx import AsyncClient

from .conftest import _build_client, make_settings

STATIC_API_TOKEN = "static-admin-api-token-0123456789"


def _settings_with_api_token(token: str | None) -> Settings:
    """Auth-ON settings carrying a static ``admin_api_token``."""
    settings = make_settings(auth_on=True)
    settings.auth.admin_api_token = token
    return settings


@pytest_asyncio.fixture
async def client_api_token(db_session) -> AsyncIterator[AsyncClient]:
    """Auth-ON client whose settings carry a non-empty static admin API token."""
    settings = _settings_with_api_token(STATIC_API_TOKEN)
    async with _build_client(settings, db_session) as ac:
        yield ac


@pytest_asyncio.fixture
async def client_empty_api_token(db_session) -> AsyncIterator[AsyncClient]:
    """Auth-ON client whose static admin API token is the empty string."""
    settings = _settings_with_api_token("")
    async with _build_client(settings, db_session) as ac:
        yield ac


async def test_me_auth_off(client):
    resp = await client.get("/api/v1/auth/me")
    assert resp.status_code == 200
    body = resp.json()
    assert body["mode"] == "off"
    assert body["authenticated"] is True
    assert body["username"] == "admin"
    assert body["expires_at"] is None


async def test_login_off_returns_null_token(client):
    resp = await client.post(
        "/api/v1/auth/login", json={"username": "x", "password": "y"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["mode"] == "off"
    assert body["access_token"] is None


async def test_login_wrong_credentials(client_auth_on):
    resp = await client_auth_on.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "wrong"},
    )
    assert resp.status_code == 401
    body = resp.json()
    assert body["code"] == "auth.invalid_credentials"
    assert body["message_key"] == "errors.invalidCredentials"
    assert body["detail"] == {}


async def test_login_success_and_me(client_auth_on):
    resp = await client_auth_on.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "secret"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["mode"] == "on"
    token = body["access_token"]
    assert token
    assert body["token_type"] == "bearer"

    me = await client_auth_on.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert me.status_code == 200
    assert me.json()["authenticated"] is True
    assert me.json()["mode"] == "on"


async def test_me_without_bearer(client_auth_on):
    resp = await client_auth_on.get("/api/v1/auth/me")
    assert resp.status_code == 401
    assert resp.json()["code"] == "auth.unauthorized"


async def test_me_garbage_token(client_auth_on):
    resp = await client_auth_on.get(
        "/api/v1/auth/me",
        headers={"Authorization": "Bearer not-a-real-token"},
    )
    assert resp.status_code == 401


async def test_me_expired_token(client_auth_on, db_session, settings_auth_on):
    token = "expired-plaintext-token"
    db_session.add(
        AuthToken(
            token_hash=hash_token(
                settings_auth_on.auth.token_secret, token
            ),
            expires_at=datetime.now(UTC) - timedelta(minutes=5),
            revoked=False,
        )
    )
    await db_session.commit()
    resp = await client_auth_on.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 401


# --- phase 2.2.2: static admin API token direct auth ------------------------


async def test_static_token_authenticates_admin(client_api_token):
    # The configured static admin API token authenticates as admin with no
    # expiry, no login round-trip.
    resp = await client_api_token.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {STATIC_API_TOKEN}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["mode"] == "on"
    assert body["authenticated"] is True
    assert body["username"] == "admin"
    assert body["expires_at"] is None


async def test_wrong_static_token_rejected(client_api_token):
    resp = await client_api_token.get(
        "/api/v1/auth/me",
        headers={"Authorization": "Bearer not-the-static-token-xxxxxxxx"},
    )
    assert resp.status_code == 401
    assert resp.json()["code"] == "auth.unauthorized"


async def test_empty_configured_token_does_not_match_empty_bearer(
    client_empty_api_token,
):
    # An empty configured admin_api_token must never authenticate, even though
    # hmac.compare_digest("", "") is True — the non-empty guards block it.
    no_bearer = await client_empty_api_token.get("/api/v1/auth/me")
    assert no_bearer.status_code == 401
    empty_bearer = await client_empty_api_token.get(
        "/api/v1/auth/me", headers={"Authorization": "Bearer "}
    )
    assert empty_bearer.status_code == 401


async def test_static_token_does_not_break_login_tokens(
    client_api_token, db_session, settings_auth_on
):
    # A login-issued opaque token still authenticates when a static token is
    # also configured (the DB path is unchanged). token_secret signs it.
    token = "valid-opaque-token"
    db_session.add(
        AuthToken(
            token_hash=hash_token(settings_auth_on.auth.token_secret, token),
            expires_at=datetime.now(UTC) + timedelta(minutes=30),
            revoked=False,
        )
    )
    await db_session.commit()
    resp = await client_api_token.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200
    assert resp.json()["mode"] == "on"


async def test_me_revoked_token(client_auth_on, db_session, settings_auth_on):
    token = "revoked-plaintext-token"
    db_session.add(
        AuthToken(
            token_hash=hash_token(
                settings_auth_on.auth.token_secret, token
            ),
            expires_at=datetime.now(UTC) + timedelta(minutes=30),
            revoked=True,
        )
    )
    await db_session.commit()
    resp = await client_auth_on.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 401
