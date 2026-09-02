---
task: fix-queued-task-rollup-and-orphan-repair
date: 2026-09-02
rounds: 1
verdict: pass
---

# 任务小结:修复 queued task 在 execution 直达终态时永久卡住,并加 task 级对账自愈

生产(2026-09-02 只读核实)有两条任务自 08-26 outbox OOM 事故起停在 `queued`
7 天:各自唯一的 execution 已 `finished`(`started_at == finished_at`,无
`running` 事件),task `started_at` 为空。根因是 task 状态机没有
`queued -> complete` 边而事件消费者只在 `running` 事件时收敛,终态直达时
roll-up 被拒绝;对账循环只遍历活动态 execution,永远看不见它们。升级到并发
上限版本(0022)后这两条会永久占住 LOOTFARM 730 / MARKETCSGO 730 的额度。

用户授权:plan 评审与实现修复轮次上限均放宽至 15(frontmatter
`plan_review_max_rounds` / `impl_fix_max_rounds`);plan 人工确认闸照常执行
(用户 2026-09-02 11:50 确认);commit 需用户确认。

## 改动
| 文件 | 摘要 |
|---|---|
| `apps/server/dopilot_server/services/executions.py` | 新增纯内存 helper `converge_task`:queued task 名下任一 execution 离开 pending → running,`started_at` 取 executions 最早开始时间 |
| `apps/server/dopilot_server/services/events.py` | `_update_task` 改用 `converge_task`(超集取代"仅 running 事件收敛"),roll-up / lost 重滚逻辑不变;清理未用导入 |
| `apps/server/dopilot_server/redis/reconcile.py` | `repair_orphaned_tasks`:SQL 侧选"活动态 task 且无活动 execution",task 行锁下复核;全终态 → 收敛 + roll-up(时间线取 executions),零 execution 超 `lost_after_stalled_seconds` → `lost(no_execution)`;`status_detail.reconcile_repair` 留痕 + warning 日志;`ReconcileReport` 增三个字段;`reconcile_once` 接线 |
| `apps/server/tests/test_event_consumer.py` | +6 用例(TC-01 ~ 06):finished/failed/canceled/lost 直达、lost 重滚、started_at 不被覆盖、扇出 |
| `apps/server/tests/test_reconcile_redis.py` | +6 用例(TC-07 ~ 12):时间线、failed 优先级、部分活动不修、零 execution 观察期、终态不选且幂等、与结果记录同 tick |
| `apps/server/tests/test_reconcile_orphans_pg.py`(新) | +2 用例(TC-13、14):PostgreSQL 方言路径、并发终态写入者先提交时不被覆盖 |
| `docs/architecture/03-execution-and-logs.md` | 「状态事件与对账」新增「task 收敛与 roll-up」「task 级孤儿修复」两条 |

无 schema 变更、无迁移、无前端与 agent 改动;不新增 decision。

## 评审历程
| 轮次 | 结论 | 关键问题 |
|---|---|---|
| plan-01 | pass | 无问题 |
| impl-01 | pass | 无问题(A 档证据 TC-01 ~ 15 逐条核验,TC-16 行号引用有效,只读静态检查通过) |

## 遗留 minor 及处置
无。

## 验证结果
- `ruff check apps packages`:通过
- `pytest apps/server`(带 `DOPILOT_TEST_DATABASE_URL`):539 passed, 1 skipped
- 根目录全量 `pytest`:804 passed, 1 skipped(基线 782 + 新增 14)

## 生产数据修正(待升级后核验)
本任务合入 → CI 构建 `rabbir/dopilot-with-deps` → 生产升级 → server 首个对账
tick(≤ 5s)把 `6044a26b…` 与 `d1d2c9ae…` roll-up 为 `complete`。核验:
`GET /api/v1/tasks?status=queued` 的 `total` 为 0;两条任务 `status ==
"complete"`、`started_at == "2026-08-25T22:22:21…"`、
`status_detail.reconcile_repair.from == "queued"`;server 日志两行
`repaired by reconcile`。
