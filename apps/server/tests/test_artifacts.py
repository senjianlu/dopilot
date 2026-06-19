"""Tests for the server-side Scrapy egg artifact store endpoints."""

from __future__ import annotations

from io import BytesIO
from zipfile import ZipFile


def _egg(*, spider: str = "phase1", extra: str = "") -> bytes:
    buf = BytesIO()
    with ZipFile(buf, "w") as zf:
        zf.writestr("demo-1.0.0.egg-info/PKG-INFO", "Name: demo\nVersion: 1.0.0\n")
        zf.writestr(
            "demo/spiders/phase1.py",
            (
                "import scrapy\n"
                "class Phase1Spider(scrapy.Spider):\n"
                f"    name = {spider!r}\n"
                f"    custom = {extra!r}\n"
            ),
        )
    return buf.getvalue()


async def test_upload_egg_validates_and_stores_manifest(exec_client):
    content = _egg()
    files = {"file": ("demo_phase1.egg", content, "application/octet-stream")}
    r = await exec_client.post(
        "/api/v1/artifacts/scrapy/egg", files=files, data={"project": "demo"}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    artifact = body["artifact"]
    assert artifact["project"] == "demo"
    assert artifact["version"].startswith("sha256-")
    assert artifact["sha256"]
    assert artifact["size_bytes"] == len(content)
    assert artifact["spiders"] == ["phase1"]
    assert artifact["valid"] is True
    assert body["spiders"] == ["phase1"]
    assert body["agent_id"] is None
    assert body["endpoint"] is None

    download = await exec_client.get(
        f"/api/v1/artifacts/scrapy/{artifact['sha256']}/egg"
    )
    assert download.status_code == 200
    assert download.content == content


async def test_upload_same_filename_different_hash_can_coexist(exec_client):
    for extra in ("a", "b"):
        r = await exec_client.post(
            "/api/v1/artifacts/scrapy/egg",
            files={"file": ("demo.egg", _egg(extra=extra), "application/octet-stream")},
            data={"project": "demo"},
        )
        assert r.status_code == 200, r.text

    listed = await exec_client.get("/api/v1/artifacts/scrapy")
    assert listed.status_code == 200
    artifacts = listed.json()["artifacts"]
    assert len(artifacts) == 2
    assert {a["filename"] for a in artifacts} == {"demo.egg"}
    assert len({a["sha256"] for a in artifacts}) == 2


async def test_upload_rejects_invalid_zip(exec_client):
    r = await exec_client.post(
        "/api/v1/artifacts/scrapy/egg",
        files={"file": ("bad.egg", b"not a zip", "application/octet-stream")},
        data={"project": "demo"},
    )
    assert r.status_code == 400
    assert r.json()["code"] == "artifact.invalid_egg"


async def test_upload_rejects_egg_without_spiders(exec_client):
    buf = BytesIO()
    with ZipFile(buf, "w") as zf:
        zf.writestr("demo-1.0.0.egg-info/PKG-INFO", "Name: demo\n")
        zf.writestr("demo/__init__.py", "")
    r = await exec_client.post(
        "/api/v1/artifacts/scrapy/egg",
        files={"file": ("empty.egg", buf.getvalue(), "application/octet-stream")},
        data={"project": "demo"},
    )
    assert r.status_code == 400
    assert r.json()["code"] == "artifact.no_spiders"
