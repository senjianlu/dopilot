---
task: log-flood-guard-and-notifications
round: 03
date: 2026-08-23
---

# 实现记录:第 03 轮

> 修复轮上限 `impl_fix_max_rounds: 25`(用户授权,见 plan.md);本轮为第 2 个
> 修复轮(NN=03 < 25)。只修复 `review-round-02-fail.md` 的问题。

## 本轮改动

| 文件 | 改动摘要 |
|---|---|
| `apps/server/dopilot_server/services/maintenance.py` | R-01:`_sealed_terminal_task_ids` 额外排除"来自 `schedule_timer`/`schedule_trigger_now` 且 `outcome_recorded_at IS NULL`"的任务(记录器分批 200 条、与 sweep 并发,未入账的任务永不被保留清扫删除);R-02:`evict_logs_dir_to_budget` 对本轮淘汰失败(`summary.tasks == 0`,正文 unlink 失败、行已 `expired` 留待下轮)的候选记入 `skipped` 并继续下一个,每轮最多 `max_victims=500` 次尝试,结果增 `skipped` |
| `apps/agent/dopilot_agent/redis/commands.py` | R-03:`_truncate_local_log` 对任何 ≥ cap 的文件都截到 `cap` 并追加**恰一次**标记(首次 cap+1 也截);文件已是 `cap + marker` 且尾部确为标记时不再改写(幂等) |
| `apps/server/dopilot_server/services/logs.py` | R-05:去掉文件尾多余空行(`git diff --check` 干净) |
| `docs/architecture/05-deployment.md` | R-04:删除与 Redis 容器 `mem_limit` 冲突的旧"生产收缩 runbook"(先起新 server 再裁剪),改为「已膨胀的部署升级到本版本」:统一指向停机 → 成对备份 → 删 Redis 卷 → `up -d`;未膨胀时可直接滚动升级 |
| `apps/agent/tests/test_log_flood.py` | R-03:TC-01 断言文件内容 == `b"x"*cap + marker`、长度精确、重复一轮仍只有一个标记 |
| `apps/server/tests/test_maintenance_guard.py` | R-01:`test_cleanup_keeps_unrecorded_schedule_tasks_until_recorded`(250 条旧的未入账调度任务 > 一个记录器批次,清扫只删 direct 任务;记录器两批后才可删,计数 250 无缺失);R-02:`test_evict_skips_failing_victim_and_continues`(首个 unlink 失败被跳过、其余继续淘汰到预算内,失败行保持 `expired`) |
| `apps/server/tests/test_runbook.py` | 章节边界更新为新标题 |

## 修复对照

| 评审问题编号 | 严重度 | 修复方式 |
|---|---|---|
| R-01 | major | 清扫 eligibility 排除未入账的调度任务;回归用例覆盖 >200 条与分批记录 |
| R-02 | major | 淘汰循环跳过失败候选并继续(有界 500 次);回归用例"首个失败、第二个成功" |
| R-03 | major | 首次达 cap 即截至 cap 并只追加一次标记;TC-01 断言精确内容/长度/幂等 |
| R-04 | major | 旧收缩 runbook 重写为指向事故恢复 runbook 的升级指引,不再要求先启动 server |
| R-05 | minor | 去掉 `services/logs.py` 文件尾空行 |

## 测试结果

本轮受影响的证据文件已重新生成;其余沿用第 02 轮(代码未变)。全量回归重跑。

| 编号 | 档位 | 结果 | 证据 |
|---|---|---|---|
| TC-01 | A | pass | `tc-01-01b-01c-01h-02-02b-06-08-09-01f-log-flood.txt`(精确 `cap + marker`、幂等) |
| TC-01b | A | pass | 同上 |
| TC-01c | A | pass | 同上 |
| TC-01d | A | pass | `tc-01d-01e-01g-logcap.txt` |
| TC-01e | A | pass | 同上 |
| TC-01f | A | pass | `tc-01f-packaging.txt` + `tc-01-…-log-flood.txt` |
| TC-01g | A | pass | `tc-01d-01e-01g-logcap.txt` |
| TC-01h | A | pass | `tc-01-…-log-flood.txt` + `tc-33-01h-agent-main-heartbeat.txt` |
| TC-01i | A | pass | `tc-01i-logcap-install.txt` |
| TC-02 | A | pass | `tc-01-…-log-flood.txt` |
| TC-02b | A | pass | `tc-01-…-log-flood.txt` + `tc-18-…-outcomes.txt` + `tc-10-…-log-guard.txt` |
| TC-03 | A | pass | `tc-03-04-log-publisher.txt` |
| TC-04 | A | pass | 同上 |
| TC-05 | A | pass | `tc-05-scrapyd-stats.txt` |
| TC-06 | A | pass | `tc-01-…-log-flood.txt` |
| TC-06b | A | pass | `tc-18-…-outcomes.txt` |
| TC-07 | A | pass | `tc-07-protocol.txt` |
| TC-08 | A | pass | `tc-01-…-log-flood.txt` |
| TC-09 | A | pass | 同上 |
| TC-10 | A | pass | `tc-10-11-11b-11c-12-20e-log-guard.txt` |
| TC-11 | A | pass | 同上 |
| TC-11b | A | pass | 同上 |
| TC-11c | A | pass | 同上 |
| TC-12 | A | pass | 同上 |
| TC-13 | A | pass | `tc-13-14-15-16-27-32-maintenance-guard.txt` |
| TC-13b | A | pass | `tc-13b-13c-log-locking-postgres.txt` |
| TC-13c | A | pass | 同上 |
| TC-14 | A | pass | `tc-13-…-maintenance-guard.txt`(含 R-01/R-02 回归)+ `tc-14-r04-maintenance-api-gauge.txt` |
| TC-15 | A | pass | `tc-13-…-maintenance-guard.txt` |
| TC-16 | A | pass | 同上 |
| TC-17 | A | pass | `tc-17-janitor.txt` |
| TC-18 | A | pass | `tc-18-19-19b-19c-20-20b-20c-21-06b-23-outcomes.txt` |
| TC-19 | A | pass | 同上 |
| TC-19b | A | pass | 同上 |
| TC-19c | A | pass | 同上 |
| TC-20 | A | pass | 同上 |
| TC-20b | A | pass | 同上 |
| TC-20c | A | pass | 同上 |
| TC-20d | A | pass | `tc-20d-20f-outcomes-postgres.txt` |
| TC-20e | A | pass | `tc-10-…-log-guard.txt` |
| TC-20f | A | pass | `tc-20d-20f-outcomes-postgres.txt` |
| TC-21 | A | pass | `tc-18-…-outcomes.txt` |
| TC-22 | A | pass | `tc-22-reconcile-reload-after-commit.txt` |
| TC-23 | A | pass | `tc-23-schedules-api.txt` + `tc-18-…-outcomes.txt` |
| TC-24 | A | pass | `tc-24-notifications.txt` |
| TC-25 | A | pass | `tc-25-alembic-upgrade-downgrade-upgrade.txt`(`assets/tc-25-alembic-roundtrip.sh`) |
| TC-26 | A | pass | `tc-26-config-agent-server.txt` |
| TC-27 | A | pass | `tc-13-…-maintenance-guard.txt` |
| TC-28 | A | pass | `tc-28-web-notification-bell.txt` |
| TC-29 | A | pass | `tc-29-web-schedules-badge.txt` |
| TC-30 | A | pass | `tc-30-ruff.txt`、`tc-30-pytest-full.txt`(734 passed, 1 skipped — 既有 `test_resource_stats.py:1040` 依赖 `DOPILOT_TEST_PG_URL`,本任务未触及)、`tc-30-web-lint.txt`、`tc-30-web-typecheck.txt`、`tc-30-web-test.txt`(98 passed) |
| TC-31 | A | pass | `tc-31-compose-config.txt` |
| TC-31b | A | pass | `tc-31b-31c-runbook.txt` |
| TC-31c | A | pass | 同上 |
| TC-32 | A | pass | `tc-13-…-maintenance-guard.txt` |
| TC-33 | A | pass | `tc-33-01h-agent-main-heartbeat.txt` |

## 与方案的偏差

第 01/02 轮记录的偏差 1–10 不变。本轮新增:

11. **保留清扫的 eligibility**(R-01):plan 写"全部日志已封口";实现再加一条
    "调度任务须已入账",否则记录器(分批 200)来不及记录的旧任务会被清扫删掉
    而丢失连续计数。收紧方向,不影响非调度任务。
12. **淘汰循环容错**(R-02):plan 写"按最老优先淘汰直至预算内";实现对 unlink
    失败的候选本轮跳过、继续后续候选(每轮 ≤500 次尝试),失败行按既有两阶段
    语义留 `expired` 等下轮重试。
