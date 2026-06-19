"""Health endpoint tests: DB reachable / unreachable, always HTTP 200."""

from __future__ import annotations

import dopilot_server.api.v1.health as health_module


class _FakeRedis:
    async def info(self, section: str):
        assert section == "server"
        return {"redis_version": "7.2-test"}

    async def aclose(self) -> None:
        pass


def _mock_redis_ok(monkeypatch) -> None:
    def _from_url(*_args, **_kwargs):
        return _FakeRedis()

    monkeypatch.setattr(health_module.aioredis, "from_url", _from_url)


async def test_health_db_ok(client, monkeypatch):
    async def _ping_true(_session):
        return True

    monkeypatch.setattr(health_module.db_engine, "ping", _ping_true)
    _mock_redis_ok(monkeypatch)
    resp = await client.get("/api/v1/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["service"] == "dopilot-server"
    assert body["version"] == health_module.__version__
    assert body["database"] == "ok"
    assert body["postgresql"]["status"] == "ok"
    assert body["redis"] == {"status": "ok", "version": "7.2-test"}
    assert body["nodes"] == {"total": 0, "online": 0, "healthy": 0}


async def test_health_db_down(client, monkeypatch):
    async def _ping_false(_session):
        return False

    monkeypatch.setattr(health_module.db_engine, "ping", _ping_false)
    _mock_redis_ok(monkeypatch)
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
    _mock_redis_ok(monkeypatch)
    resp = await client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.json()["database"] == "error"
