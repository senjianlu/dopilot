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
