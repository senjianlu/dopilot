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


def validate_wheel_path(
    *, filename: str, path: str | os.PathLike[str], sha256: str, size_bytes: int
) -> WheelArtifactManifest:
    """Path-based variant of :func:`validate_wheel` (resource caps, B5).

    Validates an already-streamed temp file WITHOUT reading it into memory: the
    ``sha256`` / ``size_bytes`` were computed during streaming, and the zip
    structure + metadata are inspected directly from the file on disk. Rejects a
    non-``.whl`` filename and a body that is not a valid zip, mirroring
    :func:`validate_wheel`.
    """
    if not filename.lower().endswith(".whl"):
        raise ApiError(
            400,
            "artifact.invalid_wheel",
            "errors.invalidWheel",
            {"reason": "not_whl", "filename": filename},
        )
    try:
        with zipfile.ZipFile(path) as zf:
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

    stem = Path(filename).stem
    parts = stem.split("-")
    distribution = dist or (parts[0] if parts and parts[0] else stem)
    version = version or (parts[1] if len(parts) > 1 else _short_version(sha256))

    return WheelArtifactManifest(
        sha256=sha256,
        filename=filename,
        distribution=distribution,
        version=version,
        size_bytes=size_bytes,
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

    def save_from_path(
        self,
        *,
        filename: str,
        tmp_path: str | os.PathLike[str],
        sha256: str,
        size_bytes: int,
    ) -> WheelArtifactManifest:
        """Publish an already-streamed temp file as the stored wheel (B5).

        Validates the temp file in place, writes the manifest, then atomically
        ``os.replace``s the temp body into the store (same volume as the staging
        dir). On validation failure the temp file is left for the caller's
        cleanup. Blocking — call via ``asyncio.to_thread``.
        """
        manifest = validate_wheel_path(
            filename=filename, path=tmp_path, sha256=sha256, size_bytes=size_bytes
        )
        self._dir.mkdir(parents=True, exist_ok=True)
        # See scrapy_store.save_from_path: a pre-existing sha is byte-identical, so
        # a re-upload owns nothing new and must never be rolled back (R-02).
        pre_existed = self.wheel_path(sha256).exists()
        manifest_tmp = self.manifest_path(sha256).with_suffix(
            f".json.{os.getpid()}.tmp"
        )
        manifest_tmp.write_text(
            json.dumps(asdict(manifest), ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
        # Publish body then manifest; only a newly-created artifact is rolled back
        # on a mid-publish failure (a pre-existing one stays valid — identical body,
        # atomically-untouched original manifest).
        os.replace(tmp_path, self.wheel_path(sha256))
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
        """Delete a published wheel body + manifest (resource caps, R-04 rollback).

        Used to roll back a publish whose DB upsert/commit failed, so a body is
        never left on disk uncounted by the aggregate quota. Best-effort."""
        for path in (self.wheel_path(sha256), self.manifest_path(sha256)):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass

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
