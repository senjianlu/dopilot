"""Filesystem-backed Scrapy egg artifact store."""

from __future__ import annotations

import ast
import hashlib
import json
import os
import zipfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from email.parser import Parser
from io import BytesIO
from pathlib import Path

from ..errors import ApiError


@dataclass
class ScrapyArtifactManifest:
    sha256: str
    filename: str
    project: str
    version: str
    spiders: list[str]
    size_bytes: int
    uploaded_at: str
    valid: bool = True


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _short_version(sha256: str) -> str:
    return f"sha256-{sha256[:12]}"


def _metadata_name(zf: zipfile.ZipFile) -> str | None:
    for name in zf.namelist():
        if name.endswith(("EGG-INFO/PKG-INFO", ".dist-info/METADATA")):
            try:
                metadata = Parser().parsestr(zf.read(name).decode("utf-8", "replace"))
            except Exception:  # noqa: BLE001
                return None
            value = metadata.get("Name")
            return value.strip() if value else None
    return None


def _parse_spider_names(source: str) -> list[str]:
    try:
        module = ast.parse(source)
    except SyntaxError:
        return []
    names: list[str] = []
    for node in ast.walk(module):
        if not isinstance(node, ast.ClassDef):
            continue
        for item in node.body:
            if not isinstance(item, ast.Assign):
                continue
            if not any(isinstance(t, ast.Name) and t.id == "name" for t in item.targets):
                continue
            if isinstance(item.value, ast.Constant) and isinstance(item.value.value, str):
                names.append(item.value.value)
    return names


def _discover_spiders(zf: zipfile.ZipFile) -> list[str]:
    spiders: set[str] = set()
    for name in zf.namelist():
        normalized = name.replace("\\", "/")
        if "/spiders/" not in normalized or not normalized.endswith(".py"):
            continue
        if normalized.endswith("/__init__.py"):
            continue
        try:
            source = zf.read(name).decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            continue
        spiders.update(_parse_spider_names(source))
    return sorted(spiders)


def validate_egg(
    *, filename: str, content: bytes, project_hint: str | None = None
) -> ScrapyArtifactManifest:
    sha256 = hashlib.sha256(content).hexdigest()
    try:
        with zipfile.ZipFile(BytesIO(content)) as zf:
            bad_member = zf.testzip()
            if bad_member is not None:
                raise ApiError(
                    400,
                    "artifact.invalid_egg",
                    "errors.invalidEgg",
                    {"member": bad_member},
                )
            project = project_hint or _metadata_name(zf) or Path(filename).stem
            spiders = _discover_spiders(zf)
    except zipfile.BadZipFile as exc:
        raise ApiError(
            400,
            "artifact.invalid_egg",
            "errors.invalidEgg",
            {"reason": "not_zip"},
        ) from exc

    if not spiders:
        raise ApiError(
            400,
            "artifact.no_spiders",
            "errors.noSpiders",
            {"filename": filename},
        )

    return ScrapyArtifactManifest(
        sha256=sha256,
        filename=filename,
        project=project,
        version=_short_version(sha256),
        spiders=spiders,
        size_bytes=len(content),
        uploaded_at=_now(),
    )


def validate_egg_path(
    *,
    filename: str,
    path: str | os.PathLike[str],
    sha256: str,
    size_bytes: int,
    project_hint: str | None = None,
) -> ScrapyArtifactManifest:
    """Path-based variant of :func:`validate_egg` (resource caps, B5).

    Validates an already-streamed temp file WITHOUT reading it into memory: the
    ``sha256`` / ``size_bytes`` came from streaming; the zip structure, project
    name and spider discovery are inspected directly from the file on disk.
    """
    try:
        with zipfile.ZipFile(path) as zf:
            bad_member = zf.testzip()
            if bad_member is not None:
                raise ApiError(
                    400,
                    "artifact.invalid_egg",
                    "errors.invalidEgg",
                    {"member": bad_member},
                )
            project = project_hint or _metadata_name(zf) or Path(filename).stem
            spiders = _discover_spiders(zf)
    except zipfile.BadZipFile as exc:
        raise ApiError(
            400,
            "artifact.invalid_egg",
            "errors.invalidEgg",
            {"reason": "not_zip"},
        ) from exc

    if not spiders:
        raise ApiError(
            400,
            "artifact.no_spiders",
            "errors.noSpiders",
            {"filename": filename},
        )

    return ScrapyArtifactManifest(
        sha256=sha256,
        filename=filename,
        project=project,
        version=_short_version(sha256),
        spiders=spiders,
        size_bytes=size_bytes,
        uploaded_at=_now(),
    )


class ScrapyArtifactStore:
    def __init__(self, root_dir: str | os.PathLike[str]) -> None:
        self._dir = Path(root_dir) / "scrapy"

    def egg_path(self, sha256: str) -> Path:
        return self._dir / f"{sha256}.egg"

    def manifest_path(self, sha256: str) -> Path:
        return self._dir / f"{sha256}.json"

    def save(
        self, *, filename: str, content: bytes, project_hint: str | None = None
    ) -> ScrapyArtifactManifest:
        manifest = validate_egg(
            filename=filename, content=content, project_hint=project_hint
        )
        self._dir.mkdir(parents=True, exist_ok=True)

        egg_tmp = self.egg_path(manifest.sha256).with_suffix(
            f".egg.{os.getpid()}.tmp"
        )
        manifest_tmp = self.manifest_path(manifest.sha256).with_suffix(
            f".json.{os.getpid()}.tmp"
        )
        egg_tmp.write_bytes(content)
        manifest_tmp.write_text(
            json.dumps(asdict(manifest), ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
        os.replace(egg_tmp, self.egg_path(manifest.sha256))
        os.replace(manifest_tmp, self.manifest_path(manifest.sha256))
        return manifest

    def save_from_path(
        self,
        *,
        filename: str,
        tmp_path: str | os.PathLike[str],
        sha256: str,
        size_bytes: int,
        project_hint: str | None = None,
    ) -> ScrapyArtifactManifest:
        """Publish an already-streamed temp file as the stored egg (B5).

        Validates the temp file in place, writes the manifest, then atomically
        ``os.replace``s the temp body into the store (same volume as staging). On
        validation failure the temp file is left for the caller's cleanup.
        Blocking — call via ``asyncio.to_thread``.
        """
        manifest = validate_egg_path(
            filename=filename,
            path=tmp_path,
            sha256=sha256,
            size_bytes=size_bytes,
            project_hint=project_hint,
        )
        self._dir.mkdir(parents=True, exist_ok=True)
        # A body with this sha already on disk is byte-identical (sha == content),
        # so a re-upload owns NOTHING new: on a mid-publish failure we must NOT
        # delete the pre-existing artifact another commit references (resource
        # caps, R-02). Only a brand-new sha is rolled back by the store.
        pre_existed = self.egg_path(sha256).exists()
        manifest_tmp = self.manifest_path(sha256).with_suffix(
            f".json.{os.getpid()}.tmp"
        )
        manifest_tmp.write_text(
            json.dumps(asdict(manifest), ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
        # Publish body then manifest. os.replace is atomic: if the manifest replace
        # fails the ORIGINAL manifest is untouched, and the body was overwritten
        # with identical bytes — so a pre-existing artifact stays valid. Only a
        # newly-created artifact is rolled back so a partial publish never leaves
        # an uncounted egg on disk.
        os.replace(tmp_path, self.egg_path(sha256))
        try:
            os.replace(manifest_tmp, self.manifest_path(sha256))
        except OSError:
            if not pre_existed:
                self.remove_stored(sha256)
            try:
                manifest_tmp.unlink(missing_ok=True)
            except OSError:
                pass
            raise
        return manifest

    def remove_stored(self, sha256: str) -> None:
        """Delete a published egg body + manifest (resource caps, R-04 rollback).

        Used to roll back a publish whose DB upsert/commit failed, so a body is
        never left on disk uncounted by the aggregate quota. Best-effort."""
        for path in (self.egg_path(sha256), self.manifest_path(sha256)):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass

    def list(self) -> list[ScrapyArtifactManifest]:
        if not self._dir.is_dir():
            return []
        manifests: list[ScrapyArtifactManifest] = []
        for path in sorted(self._dir.glob("*.json")):
            try:
                manifests.append(
                    ScrapyArtifactManifest(**json.loads(path.read_text("utf-8")))
                )
            except (OSError, TypeError, ValueError, json.JSONDecodeError):
                continue
        return sorted(manifests, key=lambda item: item.uploaded_at, reverse=True)

    def get(self, sha256: str) -> ScrapyArtifactManifest:
        path = self.manifest_path(sha256)
        if not path.is_file():
            raise ApiError(
                404,
                "artifact.not_found",
                "errors.artifactNotFound",
                {"sha256": sha256},
            )
        return ScrapyArtifactManifest(**json.loads(path.read_text("utf-8")))
