"""Filesystem-backed Python-wheel artifact store (phase 2b).

Mirrors :mod:`scrapy_store` for ``.whl`` build artifacts. A wheel is a zip whose
``*.dist-info/METADATA`` carries the distribution ``Name`` / ``Version``. The
store only needs the bytes (the agent installs them in packet 2b-2); it parses
the distribution/version best-effort for display and rejects anything that is not
a ``.whl`` (wrong extension) or not a valid zip.
"""

from __future__ import annotations

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
class WheelArtifactManifest:
    sha256: str
    filename: str
    distribution: str
    version: str
    size_bytes: int
    uploaded_at: str
    valid: bool = True


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _short_version(sha256: str) -> str:
    return f"sha256-{sha256[:12]}"


def _metadata_name_version(zf: zipfile.ZipFile) -> tuple[str | None, str | None]:
    """Best-effort ``(Name, Version)`` from a wheel ``*.dist-info/METADATA``."""
    for name in zf.namelist():
        normalized = name.replace("\\", "/")
        if normalized.endswith(".dist-info/METADATA"):
            try:
                metadata = Parser().parsestr(
                    zf.read(name).decode("utf-8", "replace")
                )
            except Exception:  # noqa: BLE001
                return None, None
            dist = metadata.get("Name")
            version = metadata.get("Version")
            return (
                dist.strip() if dist else None,
                version.strip() if version else None,
            )
    return None, None


def validate_wheel(*, filename: str, content: bytes) -> WheelArtifactManifest:
    """Validate a ``.whl`` upload, returning its manifest.

    Rejects a non-``.whl`` filename (``artifact.invalid_wheel``) and a body that
    is not a valid zip (wheels are zips). Distribution/version are parsed
    best-effort from ``*.dist-info/METADATA`` and fall back to the wheel filename
    stem / a content-derived version.
    """
    if not filename.lower().endswith(".whl"):
        raise ApiError(
            400,
            "artifact.invalid_wheel",
            "errors.invalidWheel",
            {"reason": "not_whl", "filename": filename},
        )
    sha256 = hashlib.sha256(content).hexdigest()
    try:
        with zipfile.ZipFile(BytesIO(content)) as zf:
            bad_member = zf.testzip()
            if bad_member is not None:
                raise ApiError(
                    400,
                    "artifact.invalid_wheel",
                    "errors.invalidWheel",
                    {"member": bad_member},
                )
            dist, version = _metadata_name_version(zf)
    except zipfile.BadZipFile as exc:
        raise ApiError(
            400,
            "artifact.invalid_wheel",
            "errors.invalidWheel",
            {"reason": "not_zip"},
        ) from exc

    # Wheel filename convention: ``{distribution}-{version}-...whl``.
    stem = Path(filename).stem
    parts = stem.split("-")
    distribution = dist or (parts[0] if parts and parts[0] else stem)
    version = version or (parts[1] if len(parts) > 1 else _short_version(sha256))

    return WheelArtifactManifest(
        sha256=sha256,
        filename=filename,
        distribution=distribution,
        version=version,
        size_bytes=len(content),
        uploaded_at=_now(),
    )


class WheelArtifactStore:
    def __init__(self, root_dir: str | os.PathLike[str]) -> None:
        self._dir = Path(root_dir) / "python_wheel"

    def wheel_path(self, sha256: str) -> Path:
        return self._dir / f"{sha256}.whl"

    def manifest_path(self, sha256: str) -> Path:
        return self._dir / f"{sha256}.json"

    def save(self, *, filename: str, content: bytes) -> WheelArtifactManifest:
        manifest = validate_wheel(filename=filename, content=content)
        self._dir.mkdir(parents=True, exist_ok=True)

        wheel_tmp = self.wheel_path(manifest.sha256).with_suffix(
            f".whl.{os.getpid()}.tmp"
        )
        manifest_tmp = self.manifest_path(manifest.sha256).with_suffix(
            f".json.{os.getpid()}.tmp"
        )
        wheel_tmp.write_bytes(content)
        manifest_tmp.write_text(
            json.dumps(asdict(manifest), ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
        os.replace(wheel_tmp, self.wheel_path(manifest.sha256))
        os.replace(manifest_tmp, self.manifest_path(manifest.sha256))
        return manifest

    def list(self) -> list[WheelArtifactManifest]:
        if not self._dir.is_dir():
            return []
        manifests: list[WheelArtifactManifest] = []
        for path in sorted(self._dir.glob("*.json")):
            try:
                manifests.append(
                    WheelArtifactManifest(**json.loads(path.read_text("utf-8")))
                )
            except (OSError, TypeError, ValueError, json.JSONDecodeError):
                continue
        return sorted(manifests, key=lambda item: item.uploaded_at, reverse=True)

    def get(self, sha256: str) -> WheelArtifactManifest:
        path = self.manifest_path(sha256)
        if not path.is_file():
            raise ApiError(
                404,
                "artifact.not_found",
                "errors.artifactNotFound",
                {"sha256": sha256},
            )
        return WheelArtifactManifest(**json.loads(path.read_text("utf-8")))
