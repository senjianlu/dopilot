---
task: log-flood-guard-and-notifications
round: 02
date: 2026-08-23
---

# 实现记录:第 02 轮

> 修复轮上限:plan frontmatter `impl_fix_max_rounds: 25`(用户 2026-08-22 明确
> 授权放宽,见 plan.md 顶部授权记录);本轮为第 1 个修复轮(NN=02 < 25)。
> 只修复 `review-round-01-fail.md` 列出的问题,不做评审范围外的改动。

## 本轮改动

| 文件 | 改动摘要 |
|---|---|
| `apps/agent/dopilot_agent/redis/commands.py` | R-03:`_find_crawler_pids` 改为 argv token **精确相等** `f"_job={job_id}" in args`(不再子串匹配);R-05:首次发现洪泛时立即 `_truncate_local_log`(不再等下一 tick) |
| `apps/agent/dopilot_agent/redis/logs.py` | R-06:为截断标记在 cap 内预留空间(`_content_cap = cap - len(marker)`),正文 + 标记总量 ≤ `max_job_log_bytes` |
| `apps/server/dopilot_server/api/v1/maintenance.py` | R-04:`terminal-cleanup` 与 `sweep-now` 两个手工入口从 `request.app.state.logs_gauge` 取运行时 gauge 传入 `cleanup_terminal_data` |
| `apps/web/components/layout/notification-bell.tsx` | R-08:严重度圆点改语义 token(`bg-destructive` / `bg-primary` / `bg-muted-foreground`);加载/空态改用 `Empty` + `Spinner`;菜单项包在 `DropdownMenuGroup` |
| `docs/architecture/04-configuration.md` | R-07:配置表中 server `max_file_bytes` 与 agent `max_job_log_bytes` 统一为 32MiB,并补 `max_total_bytes` 等键 |
| `apps/agent/tests/test_log_flood.py` | R-03 回归用例 `test_job_id_prefix_collision_never_kills_other_crawler`(目标已退出、仅 `_job=<id>2` 存活 → 不杀);R-05:TC-01b 在 t=0 断言文件 ≤ cap + 标记 |
| `apps/agent/tests/test_log_publisher.py` | R-06:TC-03 统计**全部**非 eof entry(含标记)≤ 4096 |
| `apps/server/tests/test_maintenance.py` | R-04:`test_terminal_cleanup_api_settles_shared_logs_gauge`(两个入口删除后 gauge == 实测) |
| `.ai/…/assets/tc-25-alembic-roundtrip.sh`(新) | R-01:TC-25 全部步骤显式命令化(`set -x` 回显),证据由脚本输出构成 |
| `evidence/*` | 全部证据按修复后的代码重新采集;R-02:TC-31 三条 compose 命令完整写出(含环境变量) |

## 修复对照

| 评审问题编号 | 严重度 | 修复方式 |
|---|---|---|
| R-01 | blocker | 新增 `assets/tc-25-alembic-roundtrip.sh`,schema 重置 / 升级前 seed / 结构检查 / 记录器执行全部为可复现命令并经 `set -x` 回显;`evidence/tc-25-alembic-upgrade-downgrade-upgrade.txt` 为其完整输出(每步退出码,9 步全 0) |
| R-02 | blocker | `evidence/tc-31-compose-config.txt` 重新采集:三条 `docker compose -f … config` 命令连同环境变量完整写出,各自完整输出与退出码(3/3 为 0) |
| R-03 | blocker | `_find_crawler_pids` 以 argv token 精确匹配 `_job=<id>`;新增前缀碰撞回归用例(TC-01b 证据文件内 `test_job_id_prefix_collision_never_kills_other_crawler`) |
| R-04 | major | 两个手工维护端点传入 `app.state.logs_gauge`;新增 API 用例验证删除后 gauge == `os.walk` 实测(`evidence/tc-14-r04-maintenance-api-gauge.txt`) |
| R-05 | major | 首次达 cap 即截回(与每 tick 截回同一函数);TC-01b 补 t=0 大小断言 |
| R-06 | major | 发布端为标记预留空间;TC-03 改为统计全部非 eof entry ≤ cap |
| R-07 | minor | docs/04 配置表统一 32MiB |
| R-08 | minor | 语义 token + `Empty`/`Spinner` + `DropdownMenuGroup` |

## 测试结果

证据文件均已按修复后代码重新生成(命令 + 完整输出 + 退出码)。与第 01 轮相比新增
`tc-14-r04-maintenance-api-gauge.txt`;`tc-25-*` 与 `tc-31-*` 形态按 R-01/R-02 重做。

| 编号 | 档位 | 结果 | 证据 |
|---|---|---|---|
| TC-01 | A | pass | `tc-01-01b-01c-01h-02-02b-06-08-09-01f-log-flood.txt` |
| TC-01b | A | pass | 同上(含 t=0 立即截回断言;另含 R-03 回归用例) |
| TC-01c | A | pass | 同上 |
| TC-01d | A | pass | `tc-01d-01e-01g-logcap.txt` |
| TC-01e | A | pass | 同上 |
| TC-01f | A | pass | `tc-01f-packaging.txt` + `tc-01-…-log-flood.txt` |
| TC-01g | A | pass | `tc-01d-01e-01g-logcap.txt` |
| TC-01h | A | pass | `tc-01-…-log-flood.txt` + `tc-33-01h-agent-main-heartbeat.txt` |
| TC-01i | A | pass | `tc-01i-logcap-install.txt` |
| TC-02 | A | pass | `tc-01-…-log-flood.txt` |
| TC-02b | A | pass | `tc-01-…-log-flood.txt` + `tc-18-…-outcomes.txt` + `tc-10-…-log-guard.txt` |
| TC-03 | A | pass | `tc-03-04-log-publisher.txt`(全部 entry ≤ 4096) |
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
| TC-14 | A | pass | `tc-13-…-maintenance-guard.txt`;手工 API 入口的 gauge 结算见 `tc-14-r04-maintenance-api-gauge.txt` |
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
| TC-25 | A | pass | `tc-25-alembic-upgrade-downgrade-upgrade.txt`(`assets/tc-25-alembic-roundtrip.sh` 的 `set -x` 全量输出:9 步退出码全 0;downgrade 后新表/新列消失,再次 upgrade 恢复;升级前 task 回填代际 0 并入账) |
| TC-26 | A | pass | `tc-26-config-agent-server.txt` |
| TC-27 | A | pass | `tc-13-…-maintenance-guard.txt` |
| TC-28 | A | pass | `tc-28-web-notification-bell.txt` |
| TC-29 | A | pass | `tc-29-web-schedules-badge.txt` |
| TC-30 | A | pass | `tc-30-ruff.txt`、`tc-30-pytest-full.txt`(732 passed, 1 skipped — 既有 `test_resource_stats.py:1040` 依赖另一变量 `DOPILOT_TEST_PG_URL`,本任务未触及)、`tc-30-web-lint.txt`、`tc-30-web-typecheck.txt`、`tc-30-web-test.txt`(98 passed) |
| TC-31 | A | pass | `tc-31-compose-config.txt`(三条完整命令,3/3 退出码 0,输出含 `mem_limit`/`memswap_limit`/`--maxmemory 512mb`) |
| TC-31b | A | pass | `tc-31b-31c-runbook.txt` |
| TC-31c | A | pass | 同上 |
| TC-32 | A | pass | `tc-13-…-maintenance-guard.txt` |
| TC-33 | A | pass | `tc-33-01h-agent-main-heartbeat.txt` |

## 与方案的偏差

第 01 轮记录的偏差 1–8 不变。本轮新增:

9. **发布端上限语义**(R-06):plan TC-03 写"内容字节总和 ≤ 4096,最后一条为截断
   标记"。实现改为标记在 cap 内预留空间:正文最多 `cap - len(marker)`,正文 +
   标记 ≤ cap(比 plan 字面更严格,满足评审对"每执行上限"的理解)。
10. **手工维护入口传 gauge**(R-04):plan 未列 `api/v1/maintenance.py`,本轮
    为保持 gauge 精确性加入该文件(两处调用各加一个参数)。
