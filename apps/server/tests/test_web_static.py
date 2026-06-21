"""Bundled web UI serving tests (Next.js static export).

Next ``output: export`` with ``trailingSlash: true`` emits one HTML file per
route (``<route>/index.html``) plus hashed assets under ``_next/`` and a
top-level ``404.html``. The server resolves route paths to those files and must
NOT fall back to a single SPA ``index.html`` for unknown routes, and must never
rewrite ``/api/*`` to a web asset.
"""

from __future__ import annotations

from dopilot_server.app import create_app
from httpx import ASGITransport, AsyncClient


def _build_export(root) -> None:
    """Lay out a minimal Next static-export tree under ``root``."""
    root.mkdir()
    (root / "index.html").write_text("<!doctype html><div>home</div>")
    (root / "404.html").write_text("<!doctype html><div>not-found</div>")
    # Per-route HTML: /dashboard/ -> dashboard/index.html.
    dashboard = root / "dashboard"
    dashboard.mkdir()
    (dashboard / "index.html").write_text("<!doctype html><div>dashboard</div>")
    # Nested route with a query param: /tasks/detail/?id=... .
    detail = root / "tasks" / "detail"
    detail.mkdir(parents=True)
    (detail / "index.html").write_text("<!doctype html><div>task-detail</div>")
    # Hashed asset bundle.
    assets = root / "_next" / "static"
    assets.mkdir(parents=True)
    (assets / "app.js").write_text("console.log('ok')")


async def test_serves_exported_route_html_and_assets(tmp_path, monkeypatch):
    dist = tmp_path / "web"
    _build_export(dist)
    monkeypatch.setenv("DOPILOT_WEB_DIST", str(dist))

    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        index = await client.get("/")
        dashboard = await client.get("/dashboard/")
        # trailing-slash route resolves to <route>/index.html.
        detail = await client.get("/tasks/detail/?id=abc")
        asset = await client.get("/_next/static/app.js")

    assert index.status_code == 200
    assert "home" in index.text
    assert dashboard.status_code == 200
    assert "dashboard" in dashboard.text
    assert detail.status_code == 200
    assert "task-detail" in detail.text
    assert asset.status_code == 200
    assert asset.text == "console.log('ok')"


async def test_resolves_route_without_trailing_slash(tmp_path, monkeypatch):
    dist = tmp_path / "web"
    _build_export(dist)
    monkeypatch.setenv("DOPILOT_WEB_DIST", str(dist))

    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        # No trailing slash still resolves to the exported route HTML.
        dashboard = await client.get("/dashboard")

    assert dashboard.status_code == 200
    assert "dashboard" in dashboard.text


async def test_unknown_route_serves_exported_404(tmp_path, monkeypatch):
    dist = tmp_path / "web"
    _build_export(dist)
    monkeypatch.setenv("DOPILOT_WEB_DIST", str(dist))

    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        missing = await client.get("/does-not-exist/")

    # Exported 404.html (NOT an SPA always-200 index fallback).
    assert missing.status_code == 404
    assert "not-found" in missing.text
    assert "home" not in missing.text


async def test_api_404_is_not_rewritten_to_web(tmp_path, monkeypatch):
    dist = tmp_path / "web"
    _build_export(dist)
    monkeypatch.setenv("DOPILOT_WEB_DIST", str(dist))

    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/not-found")

    assert response.status_code == 404
    assert "home" not in response.text
    assert "not-found" not in response.text
