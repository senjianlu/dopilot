---
task: disable-all-schedules
round: 01
date: 2026-08-10
---

# 实现记录:第 01 轮

## 本轮改动

| 文件 | 改动摘要 |
|---|---|
| apps/server/dopilot_server/services/schedules.py | 新增 `disable_all_schedules`(单条批量 UPDATE,返回行数)与 `count_enabled_schedules`(全局 COUNT,不受列表 limit 影响) |
| apps/server/dopilot_server/api/v1/schemas.py | `SchedulesResponse` 增加 `enabled_total: int = 0`;新增 `ScheduleDisableAllResponse { disabled }` |
| apps/server/dopilot_server/api/v1/schedules.py | 新增 `POST /schedules/disable-all`(admin 鉴权,commit 后恰好一次 `_reload_runner`);`GET /schedules` 填充 `enabled_total` |
| apps/web/lib/api/types.ts | `SchedulesResponse` 增加 `enabled_total`;新增 `ScheduleDisableAllResponse` |
| apps/web/lib/api/schedules.ts | `listSchedules` 改为返回完整 `SchedulesResponse`;新增 `disableAllSchedules()` |
| apps/web/app/(app)/schedules/page.tsx | 新增「一键停用」按钮(`schedule-disable-all`):可用性与确认文案数量取 `enabled_total`;`useConfirm` destructive 确认;在途 `disablingAll` 禁用 + Spinner;确认后调 API 并 `load()` |
| apps/web/lib/i18n/locales/zh.ts、en.ts | 新增 `schedules.disableAll` / `schedules.confirmDisableAll`(带 {{count}},注明升级前止血、恢复需逐条开启) |
| apps/server/tests/test_schedules.py | TC-01/02/07/09 用例(批量停用、幂等边界、fake runner 注入断言 reload 恰一次、201 条截断下 enabled_total) |
| apps/web/app/(app)/schedules/__tests__/schedules.test.tsx | TC-03/04/05/08/10 用例;既有 mock 随 `listSchedules` 返回形状同步为 `schedulesResponse()` helper |

## 修复对照

(第 1 轮,不适用)

## 测试结果

| 编号 | 档位 | 结果 | 证据 |
|---|---|---|---|
| TC-01 | A | pass | evidence/tc-01-02-07-09-server-schedules.txt(`test_disable_all_disables_every_enabled_schedule`,28 passed,exit_code=0) |
| TC-02 | A | pass | 同上(`test_disable_all_idempotent_when_nothing_enabled`) |
| TC-03 | A | pass | evidence/tc-03-04-05-08-10-web-vitest.txt(`disables all schedules after confirmation and reloads`,93 passed,exit_code=0) |
| TC-04 | A | pass | 同上(`does not disable anything when the confirm dialog is cancelled`) |
| TC-05 | A | pass | 同上(`disables the disable-all button when nothing is enabled globally`) |
| TC-06 | A | pass | evidence/tc-06-full-pytest.txt(650 passed, 1 skipped——skip 为既有 `DOPILOT_TEST_PG_URL not set`,exit_code=0)、tc-06-ruff.txt、tc-06-web-typecheck.txt、tc-06-web-lint.txt(均 exit_code=0);web 全量见 tc-03-04-05-08-10-web-vitest.txt |
| TC-07 | A | pass | evidence/tc-01-02-07-09-server-schedules.txt(`test_disable_all_reloads_runner_exactly_once`) |
| TC-08 | A | pass | evidence/tc-03-04-05-08-10-web-vitest.txt(`blocks a second click while the bulk disable is in flight`) |
| TC-09 | A | pass | evidence/tc-01-02-07-09-server-schedules.txt(`test_enabled_total_not_bounded_by_list_truncation`) |
| TC-10 | A | pass | evidence/tc-03-04-05-08-10-web-vitest.txt(`keeps disable-all clickable when only unloaded rows are enabled`) |

## 与方案的偏差

1. TC-07 的 fake runner 注入通过 `exec_client._transport.app.state.schedule_runner`
   实现(httpx ASGITransport 暴露 `app` 属性)——plan 只写「向 app.state 注入」,
   未指定注入通道;测试内私有属性访问仅限测试代码,不影响生产路径。
2. 其余按 plan 实现,无偏差。
