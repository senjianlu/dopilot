# Claude Progress — task-web-ui-followups

**Size class:** Small–Medium (5 scoped UI items + 1 narrow backend query filter; touches web + server, tests on both sides).

**Planned checkpoints:**

1. Schedules UI: `enabled` types + dialog Switch + table quick-toggle column. ✅
2. Tasks status filter: backend `TASK_STATUSES` + API/service `status` filter + 400 on invalid; web `status` param + Select. ✅
3. Task-detail execution/log ordering by `agent_id`. ✅
4. Sidebar duplicate group label removal. ✅
5. Favicon via `metadata.icons`. ✅
6. Tests (web + server) updated/added. ✅ (server tests authored; run blocked — see below)
7. Required commands run + report written. ◐

## Command results

- `corepack pnpm --filter web test` — ✅ 64 passed (12 files), incl. new schedule/tasks/task-detail cases.
- `corepack pnpm --filter web build` — ✅ build + static export succeeded; `out/index.html` contains
  `<link rel="icon" href="/logo.svg"/>`.
- `.venv/bin/python -m pytest apps/server/tests/test_executions_pagination.py -q` — ⛔ BLOCKED.
  The harness returns `This command requires approval` for every Python invocation (even
  `python -c "print('hello')"`); `pnpm` commands are not gated. Needs the operator to approve the
  Python command, after which it can be re-run. No code blocker — only a permission gate.

## Notes

- Backend schedule schemas already carried `enabled` (ScheduleView/Create/Update), so no backend
  schedule changes were needed — scope was web typing + UI only.
- Started + implemented 2026-06-23.
