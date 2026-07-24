# 执行与日志链路

> 决策依据:[0008 Redis Streams 通信](../decisions/0008-redis-streams-agent-communication.md)、
> [0009 实时日志](../decisions/0009-realtime-logs-redis-push-sse.md)、
> [0013 Python wheel 运行模型](../decisions/0013-python-wheel-execution-model.md)。
> 更细的原始设计（含完整测试要求清单）见 git 历史中的
> `docs/refactor/00-redis-streams-agent-communication.md`。

## 任务投递（command outbox，at-least-once）

1. server 在**同一个 PostgreSQL 事务**内创建 execution / attempt /
   `command_outbox` 记录（outbox 状态机:`pending / dispatching / sent /
   failed_retryable / failed / canceled`，含 `max_retry` / `expire_at` /
   `give_up_at` 兜底终态）。
2. dispatcher 扫描未投递 outbox 行并 `XADD` 到目标 agent 的 command
   stream;成功后标 `sent`。重发是预期的 at-least-once 行为。
3. agent 经 consumer group 消费，按 **`attempt_id` 幂等**接管（本地互斥锁
   + 状态文件两阶段 CAS `reserved`→`started`），`XACK` 表示可靠接管而非
   完成;启动时先认领超时 pending entries。
4. agent 推 `attempt.accepted` / `attempt.running`，server event consumer
   消费更新 PostgreSQL。

Redis 不可用时的降级:手动 run 请求内同步 `try_dispatch` 一次，失败标
failed（`dispatch_unavailable`）返回 503;`XADD` 成功但 `sent` 标记失败
返回 202 `dispatch_unknown`（不返回"未投递"语义），由后续事件收敛。定时
触发进 queued + pending outbox，超限转 failed（`dispatch_timeout`），并做
coalesce 抑制同源堆积。取消先 CAS 置未 sent outbox 为 `canceled`，同时投
`stop(intent=cancel)`——agent 无论进程是否仍在都回 `attempt.canceled`。

## 状态事件与对账

- agent 状态事件经本地 event outbox at-least-once 重放;server 以
  `event_id` + stream message id 去重（PostgreSQL 事件去重/审计表），状态
  更新单调，terminal 不被非 terminal 回退。
- `attempt.finished/failed/canceled` 是 agent 权威 terminal;
  `attempt.lost` 是**软 terminal**，可被后续权威 terminal 覆盖并记
  `reconciled_from=lost`。lost 必须带 reason:server 推断
  `heartbeat_timeout` / `event_stall`，agent 上报 `state_missing` /
  `process_missing` / `runner_recovered_unknown`。
- server reconcile loop 只做 heartbeat/event 对账（不访问 agent HTTP）:
  heartbeat 超时 → 相关 running attempt 标 `lost(heartbeat_timeout)`;
  事件停滞先出 operator 可见的 `stalled` 告警（非 terminal），持续超阈值
  转 `lost(event_stall)` 并投 `stop(intent=reclaim)` 回收真实进程。
- agent 恢复后先 reconcile（进程仍在 → 重发 `attempt.running`，server 先
  stop 再清理;有真实终态 → outbox 补发;无法判定 → 上报 lost），避免删掉
  仍活跃 attempt 的日志/状态文件。

## 执行器与 runner

- server 侧:`apps/server/dopilot_server/executors/`——`BaseExecutor` 按
  resolved `artifact_type` 分派（scrapy / python_wheel;docker 预留）。
  下发 = 写 command stream;状态 = 消费 agent-events。
- agent 侧:`apps/agent/dopilot_agent/runners/` + `scrapyd/`:
  - **scrapy**:执行 `run` 时按 `fetch_path` 从 server 拉取 egg
    （`ScrapyArtifactCache`，携带 agent_token）→ 部署到本机 scrapyd
    `/addversion.json` → `schedule.json` 调度 → tail `job.log`。
  - **python_wheel**:按 sha256 `pip install --no-deps --target` 到缓存
    site 目录，注入 `PYTHONPATH`，`/bin/sh -c "<command>"` 独立进程组运行，
    `PYTHONUNBUFFERED=1`，退出码收敛状态（详见
    [0013](../decisions/0013-python-wheel-execution-model.md)）。
  - agent 状态映射持久化在 `/agent-data`（state 文件 + event/log outbox）。

## 日志链路

```text
agent tail 本地日志 ──XADD dopilot:server:logs(base64 字节+offset)──►
server log consumer ──追加写 /server-data/logs/YYYY/MM/{execution_id}/{attempt_id}.{stream}.log
                     └─更新 PG execution_log_files(索引/offset/状态) ──SSE──► Web
```

- `stream` 取值 `log`（scrapyd `job.log`）/ `stdout` / `stderr` /
  `system`;第一版不使用 WebSocket。
- **offset 语义**:`last_pulled_offset` 是 server 已消费的 agent 逻辑字节
  offset 权威。`offset == last_pulled_offset` 追加;小于则丢弃重复片段;
  大于则为缺片——插入可见 gap marker、`log_integrity` 置黏性 `partial`、
  推进 offset 继续接收。`final_offset` 是 server 文件物理大小（含 gap
  marker），与逻辑 offset 不混用。
- **完整性与生命周期分离**:`execution_log_files.status`
  （`active/finalizing/complete/missing/expired`）表达生命周期;
  `log_integrity`（`complete/partial/truncated/missing/expired`）表达完整性。
  日志 RPO≠0 是接受的设计行为，日志缺口永不阻塞执行状态收敛。
  `truncated`（资源硬上限 B1）:单执行日志达到 `[logs].max_file_bytes`
  （默认 100MiB）后停止追加正文但**继续消费 + ACK**（消费不失速），写一行
  截断标记;粘滞、优先于 `partial`，且不被定稿路径覆盖（定稿只改生命周期
  `status`）。
- **清理**:terminal 事件 → bounded drain 窗口（`eof` 是优化信号非前置
  条件）→ 定稿 complete/partial → server 投 `cleanup_logs` → agent 删本地
  日志与状态文件。此外:
  - server 端 `RetentionSweepLoop`（资源硬上限 B2）每
    `[maintenance].sweep_interval_seconds` 自动按 `[logs].retention_days`
    清理终态数据,失败安全两阶段(先标 `expired` 提交、再删正文、再删行,
    崩溃后下轮幂等续作),不再仅依赖手动 `POST /maintenance/terminal-cleanup`;
  - agent 端 `AgentJanitor`（资源硬上限 C1）实装 TTL 兜底 GC:终态
    workspace/日志/state/`.logpos` 超 `completed_log_ttl_days`、孤儿超
    `orphan_log_ttl_days` 即删,运行中(内存活跃集 / `job.pgid` 存活 /
    树静默期三重判定)永不删。
  详见 [0019 资源硬上限](../decisions/0019-resource-hard-limits.md)。
