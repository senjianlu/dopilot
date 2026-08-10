---
task: event-stall-heartbeat
round: 02
date: 2026-08-10
---

# 实现记录:第 02 轮

## 本轮改动

| 文件 | 改动摘要 |
|---|---|
| apps/agent/dopilot_agent/redis/commands.py | `_await_wheel` 进锁后立即 `_last_attempt_heartbeat.pop(execution_id, None)`(自然终态/已被他路径终态均覆盖);`_handle_stop` 入口统一 pop(cancel 与 reclaim 的 scrapy/wheel 全部路径) |
| apps/agent/tests/test_command_consumer.py | 新增 `test_wheel_natural_terminal_clears_heartbeat_stamp`(FakeWheelRunner 补 `wait()`,wheel 自然结束清记录)与 `test_stop_cancel_clears_heartbeat_stamp`(cancel 清记录) |

## 修复对照

| 评审问题编号 | 严重度 | 修复方式 |
|---|---|---|
| R-01 | major | wheel wait 终态路径与 stop(cancel/reclaim)全路径统一清除 `_last_attempt_heartbeat`(pop 幂等,已终态/无记录时无害);连同既有的 scrapy reconcile 终态清理与 `_release_execution` 清理,所有终态出口均已覆盖。补两条测试分别覆盖 wheel 自然结束与 cancel |

## 测试结果

| 编号 | 档位 | 结果 | 证据 |
|---|---|---|---|
| TC-01 | A | pass | evidence/tc-01-protocol-stream-schemas.txt(exit_code=0;本轮未触及 protocol,沿用第 01 轮证据) |
| TC-02 | A | pass | evidence/tc-02-03-11-12-server-event-consumer.txt(本轮未触及 server,沿用第 01 轮证据) |
| TC-03 | A | pass | 同上 |
| TC-04 | A | pass | evidence/tc-04-server-reconcile.txt(沿用第 01 轮证据) |
| TC-05 | A | pass | evidence/tc-05-config-defaults.txt(沿用第 01 轮证据) |
| TC-06 | A | pass | evidence/r02-tc-06-07-08-09-agent-heartbeat.txt(21 passed,exit_code=0) |
| TC-07 | A | pass | evidence/r02-tc-06-07-08-09-agent-heartbeat.txt |
| TC-08 | A | pass | evidence/r02-tc-06-07-08-09-agent-heartbeat.txt |
| TC-09 | A | pass | evidence/r02-tc-06-07-08-09-agent-heartbeat.txt |
| TC-10 | A | pass | evidence/r02-tc-10-full-pytest.txt(646 passed, 1 skipped,exit_code=0;skip 为既有 `DOPILOT_TEST_PG_URL not set`)、evidence/r02-tc-10-ruff.txt(All checks passed,exit_code=0) |
| TC-11 | A | pass | evidence/tc-02-03-11-12-server-event-consumer.txt(沿用第 01 轮证据) |
| TC-12 | A | pass | 同上 |

## 与方案的偏差

无新增偏差(第 01 轮记录的两点仍然有效)。R-01 修复属 plan §3
「terminal 发出与 `_release_execution` 时清理」既定要求的补全,未改变方案
设计。
