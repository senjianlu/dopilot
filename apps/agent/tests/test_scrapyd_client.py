"""Unit tests for ScrapydClient request encoding + error handling."""

from __future__ import annotations

from urllib.parse import parse_qs

import httpx
import pytest
from dopilot_agent.scrapyd.client import ScrapydClient, ScrapydError


def _client(handler) -> ScrapydClient:
    return ScrapydClient(
        base_url="http://scrapyd.test", transport=httpx.MockTransport(handler)
    )


async def test_schedule_encodes_version_settings_args() -> None:
    captured: dict[str, list[str]] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured
        captured = parse_qs(request.content.decode("utf-8"))
        return httpx.Response(200, json={"status": "ok", "jobid": "j1"})

    client = _client(handler)
    job_id = await client.schedule(
        "demo",
        "phase1",
        version="2",
        settings={"LOG_LEVEL": "DEBUG", "CONCURRENT_REQUESTS": "4"},
        args={"start_url": "http://x"},
    )

    assert job_id == "j1"
    assert captured["project"] == ["demo"]
    assert captured["spider"] == ["phase1"]
    assert captured["_version"] == ["2"]
    # settings become repeated setting=KEY=VALUE form fields.
    assert sorted(captured["setting"]) == [
        "CONCURRENT_REQUESTS=4",
        "LOG_LEVEL=DEBUG",
    ]
    assert captured["start_url"] == ["http://x"]


async def test_schedule_omits_version_when_none() -> None:
    captured: dict[str, list[str]] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured
        captured = parse_qs(request.content.decode("utf-8"))
        return httpx.Response(200, json={"status": "ok", "jobid": "j1"})

    client = _client(handler)
    await client.schedule("demo", "phase1")
    assert "_version" not in captured


async def test_non_ok_status_raises_scrapyd_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "error", "message": "nope"})

    client = _client(handler)
    with pytest.raises(ScrapydError) as exc:
        await client.schedule("demo", "phase1")
    assert "nope" in str(exc.value)


async def test_schedule_without_jobid_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "ok"})

    client = _client(handler)
    with pytest.raises(ScrapydError):
        await client.schedule("demo", "phase1")


async def test_transport_error_raises_scrapyd_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    client = _client(handler)
    with pytest.raises(ScrapydError):
        await client.listjobs("demo")


async def test_listjobs_returns_body() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "status": "ok",
                "pending": [],
                "running": [{"id": "j1"}],
                "finished": [],
            },
        )

    client = _client(handler)
    body = await client.listjobs("demo")
    assert body["running"] == [{"id": "j1"}]


async def test_addversion_posts_egg_and_returns_spiders() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["content_type"] = request.headers.get("content-type", "")
        seen["has_egg"] = b"egg-bytes" in request.content
        return httpx.Response(200, json={"status": "ok", "spiders": ["phase1"]})

    client = _client(handler)
    body = await client.addversion("demo", "1", b"egg-bytes")
    assert body["spiders"] == ["phase1"]
    assert "multipart/form-data" in seen["content_type"]
    assert seen["has_egg"] is True
