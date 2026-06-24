"""Built-in default artifact startup import tests."""

from __future__ import annotations

import hashlib
import importlib.util
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from dopilot_server.config.settings import Settings
from dopilot_server.errors import ApiError
from dopilot_server.models.execution import BuildArtifact
from dopilot_server.services.builtin_artifacts import seed_builtin_artifacts
from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[3]


def _settings(root: Path) -> Settings:
    return Settings.model_validate(
        {
            "database": {"url": "sqlite+aiosqlite:///:memory:"},
            "artifacts": {"root_dir": str(root)},
        }
    )


def _egg(*, spider: str = "clock", extra: str = "") -> bytes:
    buf = BytesIO()
    with ZipFile(buf, "w", compression=ZIP_DEFLATED) as zf:
        zf.writestr(
            "dopilot_clock-1.0.0.egg-info/PKG-INFO",
            "Name: dopilot_clock\nVersion: 1.0.0\n",
        )
        zf.writestr(
            "dopilot_clock/spiders/clock.py",
            (
                "import scrapy\n"
                "class ClockSpider(scrapy.Spider):\n"
                f"    name = {spider!r}\n"
                f"    extra = {extra!r}\n"
            ),
        )
    return buf.getvalue()


def _wheel(*, extra: str = "") -> bytes:
    buf = BytesIO()
    with ZipFile(buf, "w", compression=ZIP_DEFLATED) as zf:
        zf.writestr("main.py", f"print('dopilot demo {extra}')\n")
        zf.writestr(
            "dopilot_demo-0.1.0.dist-info/METADATA",
            "Metadata-Version: 2.1\nName: dopilot-demo\nVersion: 0.1.0\n",
        )
        zf.writestr(
            "dopilot_demo-0.1.0.dist-info/WHEEL",
            "Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        )
    return buf.getvalue()


async def _artifacts(session) -> list[BuildArtifact]:
    result = await session.execute(
        select(BuildArtifact).order_by(
            BuildArtifact.artifact_type, BuildArtifact.content_hash
        )
    )
    return list(result.scalars().all())


async def test_seed_builtin_artifacts_imports_scrapy_and_wheel(
    tmp_path, db_session
):
    builtin = tmp_path / "builtin"
    (builtin / "scrapy").mkdir(parents=True)
    (builtin / "python_wheel").mkdir(parents=True)
    (builtin / "scrapy" / "dopilot_clock.egg").write_bytes(_egg())
    (builtin / "python_wheel" / "dopilot_demo.whl").write_bytes(_wheel())

    settings = _settings(tmp_path / "artifacts")
    await seed_builtin_artifacts(db_session, settings, builtin_root=builtin)

    artifacts = await _artifacts(db_session)
    assert [a.artifact_type for a in artifacts] == ["python_wheel", "scrapy"]
    assert (tmp_path / "artifacts" / "scrapy").is_dir()
    assert (tmp_path / "artifacts" / "python_wheel").is_dir()


async def test_seed_builtin_artifacts_repeated_import_is_noop(
    tmp_path, db_session
):
    builtin = tmp_path / "builtin"
    (builtin / "scrapy").mkdir(parents=True)
    egg = _egg()
    sha = hashlib.sha256(egg).hexdigest()
    (builtin / "scrapy" / "dopilot_clock.egg").write_bytes(egg)

    settings = _settings(tmp_path / "artifacts")
    await seed_builtin_artifacts(db_session, settings, builtin_root=builtin)
    manifest = tmp_path / "artifacts" / "scrapy" / f"{sha}.json"
    first_manifest = manifest.read_text("utf-8")

    await seed_builtin_artifacts(db_session, settings, builtin_root=builtin)

    assert manifest.read_text("utf-8") == first_manifest
    artifacts = await _artifacts(db_session)
    assert len(artifacts) == 1


async def test_seed_builtin_artifacts_changed_bytes_create_new_hash(
    tmp_path, db_session
):
    builtin = tmp_path / "builtin" / "scrapy"
    builtin.mkdir(parents=True)
    path = builtin / "dopilot_clock.egg"
    settings = _settings(tmp_path / "artifacts")

    path.write_bytes(_egg(extra="one"))
    await seed_builtin_artifacts(db_session, settings, builtin_root=tmp_path / "builtin")
    path.write_bytes(_egg(extra="two"))
    await seed_builtin_artifacts(db_session, settings, builtin_root=tmp_path / "builtin")

    artifacts = await _artifacts(db_session)
    assert len(artifacts) == 2
    assert len({a.content_hash for a in artifacts}) == 2


async def test_seed_builtin_artifacts_preserves_same_hash_existing_row_metadata(
    tmp_path, db_session
):
    builtin = tmp_path / "builtin" / "python_wheel"
    builtin.mkdir(parents=True)
    wheel = _wheel()
    sha = hashlib.sha256(wheel).hexdigest()
    (builtin / "dopilot_demo.whl").write_bytes(wheel)

    existing = BuildArtifact(
        id="existing",
        artifact_type="python_wheel",
        package_format="wheel",
        name="user-visible-name",
        filename="user-upload.whl",
        content_hash=sha,
        size_bytes=999,
        artifact_metadata={
            "distribution": "user-dist",
            "version": "user-version",
            "fetch_path": f"/api/v1/artifacts/python_wheel/{sha}/wheel",
        },
    )
    db_session.add(existing)
    await db_session.commit()

    settings = _settings(tmp_path / "artifacts")
    await seed_builtin_artifacts(db_session, settings, builtin_root=tmp_path / "builtin")

    result = await db_session.execute(
        select(BuildArtifact).where(BuildArtifact.content_hash == sha)
    )
    row = result.scalar_one()
    assert row.name == "user-visible-name"
    assert row.filename == "user-upload.whl"
    assert row.size_bytes == 999
    assert (tmp_path / "artifacts" / "python_wheel" / f"{sha}.whl").is_file()


async def test_seed_builtin_artifacts_invalid_builtin_fails_startup(
    tmp_path, db_session
):
    builtin = tmp_path / "builtin" / "scrapy"
    builtin.mkdir(parents=True)
    (builtin / "broken.egg").write_bytes(b"not a zip")

    with pytest.raises(ApiError) as exc:
        await seed_builtin_artifacts(
            db_session,
            _settings(tmp_path / "artifacts"),
            builtin_root=tmp_path / "builtin",
        )

    assert exc.value.code == "artifact.invalid_egg"


def test_dopilot_clock_default_duration_and_runtime_logging_source():
    path = ROOT / "examples/scrapy_clock/dopilot_clock/spiders/clock.py"
    spec = importlib.util.spec_from_file_location("dopilot_clock_spider", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)

    source = path.read_text("utf-8")
    assert module.DEFAULT_DURATION_SECONDS == 45.0
    assert "key.startswith(\"DOPILOT_\")" in source
    assert "dopilot env:" in source
    assert "dopilot settings:" in source


def test_rebuilt_dopilot_demo_wheel_contains_runtime_env_logging():
    wheel = ROOT / "tests/fixtures/python_wheel_demo/dopilot_demo-0.1.0-py3-none-any.whl"
    with ZipFile(wheel) as zf:
        source = zf.read("main.py").decode("utf-8")

    assert "key.startswith(\"DOPILOT_\")" in source
    assert "dopilot-demo: dopilot env:" in source
