"""Auth endpoint tests: off mode, login, token lifecycle (expired/revoked)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from dopilot_server.auth.tokens import hash_token
from dopilot_server.models.auth_token import AuthToken


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
