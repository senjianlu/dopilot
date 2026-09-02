---
task: fix-queued-task-rollup-and-orphan-repair
round: 01
date: 2026-09-02
---

# 实现记录:第 01 轮

轮次上限:plan.md frontmatter `impl_fix_max_rounds: 15`(用户 2026-09-02 明确
放宽,见 plan「用户授权记录」)。本轮按 plan 实现。

## 本轮改动

| 文件 | 改动摘要 |
|---|---|
| `apps/server/dopilot_server/services/executions.py` | 新增纯内存 helper `converge_task(task, executions, now) -> bool`(`executions.py:203-229`):task 为 `queued` 且任一 execution 已离开 `pending` → 置 `running`,`started_at` 取已开始 executions 的最早 `started_at`(缺失则 `now`) |
| `apps/server/dopilot_server/services/events.py` | `_update_task`(`events.py:145-178`):先 `list_executions`(:153),用 `svc.converge_task`(:157)取代原"仅 running 事件收敛"分支,roll-up / lost 重滚 / `outcome_recorded_at` 复位逻辑原样保留;移除不再使用的 `TASK_QUEUED` / `TASK_RUNNING` 导入 |
| `apps/server/dopilot_server/redis/reconcile.py` | 常量 `ORPHAN_NO_EXECUTION` / `REPAIR_KEY`(:53-54);`ReconcileReport` 增 `orphan_rolled_up` / `orphan_lost` / `repaired_task_ids`(:71-73);新增 `repair_orphaned_tasks()`(:204-300):SQL 侧 `status IN active AND NOT EXISTS(active execution)` 选候选 → 逐条 `get_task(for_update=True)` 锁下复核 → 全终态则 `converge_task` + roll-up(时间线取 executions),零 execution 超 `lost_after_stalled_seconds` 则 `lost(no_execution)` → 写 `status_detail[reconcile_repair]` + warning 日志;`reconcile_once` 在 execution 循环后调用(:200) |
| `apps/server/tests/test_event_consumer.py` | 新增 6 个用例(TC-01 ~ TC-06)与 `_utc` 归一化 helper |
| `apps/server/tests/test_reconcile_redis.py` | 新增 `_seed_stuck` / `_zero` helper 与 6 个用例(TC-07 ~ TC-12) |
| `apps/server/tests/test_reconcile_orphans_pg.py`(新) | PostgreSQL 用例 2 个(TC-13、TC-14) |
| `docs/architecture/03-execution-and-logs.md` | 「状态事件与对账」新增「task 收敛与 roll-up」与「task 级孤儿修复」两条(:56-72) |

## 修复对照

(第 1 轮,不适用)

## 测试结果

| 编号 | 档位 | 结果 | 证据 |
|---|---|---|---|
| TC-01 | A | pass | `evidence/tc-01-06-events.txt`(`test_finished_without_running_rolls_queued_task_to_complete`) |
| TC-02 | A | pass | 同上(`test_failed_without_running_rolls_queued_task_to_failed`) |
| TC-03 | A | pass | 同上(`test_canceled_without_running_rolls_queued_task_to_canceled`) |
| TC-04 | A | pass | 同上(`test_lost_without_running_then_override_rerolls_complete`) |
| TC-05 | A | pass | 同上(`test_running_then_finished_keeps_started_at_from_running`;既有 `test_running_converges_task_and_is_idempotent` / `test_running_then_finished_rolls_up_complete` 同批通过) |
| TC-06 | A | pass | 同上(`test_fan_out_converges_on_first_terminal_completes_on_last`);8 passed, exit=0 |
| TC-07 | A | pass | `evidence/tc-07-12-reconcile.txt`(`test_orphan_all_terminal_rolls_up_with_execution_timeline`) |
| TC-08 | A | pass | 同上(`test_orphan_rollup_precedence_failed_over_finished`) |
| TC-09 | A | pass | 同上(`test_orphan_not_selected_while_an_execution_is_active`) |
| TC-10 | A | pass | 同上(`test_orphan_zero_execution_respects_observation_window`) |
| TC-11 | A | pass | 同上(`test_orphan_terminal_tasks_untouched_and_repair_is_idempotent`) |
| TC-12 | A | pass | 同上(`test_orphan_repair_and_outcome_recorded_in_same_tick`);6 passed, exit=0 |
| TC-13 | A | pass | `evidence/tc-13-14-pg.txt`(`test_orphan_repair_on_postgres`,含幂等二次调用) |
| TC-14 | A | pass | 同上(`test_orphan_repair_yields_to_concurrent_terminal_writer`);2 passed, exit=0 |
| TC-15 | A | pass | `evidence/tc-15-ruff.txt`(All checks passed, exit=0);`evidence/tc-15-pytest.txt`(`pytest apps/server`:539 passed, 1 skipped, exit=0);`evidence/tc-15-pytest-all.txt`(根目录全量 `pytest`:804 passed, 1 skipped, exit=0;基线 782 + 新增 14 = 796 ≤ 804) |
| TC-16 | B | pass | `docs/architecture/03-execution-and-logs.md:56-62`(task 收敛与 roll-up)、`:63-72`(task 级孤儿修复) |

TC-15 说明:plan 写的基线 782 是根目录聚合(apps/server + apps/agent +
packages/protocol)的通过数,故同时留了 `pytest apps/server` 与根目录全量两份
证据;`1 skipped` 为既有跳过项,与本次无关。

## 与方案的偏差

无(架构、接口、文件范围与 plan 一致)。两处实现细节备注:

- `repair_orphaned_tasks` 增加可选 `report` 入参以便 `reconcile_once` 把计数
  合并进同一份 `ReconcileReport`(plan 伪码为"返回 report",语义相同);
- 自测中修正了两处**用例本身**的问题,不涉及被测代码:TC-05 在 SQLite 下
  重载得到 naive datetime,与首轮 aware 值直接比较失败,改为 `_utc` 归一化
  后比较;TC-13/14 的 PG seed 需在插入 execution 前 `flush()` task 行
  (PostgreSQL 强制外键,SQLite 不强制)。
