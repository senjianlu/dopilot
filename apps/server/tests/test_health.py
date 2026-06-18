"""Health endpoint tests: DB reachable / unreachable, always HTTP 200."""

from __future__ import annotations

import dopilot_server.api.v1.health as health_module


async def test_health_db_ok(client, monkeypatch):
    async def _ping_true(_session):
        return True

    monkeypatch.setattr(health_module.db_engine, "ping", _ping_true)
    resp = await client.get("/api/v1/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {
        "status": "ok",
        "service": "dopilot-server",
        "version": health_module.__version__,
        "database": "ok",
    }


async def test_health_db_down(client, monkeypatch):
    async def _ping_false(_session):
        return False

    monkeypatch.setattr(health_module.db_engine, "ping", _ping_false)
    resp = await client.get("/api/v1/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "degraded"
    assert body["database"] == "error"


async def test_health_db_raises_is_degraded(client, monkeypatch):
    async def _ping_raises(_session):
        raise RuntimeError("boom")

    # ping() itself swallows exceptions, but emulate a raising backend to be safe.
    async def _safe_ping(_session):
        try:
            return await _ping_raises(_session)
        except Exception:
            return False

    monkeypatch.setattr(health_module.db_engine, "ping", _safe_ping)
    resp = await client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.json()["database"] == "error"
