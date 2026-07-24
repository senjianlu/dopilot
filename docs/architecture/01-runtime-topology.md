# 运行拓扑

> 决策依据:[0008 Redis Streams 通信](../decisions/0008-redis-streams-agent-communication.md)、
> [0007 PostgreSQL 唯一数据库](../decisions/0007-postgresql-only-log-bodies-on-disk.md)、
> [0010 单实例](../decisions/0010-single-instance-server.md)。

## 组件与数据流

```text
┌─────────────────────────────┐                    ┌──────────────────────────┐
│  dopilot-server (Docker)    │                    │  dopilot-agent (Docker)  │
│  - FastAPI /api/v1 + SSE    │   ┌────────────┐   │  - 本机 scrapyd(子进程)  │
│  - APScheduler 定时         │ ─►│   Redis    │◄─ │  - Python 脚本 runner    │
│  - command outbox/dispatcher│   │  Streams   │   │  - command consumer      │
│  - event/log consumer       │◄─ │ (消息总线) │ ─►│  - 状态/日志 XADD 推送   │
│  - PostgreSQL(业务+日志索引)│   └────────────┘   │  - 本地 exec healthcheck │
│  - 日志正文 /server-data    │                    │  - 纯出站,无监听端口     │
│  - 单管理员认证 + SSE→web   │◄── heartbeat ───── │  - 主动 POST heartbeat   │
└─────────────────────────────┘                    └──────────────────────────┘
```

三条 Redis stream + 一条 HTTP 心跳:

| 通道 | 方向 | 内容 |
|---|---|---|
| `dopilot:agent:{agent_id}:commands` | server → agent(每 agent 一条) | `run` / `stop`(带 `intent=cancel\|reclaim`)/ `cleanup_logs` |
| `dopilot:server:agent-events` | agent → server(全体共用) | `attempt.accepted/running/finished/failed/canceled/lost` 状态事件 |
| `dopilot:server:logs` | agent → server(全体共用) | 日志增量:base64 字节 + 逻辑字节 `offset`/`size_bytes`/`eof` |
| `POST /api/v1/agents/{agent_id}/heartbeat` | agent → server(HTTP) | 健康/能力/负载;server 写 `nodes.last_seen_at` |

消息 schema 统一定义在 `packages/protocol/dopilot_protocol/streams.py`
（`AgentCommand` / `AgentEvent` / `AgentLogEvent` / `AgentHeartbeat*`）。

## 角色边界

- **server** 是唯一连接 PostgreSQL 的角色（业务表 + 日志索引 + 事件
  去重/审计 + `command_outbox`）;唯一持有 in-process 调度器
  （APScheduler `AsyncIOScheduler`，jobs 与 DB `schedules` 表同步）;
  server→web 实时推送走 SSE，fan-out 在单进程内存完成。
- **agent** 是纯出站守护进程（阶段 2.2.7 起）:不监听任何端口、无入站
  HTTP;经 consumer group 消费自己的 command stream，主动推事件/日志/
  心跳。agent 作 PID 1（`init: true`）以子进程拉起本机 scrapyd（内部端口
  如 6801，仅本机可见）。容器健康检查是本地 exec
  `dopilot-agent-healthcheck`;真正的存活判定以 server 侧 heartbeat 为准。
- **Redis** 是瞬时传输层:不持久化业务真相、不是备份目标;生产启用
  AUTH/ACL + AOF。仅作单实例 server↔agent 总线，不用于多副本
  HA/fan-out/分布式锁。
- **节点健康**:`healthy = now - nodes.last_seen_at <=
  heartbeat_timeout_seconds`;超时的 agent 即使 Redis 可达也不再被投递新
  任务。agent 以稳定 `agent_id`（容器重启不变）为节点主标识落入 `nodes` 表。

## 单实例约束

server 固定单容器 + uvicorn `workers=1` + 单调度器实例。多 worker/多副本
会导致定时重复触发，且进程内的 stream consumer、dispatcher、SSE 订阅表
跨进程即坏——这是硬约束，不做也不会做（[0010](../decisions/0010-single-instance-server.md)）。
