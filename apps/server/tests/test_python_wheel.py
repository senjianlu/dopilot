"""Python-wheel dispatch tests (phase 2b packet 1): server/protocol/web-facing.

Covers the wheel artifact store/API (upload/download/dedupe/reject), type-aware
template validation, dynamic ``template_view.artifact_type``, and the
``PythonWheelExecutor`` (script-capable node selection, outbox payload shape, log
row creation). The agent runner (download/install/subprocess) is packet 2b-2 and
is NOT exercised here — the server never runs Python.
"""

from __future__ import annotations

import sys
from pathlib import Path

from dopilot_protocol import AgentCommand, command_stream, from_stream_entry

_FIXTURES = Path(__file__).resolve().parents[3] / "tests" / "fixtures"
sys.path.insert(0, str(_FIXTURES / "python_wheel_demo"))
from build_wheel import build_demo_wheel  # noqa: E402


async def _commands(redis, agent_id="agent-1") -> list[AgentCommand]:
    entries = await redis.entries(command_stream(agent_id))
    return [from_stream_entry(AgentCommand, f) for _id, f in entries]


async def _upload_wheel(exec_client, *, filename="dopilot_demo-0.1.0-py3-none-any.whl"):
    content = build_demo_wheel()
    files = {"file": (filename, content, "application/octet-stream")}
    r = await exec_client.post("/api/v1/artifacts/python_wheel/wheel", files=files)
    return content, r


# ---------------------------------------------------------------------------
# artifact store / API
# ---------------------------------------------------------------------------


async def test_upload_wheel_creates_runnable_build_artifact(exec_client):
    content, r = await _upload_wheel(exec_client)
    assert r.status_code == 200, r.text
    artifact = r.json()["artifact"]
    assert artifact["artifact_type"] == "python_wheel"
    assert artifact["package_format"] == "wheel"
    assert artifact["distribution"] == "dopilot-demo"
    assert artifact["version"] == "0.1.0"
    assert artifact["content_hash"]
    assert artifact["size_bytes"] == len(content)
    assert artifact["runnable"] is True
    assert artifact["fetch_path"].endswith("/wheel")

    listed = await exec_client.get("/api/v1/artifacts")
    rows = listed.json()["artifacts"]
    assert any(a["id"] == artifact["id"] for a in rows)


async def test_download_wheel_byte_identical(exec_client):
    content, r = await _upload_wheel(exec_client)
    sha = r.json()["artifact"]["content_hash"]
    download = await exec_client.get(f"/api/v1/artifacts/python_wheel/{sha}/wheel")
    assert download.status_code == 200
    assert download.content == content


async def test_upload_same_wheel_dedupes(exec_client):
    _content, first = await _upload_wheel(exec_client)
    _content2, second = await _upload_wheel(exec_client)
    assert first.json()["artifact"]["id"] == second.json()["artifact"]["id"]
    listed = await exec_client.get("/api/v1/artifacts")
    wheels = [
        a
        for a in listed.json()["artifacts"]
        if a["artifact_type"] == "python_wheel"
    ]
    assert len(wheels) == 1


async def test_upload_non_wheel_rejected(exec_client):
    files = {"file": ("notawheel.txt", b"hello", "text/plain")}
    r = await exec_client.post("/api/v1/artifacts/python_wheel/wheel", files=files)
    assert r.status_code == 400
    assert r.json()["code"] == "artifact.invalid_wheel"


async def test_upload_corrupt_wheel_rejected(exec_client):
    files = {"file": ("broken.whl", b"not a zip", "application/octet-stream")}
    r = await exec_client.post("/api/v1/artifacts/python_wheel/wheel", files=files)
    assert r.status_code == 400
    assert r.json()["code"] == "artifact.invalid_wheel"


# ---------------------------------------------------------------------------
# type-aware template validation + dynamic artifact_type
# ---------------------------------------------------------------------------


async def test_wheel_template_accepts_arbitrary_shell_command(exec_client, seeder):
    artifact = await seeder.build_artifact(
        artifact_type="python_wheel", package_format="wheel", sha256="d" * 64
    )
    r = await exec_client.post(
        "/api/v1/templates",
        json={
            "name": "wheel-t",
            "build_artifact_id": artifact.id,
            "command": "python -m main && echo done",
            "node_strategy": "all",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # dynamic artifact_type resolved from the bound artifact (not hardcoded).
    assert body["artifact_type"] == "python_wheel"
    assert body["command"] == "python -m main && echo done"


async def test_wheel_template_rejects_empty_command(exec_client, seeder):
    artifact = await seeder.build_artifact(
        artifact_type="python_wheel", package_format="wheel", sha256="d" * 64
    )
    r = await exec_client.post(
        "/api/v1/templates",
        json={
            "name": "wheel-t",
            "build_artifact_id": artifact.id,
            "command": "   ",
            "node_strategy": "all",
        },
    )
    assert r.status_code == 400
    assert r.json()["code"] == "template.invalid_params"


async def test_scrapy_template_still_uses_scrapy_parser(exec_client, seeder):
    # A non-scrapy command must still be rejected for a scrapy artifact.
    artifact = await seeder.build_artifact()
    r = await exec_client.post(
        "/api/v1/templates",
        json={
            "name": "scrapy-t",
            "build_artifact_id": artifact.id,
            "command": "python -m main",
            "node_strategy": "all",
        },
    )
    assert r.status_code == 400
    assert r.json()["code"] == "command.invalid"


async def test_template_list_reports_per_artifact_type(exec_client, seeder):
    scrapy_art = await seeder.build_artifact()
    wheel_art = await seeder.build_artifact(
        artifact_type="python_wheel", package_format="wheel", sha256="d" * 64
    )
    await exec_client.post(
        "/api/v1/templates",
        json={
            "name": "s",
            "build_artifact_id": scrapy_art.id,
            "command": "scrapy crawl phase1",
        },
    )
    await exec_client.post(
        "/api/v1/templates",
        json={
            "name": "w",
            "build_artifact_id": wheel_art.id,
            "command": "python -m main",
        },
    )
    listed = await exec_client.get("/api/v1/templates")
    types = {t["name"]: t["artifact_type"] for t in listed.json()["templates"]}
    assert types["s"] == "scrapy"
    assert types["w"] == "python_wheel"


# ---------------------------------------------------------------------------
# executor: dispatch shape + node selection + log rows
# ---------------------------------------------------------------------------


async def _wheel_template(exec_client, seeder, *, command="python -m main"):
    artifact = await seeder.build_artifact(
        artifact_type="python_wheel", package_format="wheel", sha256="d" * 64
    )
    r = await exec_client.post(
        "/api/v1/templates",
        json={
            "name": "wheel-t",
            "build_artifact_id": artifact.id,
            "command": command,
            "node_strategy": "all",
        },
    )
    assert r.status_code == 200, r.text
    return artifact, r.json()


async def test_wheel_run_dispatches_python_wheel_command(
    exec_client, exec_redis, seeder
):
    await seeder.healthy_node(agent_id="agent-1", scrapy=False, script=True)
    _artifact, template = await _wheel_template(exec_client, seeder)
    r = await exec_client.post(f"/api/v1/templates/{template['id']}/run")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "queued"

    cmds = await _commands(exec_redis)
    assert len(cmds) == 1
    assert cmds[0].type.value == "run"
    # wire seam: the runner discriminator is python_wheel
    assert cmds[0].task_type == "python_wheel"
    assert cmds[0].payload["task_type"] == "python_wheel"
    assert cmds[0].payload["shell_command"] == "python -m main"
    assert cmds[0].payload["env"] == {}
    assert cmds[0].payload["working_dir"] is None
    assert cmds[0].payload["artifact"]["fetch_path"].endswith("/wheel")

    detail = await exec_client.get(f"/api/v1/tasks/{body['task_id']}")
    view = detail.json()
    assert view["artifact_type"] == "python_wheel"
    assert len(view["executions"]) == 1
    execution = view["executions"][0]
    ctx = cmds[0].payload["runtime_context"]
    assert ctx["task_id"] == body["task_id"]
    assert ctx["execution_id"] == execution["id"]
    assert ctx["agent_id"] == "agent-1"
    assert ctx["artifact_type"] == "python_wheel"
    assert ctx["task_type"] == "python_wheel"
    assert ctx["source"] == "template"
    assert ctx["execution_template_id"] == view["execution_template_id"]
    assert ctx["schedule_id"] is None


async def test_wheel_run_creates_log_row(exec_client, exec_redis, seeder, db_session):
    from dopilot_server.models.execution import ExecutionLogFile
    from sqlalchemy import select

    await seeder.healthy_node(agent_id="agent-1", scrapy=False, script=True)
    _artifact, template = await _wheel_template(exec_client, seeder)
    r = await exec_client.post(f"/api/v1/templates/{template['id']}/run")
    task_id = r.json()["task_id"]

    rows = (
        await db_session.execute(
            select(ExecutionLogFile).where(ExecutionLogFile.task_id == task_id)
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].stream == "log"


async def test_wheel_run_excludes_scrapy_only_node(exec_client, seeder):
    # A scrapy-only node must NOT be a target for a python_wheel run.
    await seeder.healthy_node(agent_id="scrapy-only", scrapy=True, script=False)
    _artifact, template = await _wheel_template(exec_client, seeder)
    r = await exec_client.post(f"/api/v1/templates/{template['id']}/run")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "no_target"
    detail = await exec_client.get(f"/api/v1/tasks/{body['task_id']}")
    assert detail.json()["status_detail"]["healthy_count"] == 0


async def test_wheel_run_selects_script_capable_node(exec_client, seeder):
    # A script-capable node IS a valid target for a python_wheel run.
    await seeder.healthy_node(agent_id="script-node", scrapy=False, script=True)
    _artifact, template = await _wheel_template(exec_client, seeder)
    r = await exec_client.post(f"/api/v1/templates/{template['id']}/run")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "queued"


async def test_wheel_schedule_command_override_accepted(exec_client, seeder):
    # Codex review: a wheel schedule command override (a free-form shell command
    # the scrapy parser would reject) is accepted — NOT a packet-1 limitation.
    _artifact, template = await _wheel_template(exec_client, seeder)
    r = await exec_client.post(
        "/api/v1/schedules",
        json={
            "name": "wheel-sched",
            "execution_template_id": template["id"],
            "trigger_type": "interval",
            "interval_seconds": 30,
            "overrides": {"command": "python -m main | tee out.log"},
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["overrides"]["command"] == "python -m main | tee out.log"


async def test_wheel_schedule_override_dispatches_override_command(
    exec_client, exec_redis, seeder
):
    # The wheel schedule override flows through to the dispatched run payload.
    await seeder.healthy_node(agent_id="agent-1", scrapy=False, script=True)
    _artifact, template = await _wheel_template(exec_client, seeder)
    sched = await exec_client.post(
        "/api/v1/schedules",
        json={
            "name": "wheel-sched",
            "execution_template_id": template["id"],
            "trigger_type": "interval",
            "interval_seconds": 30,
            "overrides": {"command": "python -m main --once"},
        },
    )
    sid = sched.json()["id"]
    r = await exec_client.post(f"/api/v1/schedules/{sid}/trigger-now")
    assert r.status_code == 200, r.text
    cmds = await _commands(exec_redis)
    assert cmds[0].payload["shell_command"] == "python -m main --once"
    assert cmds[0].task_type == "python_wheel"
