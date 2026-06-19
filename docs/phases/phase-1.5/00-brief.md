# 00 · 阶段 1.5 重构任务书（server↔agent 通信迁移到 Redis Streams）

> **【scrapydweb 参考边界】** scrapydweb 仅作**功能层/行为参考**与**测试 oracle**；其代码写法、目录结构、模块划分、命名、依赖、配置形态**一律不得作为 dopilot 的设计依据**。本阶段仍不 import `reference/scrapydweb`，不把 `reference/` 放进 Docker build context。
>
> **【权威设计 = refactor/00】** 本阶段的**唯一设计真相**是 [`docs/refactor/00-redis-streams-agent-communication.md`](../../refactor/00-redis-streams-agent-communication.md)。本任务书只负责**工程执行编排**（顺序、范围、验收），所有协议/语义/边界细节以该 refactor 文档为准，凡冲突一律以 refactor 文档为准，不在此复述。
>
> 本文是阶段 1.5 的工程执行任务书。开发与初测交由 Claude 完成；Codex 拿到代码后负责 review、复跑关键测试、执行集成验收，并把问题写入本阶段 review 文档。

---

## 0. 为什么有阶段 1.5

阶段 1（[`phases/phase-1/00-brief.md`](../phase-1/00-brief.md)，**已验收**）以 **server 主动 HTTP pull**（agent 暴露 `/logs/tail`·`/status`·`/cleanup`，server 轮询 `/health`、按 offset pull 日志、不依赖 agent 回调）跑通了 Scrapy 执行闭环。这套链路在单 server/单 agent 下直观，但存在结构性问题：server 必须主动可达每个 agent，调度/状态/日志都耦合在 agent HTTP 可达性上，且任务接收/重试/恢复/积压缺统一消息语义。

**决策（见 refactor/00「已确认决策」）**：**立即启动**通信层破坏性重构（不等 script/docker executor），把 server↔agent 主路径从 HTTP pull 整体翻案为 **Redis Streams + agent 主动 heartbeat**。这是一次**独立的重构阶段**，插在阶段 1（Scrapy 跑稳）与阶段 2（脚本）之间：

```
阶段1 Scrapy 跑稳(HTTP pull,已验收) ──► 阶段1.5 通信层重构(→ Redis Streams) ──► 阶段2 脚本 ──► 阶段3 长连接
```

> **阶段 1 是既定事实，本阶段不回改 phase-1 的历史记录/验收结论**；阶段 1 交付的 HTTP pull 链路在本阶段被新链路**替换**（破坏性、无双轨），替换范围与作废清单见 §3。

## 1. 目标

把 server↔agent 的**任务调度、状态同步、日志回流**三条链路从「server 主动 HTTP」迁移到 **Redis Streams**，健康检查改为 **agent 主动 heartbeat**：

```text
Web/API
  -> server: 写 PostgreSQL(execution/attempt/command_outbox) + dispatcher XADD command
  -> Redis: dopilot:agent:{agent_id}:commands
  -> agent: consumer group 消费 → 执行 → XADD 状态/日志
  -> Redis: dopilot:server:agent-events / dopilot:server:logs
  -> server: event/log consumer 更新 PostgreSQL + 写 /server-data/logs + server→web SSE
健康: agent -> POST /api/v1/agents/{agent_id}/heartbeat -> server(更新 nodes.last_seen_at)
```

完成后：原 Scrapy 闭环行为不变，但 server↔agent 不再走 HTTP run/status/tail，Redis 成为 server↔agent 的关键通信基础设施。

**保留不变（四不变量 + 单实例）**：第一版不用 WebSocket；server→web 走 SSE；日志正文落 `/server-data/logs`；PostgreSQL 只存日志索引/offset/状态；server 单实例、uvicorn `workers=1`、单 APScheduler；Redis 仅作单实例 server↔agent 通信总线，**不引入做多副本 HA/fan-out/分布式锁**，SSE fan-out 仍单进程内存完成。

## 2. 范围（in / out）

**in**：Redis 依赖与连接管理；三条 stream 与 protocol schema；command_outbox + producer + dispatcher；agent command consumer（接现有 `ScrapyRunner`）；agent event/log publisher + event outbox；server event/log consumer + reconcile loop；heartbeat API + agent heartbeat worker；node selection 改 heartbeat；数据模型迁移（Alembic 0003+）；删除旧 HTTP 主路径；部署与测试更新。

**out**：script/docker executor（阶段 2/3）；多 server 多副本/HA（永不支持）；WebSocket；Redis 之上的任何业务持久化（Redis 不是数据库）。

## 3. 对阶段 1 已交付链路的替换 / 作废清单

> 破坏性、不要求兼容旧 HTTP 调度链路。以下阶段 1 落点被替换或降级（**不回改 phase-1 文档，仅在本阶段实际改代码**）：

- **删除/降为 legacy**：server→agent `/run`、`/status`、`/logs/tail` 作为 server 调度/状态/日志主路径；依赖 HTTP tail 的 `AgentTailLogSource` 主路径；server 轮询 agent `/status`/`/health`。
- **保留**：`ScrapyRunner`（agent 内管本机 scrapyd 的执行逻辑）；attempt 本地状态文件（升级为两阶段 `reserved`→`started` CAS）；`/addversion.json` egg 转发（仍走 HTTP）；agent `/health`（降为容器本地 healthcheck，不再作 server 节点发现/健康来源）；正文落盘 + PG 索引 + SSE。
- **protocol**：`AgentRunRequest`/`AgentStatusResponse`/`TailRequest`/`TailResponse` 标 **legacy**（删除或仅留测试遗留），不再代表当前协议；`AgentLogEvent.offset` 为 **agent 本地日志的逻辑 byte offset**，server 的 `last_pulled_offset` 是**消费进度权威**（二者不混用）。
- **phase-1 对抗性 review 修复**（UTF-8 边界回退、崩溃幂等 write_increment、lost 计时、阻塞 finalize、SSE 连接池隔离等）需在 Redis 模型下逐项重新论证：复用 / 需重写 / 语义变更（实现时建判定表）。

## 4. 实现顺序（详见 refactor/00 §迁移步骤）

> 关键约束：**log publisher/consumer 必须先于 executor 切换上线**，避免经 Redis 执行的 attempt 没有日志承载链路（refactor/00 §迁移步骤 step 10–12）。

1. Redis 依赖、配置、连接管理。
2. protocol `streams.py`（AgentCommand/Event/LogEvent/Heartbeat·Response）。
3. heartbeat API + agent heartbeat worker。
4. node selection 改 heartbeat（`nodes.last_seen_at`）。
5. server command_outbox + producer + dispatcher。
6. agent command consumer，接 `ScrapyRunner`。
7. agent event outbox + event publisher。
8. server event consumer（替代 status poll）。
9. server reconcile loop（heartbeat/event 对账，不再访问 agent HTTP status）。
10. agent log publisher。
11. server log consumer（替代 HTTP tail pull）。
12. server executor 由 HTTP agent client 改为写 command stream（**晚于 10–11**）。
13. 删除/隔离旧 server→agent HTTP 调度/状态/日志主路径。
14. 部署：docker compose 加 redis 服务并启用 AUTH/AOF。
15. 测试：覆盖 ack/pending 恢复/幂等/offset gap/heartbeat 等（见 §7）。

## 5. 数据模型与迁移（server 拥有，Alembic 0003+）

- 新增 `command_outbox` 表（command 投递状态、redis_msg_id、retry/expire/give_up）。
- `execution_log_files`：新增 `log_integrity`（complete/partial/missing/expired）+ gap 记录字段（如 `gap_count`/`first_gap_expected_offset`/`first_gap_actual_offset`）；明确 `final_offset` = server 文件物理大小、`last_pulled_offset` = agent 逻辑字节进度。
- `execution_attempts`：新增 `reconciled_from`、`lost_reason`；状态机放开 `lost → {finished,failed,canceled}` 软 terminal 覆盖出边（仅在 `reconciled_from=lost` 审计下）。
- `nodes.last_seen_at`：语义由 server 轮询 `/health` 回填**翻转**为 agent heartbeat 写入。
- 新增 event dedupe / audit 表（事件消费幂等 + terminal/lost 覆盖审计）。
- **不得**把上述变更塞进既有 `0001`/`0002` 迁移。

## 6. 配置与部署

- server `[redis]`：`url` / `stream_maxlen_commands|events|logs` / `log_retention_seconds` / `consumer_name` / `require_aof`；`[agents]`：`heartbeat_timeout_seconds` / `stalled_attempt_seconds` / `lost_after_stalled_seconds`；`[logs].log_drain_timeout_seconds`。
- agent `[redis]`：`url` / `command_block_ms` / `pending_idle_ms` / `event_outbox_dir`；`[agent]`：`server_url` / `heartbeat_interval_seconds` / `server_shared_token`。
- `configs/{server,agent}.example.toml`、`server.docker.toml` 同步新增以上段；docker compose 新增 `redis` 服务、AUTH/ACL + AOF。
- 目录：`apps/server/dopilot_server/redis/`、`apps/agent/dopilot_agent/redis/`、`packages/protocol/dopilot_protocol/streams.py`。

## 7. 测试要求（dopilot 独有域，自写、可 mock；见 refactor/00 §测试要求）

必须覆盖：写 `run` command 后 agent 消费并启动；同 `attempt_id` 重复不重复启动；agent 读 command 后崩溃 pending 可恢复；status event 重复不回退/terminal 不被回退；log offset 追加/重复丢弃/`offset>last_pulled_offset` 显式 `partial` 且不阻塞 terminal；gap 后连续片段继续落盘、`log_integrity` 黏性；heartbeat 超时不选节点 + reconcile 标 `lost`；server-lost 可被 agent 真实 terminal 覆盖记 `reconciled_from`；lost reason 区分 server 推断（heartbeat_timeout/event_stall）与 agent 上报（state_missing/process_missing/runner_recovered_unknown）；event `XADD` 失败入 outbox 并重放；Redis 不可用——手动 run 503、定时 queued+outbox 超限 failed `dispatch_timeout`；取消投 `stop(intent=cancel)` 终结 `canceled` 不被 rollup 成 lost、不留僵尸；terminal status + drain timeout 触发 `cleanup_logs`（不依赖有损 `eof`）；agent 状态文件 `reserved` 后崩溃→`attempt.failed(spawn_aborted)`。归 `apps/server/tests` + `apps/agent/tests` + `packages/protocol` schema 校验。

## 8. 验收标准

- 原 Scrapy 闭环（上传 egg → 运行 spider → DB 见 execution/attempt/log index → Web 实时看日志）行为不变，但全程经 Redis、无 server→agent HTTP run/status/tail。
- §7 测试矩阵全绿并纳入 CI。
- Redis 不可用时 server run 请求返回明确错误、不创建不可恢复的半成品调度；启用 AOF 后，在 Redis 持久化窗口内 stream / consumer group 状态可恢复，AOF fsync 窗口内的丢失按已接受 RPO / Redis 运维风险处理。
- 旧 HTTP 主路径与 `AgentTailLogSource` 主路径已删除/隔离，文档与代码入口标 legacy。
- 文档同步到位：`00-requirements` 决策 #10/#11/#12、`10-roadmap`、`01/02/03/06/08` gap、`05` 布局、`07` 测试、`CLAUDE.md` 已与 refactor/00 一致。

## 9. 风险（见 refactor/00 §风险）

Redis retention 过小致 server 恢复缺日志片段；`XACK` 时机过早丢命令/过晚重复执行压力；agent 幂等不完整致重复启动；日志事件量大需控 batch/maxlen/消费延迟；破坏性删 HTTP 后 Redis 成关键设施、部署监控须同步补齐；已接受日志 RPO≠0（长停/裁剪致 `partial`，设计内行为）。单实例约束不变——引入 Redis 不等于支持多 server。
