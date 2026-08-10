---
task: event-stall-heartbeat
date: 2026-08-10
rounds: 2
verdict: pass
---

# 任务小结:补运行期 attempt 心跳,修复 15 分钟 event-stall 误杀长任务

## 改动

| 文件 | 摘要 |
|---|---|
| packages/protocol/dopilot_protocol/streams.py | `AgentEventType` 新增 `heartbeat = "attempt.heartbeat"`(非 terminal 存活信号) |
| apps/server/dopilot_server/services/events.py | `apply_event` 心跳分支:刷新 `last_event_at`/清 `stalled_at`,不进状态机不写审计;`EXEC_LOST` 时按「曾投递过即不再投」投递 reclaim(新投递才写审计) |
| apps/server/dopilot_server/services/outbox.py | 新增 `reclaim_ever_issued` 共享助手(状态盲查) |
| apps/server/dopilot_server/redis/reconcile.py | `finalize_drained_logs` 复用该助手,删除重复实现 |
| apps/server/dopilot_server/config/settings.py | `lost_after_stalled_seconds` 默认 900 → 3600 |
| apps/server/dopilot_server/redis/consumers.py | 事件消费者毒丸容错:解析失败记 warning 后 XACK 跳过 |
| apps/agent/dopilot_agent/config/settings.py | 新增 `attempt_heartbeat_interval_seconds`(默认 60,0 关闭) |
| apps/agent/dopilot_agent/redis/events.py | `emit_heartbeat`:直接 XADD 不落持久 outbox,失败吞掉返回 False |
| apps/agent/dopilot_agent/redis/commands.py | 存活确认循环挂心跳(scrapyd 列出 running / wheel 子进程存活才发,monotonic 限频,仅成功记时戳);所有终态出口清限频记录 |
| apps/agent/dopilot_agent/main.py | 新配置接入 `CommandConsumer` |
| configs/*.toml(3 份样例) | 新默认值与新配置项 + 注释 |
| docs/architecture/03/04/05 | 回写心跳语义、配置项、升级顺序约束(server 先于 agent) |
| 测试(protocol/server/agent 共 6 个测试文件) | plan 12 条用例全 A 档落地 + R-01 修复回归 2 条 |

## 评审历程

plan 阶段(用户授权上限 15 轮,实际 4 轮;另有 1 次 Codex 容量不足的执行
失败重试,不计轮次):

| 轮次 | 结论 | 关键问题 |
|---|---|---|
| 1 | fail | plan-blocker:心跳短路绕过 server-lost 恢复后的 reclaim 保护 → 改为 lost 分支触发回收 |
| 2 | fail | plan-blocker:评审侧无法见到用户 15 轮授权 → plan 正文记录授权;major:「统一镜像天然保证升级顺序」不成立 → 可执行升级顺序 + 毒丸容错 |
| 3 | fail | major:reclaim 去重漏 `sent` 态会周期重复投递 → 改「曾投递过即不再投」持久去重 |
| 4 | pass | — |

实现阶段(上限 15 轮,实际 2 轮):

| 轮次 | 结论 | 关键问题 |
|---|---|---|
| 1 | fail | major R-01:wheel 终态/stop 路径未清心跳限频记录,长期运行累积 → 全终态出口统一 pop + 2 条回归测试 |
| 2 | pass | — |

## 遗留 minor 及处置

无(最后一轮评审问题清单为空)。
