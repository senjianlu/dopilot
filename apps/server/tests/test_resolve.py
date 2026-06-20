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


def test_capability_mapping_covers_all_artifact_types():
    for atype in states.ARTIFACT_TYPES:
        assert atype in states.ARTIFACT_CAPABILITY
    assert states.ARTIFACT_CAPABILITY["scrapy"] == "scrapy"
    assert states.ARTIFACT_CAPABILITY["python_wheel"] == "python_wheel"
    assert states.ARTIFACT_CAPABILITY["docker_image"] == "docker_runtime"
