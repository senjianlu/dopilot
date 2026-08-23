---
task: log-flood-guard-and-notifications
round: 05
date: 2026-08-23
---

# 实现记录:第 05 轮

> 修复轮上限 `impl_fix_max_rounds: 25`(用户授权,见 plan.md);本轮为第 4 个
> 修复轮(NN=05 < 25)。只修复 `review-round-04-fail.md` 的问题。

## 本轮改动

| 文件 | 改动摘要 |
|---|---|
| `apps/agent/dopilot_agent/config/settings.py` | R-01:新增 `LOG_PUBLISH_RATE_MIN = 128`,`log_publish_rate_bytes_per_second` 字段校验:必须为 0(不限)或 ≥ 128(2 秒桶 ≥ 256B,能装下任何 cap 值的标记 ≤ 160B),负数 / 1–127 加载即拒绝 |
| `apps/agent/dopilot_agent/redis/logs.py` | R-01:删掉上轮"满桶放行"分支——`_marker_allowed` 只看 `allowance >= len(marker)`;构造时若 `rate > 0` 且桶容量 < 标记长度直接 `ValueError`(双保险),标记永不超桶 |
| `apps/server/dopilot_server/redis/dispatcher.py` | R-02:`reconcile_sent_once` 回退 `pending` 时重开窗口:`give_up_at`/`expire_at = now + 900s`,`retry_count = 0`,同一 tick 的 `_process_row` 走重投而非 `dispatch_timeout` |
| `apps/agent/dopilot_agent/janitor.py` | R-03:候选阈值改为 `size > cap`;新增 `already_capped()`(读 cap 之后的尾部,精确等于"一条 dopilot 截断标记"才视为已处理)用于扫描跳过与 `_truncate_log` 幂等;`cap+1` 无标记文件会被截回 |
| `apps/server/dopilot_server/services/maintenance.py` | R-03:候选 SQL 改为 `size_bytes > cap AND (integrity 非 truncated OR size_bytes > cap + 标记)`(已结算的 `cap+标记` 行不挤占 `limit` 窗口);`_truncate_file` 以 `_already_capped` 尾部检查为最终幂等守卫,`cap+1` 原始文件被截回并记 `truncation_reason=maintenance` |
| `apps/web/app/(app)/schedules/page.tsx` | R-04:Tooltip 触发器改为 `Badge asChild` 包裹 `<button type="button">`,可 Tab 聚焦、聚焦即显示原因 |
| `docs/architecture/03-execution-and-logs.md`、`04-configuration.md`、`configs/agent.example.toml` | R-01/R-02:速率下限与标记记账、sent 对账重开 give-up 窗口 |
| `apps/agent/tests/test_config.py` | R-01:`test_log_publish_rate_below_marker_capacity_is_rejected`(1 / 127 / -5 拒绝,128 / 0 通过) |
| `apps/agent/tests/test_log_publisher.py` | R-01:`test_marker_never_overshoots_bucket_at_minimum_rate`:(a) `rate=1`(桶 2B < 标记)构造即拒绝、Redis 为空;(b) 最低合法速率 128B/s 下额度 < 标记时标记等待、每 tick Redis 实际落地字节 ≤ 桶、补满后恰一条标记 |
| `apps/server/tests/test_log_guard.py` | R-02:`test_sent_reconcile_requeues_past_give_up_deadline`(`give_up_at` 过期 2h45m 的 `sent` 行、流被清空,单个 `_tick` 后重新 XADD、`retry_count=0`、新窗口 ≥ 14min,task/execution 仍 queued/pending) |
| `apps/server/tests/test_maintenance_guard.py` | R-03:`test_truncate_boundary_cap_plus_one_and_idempotent_marker_state`(`cap+1` 被截、`cap+size-cap 标记` 不动且 mtime 不变、legacy 5000+标记被截;第二遍 0) |
| `apps/agent/tests/test_janitor.py` | R-03:TC-17 增 (f) `CAP+1` 截回、(g) `CAP+标记` 不入候选(无锁、内容与 mtime 不变) |
| `apps/web/app/(app)/schedules/__tests__/schedules.test.tsx` | R-04:触发器为 `BUTTON`、Tab 可达并 `toHaveFocus`、聚焦即出现 tooltip 文案 |

## 修复对照

| 评审问题编号 | 严重度 | 修复方式 |
|---|---|---|
| R-01 | major | 配置层拒绝装不下标记的速率 + 发布端删除满桶放行分支并在构造时校验;新增拒绝用例与最低合法速率下 Redis 实际落地字节用例 |
| R-02 | major | sent 对账回退时重开 give-up 窗口与重试额度;新增过期 `give_up_at` 重投用例 |
| R-03 | major | 两端候选阈值改为 `> cap`,尾部标记检查判幂等;两端各补 `cap+1` 与 `cap+标记` 用例 |
| R-04 | minor | Tooltip 触发器改为可聚焦按钮(`Badge asChild`);补键盘聚焦断言 |

## 测试结果

本轮重新生成:`tc-03-04`、`tc-10-…-log-guard`、`tc-13-…-maintenance-guard`、`tc-13b-13c`、
`tc-17`、`tc-26`、`tc-29`、`tc-30-*`。其余证据沿用第 02–04 轮(对应代码未变)。

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
| TC-04 | A | pass | 同上(含 R-01 回归:标记记账;最低合法速率下标记不超桶、过低速率构造即拒绝) |
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
| TC-13 | A | pass | `tc-13-14-15-16-27-32-maintenance-guard.txt`(含 R-03 `cap+1` 边界与 `cap+标记` 幂等用例) |
| TC-13b | A | pass | `tc-13b-13c-log-locking-postgres.txt` |
| TC-13c | A | pass | 同上 |
| TC-14 | A | pass | `tc-13-…-maintenance-guard.txt` + `tc-14-r04-maintenance-api-gauge.txt` |
| TC-15 | A | pass | `tc-13-…-maintenance-guard.txt` |
| TC-16 | A | pass | 同上 |
| TC-17 | A | pass | `tc-17-janitor.txt`(含 R-03 `CAP+1` 截回与 `CAP+标记` 不触碰) |
| TC-18 | A | pass | `tc-18-19-19b-19c-20-20b-20c-21-06b-23-outcomes.txt` |
| TC-19 | A | pass | 同上 |
| TC-19b | A | pass | 同上 |
| TC-19c | A | pass | 同上 |
| TC-20 | A | pass | 同上 |
| TC-20b | A | pass | 同上 |
| TC-20c | A | pass | 同上 |
| TC-20d | A | pass | `tc-20d-20f-outcomes-postgres.txt` |
| TC-20e | A | pass | `tc-10-…-log-guard.txt`(含 R-02 过期 `give_up_at` 重投用例) |
| TC-20f | A | pass | `tc-20d-20f-outcomes-postgres.txt` |
| TC-21 | A | pass | `tc-18-…-outcomes.txt` |
| TC-22 | A | pass | `tc-22-reconcile-reload-after-commit.txt` |
| TC-23 | A | pass | `tc-23-schedules-api.txt` + `tc-18-…-outcomes.txt` |
| TC-24 | A | pass | `tc-24-notifications.txt` |
| TC-25 | A | pass | `tc-25-alembic-upgrade-downgrade-upgrade.txt`(`assets/tc-25-alembic-roundtrip.sh`) |
| TC-26 | A | pass | `tc-26-config-agent-server.txt`(含 R-01 速率下限拒绝用例) |
| TC-27 | A | pass | `tc-13-…-maintenance-guard.txt` |
| TC-28 | A | pass | `tc-28-web-notification-bell.txt` |
| TC-29 | A | pass | `tc-29-web-schedules-badge.txt`(含 R-04 键盘 Tab 聚焦断言) |
| TC-30 | A | pass | `tc-30-ruff.txt`(All checks passed)、`tc-30-pytest-full.txt`(739 passed, 1 skipped — 既有 `test_resource_stats.py:1040` 依赖 `DOPILOT_TEST_PG_URL`,本任务未触及)、`tc-30-web-lint.txt`、`tc-30-web-typecheck.txt`、`tc-30-web-test.txt`(98 passed) |
| TC-31 | A | pass | `tc-31-compose-config.txt` |
| TC-31b | A | pass | `tc-31b-31c-runbook.txt` |
| TC-31c | A | pass | 同上 |
| TC-32 | A | pass | `tc-13-…-maintenance-guard.txt` |
| TC-33 | A | pass | `tc-33-01h-agent-main-heartbeat.txt` |

## 与方案的偏差

第 01–04 轮记录的偏差 1–14 中,**第 13 条(标记满桶放行)本轮撤销**:改为配置
下限 + 构造校验,不再存在任何超桶路径。其余不变。本轮新增:

15. **速率配置下限**(R-01):plan 只写"0 = 不限";实现追加"非 0 时 ≥ 128"的
    加载期校验(pydantic `ValidationError`),以保证桶恒能容纳一条标记。默认
    2MiB/s 不受影响。
16. **sent 对账重开窗口**(R-02):plan 写"回退 pending 重投";实现明确重置
    `give_up_at`/`expire_at`(+900s)与 `retry_count`,否则长停机后的回退行会在
    同一 tick 被判 `dispatch_timeout`。
17. **服务端截断候选 SQL**(R-03):为避免已结算的 `cap+标记` 行长期挤占
    `limit=500` 窗口,候选条件在 `size_bytes > cap` 之上加了
    "integrity 非 truncated 或仍 > cap+标记";磁盘尾部检查仍是最终幂等守卫。
