"""Run-resolution tests (phase 1.8): precedence + build-artifact immutability."""

from __future__ import annotations

import pytest
from dopilot_server.errors import ApiError
from dopilot_server.models.execution import BuildArtifact
from dopilot_server.services import resolve, states


def _artifact(artifact_type: str = "scrapy") -> BuildArtifact:
    return BuildArtifact(
        id="a1",
        artifact_type=artifact_type,
        package_format=states.ARTIFACT_PACKAGE_FORMAT[artifact_type],
        name="demo",
        filename="demo.egg",
        content_hash="h" * 64,
        size_bytes=10,
        artifact_metadata={
            "project": "demo",
            "version": "v1",
            "spiders": ["s1", "s2"],
            "fetch_path": "/api/v1/artifacts/scrapy/" + "h" * 64 + "/egg",
        },
    )


def _wheel_artifact() -> BuildArtifact:
    return BuildArtifact(
        id="w1",
        artifact_type=states.ARTIFACT_PYTHON_WHEEL,
        package_format=states.ARTIFACT_PACKAGE_FORMAT[
            states.ARTIFACT_PYTHON_WHEEL
        ],
        name="dopilot-demo",
        filename="dopilot_demo-0.1.0-py3-none-any.whl",
        content_hash="h" * 64,
        size_bytes=10,
        artifact_metadata={
            "distribution": "dopilot-demo",
            "version": "0.1.0",
            "fetch_path": "/api/v1/artifacts/python_wheel/" + "h" * 64 + "/wheel",
        },
    )


def test_resolve_uses_artifact_defaults_for_project_version():
    req, snap = resolve.resolve_run(
        build_artifact=_artifact(),
        template_defaults={"command": "scrapy crawl s1"},
        overrides={},
    )
    assert req.artifact_type == "scrapy"
    assert req.params["project"] == "demo"
    assert req.params["version"] == "v1"
    assert req.params["command"] == "scrapy crawl s1"
    # spider is DERIVED from the parsed command for Task.spider convenience.
    assert req.params["spider"] == "s1"
    assert snap["build_artifact"]["id"] == "a1"
    # the artifact context travels in params for the agent.
    assert req.params["artifact"]["project"] == "demo"


def test_resolve_command_override_fully_replaces_template():
    req, snap = resolve.resolve_run(
        build_artifact=_artifact(),
        template_defaults={
            "command": "scrapy crawl s1 -a a=t -s X=1",
            "node_strategy": "all",
            "node_ids": [],
        },
        overrides={
            "command": "scrapy crawl s2 -s X=2",
            "node_strategy": "selected",
            "node_ids": ["n1"],
        },
    )
    # override command fully replaces template command (no arg/setting merge).
    assert req.params["command"] == "scrapy crawl s2 -s X=2"
    assert req.params["spider"] == "s2"
    assert req.node_strategy == "selected"
    assert req.node_ids == ["n1"]
    assert snap["overrides"]["command"] == "scrapy crawl s2 -s X=2"
    assert snap["command"] == "scrapy crawl s2 -s X=2"


def test_resolve_scrapy_missing_command_raises():
    with pytest.raises(ApiError) as exc:
        resolve.resolve_run(
            build_artifact=_artifact(), template_defaults={}, overrides={}
        )
    assert exc.value.code == "command.invalid"


def test_resolve_scrapy_invalid_command_raises():
    with pytest.raises(ApiError) as exc:
        resolve.resolve_run(
            build_artifact=_artifact(),
            template_defaults={"command": "rm -rf /"},
            overrides={},
        )
    assert exc.value.code == "command.invalid"


def test_resolve_rejects_command_spider_not_in_artifact():
    # Artifact exposes s1/s2; a typo'd override spider is rejected before dispatch.
    with pytest.raises(ApiError) as exc:
        resolve.resolve_run(
            build_artifact=_artifact(),
            template_defaults={"command": "scrapy crawl s1"},
            overrides={"command": "scrapy crawl typo_spider"},
        )
    assert exc.value.code == "command.unknown_spider"


def test_resolve_blank_command_override_inherits_template_command():
    # A blank override is dropped by sanitize, so the run inherits the template.
    overrides = resolve.sanitize_overrides({"command": "   "})
    assert "command" not in overrides
    req, snap = resolve.resolve_run(
        build_artifact=_artifact(),
        template_defaults={"command": "scrapy crawl s1"},
        overrides=overrides,
    )
    assert req.params["command"] == "scrapy crawl s1"
    assert snap["command"] == "scrapy crawl s1"
    assert "command" not in snap["overrides"]


def test_sanitize_overrides_blank_command_not_persisted():
    assert resolve.sanitize_overrides({"command": ""}) == {}
    assert resolve.sanitize_overrides({"command": "  \t "}) == {}


def test_sanitize_overrides_forbids_build_artifact_id():
    with pytest.raises(ApiError) as exc:
        resolve.sanitize_overrides({"build_artifact_id": "x"})
    assert exc.value.code == "schedule.artifact_override_forbidden"


def test_sanitize_overrides_keeps_only_allowed_keys():
    out = resolve.sanitize_overrides(
        {
            "command": "scrapy crawl s2",
            "node_strategy": "random",
            "node_ids": [1, 2],
            "name": "ignored-by-sanitize",
        }
    )
    assert out == {
        "command": "scrapy crawl s2",
        "node_strategy": "random",
        "node_ids": ["1", "2"],
    }


def test_sanitize_overrides_rejects_invalid_command():
    with pytest.raises(ApiError) as exc:
        resolve.sanitize_overrides({"command": "scrapy crawl x; rm -rf /"})
    assert exc.value.code == "command.invalid"


def test_resolve_python_wheel_shell_command_branch():
    # A wheel command is a free-form shell command (no scrapy parse, no spider).
    req, snap = resolve.resolve_run(
        build_artifact=_wheel_artifact(),
        template_defaults={"command": "python -m main", "node_strategy": "all"},
        overrides={},
        name="demo-run",
    )
    assert req.artifact_type == "python_wheel"
    assert req.params["shell_command"] == "python -m main"
    assert req.params["command"] == "python -m main"
    assert req.params["env"] == {}
    assert req.params["working_dir"] is None
    assert "spider" not in req.params
    assert req.params["artifact"]["fetch_path"].endswith("/wheel")
    assert req.params["artifact"]["distribution"] == "dopilot-demo"
    assert req.target == "demo-run"
    # snapshot carries the shell command + reserved env/working_dir.
    assert snap["artifact_type"] == "python_wheel"
    assert snap["shell_command"] == "python -m main"
    assert snap["env"] == {}
    assert snap["working_dir"] is None


def test_resolve_python_wheel_empty_command_raises():
    with pytest.raises(ApiError) as exc:
        resolve.resolve_run(
            build_artifact=_wheel_artifact(),
            template_defaults={"command": "   "},
            overrides={},
        )
    assert exc.value.code == "template.invalid_params"


def test_resolve_python_wheel_command_override_is_free_form():
    # An arbitrary shell command override is honored verbatim (NOT scrapy-parsed).
    overrides = resolve.sanitize_overrides(
        {"command": "python -m other --flag"}, artifact_type="python_wheel"
    )
    req, snap = resolve.resolve_run(
        build_artifact=_wheel_artifact(),
        template_defaults={"command": "python -m main"},
        overrides=overrides,
    )
    assert req.params["shell_command"] == "python -m other --flag"
    assert snap["overrides"]["command"] == "python -m other --flag"


def test_sanitize_overrides_wheel_command_not_scrapy_parsed():
    # The same command that the scrapy parser rejects is allowed for a wheel.
    out = resolve.sanitize_overrides(
        {"command": "python -m main | tee out.log"},
        artifact_type="python_wheel",
    )
    assert out["command"] == "python -m main | tee out.log"
    # ...but the scrapy default still rejects it.
    with pytest.raises(ApiError):
        resolve.sanitize_overrides({"command": "python -m main | tee out.log"})


def test_capability_mapping_covers_all_artifact_types():
    for atype in states.ARTIFACT_TYPES:
        assert atype in states.ARTIFACT_CAPABILITY
    assert states.ARTIFACT_CAPABILITY["scrapy"] == "scrapy"
    # Phase 2b: python_wheel runs on ``script``-capable nodes.
    assert states.ARTIFACT_CAPABILITY["python_wheel"] == "script"
    assert states.ARTIFACT_CAPABILITY["docker_image"] == "docker_runtime"


def test_python_wheel_is_runnable():
    assert states.ARTIFACT_PYTHON_WHEEL in states.RUNNABLE_ARTIFACT_TYPES
    assert states.ARTIFACT_SCRAPY in states.RUNNABLE_ARTIFACT_TYPES
    # docker is still reserved (not runnable in phase 2b).
    assert states.ARTIFACT_DOCKER_IMAGE not in states.RUNNABLE_ARTIFACT_TYPES
