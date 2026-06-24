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


async def _upload_egg(exec_client, *, extra: str = "") -> dict:
    r = await exec_client.post(
        "/api/v1/artifacts/scrapy/egg",
        files={"file": ("demo.egg", _egg(extra=extra), "application/octet-stream")},
        data={"project": "demo"},
    )
    assert r.status_code == 200, r.text
    return r.json()["artifact"]


async def test_new_artifact_is_not_archived(exec_client):
    artifact = await _upload_egg(exec_client)
    assert artifact["archived"] is False
    assert artifact["archived_at"] is None


async def test_archive_then_unarchive_is_idempotent(exec_client):
    artifact = await _upload_egg(exec_client)
    aid = artifact["id"]

    # Archive: derived flag + aware-UTC timestamp set.
    first = await exec_client.post(f"/api/v1/artifacts/{aid}/archive")
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["id"] == aid
    assert body["archived"] is True
    assert body["archived_at"] is not None
    # runnable is orthogonal to archived: still runnable.
    assert body["runnable"] is True
    stamp = body["archived_at"]

    # Re-archiving keeps the ORIGINAL timestamp (stable, idempotent 200).
    again = await exec_client.post(f"/api/v1/artifacts/{aid}/archive")
    assert again.status_code == 200
    assert again.json()["archived_at"] == stamp

    # Unarchive clears it; unarchiving again is a no-op 200.
    un = await exec_client.post(f"/api/v1/artifacts/{aid}/unarchive")
    assert un.status_code == 200
    assert un.json()["archived"] is False
    assert un.json()["archived_at"] is None
    un2 = await exec_client.post(f"/api/v1/artifacts/{aid}/unarchive")
    assert un2.status_code == 200
    assert un2.json()["archived"] is False


async def test_archive_unknown_artifact_404(exec_client):
    r = await exec_client.post("/api/v1/artifacts/nope/archive")
    assert r.status_code == 404
    assert r.json()["code"] == "artifact.not_found"


async def test_archived_state_visible_in_list(exec_client):
    artifact = await _upload_egg(exec_client)
    await exec_client.post(f"/api/v1/artifacts/{artifact['id']}/archive")
    rows = (await exec_client.get("/api/v1/artifacts")).json()["artifacts"]
    match = next(a for a in rows if a["id"] == artifact["id"])
    assert match["archived"] is True


async def test_archive_reserved_non_runnable_artifact(exec_client, seeder):
    # Archive is orthogonal to runnable: a reserved/non-runnable type can be
    # archived too.
    artifact = await seeder.build_artifact(
        artifact_type="docker_image", package_format="image", sha256="d" * 64
    )
    r = await exec_client.post(f"/api/v1/artifacts/{artifact.id}/archive")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["archived"] is True
    assert body["runnable"] is False


async def test_reupload_identical_bytes_preserves_archive_state(exec_client):
    artifact = await _upload_egg(exec_client)
    aid = artifact["id"]
    await exec_client.post(f"/api/v1/artifacts/{aid}/archive")

    # Same-content re-upload reuses the row and must NOT clear archived_at.
    reuploaded = await _upload_egg(exec_client)
    assert reuploaded["id"] == aid
    assert reuploaded["archived"] is True
    assert reuploaded["archived_at"] is not None


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
