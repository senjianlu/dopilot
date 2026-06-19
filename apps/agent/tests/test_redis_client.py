"""Agent Redis client construction tests."""

from __future__ import annotations

from dopilot_agent.redis import client as redis_client


def test_from_url_disables_socket_read_timeout(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_from_url(url: str, **kwargs: object) -> object:
        captured["url"] = url
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(redis_client.aioredis, "from_url", fake_from_url)

    redis_client.RedisStreams.from_url("redis://redis:6379/0")

    assert captured["decode_responses"] is False
    assert captured["socket_timeout"] is None
