"""Build-artifact endpoint tests (phase 1.8): Scrapy egg upload -> build artifact."""

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


async def test_upload_egg_creates_build_artifact(exec_client):
    content = _egg()
    files = {"file": ("demo_phase1.egg", content, "application/octet-stream")}
    r = await exec_client.post(
        "/api/v1/artifacts/scrapy/egg", files=files, data={"project": "demo"}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    artifact = body["artifact"]
    assert artifact["artifact_type"] == "scrapy"
    assert artifact["package_format"] == "egg"
    assert artifact["project"] == "demo"
    assert artifact["version"].startswith("sha256-")
    assert artifact["content_hash"]
    assert artifact["size_bytes"] == len(content)
    assert artifact["spiders"] == ["phase1"]
    assert artifact["runnable"] is True
    assert body["spiders"] == ["phase1"]

    # the canonical build-artifact list now surfaces it
    listed = await exec_client.get("/api/v1/artifacts")
    rows = listed.json()["artifacts"]
    assert any(a["id"] == artifact["id"] for a in rows)

    download = await exec_client.get(
        f"/api/v1/artifacts/scrapy/{artifact['content_hash']}/egg"
    )
    assert download.status_code == 200
    assert download.content == content


async def test_upload_same_content_dedups_build_artifact(exec_client):
    files = {"file": ("demo.egg", _egg(), "application/octet-stream")}
    first = await exec_client.post(
        "/api/v1/artifacts/scrapy/egg", files=files, data={"project": "demo"}
    )
    second = await exec_client.post(
        "/api/v1/artifacts/scrapy/egg",
        files={"file": ("demo.egg", _egg(), "application/octet-stream")},
        data={"project": "demo"},
    )
    assert first.json()["artifact"]["id"] == second.json()["artifact"]["id"]
    listed = await exec_client.get("/api/v1/artifacts")
    rows = listed.json()["artifacts"]
    assert len([a for a in rows if a["content_hash"]]) == 1


async def test_upload_different_hash_two_artifacts(exec_client):
    for extra in ("a", "b"):
        r = await exec_client.post(
            "/api/v1/artifacts/scrapy/egg",
            files={"file": ("demo.egg", _egg(extra=extra), "application/octet-stream")},
            data={"project": "demo"},
        )
        assert r.status_code == 200, r.text

    listed = await exec_client.get("/api/v1/artifacts")
    artifacts = listed.json()["artifacts"]
    assert len(artifacts) == 2
    assert len({a["content_hash"] for a in artifacts}) == 2


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
