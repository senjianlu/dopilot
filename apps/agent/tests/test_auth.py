"""Single-token bearer auth on the surviving protected endpoint (egg deploy).

Phase 1.5 removed the server->agent run/status/logs-tail/cleanup HTTP endpoints;
the only auth-guarded agent endpoint left is ``POST /artifacts/scrapy/egg``.
"""

from __future__ import annotations

from pathlib import Path

from .conftest import FakeScrapyd, app_with_fake_scrapyd, client_for_app

TEST_TOKEN = "test-shared-token"
EGG_DATA = {"project": "demo", "version": "1"}
EGG_FILES = {"file": ("demo.egg", b"PK\x03\x04egg", "application/octet-stream")}


def _egg_client(workdir: Path, *, agent_token: str):
    app = app_with_fake_scrapyd(workdir, FakeScrapyd(), agent_token=agent_token)
    return client_for_app(app)


async def test_protected_requires_bearer_when_auth_on(workdir: Path) -> None:
    async with _egg_client(workdir, agent_token=TEST_TOKEN) as client:
        resp = await client.post(
            "/artifacts/scrapy/egg", data=EGG_DATA, files=EGG_FILES
        )
    assert resp.status_code == 401
    body = resp.json()
    assert body["code"] == "agent.unauthorized"
    assert body["message_key"] == "errors.unauthorized"
    assert body["detail"] == {}


async def test_protected_passes_auth_then_handler(workdir: Path) -> None:
    async with _egg_client(workdir, agent_token=TEST_TOKEN) as client:
        resp = await client.post(
            "/artifacts/scrapy/egg",
            data=EGG_DATA,
            files=EGG_FILES,
            headers={"Authorization": f"Bearer {TEST_TOKEN}"},
        )
    # Correct token => passes auth and reaches the handler (egg deploys).
    assert resp.status_code == 200
    assert resp.json()["project"] == "demo"


async def test_wrong_token_rejected(workdir: Path) -> None:
    async with _egg_client(workdir, agent_token=TEST_TOKEN) as client:
        resp = await client.post(
            "/artifacts/scrapy/egg",
            data=EGG_DATA,
            files=EGG_FILES,
            headers={"Authorization": "Bearer wrong-token"},
        )
    assert resp.status_code == 401


async def test_no_auth_mode_skips_token(workdir: Path) -> None:
    # Empty agent token => auth OFF; the endpoint reaches the handler directly.
    async with _egg_client(workdir, agent_token="") as client:
        resp = await client.post(
            "/artifacts/scrapy/egg", data=EGG_DATA, files=EGG_FILES
        )
    assert resp.status_code == 200
