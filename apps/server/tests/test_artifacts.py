"""Tests for the egg upload/deploy endpoint."""

from __future__ import annotations

from dopilot_server.clients.agent import AgentResponseError


async def test_upload_egg_deploys_and_records(exec_client, seeder, fake_agent):
    await seeder.healthy_node()
    files = {"file": ("demo_phase1.egg", b"PK\x03\x04egg-bytes", "application/octet-stream")}
    data = {"project": "demo", "version": "1700000000"}
    r = await exec_client.post(
        "/api/v1/artifacts/scrapy/egg", files=files, data=data
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["artifact"]["project"] == "demo"
    assert body["artifact"]["version"] == "1700000000"
    assert body["artifact"]["sha256"]
    assert body["artifact"]["size_bytes"] == len(b"PK\x03\x04egg-bytes")
    assert body["spiders"] == ["phase1"]
    assert body["agent_id"] == "agent-1"
    assert "deploy_egg" in fake_agent.call_names()


async def test_upload_egg_default_version(exec_client, seeder):
    await seeder.healthy_node()
    files = {"file": ("demo.egg", b"egg", "application/octet-stream")}
    r = await exec_client.post(
        "/api/v1/artifacts/scrapy/egg", files=files, data={"project": "demo"}
    )
    assert r.status_code == 200
    assert r.json()["artifact"]["version"]  # auto timestamp version


async def test_upload_egg_no_healthy_node_409(exec_client):
    files = {"file": ("demo.egg", b"egg", "application/octet-stream")}
    r = await exec_client.post(
        "/api/v1/artifacts/scrapy/egg", files=files, data={"project": "demo"}
    )
    assert r.status_code == 409
    assert r.json()["code"] == "execution.no_healthy_nodes"


async def test_upload_egg_agent_failure_502(exec_client, seeder, fake_agent):
    await seeder.healthy_node()
    fake_agent.raises["deploy_egg"] = AgentResponseError(
        "http://agent:6800", 502, {"code": "agent.addversion_failed"}
    )
    files = {"file": ("demo.egg", b"egg", "application/octet-stream")}
    r = await exec_client.post(
        "/api/v1/artifacts/scrapy/egg", files=files, data={"project": "demo"}
    )
    assert r.status_code == 502
    assert r.json()["code"] == "agent.addversion_failed"
