# 0008:server↔agent 通信 = Redis Streams + agent 主动 heartbeat

- 日期:2026-06-19（阶段 1.5 落地；阶段 2.2.7 收敛为 agent 纯出站）
- 背景:阶段 1 交付的通信是 server 主动 HTTP（run/status/tail pull + 轮询
  agent `/health`）。该模型要求 server 能主动访问每个 agent，调度/状态/日志
  全部耦合在 agent HTTP 可达性上，节点增多后轮询成本上升，且缺少统一的消息
  重试/恢复语义。
- 决定:**破坏性翻案、无双轨**——server↔agent 主路径改为 **Redis Streams**：
  - server 经 `dopilot:agent:{agent_id}:commands` 投递命令
    （`run`/`stop`/`cleanup_logs`；事务性 `command_outbox` + dispatcher，
    at-least-once，`attempt_id` 为 agent 执行幂等键）；
  - **agent 主动**经 consumer group 消费命令、主动 `XADD` 状态事件
    （`dopilot:server:agent-events`）与日志（`dopilot:server:logs`）；
  - 健康检查不走 Redis：agent 周期性 **POST
    `/api/v1/agents/{agent_id}/heartbeat`**，server 以
    `nodes.last_seen_at` 判健康（`healthy = now - last_seen_at <=
    heartbeat_timeout_seconds`），超时不再投递新任务。
  - 删除 server→agent HTTP run/status/tail 主路径，不保留 HTTP 兜底。
  被否掉的备选：HTTP/Redis 双轨灰度（维护两套主路径成本高于收益）。
- 影响:
  - 可靠性语义随之确立：`XACK`=可靠接管而非完成；agent 启动先认领超时
    pending entries；状态事件走 agent 本地 event outbox at-least-once 重放，
    server 以 `event_id` + message id 去重、terminal 不被回退；server 对账
    loop 可推断软 terminal `lost`（reason 至少区分
    `heartbeat_timeout`/`event_stall`，agent 上报的真实 terminal 可覆盖并记
    `reconciled_from=lost`）；取消路径投 `stop(intent=cancel)`、回收路径投
    `stop(intent=reclaim)`。完整语义细节见
    `../architecture/03-execution-and-logs.md` 与 git 历史中的
    `docs/refactor/00-redis-streams-agent-communication.md`。
  - 节点持久化：第一版即建 `nodes` 表；agent 启动携带容器重启不变的稳定
    `agent_id` 作为节点主标识。
  - Redis 仅作**单实例** server↔agent 总线（[0010](0010-single-instance-server.md)），
    生产启用 AUTH/ACL + AOF。

## 修订

- 阶段 2.2.7:**agent 成为纯出站守护进程**——删除 agent 全部入站 HTTP（含
  egg 部署端点与 `/health`），不再监听任何端口（`6800` 移除）。Scrapy egg 改
  由 agent 执行 Redis `run` 命令时从 server 拉取后部署到本机 scrapyd；容器
  健康检查改用本地 exec `dopilot-agent-healthcheck`。
