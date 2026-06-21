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

from dopilot_protocol import (
    ExecutionRunRequest,
    ScrapyCommandError,
    parse_scrapy_command,
)

from ..errors import ApiError
from ..models.execution import BuildArtifact
from . import artifacts as artifact_svc
from . import states

# Override keys a schedule may set (build_artifact_id excluded). Phase 1.8.1:
# command-first — a ``command`` override fully replaces the template command;
# legacy ``spider`` / ``settings`` / ``args`` keys are no longer accepted.
OVERRIDE_KEYS = ("command", "node_strategy", "node_ids")


def validate_command(command: str | None):
    """Validate a ``scrapy crawl`` command, raising a structured 400 if invalid.

    Returns the parsed command so callers can reuse the derived spider.
    """
    try:
        return parse_scrapy_command(command)
    except ScrapyCommandError as exc:
        raise ApiError(400, exc.code, exc.message_key, exc.detail) from exc


def validate_wheel_command(command: str | None) -> str:
    """Validate a Python-wheel shell command: only requires non-empty (phase 2b).

    A wheel ``command`` is a free-form shell command (serialized to the agent as
    ``shell_command``); it deliberately does NOT go through the Scrapy parser.
    Returns the stripped command. Raises a 400 if blank.
    """
    stripped = str(command or "").strip()
    if not stripped:
        raise ApiError(
            400,
            "template.invalid_params",
            "errors.invalidParams",
            {"missing": ["command"]},
        )
    return stripped


def validate_command_by_type(command: str | None, artifact_type: str) -> None:
    """Type-aware command grammar check (scrapy parser vs wheel non-empty)."""
    if artifact_type == states.ARTIFACT_SCRAPY:
        validate_command(command)
    else:
        validate_wheel_command(command)


def ensure_spider_in_artifact(spider: str, spiders: Any) -> None:
    """Reject a command whose spider is not exposed by the build artifact.

    The artifact metadata/snapshot ``spiders`` list is authoritative for what the
    egg can run, so a typo'd spider (``scrapy crawl typo_spider``) is caught here
    instead of failing only at the agent. Enforced whenever the artifact lists
    spiders (every uploaded Scrapy egg does); an empty/absent list cannot be
    validated against and is left to the agent.
    """
    allowed = [str(s) for s in (spiders or [])]
    if allowed and spider not in allowed:
        raise ApiError(
            400,
            "command.unknown_spider",
            "errors.unknownSpider",
            {"spider": spider, "spiders": allowed},
        )


def validate_command_for_artifact(command: str | None, spiders: Any) -> None:
    """Validate command grammar AND that its spider belongs to the artifact."""
    parsed = validate_command(command)
    ensure_spider_in_artifact(parsed.spider, spiders)


def sanitize_overrides(
    data: dict[str, Any] | None, *, artifact_type: str = "scrapy"
) -> dict[str, Any]:
    """Keep only allowed override keys; reject any build-artifact override.

    A ``command`` override is validated here too so an invalid override is
    rejected at create/update time, not only at firing time. Validation is
    TYPE-AWARE (phase 2b): a ``scrapy`` command override is parsed by the Scrapy
    grammar; a ``python_wheel`` command override only needs to be non-empty (it
    is a free-form shell command). ``artifact_type`` defaults to ``scrapy`` so
    legacy callers keep the original behavior.
    """
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
        if key == "node_ids":
            out[key] = [str(n) for n in (data[key] or [])]
        elif key == "command":
            command = str(data[key]).strip()
            # A blank command override is treated as absent: the run inherits the
            # template command, so it is neither validated nor persisted here.
            if not command:
                continue
            validate_command_by_type(command, artifact_type)
            out[key] = command
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

    ``template_defaults`` carries the execution-template fields (command /
    node_strategy / node_ids / project / version). ``overrides`` is the sanitized
    schedule override payload. Command-first precedence: a ``command`` override
    FULLY replaces the template command (no arg/setting merge). Raises a 400 when
    the resolved scrapy run has no valid command.
    """
    defaults = template_defaults or {}
    overrides = overrides or {}
    snap = artifact_svc.artifact_snapshot(build_artifact)
    artifact_type = build_artifact.artifact_type

    # project / version are resolved from the build artifact (not user-editable),
    # falling back to any template-stored value for legacy rows.
    project = snap.get("project") or defaults.get("project")
    version = snap.get("version") or defaults.get("version")
    # command-first: an override command fully replaces the template command.
    command = overrides.get("command") or defaults.get("command")
    node_strategy = (
        overrides.get("node_strategy") or defaults.get("node_strategy") or "all"
    )
    node_ids = (
        overrides.get("node_ids")
        if "node_ids" in overrides
        else list(defaults.get("node_ids") or [])
    )

    artifact_descriptor = {
        "sha256": build_artifact.content_hash,
        "hash": build_artifact.content_hash,
        "filename": build_artifact.filename,
        "project": project,
        "version": version,
        "size_bytes": build_artifact.size_bytes,
        "fetch_path": snap.get("fetch_path"),
    }

    spider: str | None = None
    if artifact_type == states.ARTIFACT_PYTHON_WHEEL:
        # Python wheel (phase 2b): the command is a free-form shell command,
        # serialized to the agent payload as ``shell_command``. No Scrapy parse,
        # no spider. ``env`` / ``working_dir`` are reserved for the agent runner
        # (packet 2b-2); the server currently emits an empty ``env`` and a null
        # ``working_dir`` (per-execution workspace) — agent install/exec is NOT
        # done here.
        shell_command = validate_wheel_command(command)
        artifact_descriptor["distribution"] = snap.get("distribution")
        target = name or build_artifact.name or "python_wheel"
        params = {
            "command": shell_command,
            "shell_command": shell_command,
            "artifact": artifact_descriptor,
            "env": {},
            "working_dir": None,
            "version": version,
        }
        snapshot = {
            "build_artifact": snap,
            "execution_template_id": execution_template_id,
            "name": name,
            "artifact_type": artifact_type,
            "version": version,
            "command": shell_command,
            "shell_command": shell_command,
            "env": {},
            "working_dir": None,
            "node_strategy": node_strategy,
            "node_ids": list(node_ids or []),
            "overrides": dict(overrides),
        }
    else:
        # Scrapy: validate + parse the authoritative command. The spider is
        # DERIVED for Task.spider/target convenience; the command stays the
        # execution model.
        try:
            parsed = parse_scrapy_command(command)
        except ScrapyCommandError as exc:
            raise ApiError(400, exc.code, exc.message_key, exc.detail) from exc
        # The command spider must belong to the bound artifact. This covers
        # schedule command overrides at run/trigger resolution, before dispatch.
        ensure_spider_in_artifact(parsed.spider, snap.get("spiders"))
        spider = parsed.spider
        target = name or f"{project}:{spider}"
        params = {
            "command": command,
            "project": project,
            "version": version,
            "spider": spider,
            "artifact": artifact_descriptor,
        }
        snapshot = {
            "build_artifact": snap,
            "execution_template_id": execution_template_id,
            "name": name,
            "artifact_type": artifact_type,
            "project": project,
            "version": version,
            "command": command,
            "spider": spider,
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
