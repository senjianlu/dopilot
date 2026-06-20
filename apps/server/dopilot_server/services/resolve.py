"""Run resolution (phase 1.8): build artifact + template + overrides -> run.

A single resolver feeds every run path — direct build-artifact run, execution
template run, schedule trigger-now, and schedule timer firing — so the resolved
run snapshot is computed identically everywhere. Precedence (per the brief):

    schedule override > execution template default > build artifact default

The build artifact is NEVER overridable. The resolver returns the internal
:class:`ExecutionRunRequest` (carrying the resolved ``artifact_type`` +
type-specific ``params``) and the immutable snapshot frozen onto the task.
"""

from __future__ import annotations

from typing import Any

from dopilot_protocol import ExecutionRunRequest

from ..errors import ApiError
from ..models.execution import BuildArtifact
from . import artifacts as artifact_svc

# Override keys a schedule / direct run may set (build_artifact_id excluded).
OVERRIDE_KEYS = ("spider", "settings", "args", "node_strategy", "node_ids")


def _merge_str_map(*maps: Any) -> dict[str, str]:
    out: dict[str, str] = {}
    for m in maps:
        if isinstance(m, dict):
            out.update({str(k): str(v) for k, v in m.items()})
    return out


def sanitize_overrides(data: dict[str, Any] | None) -> dict[str, Any]:
    """Keep only allowed override keys; reject any build-artifact override."""
    data = data or {}
    if "build_artifact_id" in data:
        raise ApiError(
            400,
            "schedule.artifact_override_forbidden",
            "errors.artifactOverrideForbidden",
            {},
        )
    out: dict[str, Any] = {}
    for key in OVERRIDE_KEYS:
        if key not in data or data[key] is None:
            continue
        if key == "settings":
            out[key] = _merge_str_map(data[key])
        elif key == "args":
            out[key] = _merge_str_map(data[key])
        elif key == "node_ids":
            out[key] = [str(n) for n in (data[key] or [])]
        else:
            out[key] = str(data[key])
    return out


def resolve_run(
    *,
    build_artifact: BuildArtifact,
    template_defaults: dict[str, Any] | None = None,
    overrides: dict[str, Any] | None = None,
    name: str | None = None,
    execution_template_id: str | None = None,
) -> tuple[ExecutionRunRequest, dict[str, Any]]:
    """Resolve a run from a build artifact + template defaults + overrides.

    ``template_defaults`` carries the execution-template fields (spider /
    settings / args / node_strategy / node_ids / project / version); pass ``{}``
    for a direct ad-hoc artifact run. ``overrides`` is the sanitized schedule /
    direct-run override payload. Raises a 400 when the resolved scrapy run is
    missing a spider.
    """
    defaults = template_defaults or {}
    overrides = overrides or {}
    snap = artifact_svc.artifact_snapshot(build_artifact)
    artifact_type = build_artifact.artifact_type

    # project / version are resolved from the build artifact (not user-editable),
    # falling back to any template-stored value for legacy rows.
    project = snap.get("project") or defaults.get("project")
    version = snap.get("version") or defaults.get("version")
    spider = overrides.get("spider") or defaults.get("spider")
    settings = _merge_str_map(defaults.get("settings"), overrides.get("settings"))
    args = _merge_str_map(defaults.get("args"), overrides.get("args"))
    node_strategy = (
        overrides.get("node_strategy") or defaults.get("node_strategy") or "all"
    )
    node_ids = (
        overrides.get("node_ids")
        if "node_ids" in overrides
        else list(defaults.get("node_ids") or [])
    )

    if artifact_type == "scrapy" and not spider:
        raise ApiError(
            400,
            "execution.invalid_params",
            "errors.invalidParams",
            {"missing": ["spider"]},
        )

    target = name or f"{project}:{spider}"
    artifact_descriptor = {
        "sha256": build_artifact.content_hash,
        "hash": build_artifact.content_hash,
        "filename": build_artifact.filename,
        "project": project,
        "version": version,
        "size_bytes": build_artifact.size_bytes,
        "fetch_path": snap.get("fetch_path"),
    }
    params: dict[str, Any] = {
        "project": project,
        "spider": spider,
        "version": version,
        "settings": settings,
        "args": args,
        "artifact": artifact_descriptor,
    }
    snapshot: dict[str, Any] = {
        "build_artifact": snap,
        "execution_template_id": execution_template_id,
        "name": name,
        "artifact_type": artifact_type,
        "project": project,
        "version": version,
        "spider": spider,
        "settings": settings,
        "args": args,
        "node_strategy": node_strategy,
        "node_ids": list(node_ids or []),
        "overrides": dict(overrides),
    }
    request = ExecutionRunRequest(
        artifact_type=artifact_type,
        target=target,
        node_strategy=node_strategy,
        node_ids=list(node_ids or []),
        params=params,
    )
    return request, snapshot
