# 0010:单实例硬约束：server 单副本 + uvicorn `workers=1`

- 日期:2026-06-17
- 背景:进程内调度器（APScheduler）没有分布式锁，多副本/多 worker 会重复
  触发同一批定时任务；进程内的 Redis stream consumer、dispatcher 与 SSE
  订阅表也都以单进程为前提。
- 决定:server 固定**单容器 + uvicorn `workers=1` + 单一 in-process
  调度器**。**不支持多副本/多 worker，未来也不做**。显式允许 Redis 作
  **单实例** server↔agent 通信总线（[0008](0008-redis-streams-agent-communication.md)）；
  排除在外的是用 Redis（或 NATS / PG LISTEN-NOTIFY）做多副本 HA/fan-out/
  选主/分布式锁——server→web SSE fan-out 始终在单进程内存完成。
- 影响:
  - 部署与文档中任何"扩容 server 副本"的诉求直接按本决策拒绝；横向扩展的
    单位是 agent 节点数，不是 server。
  - compose/运维基线：server 服务单实例，`init: true`，不设 replicas。
