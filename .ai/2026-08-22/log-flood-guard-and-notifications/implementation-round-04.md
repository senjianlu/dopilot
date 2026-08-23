---
task: log-flood-guard-and-notifications
round: 04
date: 2026-08-23
---

# 实现记录:第 04 轮

> 修复轮上限 `impl_fix_max_rounds: 25`(用户授权,见 plan.md);本轮为第 3 个
> 修复轮(NN=04 < 25)。只修复 `review-round-03-fail.md` 的问题。

## 本轮改动

| 文件 | 改动摘要 |
|---|---|
| `apps/agent/dopilot_agent/redis/logs.py` | R-01:截断标记纳入令牌桶——`_marker_allowed()` 要求剩余额度 ≥ 标记长度(桶永远装不下标记的退化配置只允许从满桶发出),额度不足则本 tick 不发、等下一 tick;发出后 `_spend(len(marker))` 并计入 `publish_attempt` 返回总数;模块 docstring 注明"正文与标记一律记账" |
| `apps/server/dopilot_server/app.py` | R-02:`stream_guard.start()` 移到 retention 之后,接线顺序与 plan TC-32 一致(`dispatcher → event_consumer → log_consumer → reconcile → retention → stream_guard`);启动裁剪 `enforce_once` 仍在任何消费者之前 |
| `docs/architecture/05-deployment.md` | R-03:回滚段改为 5 步编号列表,第 ④ 步给出可执行命令:`docker volume rm` 两卷 → `docker compose create` 重建带 compose 标签的空卷 → 对 `${P}_dopilot-db`、`${P}_dopilot-server-data` 各一条 `docker run … tar xzf … -C /dst` 恢复命令 |
| `docs/architecture/03-execution-and-logs.md` | R-01:闸 2 描述补"正文与截断标记一律记账、额度不足时标记等下一 tick" |
| `apps/web/components/layout/notification-bell.tsx` | R-04:未读数改为复用 shadcn `Badge variant="destructive"`,删掉手写 `<span>` 与硬编码 `text-white`(前景色由 Badge 变体语义承担;本项目主题没有 `--destructive-foreground` token,`text-destructive-foreground` 类不会生成) |
| `apps/agent/tests/test_log_publisher.py` | R-01 回归 `test_markers_are_bucket_accounted_under_starved_allowance`:额度 < 一条标记 + 3 个同时达 cap 的执行,逐 tick 按 **Redis 实际落地 entry 字节**断言 ≤ 桶容量、饿额 tick 零标记、补满后 3 条标记各自扣减 |
| `apps/server/tests/test_maintenance_guard.py` | R-02:TC-32 改为断言完整顺序前缀 `[enforce_once, calibrate, dispatcher, event_consumer, log_consumer, reconcile, retention, stream_guard]`(不再 membership) |
| `apps/server/tests/test_runbook.py` | R-03:TC-31c 对每个卷分别匹配一条 `-v <卷>:/src … tar czf` 备份命令与一条 `-v <卷>:/dst … tar xzf` 恢复命令(备份命令不再能满足恢复分支),并断言回滚顺序 downgrade → 旧 compose → `volume rm` → `tar xzf` → `up -d` |
| `apps/web/components/layout/__tests__/notification-bell.test.tsx` | R-04:TC-28 断言徽标 `data-slot="badge"`、`data-variant="destructive"` |

## 修复对照

| 评审问题编号 | 严重度 | 修复方式 |
|---|---|---|
| R-01 | major | 标记纳入 allowance 判定、扣减与返回总数;新增饿额多执行回归用例,按 Redis 实际 entry 字节断言 |
| R-02 | major | 接线顺序改回 plan 顺序;TC-32 断言精确顺序前缀 |
| R-03 | major | 回滚段写出两卷各自的删除/重建/`tar xzf` 命令;TC-31c 分别匹配两条恢复命令与顺序 |
| R-04 | minor | 复用 `Badge`,去掉手写 span 与 `text-white`;TC-28 断言组件来源 |

## 测试结果

本轮重新生成:`tc-03-04-log-publisher.txt`、`tc-13-14-15-16-27-32-maintenance-guard.txt`、
`tc-31b-31c-runbook.txt`、`tc-28-web-notification-bell.txt`、`tc-30-*`(ruff / 全量
pytest / web lint / typecheck / test)。其余证据沿用第 02/03 轮(对应代码未变)。

| 编号 | 档位 | 结果 | 证据 |
|---|---|---|---|
| TC-01 | A | pass | `tc-01-01b-01c-01h-02-02b-06-08-09-01f-log-flood.txt` |
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
| TC-04 | A | pass | 同上(含 R-01 回归:标记记账) |
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
| TC-14 | A | pass | `tc-13-…-maintenance-guard.txt` + `tc-14-r04-maintenance-api-gauge.txt` |
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
| TC-28 | A | pass | `tc-28-web-notification-bell.txt`(含 Badge 组件断言) |
| TC-29 | A | pass | `tc-29-web-schedules-badge.txt` |
| TC-30 | A | pass | `tc-30-ruff.txt`(All checks passed)、`tc-30-pytest-full.txt`(735 passed, 1 skipped — 既有 `test_resource_stats.py:1040` 依赖 `DOPILOT_TEST_PG_URL`,本任务未触及)、`tc-30-web-lint.txt`、`tc-30-web-typecheck.txt`、`tc-30-web-test.txt`(98 passed) |
| TC-31 | A | pass | `tc-31-compose-config.txt` |
| TC-31b | A | pass | `tc-31b-31c-runbook.txt` |
| TC-31c | A | pass | 同上(两卷各一条备份 + 一条恢复命令,回滚顺序断言) |
| TC-32 | A | pass | `tc-13-…-maintenance-guard.txt`(精确顺序前缀) |
| TC-33 | A | pass | `tc-33-01h-agent-main-heartbeat.txt` |

## 与方案的偏差

第 01–03 轮记录的偏差 1–12 不变。本轮新增:

13. **标记的桶记账退化分支**(R-01):plan 只写"标记一条、令牌桶限速";实现
    在标记长度 > 桶容量(`rate` 小于标记长度的极端配置)时允许从满桶发出,
    避免该执行永远发不出标记而无法进入 `log_capped`。默认配置(2MiB/s)不会
    触发该分支。
14. **回滚用 `docker compose create` 重建卷**(R-03):plan 未规定卷重建方式;
    选用 compose 自建空卷以保留 compose 标签,避免 `docker volume create` 手建
    卷被 compose 视为外部卷而告警。
