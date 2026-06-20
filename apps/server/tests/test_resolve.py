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
        template_defaults={"spider": "s1"},
        overrides={},
    )
    assert req.artifact_type == "scrapy"
    assert req.params["project"] == "demo"
    assert req.params["version"] == "v1"
    assert req.params["spider"] == "s1"
    assert snap["build_artifact"]["id"] == "a1"


def test_resolve_precedence_override_beats_template():
    req, snap = resolve.resolve_run(
        build_artifact=_artifact(),
        template_defaults={
            "spider": "s1",
            "settings": {"X": "1", "Y": "1"},
            "args": {"a": "t"},
            "node_strategy": "all",
            "node_ids": [],
        },
        overrides={
            "spider": "s2",
            "settings": {"X": "2"},
            "node_strategy": "selected",
            "node_ids": ["n1"],
        },
    )
    # override wins for spider / node strategy / node ids; settings merge with
    # override on top of template default.
    assert req.params["spider"] == "s2"
    assert req.params["settings"] == {"X": "2", "Y": "1"}
    assert req.params["args"] == {"a": "t"}
    assert req.node_strategy == "selected"
    assert req.node_ids == ["n1"]
    assert snap["overrides"]["spider"] == "s2"


def test_resolve_scrapy_missing_spider_raises():
    with pytest.raises(ApiError) as exc:
        resolve.resolve_run(
            build_artifact=_artifact(), template_defaults={}, overrides={}
        )
    assert exc.value.code == "execution.invalid_params"


def test_sanitize_overrides_forbids_build_artifact_id():
    with pytest.raises(ApiError) as exc:
        resolve.sanitize_overrides({"build_artifact_id": "x"})
    assert exc.value.code == "schedule.artifact_override_forbidden"


def test_sanitize_overrides_keeps_only_allowed_keys():
    out = resolve.sanitize_overrides(
        {
            "spider": "s2",
            "settings": {"A": 1},
            "args": {"B": 2},
            "node_strategy": "random",
            "node_ids": [1, 2],
            "name": "ignored-by-sanitize",
        }
    )
    assert out == {
        "spider": "s2",
        "settings": {"A": "1"},
        "args": {"B": "2"},
        "node_strategy": "random",
        "node_ids": ["1", "2"],
    }


def test_capability_mapping_covers_all_artifact_types():
    for atype in states.ARTIFACT_TYPES:
        assert atype in states.ARTIFACT_CAPABILITY
    assert states.ARTIFACT_CAPABILITY["scrapy"] == "scrapy"
    assert states.ARTIFACT_CAPABILITY["python_wheel"] == "python_wheel"
    assert states.ARTIFACT_CAPABILITY["docker_image"] == "docker_runtime"
