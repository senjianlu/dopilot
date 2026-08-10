---
task: event-stall-heartbeat
round: 01
date: 2026-08-10
---

# 实现记录:第 01 轮

## 本轮改动

| 文件 | 改动摘要 |
|---|---|
| packages/protocol/dopilot_protocol/streams.py | `AgentEventType` 新增 `heartbeat = "attempt.heartbeat"`(非 terminal,docstring 说明存活语义) |
| apps/server/dopilot_server/services/events.py | `apply_event` 对 heartbeat 前置分支:仅刷新 `last_event_at`/清 `stalled_at`;`EXEC_LOST` 时经 `reclaim_ever_issued` 持久去重投递 reclaim(新投递才写 `OUTCOME_RECLAIM_REQUESTED` 审计);新增 `OUTCOME_HEARTBEAT` 常量(仅返回值不落库) |
| apps/server/dopilot_server/services/outbox.py | 新增共享助手 `reclaim_ever_issued`(type=stop、intent=reclaim、不过滤状态) |
| apps/server/dopilot_server/redis/reconcile.py | 删除本地 `_reclaim_issued`(语义相同),`finalize_drained_logs` 改用 `outbox_svc.reclaim_ever_issued`;移除不再使用的 `CommandOutbox` 导入 |
| apps/server/dopilot_server/config/settings.py | `lost_after_stalled_seconds` 默认 900 → 3600(注释说明新语义) |
| apps/server/dopilot_server/redis/consumers.py | `EventConsumer._apply_one` 毒丸容错:解析失败记 warning 后 XACK 跳过 |
| apps/agent/dopilot_agent/config/settings.py | `AgentSettings` 新增 `attempt_heartbeat_interval_seconds: int = 60`(0 关闭) |
| apps/agent/dopilot_agent/redis/events.py | `EventPublisher.emit_heartbeat`:直接 XADD 不落持久 outbox,失败吞掉返回 False |
| apps/agent/dopilot_agent/redis/commands.py | `reconcile_started_attempts` 心跳挂载:scrapy `listjobs` 确认 running 才发;wheel 在 `_inproc_wheel` 且子进程存活才发;`_maybe_emit_heartbeat` 按 monotonic 限频、仅成功才记时戳;terminal/`_release_execution` 清理限频记录 |
| apps/agent/dopilot_agent/main.py | 将 `attempt_heartbeat_interval_seconds` 接入 `CommandConsumer` 构造 |
| configs/server.example.toml、configs/server.docker.toml | `lost_after_stalled_seconds` 样例 3600 + 语义注释 |
| configs/agent.example.toml | 新增 `attempt_heartbeat_interval_seconds = 60` 条目与注释 |
| docs/architecture/03-execution-and-logs.md | 回写运行期心跳语义、lost 心跳触发 reclaim、毒丸容错 |
| docs/architecture/04-configuration.md | `[agents]`/`[agent]` 配置表补新配置项与新默认值 |
| docs/architecture/05-deployment.md | 新增「升级顺序:server 先于 agent」小节(一体栈/远端 agent 可执行顺序 + 顺序颠倒自愈) |
| packages/protocol/tests/test_stream_schemas.py | TC-01 用例(heartbeat 类型属性 + wire 往返) |
| apps/server/tests/test_event_consumer.py | TC-02/03/11/12 用例(刷新无审计、未知 execution、lost 终生一条 reclaim 含 sent 场景、毒丸跳过) |
| apps/server/tests/test_reconcile_redis.py | TC-04 用例(2 小时长任务 + 新鲜心跳不误杀,对照组停滞仍捕获) |
| apps/server/tests/test_config.py、apps/agent/tests/test_config.py | TC-05 用例(server 默认 3600;agent 默认 60 + TOML 覆盖) |
| apps/agent/tests/test_command_consumer.py | TC-06/07/08/09 用例(限频与终态、scrapyd 不可达不发、wheel 存活判定、XADD 失败吞掉不落 outbox 且下轮重试) |

## 修复对照

(第 1 轮,不适用)

## 测试结果

| 编号 | 档位 | 结果 | 证据 |
|---|---|---|---|
| TC-01 | A | pass | evidence/tc-01-protocol-stream-schemas.txt(exit_code=0) |
| TC-02 | A | pass | evidence/tc-02-03-11-12-server-event-consumer.txt(`test_heartbeat_refreshes_stall_clock_without_audit`,exit_code=0) |
| TC-03 | A | pass | evidence/tc-02-03-11-12-server-event-consumer.txt(`test_heartbeat_unknown_execution_skips_without_audit`) |
| TC-04 | A | pass | evidence/tc-04-server-reconcile.txt(`test_old_attempt_with_fresh_heartbeat_event_not_lost`,exit_code=0) |
| TC-05 | A | pass | evidence/tc-05-config-defaults.txt(server 3600 / agent 60 + TOML 45 覆盖,exit_code=0) |
| TC-06 | A | pass | evidence/tc-06-07-08-09-agent-heartbeat.txt(`test_reconcile_running_attempt_heartbeat_rate_limited`,exit_code=0) |
| TC-07 | A | pass | evidence/tc-06-07-08-09-agent-heartbeat.txt(`test_reconcile_no_heartbeat_when_scrapyd_unreachable`) |
| TC-08 | A | pass | evidence/tc-06-07-08-09-agent-heartbeat.txt(`test_reconcile_wheel_heartbeat_only_when_child_alive`) |
| TC-09 | A | pass | evidence/tc-06-07-08-09-agent-heartbeat.txt(`test_heartbeat_xadd_failure_swallowed_and_not_outboxed`) |
| TC-10 | A | pass | evidence/tc-10-full-pytest.txt(644 passed, 1 skipped,exit_code=0;skip 为既有 `DOPILOT_TEST_PG_URL not set` 条件跳过,与本任务无关)、evidence/tc-10-ruff.txt(All checks passed,exit_code=0) |
| TC-11 | A | pass | evidence/tc-02-03-11-12-server-event-consumer.txt(`test_heartbeat_on_server_lost_reclaims_at_most_once`,含 sent 后二次心跳断言) |
| TC-12 | A | pass | evidence/tc-02-03-11-12-server-event-consumer.txt(`test_event_consumer_skips_unparseable_entry`) |

## 与方案的偏差

1. **TC-09 断言强于 plan**:plan 允许"失败后下一轮再发",实现让
   `emit_heartbeat` 返回 bool、仅成功才记限频时戳,测试额外断言了
   "失败不记时戳、恢复后下一轮立即重试"。属 plan §3 既定设计的落实,
   非行为偏差。
2. **环境修复(不入库)**:本机 `.venv` 的 editable 安装指向仓库迁移前的
   旧路径(`/home/rabbir/dopilot`),已重新
   `pip install --no-deps -e packages/protocol -e apps/server -e apps/agent`
   指到现路径;不涉及任何仓库文件改动。
3. 其余按 plan 实现,无偏差。
