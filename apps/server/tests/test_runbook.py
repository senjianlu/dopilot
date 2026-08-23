"""TC-31b / TC-31c: the recovery runbook's pre-checks are executable and complete."""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
RUNBOOK = REPO / "docs" / "architecture" / "05-deployment.md"


async def test_runbook_task_status_queries_are_valid(client):
    # The runbook tells the operator to poll three SINGLE-valued status filters.
    for status in ("queued", "running", "finalizing"):
        resp = await client.get("/api/v1/tasks", params={"status": status})
        assert resp.status_code == 200, status
        assert "total" in resp.json()
    # ...and a comma-joined multi-value is NOT accepted (documented pitfall).
    resp = await client.get("/api/v1/tasks", params={"status": "queued,running"})
    assert resp.status_code == 400
    assert resp.json()["code"] == "task.invalid_status"

    text = RUNBOOK.read_text(encoding="utf-8")
    for status in ("queued", "running", "finalizing"):
        assert f"status={status}" in text, status
    assert "status=queued,running" not in text


def test_runbook_backs_up_and_restores_both_volumes():
    text = RUNBOOK.read_text(encoding="utf-8")
    section = text[text.index("### 事故恢复 runbook") :]
    section = section[: section.index("### 已膨胀的部署升级到本版本")]
    rollback = section[section.index("**回滚**") :]
    for volume in ("${P}_dopilot-db", "${P}_dopilot-server-data"):
        v = re.escape(volume)
        # one executable BACKUP command per volume (volume mounted as the source)
        backup = rf"docker run [^\n]*-v {v}:/src[^\n]* tar czf [^\n]*-C /src"
        assert re.search(backup, section), volume
        # ...and one executable RESTORE command per volume in the rollback
        # (volume mounted as the destination of `tar xzf`), after its removal
        assert re.search(rf"docker volume rm [^\n]*{v}", rollback), volume
        restore = rf"docker run [^\n]*-v {v}:/dst[^\n]* tar xzf [^\n]*-C /dst"
        assert re.search(restore, rollback), volume
    assert "成对恢复" in rollback and "成对备份" in section
    assert "alembic downgrade 0012" in rollback
    # rollback order: downgrade with the NEW image -> old compose -> volume
    # removal -> restore both volumes -> up
    idx = [
        rollback.index("alembic downgrade 0012"),
        rollback.index("docker-compose.yml.bak"),
        rollback.index("docker volume rm"),
        rollback.index("tar xzf"),
        rollback.index("docker compose up -d"),
    ]
    assert idx == sorted(idx)
