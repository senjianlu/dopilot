"""Contract tests for the surviving agent egg-deploy endpoint.

Phase 1.5 removed the agent ``/logs/tail`` + cleanup HTTP endpoints (now Redis
log publishing + a ``cleanup_logs`` command), so only egg deploy remains here.
"""

from __future__ import annotations

from pathlib import Path

from .conftest import FakeScrapyd, app_with_fake_scrapyd, client_for_app


async def test_egg_deploy_returns_spiders(workdir: Path) -> None:
    fake = FakeScrapyd()
    fake.spiders = ["phase1", "another"]
    app = app_with_fake_scrapyd(workdir, fake)
    async with client_for_app(app) as client:
        resp = await client.post(
            "/artifacts/scrapy/egg",
            data={"project": "demo", "version": "1"},
            files={"file": ("demo.egg", b"PK\x03\x04egg-bytes", "application/octet-stream")},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["project"] == "demo"
    assert body["version"] == "1"
    assert body["spiders"] == ["phase1", "another"]


async def test_egg_deploy_failure_envelope(workdir: Path) -> None:
    fake = FakeScrapyd()
    fake.fail_addversion = True
    app = app_with_fake_scrapyd(workdir, fake)
    async with client_for_app(app) as client:
        resp = await client.post(
            "/artifacts/scrapy/egg",
            data={"project": "demo", "version": "1"},
            files={"file": ("demo.egg", b"bad", "application/octet-stream")},
        )
    assert resp.status_code == 502
    assert resp.json()["code"] == "agent.addversion_failed"
