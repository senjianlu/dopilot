"""Bundled web UI serving tests."""

from __future__ import annotations

from dopilot_server.app import create_app
from httpx import ASGITransport, AsyncClient


async def test_serves_bundled_web_index_and_spa_routes(tmp_path, monkeypatch):
    dist = tmp_path / "web"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><div id=\"app\"></div>")
    assets = dist / "assets"
    assets.mkdir()
    (assets / "app.js").write_text("console.log('ok')")
    monkeypatch.setenv("DOPILOT_WEB_DIST", str(dist))

    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        index = await client.get("/")
        route = await client.get("/tasks/abc")
        asset = await client.get("/assets/app.js")

    assert index.status_code == 200
    assert "<div id=\"app\"></div>" in index.text
    assert route.status_code == 200
    assert "<div id=\"app\"></div>" in route.text
    assert asset.status_code == 200
    assert asset.text == "console.log('ok')"


async def test_api_404_is_not_rewritten_to_spa(tmp_path, monkeypatch):
    dist = tmp_path / "web"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><div id=\"app\"></div>")
    monkeypatch.setenv("DOPILOT_WEB_DIST", str(dist))

    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/not-found")

    assert response.status_code == 404
    assert "<div id=\"app\"></div>" not in response.text
