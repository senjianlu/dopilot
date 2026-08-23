---
task: log-flood-guard-and-notifications
round: 06
date: 2026-08-23
---

# 实现记录:第 06 轮

> 修复轮上限 `impl_fix_max_rounds: 25`(用户授权,见 plan.md);本轮为第 5 个
> 修复轮(NN=06 < 25)。只修复 `review-round-05-fail.md` 的问题。

## 本轮改动

| 文件 | 改动摘要 |
|---|---|
| `apps/agent/dopilot_agent/scrapyd/stats.py` | R-01:`parse_scrapy_stats` 只解析**最后一个** `Dumping Scrapy stats` 标记行之后、scrapy 漂亮打印字典的连续行(以 `{` 或 `'` 开头,直到以 `}` 结尾的行);无块 → `(None, None)`;块被截断到 `log_count/ERROR` 之前 → `error_count=None`(不再按 0);业务日志中的同名字段不参与解析 |
| `apps/agent/dopilot_agent/state/store.py` | R-02:新增 `mark_canceled(execution_id)`:重读状态再置 `canceled=True`(合并写,幂等) |
| `apps/agent/dopilot_agent/runners/scrapyd.py` | R-02:`stop()` 在 `await cancel()` 之后改调 `mark_canceled`,不再把 await 前读取的陈旧 `AttemptState` 整体写回(否则会清掉发布端并发置位的 `log_capped`) |
| `docs/architecture/03-execution-and-logs.md` | R-01:stats 解析范围说明 |
| `apps/agent/tests/test_scrapyd_stats.py` | R-01:三条回归——无块但业务行含 `finish_reason`/`log_count/ERROR` → `(None, None)`;块之后的业务行被忽略;块被 size-cap 截断到 ERROR 键之前 → `error_count None`、`finish_reason` 保留 |
| `apps/agent/tests/test_runner.py` | R-02:`test_stop_merges_state_and_never_clears_log_capped`:barrier 卡住 `cancel()`,期间 `LogPublisher` 达 cap 发标记并置 `log_capped`;stop 完成后 `canceled` 与 `log_capped` 同为 True,再次 `publish_once` 不新增 entry,标记恰一条,该执行 Redis 累计字节 ≤ cap(已验证回退为旧写法时该用例失败) |

## 修复对照

| 评审问题编号 | 严重度 | 修复方式 |
|---|---|---|
| R-01 | major | 解析限定在最后一个 stats 块的字典行内,无块返回 `(None, None)`;补三条 TC-05 回归 |
| R-02 | major | `stop()` 经 `mark_canceled` 重读合并;补 barrier 并发回归(标记恰一条、字节 ≤ cap) |

## 测试结果

本轮重新生成:`tc-05-scrapyd-stats.txt`、新增 `tc-02-r02-runner-stop-merge.txt`
(`test_runner.py` + `test_state_store.py`)、`tc-30-ruff.txt`、`tc-30-pytest-full.txt`。
其余证据沿用第 02–05 轮(对应代码未变;web 未改动)。

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
| TC-02 | A | pass | `tc-01-…-log-flood.txt`;R-02 取消/发布并发回归见 `tc-02-r02-runner-stop-merge.txt` |
| TC-02b | A | pass | `tc-01-…-log-flood.txt` + `tc-18-…-outcomes.txt` + `tc-10-…-log-guard.txt` |
| TC-03 | A | pass | `tc-03-04-log-publisher.txt` |
| TC-04 | A | pass | 同上 |
| TC-05 | A | pass | `tc-05-scrapyd-stats.txt`(含 R-01 回归:无块同名字段 → None/None、块后业务行忽略、块被截断 → error_count None) |
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
| TC-28 | A | pass | `tc-28-web-notification-bell.txt` |
| TC-29 | A | pass | `tc-29-web-schedules-badge.txt` |
| TC-30 | A | pass | `tc-30-ruff.txt`(All checks passed)、`tc-30-pytest-full.txt`(743 passed, 1 skipped — 既有 `test_resource_stats.py:1040` 依赖 `DOPILOT_TEST_PG_URL`,本任务未触及)、`tc-30-web-lint.txt`、`tc-30-web-typecheck.txt`、`tc-30-web-test.txt`(98 passed) |
| TC-31 | A | pass | `tc-31-compose-config.txt` |
| TC-31b | A | pass | `tc-31b-31c-runbook.txt` |
| TC-31c | A | pass | 同上 |
| TC-32 | A | pass | `tc-13-…-maintenance-guard.txt` |
| TC-33 | A | pass | `tc-33-01h-agent-main-heartbeat.txt` |

## 与方案的偏差

第 01–05 轮记录的偏差 1–17(第 13 条已撤销)不变。本轮新增:

18. **stats 块截断语义**(R-01):plan TC-05 只写"被截断无 stats → None";实现
    进一步规定"有块但块体在 `log_count/ERROR` 之前被截断"也返回
    `error_count=None`(而非因'块存在'按 0),避免截断日志被误判为无错。
