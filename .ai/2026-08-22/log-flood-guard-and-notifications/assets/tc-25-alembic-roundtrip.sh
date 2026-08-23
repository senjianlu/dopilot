#!/usr/bin/env bash
# TC-25: migration 0013 upgrade -> downgrade -> upgrade on the dev PostgreSQL
# (scripts/dev-db.sh up), with a pre-upgrade schedule task to prove the
# schedule_generation backfill and that the outcome recorder counts it.
# Every step is echoed (set -x); exit codes are printed after each command.
set -u
cd "$(dirname "$0")/../../../../apps/server"
export DOPILOT_DATABASE_URL="${DOPILOT_DATABASE_URL:-postgresql+psycopg://dopilot:dopilot@localhost:5432/dopilot}"
PG_DSN="${PG_DSN:-postgresql://dopilot:dopilot@localhost:5432/dopilot}"
PY="${PY:-../../.venv/bin/python}"
set -x
"$PY" -c "import psycopg; c=psycopg.connect('$PG_DSN', autocommit=True); c.execute('DROP SCHEMA public CASCADE; CREATE SCHEMA public;'); print('schema reset')"
echo "exit code: $?"
"$PY" -m alembic upgrade 0012
echo "exit code: $?"
"$PY" -c "
import psycopg
c = psycopg.connect('$PG_DSN', autocommit=True)
c.execute(\"INSERT INTO execution_templates (id, name, node_strategy, node_ids, created_at, updated_at) VALUES ('t'||repeat('0',31), 'tpl', 'any', '[]', now(), now())\")
c.execute(\"INSERT INTO schedules (id, name, enabled, execution_template_id, trigger_type, interval_seconds, overrides, created_at, updated_at) VALUES ('s'||repeat('0',31), 'sch', false, 't'||repeat('0',31), 'interval', 60, '{}', now(), now())\")
c.execute(\"INSERT INTO tasks (id, artifact_type, target, node_strategy, status, params, created_at, updated_at, status_detail, source, schedule_id, template_snapshot) VALUES ('a'||repeat('0',31), 'scrapy', 'x', 'any', 'queued', '{}', now(), now(), '{}', 'schedule_timer', 's'||repeat('0',31), '{}')\")
print('pre-upgrade schedule task inserted (schedule_timer, not terminal)')
"
echo "exit code: $?"
"$PY" -m alembic upgrade head
echo "exit code: $?"
"$PY" -c "
import psycopg
c = psycopg.connect('$PG_DSN')
q = lambda sql: c.execute(sql).fetchall()
print('backfilled tasks.schedule_generation:', q(\"SELECT schedule_generation FROM tasks WHERE schedule_id IS NOT NULL\"))
print('new tables:', [r[0] for r in q(\"SELECT table_name FROM information_schema.tables WHERE table_name IN ('notifications','schedule_outcome_ledger') ORDER BY 1\")])
print('schedules new cols:', [r[0] for r in q(\"SELECT column_name FROM information_schema.columns WHERE table_name='schedules' AND column_name IN ('outcome_generation','consecutive_error_count','auto_disabled_at','auto_disabled_reason') ORDER BY 1\")])
print('tasks new cols:', [r[0] for r in q(\"SELECT column_name FROM information_schema.columns WHERE table_name='tasks' AND column_name IN ('schedule_generation','outcome_recorded_at','outcome_erroneous') ORDER BY 1\")])
print('executions new cols:', [r[0] for r in q(\"SELECT column_name FROM information_schema.columns WHERE table_name='executions' AND column_name IN ('error_count','finish_reason','log_bytes') ORDER BY 1\")])
print('execution_log_files new cols:', [r[0] for r in q(\"SELECT column_name FROM information_schema.columns WHERE table_name='execution_log_files' AND column_name='truncation_reason'\")])
print('notifications indexes:', [r[0] for r in q(\"SELECT indexname FROM pg_indexes WHERE tablename='notifications' ORDER BY 1\")])
print('partial index def:', q(\"SELECT indexdef FROM pg_indexes WHERE indexname='uq_notifications_active_dedupe'\")[0][0])
"
echo "exit code: $?"
"$PY" -m alembic downgrade -1
echo "exit code: $?"
"$PY" -c "
import psycopg
c = psycopg.connect('$PG_DSN')
print('after downgrade, tables present:', [r[0] for r in c.execute(\"SELECT table_name FROM information_schema.tables WHERE table_name IN ('notifications','schedule_outcome_ledger')\").fetchall()])
print('after downgrade, tasks.schedule_generation column present:', bool(c.execute(\"SELECT 1 FROM information_schema.columns WHERE table_name='tasks' AND column_name='schedule_generation'\").fetchall()))
"
echo "exit code: $?"
"$PY" -m alembic upgrade head
echo "exit code: $?"
"$PY" -c "
import asyncio, datetime as dt, psycopg
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine, AsyncSession
from dopilot_server.config.settings import Settings
from dopilot_server.services.outcomes import record_task_outcomes
c = psycopg.connect('$PG_DSN', autocommit=True)
c.execute(\"UPDATE tasks SET status='failed', finished_at=now() - interval '1 hour' WHERE id='a'||repeat('0',31)\")
async def main():
    engine = create_async_engine('$DOPILOT_DATABASE_URL')
    maker = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    settings = Settings.model_validate({'database': {'url': 'x'}})
    async with maker() as s:
        await record_task_outcomes(s, settings, now=dt.datetime.now(dt.UTC))
        await s.commit()
    await engine.dispose()
asyncio.run(main())
print('ledger rows (generation, erroneous):', c.execute('SELECT generation, erroneous FROM schedule_outcome_ledger').fetchall())
print('schedule consecutive_error_count:', c.execute('SELECT consecutive_error_count FROM schedules').fetchone()[0])
"
echo "exit code: $?"
