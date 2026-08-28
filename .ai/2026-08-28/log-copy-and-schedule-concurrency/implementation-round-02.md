---
task: log-copy-and-schedule-concurrency
round: 02
date: 2026-08-28
---

# 实现记录:第 02 轮

## 本轮改动

| 文件 | 改动摘要 |
|---|---|
| `apps/web/lib/api/types.ts` | `CreateScheduleRequest` 增 `max_concurrency?: number`(修 R-02) |
| `evidence/backend-tests.log` | 重新采集:TC-25 改为 `-v` 全量输出、**不再经 `tail` 截断**,命令行写出真实数据库地址(修 R-01) |
| `evidence/web-tests.log`、`evidence/lint-typecheck.log` | 同步重采,保持与当前工作区一致;lint 三条命令统一在仓库根执行 |

仅这两处,未做评审范围外的任何改动。

## 修复对照

| 评审问题编号 | 严重度 | 修复方式 |
|---|---|---|
| R-01 | blocker | TC-25 的证据此前用 `pytest ... \| tail -30` 采集,只剩最后 30 行(从 65% 开始),且说明里的数据库地址写成了 `<pg>` 占位符。已重采:`DOPILOT_TEST_DATABASE_URL=postgresql+psycopg://dopilot:dopilot@localhost:5432/dopilot .venv/bin/python -m pytest apps/server apps/agent packages -v`,完整 stdout/stderr 落 `evidence/backend-tests.log:47-841`——含 `test session starts` 会话头(:47)、`collected 783 items`(:54)、全部逐条用例行、`782 passed, 1 skipped`(:840)与 `EXIT_CODE=0`(:841) |
| R-02 | major | `CreateScheduleRequest` 补 `max_concurrency?: number`(`apps/web/lib/api/types.ts:349-352`)。此前页面能通过类型检查只是因为先构造对象变量再传参的结构化兼容,任何按该类型直接调用 `createSchedule` / `updateSchedule`(后者取 `Partial<CreateScheduleRequest>`)的调用方都无法合法传入该字段。设为可选:省略即沿用服务端默认值 1,与后端 schema 的默认值一致 |

## 测试结果

| 编号 | 档位 | 结果 | 证据 |
|---|---|---|---|
| TC-01 | A | pass | `evidence/backend-tests.log`,锚点 `test_max_concurrency_defaults_and_values` |
| TC-02 | A | pass | `evidence/backend-tests.log`,锚点 `test_max_concurrency_invalid_inputs` |
| TC-03 | A | pass | `evidence/backend-tests.log`,锚点 `test_update_max_concurrency` |
| TC-04 | A | pass | `evidence/backend-tests.log`,锚点 `test_limit_two_allows_two_then_rejects` |
| TC-05 | A | pass | `evidence/backend-tests.log`,锚点 `test_all_active_statuses_count[queued\|running\|finalizing]` |
| TC-06 | A | pass | `evidence/backend-tests.log`,锚点 `test_terminal_statuses_release_slot[complete\|failed\|canceled\|lost\|no_target]` |
| TC-07 | A | pass | `evidence/backend-tests.log`,锚点 `test_zero_means_unlimited` |
| TC-08 | A | pass | `evidence/backend-tests.log`,锚点 `test_count_scoped_to_own_schedule` |
| TC-09 | A | pass | `evidence/backend-tests.log`,锚点 `test_multi_execution_task_counts_once` |
| TC-10 | A | pass | `evidence/backend-tests.log`,锚点 `test_fire_timer_silently_skipped_when_full` |
| TC-11 | A | pass | `evidence/backend-tests.log`,锚点 `test_non_concurrency_skips_do_not_log_limit[disabled\|backlog]` |
| TC-12 | A | pass | `evidence/pg-tests.log`,锚点 `test_concurrent_trigger_now_row_lock` |
| TC-13 | A | pass | `evidence/pg-tests.log`,锚点 `test_limit_change_visible_under_lock` |
| TC-14 | A | pass | `evidence/pg-tests.log`,锚点 `test_timer_coalesce_sees_backlog_committed_under_lock` |
| TC-15 | A | pass | `evidence/pg-tests.log`,锚点 `test_migration_0014_backfills_and_indexes` |
| TC-16 | A | pass | `evidence/web-tests.log`,锚点 `ok 4 - copies the current buffer` |
| TC-17 | A | pass | `evidence/web-tests.log`,锚点 `ok 5 - disables copy when the buffer is empty` |
| TC-18 | A | pass | `evidence/web-tests.log`,锚点 `ok 6 - warns when clipboard is unavailable` |
| TC-19 | A | pass | `evidence/web-tests.log`,锚点 `ok 7 - warns when clipboard write is rejected` |
| TC-20 | A | pass | `evidence/web-tests.log`,锚点 `ok 8 - explains the copy scope` |
| TC-21 | A | pass | `evidence/web-tests.log`,锚点 `ok 16 - submits max_concurrency on create` |
| TC-22 | A | pass | `evidence/web-tests.log`,锚点 `ok 17 - prefills and updates max_concurrency on edit` |
| TC-23 | A | pass | `evidence/web-tests.log`,锚点 `ok 18 - supports zero as unlimited` |
| TC-24 | A | pass | `evidence/web-tests.log`,锚点 `ok 19 - shows a toast when the concurrency limit is hit` |
| TC-25 | A | pass | `evidence/backend-tests.log:47-841`,完整会话:`collected 783 items` → `782 passed, 1 skipped` → `EXIT_CODE=0`(基线 759 passed,新增 23) |
| TC-26 | A | pass | `evidence/lint-typecheck.log`,三条命令均 `EXIT_CODE=0` |
| TC-27 | B | pass | `apps/server/migrations/versions/0014_schedule_max_concurrency.py:33-47`(`add_column` 带 `server_default="1"`、`create_index`)与 `:49-51`(对称 `downgrade`);模型侧索引 `apps/server/dopilot_server/models/execution.py:136` |
| TC-28 | B | pass | `docs/decisions/0022-schedule-concurrency-limit.md:1-57`;`docs/decisions/0014-node-strategy-and-push-mode.md:3-6`;`docs/decisions/README.md:46`;`docs/architecture/02-domain-model.md:32`;`docs/architecture/06-web-frontend.md:17-29`;`apps/server/dopilot_server/services/outbox.py:213-224` |
| TC-29 | A | pass | `evidence/backend-tests.log`,锚点 `test_quota_shared_across_sources` |

29 条全部 pass,无 fail、无 blocked。

## 与方案的偏差

沿用第 01 轮记录的三点(Alembic `Config` 不传 ini 路径以免 `fileConfig`
清空全局 logging、错误信封类型名用仓库既有的 `ApiError`、跳过日志取传入
实例的 id),本轮未新增偏差。
