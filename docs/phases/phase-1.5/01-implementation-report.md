# 01 · 阶段 1.5 实现报告（server↔agent 通信迁移到 Redis Streams）

> 实现/初测：Claude。本报告记录已交付的实现、精确测试结果、对抗性自审发现与处置、以及设计内的接受项。权威设计以 [`docs/refactor/00-redis-streams-agent-communication.md`](../../refactor/00-redis-streams-agent-communication.md) 为准；本阶段任务书见 [`00-brief.md`](./00-brief.md)。后续 review / 集成验收交 Codex。

## 0. 结论

server↔agent 的**任务调度、状态同步、日志回流**三条链路已从阶段 1 的 HTTP pull 破坏性迁移到 **Redis Streams**，健康检查改为 **agent 主动 heartbeat**。原 Scrapy 闭环语义保留，但 server↔agent 不再走 HTTP run/status/tail（egg 部署 `/addversion` 与 agent `/health` 保留为仅有的 HTTP 例外）。

- **测试**：全套 **236 passed**（server 131 / agent+protocol 105），`ruff check` 全绿。
- **迁移**：`0003_redis_streams` 已对真实 PostgreSQL 验证（0001→0002→0003 升级链 + 全量 downgrade/upgrade 往返）。
- **部署**：`deploy/docker/docker-compose.yml` 新增 `redis` 服务（AUTH + AOF），server/agent 均 `depends_on: redis(healthy)` 且注入 `DOPILOT_REDIS_URL`；`docker compose config` 校验通过。
- 单实例约束不变：uvicorn `workers=1`、单 APScheduler、SSE 单进程内存 fan-out、单 Redis 实例（消息总线，非多副本 HA）。agent 不直连 PostgreSQL。

## 1. 按 §4 顺序的交付

| 步 | 交付物 | 关键测试文件 |
|---|---|---|
| 1 | Redis 依赖、`[redis]`/`[agents]` 配置、连接管理（`{server,agent}/redis/client.py`）、`fakeredis` 测试替身 | `test_config.py`, `test_redis_fake.py` |
| 2 | protocol `streams.py`：AgentCommand/Event/LogEvent/Heartbeat + 流拓扑常量 + wire codec；旧 HTTP 契约标 legacy | `test_stream_schemas.py` |
| 3 | Alembic `0003`：`command_outbox`、`event_audit`、`execution_log_files`(log_integrity+gap)、`execution_attempts`(reconciled_from/lost_reason/last_event_at/stalled_at)；attempt `lost→{finished,failed,canceled}` 软 terminal 覆盖出边 | `test_states.py` + 真实 PG 验证 |
| 4 | heartbeat API + `require_server_token`（拆分 token）+ agent heartbeat worker + node selection 改 heartbeat 时新度 | `test_heartbeat_api.py`, `test_heartbeat_worker.py`, `test_node_selection.py` |
| 5 | command outbox 服务 + producer + dispatcher（run 短路、cancel CAS、retry/give-up→`dispatch_timeout`、503/202、coalesce 原语） | `test_outbox.py`, `test_dispatcher.py` |
| 6 | agent command consumer：两阶段 `reserved→started` CAS、`attempt_id` 幂等（dup/并发/跨重启）、pending 认领恢复、`spawn_aborted`、stop intent cancel/reclaim、cleanup | `test_command_consumer.py`, `test_state_cas.py` |
| 7 | agent 事件 outbox（落盘 at-least-once + replay）+ event publisher（`republish_current`） | `test_event_outbox.py` |
| 8 | server event consumer：`(stream,redis_msg_id)` 去重、terminal 不回退、lost 软 terminal 覆盖 + `reconciled_from`、agent>server lost reason、rollup、execution 收敛 | `test_event_consumer.py` |
| 9 | server reconcile loop：heartbeat_timeout→lost(无 stop)、event_stall→一次性 `stalled`→lost(event_stall)+stop(reclaim)、terminal 短路 | `test_reconcile_redis.py` |
| 10 | agent log publisher：单顺序生产者、cursor 仅在 XADD 成功后推进、raw bytes base64、eof 标记 | `test_log_publisher.py` |
| 11 | server log consumer：`offset<` 丢弃 / `==` 追加 / `>` 黏性 `partial`+gap marker+推进；`final_offset`=物理大小、`last_pulled_offset`=agent 逻辑；bounded drain→`cleanup_logs`（不依赖有损 eof，且按进程是否已知死亡门控） | `test_log_consumer.py` |
| 12 | executor 由 HTTP `AgentClient` 改为写 command stream（单次原子 commit、503 `dispatch_unavailable`、202 `dispatch_unknown`、execution 维持 queued 由事件收敛）；cancel 走 cancel CAS + stop(intent=cancel) 异步收敛 | `test_executions.py` |
| 13 | 删除旧 server→agent HTTP 主路径（`AgentClient.run/status/tail`、`AgentTailLogSource`、旧 `ReconcileLoop`/`reconcile`、`refresh_nodes`/`POST /nodes/refresh`；agent `/run`,`/status`,`/logs/tail`,`/cleanup`,`tail_file`）；保留 egg HTTP + agent `/health` | egg：`test_api_logs_egg.py`、auth：`test_auth.py` |
| 14 | docker compose `redis`（AUTH/AOF）+ 配置段 | `docker compose config` 校验 |
| 15 | 可靠性矩阵补齐 + 对抗性自审 + 修复 | 本报告 §2/§3 |

## 2. 对抗性自审（6 路 reviewer + 逐条独立 verify）

对实现做了一次多 agent 对抗性复核（按不变量分 6 路，每条 finding 由独立 skeptic 复核，refute-by-default），确认 16 条。已修复的实质问题：

- **cleanup-reconcile 链路缺失（高，refactor/00 §日志清理 lines 321–325）**：server-lost 的 attempt 在 agent 恢复后重发 `running` 时，server 此前**不发** stop(reclaim) 也不驱动清理。已补：`apply_event` 对「server-lost 上收到 running/accepted」入 `stop(intent=reclaim)`（按 attempt 去重）且**维持 lost 不回退**；`mark_lost` 将日志置 `finalizing`（非 `complete`）；`finalize_drained_logs` 对「agent 权威 terminal」或「已发 reclaim 的 lost」在 drain 窗后落 `complete`+`cleanup_logs`，对**纯 server-lost（未发 reclaim，agent 可能仍活）不清理**。
- **execution 卡 `lost` 不回滚（高）**：当 execution 已 rollup 成 `lost`、其 attempt 后被 agent 权威 terminal 覆盖时，execution 未重算。已将 execution `lost` 也设为**软 terminal**（`states` 放开 `lost→{complete,failed,canceled}`，`_update_execution` 允许从 `lost` 重 roll）。
- **dispatcher XADD 前未重读 outbox（高，refactor/00 §Command outbox）**：`try_dispatch` 现在 `session.refresh(row)` 后再判 canceled/sent，兜住并发 cancel。
- **`promote_started()` 返回值未校验（中）**：返回 None 时改发 `attempt.failed(spawn_aborted)`，不再发幻象 `running`。
- **gap 场景 SSE offset 不一致（中）**：SSE 推送的 `content` 现包含 gap marker，区间精确等于 `[physical_start, physical_end]`。

## 3. 设计内接受项（非缺陷，已在代码注释标注）

- **reserved-orphan TOCTOU**：`schedule()` 返回 job id 与 `promote_started()` 落盘之间存在亚毫秒窗口（两语句间无 await）；该窗口内 SIGKILL 会留下 scrapyd 孤儿 job + 一次 `spawn_aborted`。reserved 状态文件无 job id，无法可靠回查，符合 refactor/00「reserved == 未真正 spawn」的接受口径；孤儿 job 由 scrapyd 自行轮换。
- **SSE 文本通道 UTF-8 `replace`**：SSE/Web 是人读文本通道，按 `errors="replace"` 解码；字节级保真在 `/server-data/logs` 落盘与文件快照/下载路径，不在实时 SSE 流。
- **日志 RPO≠0**：server 长停 / Redis 裁剪致 `partial` 是设计内可见审计事实，不阻塞 execution 收敛。

## 4. 验收对照（§8）

- 原 Scrapy 闭环行为不变、全程经 Redis、无 server→agent HTTP run/status/tail：✅（单测 + compose 校验；端到端 compose 冒烟留待集成验收）。
- §7 可靠性矩阵纳入 CI：✅ 236 passed，ruff 全绿。
- Redis 不可用 server run 返回明确错误（503）、AOF 窗口内可恢复：✅（503/202/失败入 outbox 已测）。
- 旧 HTTP 主路径 + `AgentTailLogSource` 已删除/隔离：✅。
- 文档同步（00-requirements 决策 #10/#11/#12、10-roadmap、01/02/03/06/08 gap、05 布局、07 测试、CLAUDE.md）：先前 commit 已对齐 refactor/00。

## 5. 留待 Codex review / 集成验收

- `docker compose up` 端到端冒烟（egg→run→DB→SSE 全程经 Redis）。
- reserved-orphan TOCTOU、纯 server-lost 永不清理（agent 永不恢复）等接受项是否符合产品预期。
- 高频日志下 maxlen/批量/消费延迟的生产参数。
