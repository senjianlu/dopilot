---
task: log-copy-and-schedule-concurrency
round: 01
date: 2026-08-28
---

# 实现记录:第 01 轮

## 本轮改动

| 文件 | 改动摘要 |
|---|---|
| `apps/server/dopilot_server/models/scheduling.py` | `Schedule.max_concurrency`(Integer,NOT NULL,模型默认 1) |
| `apps/server/dopilot_server/models/execution.py` | `Task.__table_args__` 增 `ix_tasks_schedule_id_status` |
| `apps/server/migrations/versions/0014_schedule_max_concurrency.py`(新) | 加列(`server_default="1"`,存量回填)+ 建索引;`downgrade` 对称回滚 |
| `apps/server/dopilot_server/services/schedules.py` | `MAX_CONCURRENCY_CEILING`、`SKIP_*`、`FiringSlot`、`_validate_max_concurrency`、`count_active_tasks_for_schedule`、`acquire_firing_slot`;`create/update_schedule` 校验并写入;`trigger_now` / `fire_timer` 接入准入闸;`schedule_view` 输出字段 |
| `apps/server/dopilot_server/services/outbox.py` | 更新 `has_undispatched_backlog_for_schedule` 的注释:旧"允许并发重复运行"口径改为"积压合并只管未下发,并发由 0022 的闸负责" |
| `apps/server/dopilot_server/api/v1/schemas.py` | `ScheduleView` / `ScheduleCreateRequest` / `ScheduleUpdateRequest` 增 `max_concurrency`;两个请求 schema 各挂 `_reject_bool_concurrency` before-validator |
| `apps/server/tests/test_schedules.py` | `test_repeated_trigger_now_not_coalesced` 改用 `max_concurrency=0`;新增默认值断言 |
| `apps/server/tests/test_schedule_concurrency.py`(新) | 19 个用例:值域/类型契约、上限边界、active/终止态、0=不限、跨 schedule 隔离、多 execution 计一次、跨来源同池、定时跳过与日志分流 |
| `apps/server/tests/test_schedule_concurrency_pg.py`(新) | 3 个用例:并发双触发行锁、锁下重读上限、锁内 coalesce(Event 交错) |
| `apps/server/tests/test_migration_0014_pg.py`(新) | 0013→0014→0013 真实升级/回填/索引/回滚,自带 schema 硬重置 |
| `apps/web/components/features/log-viewer.tsx` | 复制按钮 + `onCopy`(可用性预判、成功/失败 toast、空缓冲禁用、`aria-describedby` 范围说明) |
| `apps/web/lib/api/types.ts` | `Schedule.max_concurrency` |
| `apps/web/app/(app)/schedules/page.tsx` | `maxConcurrency` 状态、创建/编辑对话框数字项(min 0 / max 2147483647,0 安全解析)、列表列(0→"不限")、`onTrigger` 捕获 409 弹 toast 且不跳转 |
| `apps/web/lib/i18n/locales/zh.ts`、`en.ts` | `logs.copy*`、`schedules.maxConcurrency*` / `unlimited` / `concurrencyLimitHit`、`errors.invalidMaxConcurrency` / `scheduleConcurrencyLimit` / `scheduleNotFound` |
| `apps/web/components/features/__tests__/log-viewer.test.tsx` | 5 个复制用例(成功/空缓冲禁用/无 clipboard/写入被拒/范围说明) |
| `apps/web/app/(app)/schedules/__tests__/schedules.test.tsx` | 4 个用例(创建提交/编辑预填/0=不限三态/409 toast);既有 edit 用例的 payload 断言补 `max_concurrency` |
| `docs/decisions/0022-schedule-concurrency-limit.md`(新) | ADR:口径、同池、超限两种表现、串行区设计与被否备选、存量回填影响 |
| `docs/decisions/0014-node-strategy-and-push-mode.md` | 顶部标注 coalesce 口径部分被 0022 取代 |
| `docs/decisions/README.md` | 索引新增 0022 |
| `docs/architecture/02-domain-model.md` | schedules 表补 `max_concurrency` 行 |
| `docs/architecture/06-web-frontend.md` | 补日志查看器复制能力与调度并发上限的前端约定 |

## 修复对照

不适用(第 1 轮)。

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
| TC-25 | A | pass | `evidence/backend-tests.log` 第二段:`782 passed, 1 skipped`,`EXIT_CODE=0`(基线为 759 passed,新增 23) |
| TC-26 | A | pass | `evidence/lint-typecheck.log`,三条命令 `EXIT_CODE=0` |
| TC-27 | B | pass | `apps/server/migrations/versions/0014_schedule_max_concurrency.py:33-47`(`add_column` 带 `server_default="1"`、`create_index`)与 `:49-51`(对称 `downgrade`);模型侧索引 `apps/server/dopilot_server/models/execution.py:136` |
| TC-28 | B | pass | `docs/decisions/0022-schedule-concurrency-limit.md:1-57`;`docs/decisions/0014-node-strategy-and-push-mode.md:3-6`(取代标注);`docs/decisions/README.md:46`(索引);`docs/architecture/02-domain-model.md:32`;`docs/architecture/06-web-frontend.md:17-29`;`apps/server/dopilot_server/services/outbox.py:213-224`(注释已同步) |
| TC-29 | A | pass | `evidence/backend-tests.log`,锚点 `test_quota_shared_across_sources` |

29 条全部 pass,无 fail、无 blocked。

## 与方案的偏差

1. **`test_migration_0014_pg.py` 构造 Alembic `Config` 时不传 ini 路径。**
   plan 只说"程序化调用 `alembic.command`"。实测发现:传 ini 路径时
   `migrations/env.py` 会执行 `fileConfig(config.config_file_name)`,那会
   **重配置全局 logging 并禁用已有 logger**,导致同一 pytest 会话中**后续所有
   `caplog` 断言失效**——首轮全量回归因此出现 6 个失败(其中 5 个是与本任务
   无关的既有 agent/server 用例)。改为 `Config()` + 直接设
   `script_location`(URL 仍由 `DOPILOT_DATABASE_URL` 提供),`config_file_name`
   为 `None` 时 env.py 跳过该分支。属实现细节修正,不改变 plan 的验收内容;
   已在测试文件里写明原因。

2. **前端错误信封类型名用 `ApiError` 而非 plan 顺手写的 `ErrorResponse`。**
   仓库 `lib/api/types.ts:464` 里该类型就叫 `ApiError`。纯命名对齐。

3. **`fire_timer` 的跳过日志用 `schedule.id` 而非锁下实例的 id。**
   二者恒等(同一行),此处取传入实例只是为了在 `slot.schedule` 为 `None`
   (missing/disabled 分支)时也能打出 id。无行为差异。

除此之外与 plan 一致;`acquire_firing_slot` 的锁内四道判断顺序、`FiringSlot`
结构、双层 bool 拒绝、`0..2147483647` 值域、按 task 计数与跨来源同池、
409 / 静默跳过两种超限表现,均按 plan 实现。
