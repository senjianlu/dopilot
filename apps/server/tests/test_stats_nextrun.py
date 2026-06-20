"""Phase 1.7.1: dashboard daily stats + schedule next_run_at metadata."""

from __future__ import annotations

from datetime import UTC, datetime

from dopilot_protocol import ExecutionRunRequest
from dopilot_server.services import executions as svc
from dopilot_server.services import schedules as sched_svc
from dopilot_server.services.stats import daily_task_counts
from sqlalchemy import event


async def test_daily_task_counts_returns_30_buckets(db_session):
    buckets = await daily_task_counts(db_session, days=30, timezone="UTC")
    assert len(buckets) == 30
    # ascending by date, each shaped {date, tasks, executions}
    dates = [b["date"] for b in buckets]
    assert dates == sorted(dates)
    assert all(set(b) == {"date", "tasks", "executions"} for b in buckets)
    assert all(b["tasks"] == 0 for b in buckets)


async def test_daily_task_counts_buckets_today(db_session):
    req = ExecutionRunRequest(
        artifact_type="scrapy",
        target="demo:s1",
        node_strategy="all",
        params={"project": "demo", "spider": "s1"},
    )
    svc.create_task(db_session, req)
    await db_session.commit()
    buckets = await daily_task_counts(db_session, days=30, timezone="UTC")
    today = datetime.now(UTC).date().isoformat()
    today_bucket = next(b for b in buckets if b["date"] == today)
    assert today_bucket["tasks"] == 1


async def test_daily_task_counts_aggregates_in_db(db_session):
    """Many rows on one day must collapse via a SQL GROUP BY, not row streaming.

    Fails if ``daily_task_counts`` reverts to selecting every ``created_at`` and
    bucketing in Python: it asserts the emitted SQL groups server-side, so each
    active day costs one row rather than one row per task/execution.
    """
    req = ExecutionRunRequest(
        artifact_type="scrapy",
        target="demo:s1",
        node_strategy="all",
        params={"project": "demo", "spider": "s1"},
    )
    for _ in range(5):
        svc.create_task(db_session, req)
    await db_session.commit()

    statements: list[str] = []

    def _capture(conn, cursor, statement, params, context, executemany):
        statements.append(statement)

    engine = db_session.bind.sync_engine
    event.listen(engine, "before_cursor_execute", _capture)
    try:
        buckets = await daily_task_counts(db_session, days=30, timezone="UTC")
    finally:
        event.remove(engine, "before_cursor_execute", _capture)

    today = datetime.now(UTC).date().isoformat()
    today_bucket = next(b for b in buckets if b["date"] == today)
    assert today_bucket["tasks"] == 5
    # Both the task and execution counts must aggregate in the database.
    grouped = [s for s in statements if "group by" in s.lower()]
    assert len(grouped) >= 2


async def test_stats_endpoint(exec_client):
    r = await exec_client.get("/api/v1/stats/tasks/daily?days=30")
    assert r.status_code == 200
    body = r.json()
    assert body["days"] == 30
    assert len(body["buckets"]) == 30


def test_next_run_interval_estimate():
    now = datetime(2026, 6, 20, 12, 0, 0, tzinfo=UTC)
    nxt = sched_svc.compute_next_run_at(
        trigger_type="interval", interval_seconds=60, cron=None, now=now
    )
    assert nxt is not None
    assert nxt.isoformat() == datetime(2026, 6, 20, 12, 1, 0, tzinfo=UTC).isoformat()


def test_next_run_cron_deterministic():
    now = datetime(2026, 6, 20, 12, 0, 30, tzinfo=UTC)
    nxt = sched_svc.compute_next_run_at(
        trigger_type="cron", interval_seconds=None, cron="*/5 * * * *", now=now
    )
    assert nxt is not None
    # next */5 minute boundary after 12:00:30 is 12:05:00
    assert nxt.hour == 12 and nxt.minute == 5


async def test_schedule_views_include_next_run_at(exec_client, seeder):
    artifact = await seeder.build_artifact()
    tpl = await exec_client.post(
        "/api/v1/templates",
        json={
            "name": "t",
            "build_artifact_id": artifact.id,
            "command": "scrapy crawl phase1",
            "node_strategy": "all",
        },
    )
    template_id = tpl.json()["id"]
    interval = await exec_client.post(
        "/api/v1/schedules",
        json={
            "name": "iv",
            "execution_template_id": template_id,
            "trigger_type": "interval",
            "interval_seconds": 60,
        },
    )
    assert interval.json()["next_run_at"] is not None

    cron = await exec_client.post(
        "/api/v1/schedules",
        json={
            "name": "cr",
            "execution_template_id": template_id,
            "trigger_type": "cron",
            "cron": "*/5 * * * *",
        },
    )
    assert cron.json()["next_run_at"] is not None


async def test_preview_next_run_endpoint(exec_client):
    r = await exec_client.post(
        "/api/v1/schedules/preview-next-run",
        json={"trigger_type": "cron", "cron": "*/5 * * * *"},
    )
    assert r.status_code == 200
    assert r.json()["next_run_at"] is not None
