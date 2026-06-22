# Redis Streams agent 通信重构提案

本文是一次**破坏性重构**的概念设计文档，目标是替换当前 server 主动 HTTP 连接 agent 的任务调度、状态同步与日志拉取链路。

重构后：

- 任务调度走 Redis Streams。
- agent 执行状态事件走 Redis Streams。
- agent 日志回流走 Redis Streams。
- agent 健康检查不走 Redis，由 agent 直接调用 server API 汇报。
- 不保留现有 server -> agent 的 HTTP run/status/tail 兜底链路。

## 已确认决策

本提案以 2026-06-19 的评审反馈和决策为准：

- **立即启动**：不等待 script/docker executor 完成，当前即以 Redis Streams 方案作为 server/agent 通信最终方向。
- **正式翻案**：改写既有 "server 主动连接 agent / server pull 日志 / agent 不主动回连" 决策，改为 agent 主动消费命令、主动推送状态/日志、主动 heartbeat。
- **破坏性重构**：不做 HTTP/Redis 双轨灰度，不保留 server -> agent HTTP run/status/tail 回退基线。
- **日志 RPO**：接受 server 长时间停机或 Redis 日志 stream 超出保留窗口后，窗口内日志片段可能丢失。日志 gap 是可见异常和审计事实，不阻塞执行状态收敛。
- **Redis 角色**：Redis 是消息总线/传输层，不是 dopilot 持久化数据库。PostgreSQL 仍是业务状态权威，`/server-data/logs` 仍是 server 已接收日志正文的最终存储。
- **日志 gap 处理**：`last_pulled_offset` 统一表示 agent 日志文件的逻辑字节 offset。发现 gap 时，server 插入可见 gap marker，写入当前片段，并把 `last_pulled_offset` 推进到当前片段结束 offset；`partial` 是黏性完整性标记。
- **Redis 不可用策略**：手动/同步 run 与定时/异步触发都经过 command outbox。手动 run 请求内同步尝试投递一次，失败则将 execution/attempt/outbox 标 failed 并返回 503；定时/异步触发进入 queued + command outbox，但 outbox 必须有过期和放弃终态。
- **lost 语义**：server 推断的 `lost` 是软 terminal，可被 agent 后续真实 terminal 覆盖；agent 上报优先于 server 推断。

## 背景

当前链路以 server 主动连接 agent 为中心：

- server 通过 agent HTTP API 下发任务。
- server 轮询 agent status API 判断执行状态。
- server 按 offset 拉取 agent logs tail API。
- server 再将日志落到本地文件，并通过 SSE 推给 Web。

这种模型在小规模单 server/单 agent 场景下直观，但存在几个结构性问题：

- server 必须能主动访问每个 agent。
- 调度、状态和日志链路都耦合在 agent HTTP 可达性上。
- agent 数量增加后，server 侧轮询和主动连接成本上升。
- 任务接收、重试、恢复、积压处理缺少统一的消息语义。

引入 Redis Streams 后，agent 变为主动消费自己的任务队列，server 只负责写命令、消费事件和落库。

## 目标架构

```text
Web / API
  |
  v
server
  | 1. 写 PostgreSQL: execution / attempt / command_outbox
  | 2. dispatcher XADD command
  v
Redis Streams
  |
  | XREADGROUP
  v
agent
  | 执行任务
  | XADD status events
  | XADD log events
  v
Redis Streams
  |
  | XREADGROUP
  v
server
  | 更新 PostgreSQL
  | 写 /server-data/logs
  | server -> web SSE
  v
Web
```

健康检查单独走：

```text
agent -> POST /api/v1/agents/{agent_id}/heartbeat -> server
```

Redis 不参与健康判断。server 以 heartbeat 的 `last_seen_at` 判断 agent 是否健康，并据此决定是否投递新任务。

## Redis Streams 定义

### Agent command stream

每个 agent 一个专属命令 stream：

```text
dopilot:agent:{agent_id}:commands
```

示例：

```json
{
  "command_id": "uuid",
  "type": "run",
  "agent_id": "agent-01",
  "execution_id": "exec-...",
  "attempt_id": "attempt-...",
  "task_type": "scrapy",
  "payload": "{...json...}",
  "created_at": "2026-06-19T00:00:00Z"
}
```

命令类型：

- `run`: 启动任务。
- `stop`: 停止任务。
- `cleanup_logs`: 清理 agent 本地日志和执行状态文件。

`stop` / `cleanup_logs` 按 `attempt_id` 幂等：agent 多次收到（如 reconcile、event_stall、取消三条路径对同一 attempt 各投一次 stop）时，对已停止/不存在的进程或已清理的文件幂等忽略，不视为故障。控制命令与 `run` 一样经 command stream 投递。`stop` 必须带 `intent`：

- `intent=cancel`（用户取消）：agent 权威终态统一为 `attempt.canceled`，无论进程是否仍在。
- `intent=reclaim`（server 已判 `lost`、杀进程回收资源）：attempt 维持 `lost`，不改判为 `canceled`；agent 若能观察到真实终态可按 agent>server 覆盖。

### Agent event stream

所有 agent 写入统一 server 事件 stream：

```text
dopilot:server:agent-events
```

示例：

```json
{
  "event_id": "uuid",
  "agent_id": "agent-01",
  "execution_id": "exec-...",
  "attempt_id": "attempt-...",
  "type": "attempt.running",
  "status": "running",
  "remote_job_id": "scrapyd-job-id",
  "exit_code": null,
  "error_code": null,
  "error_detail": "{}",
  "created_at": "2026-06-19T00:00:00Z"
}
```

事件类型：

- `attempt.accepted`
- `attempt.running`
- `attempt.finished`
- `attempt.failed`
- `attempt.canceled`
- `attempt.lost`

`attempt.finished` / `attempt.failed` / `attempt.canceled` 是 agent 权威 terminal 事件，**不属软 terminal、不得被任何 `lost` 覆盖**。`attempt.lost` 无论由 server 对账 loop 推断生成、还是由 agent 主动上报，都是**软 terminal**：可被同一 attempt 后续到达的 agent 权威 terminal（finished/failed/canceled）覆盖，并记录 `reconciled_from=lost`。多条 lost 之间按来源可信度 **agent > server** 裁决（agent 上报的 lost 优先于 server 推断的 lost），并按 `attempt_id` upsert，不因不同 `event_id` 产生重复 lost。

`attempt.lost` 必须带 reason。server 对账 loop 推断的 lost 至少区分：

- `heartbeat_timeout`: agent heartbeat 超时，server 判定 agent 不可达。
- `event_stall`: agent heartbeat 正常，但 attempt 长时间无状态事件，server 判定执行事件停滞。

agent 主动上报的 lost 用于表达本地恢复失败，至少包含：

- `state_missing`: attempt 状态文件丢失，agent 无法判定其执行进度。
- `process_missing`: 状态文件显示曾 `started`，但对应进程已不在、且无终态可补。
- `runner_recovered_unknown`: agent 重启后无法可靠重建该 attempt 的运行结果。

reason 枚举可继续扩展，但 API/Web 必须能据 reason 区分"agent 不可达 / 事件停滞 / agent 本地恢复失败"三类成因。

### Agent log stream

日志事件单独 stream，避免高频日志影响状态事件消费：

```text
dopilot:server:logs
```

示例：

```json
{
  "agent_id": "agent-01",
  "execution_id": "exec-...",
  "attempt_id": "attempt-...",
  "stream": "log",
  "offset": 12345,
  "content_b64": "...",
  "size_bytes": 4096,
  "eof": false,
  "created_at": "2026-06-19T00:00:00Z"
}
```

Redis Streams 只承担传输职责，不作为日志最终存储。日志正文仍由 server 写入 `/server-data/logs`，PostgreSQL 仍只保存日志索引、offset 和状态。

日志内容使用 base64 编码的 bytes，而不是文本字符串。这样 `offset` / `size_bytes` 与 agent 本地日志文件的字节空间一致，不受 UTF-8 边界或换行转换影响。

## 核心语义

### 任务投递

1. server 接收运行请求。
2. server 基于节点策略选择健康 agent。
3. server 在同一个 PostgreSQL 事务内创建 `execution`、`execution_attempt` 和 `command_outbox` 记录。
4. server command dispatcher 读取未发送 outbox 记录，将 `run` command 写入目标 agent 的 command stream。
5. command `XADD` 成功后，server 将 outbox 标记为 sent。
6. agent 通过 consumer group 读取自己的 command stream。
7. agent 基于 `attempt_id` 做幂等检查。
8. agent 写本地 attempt 状态文件。
9. agent 接管任务后 `XACK` command。
10. agent 写 `attempt.accepted` / `attempt.running` 事件。
11. server 消费事件并更新 PostgreSQL。

`XACK` 的语义是 agent 已经可靠接管命令，而不是任务已经完成。

server 不直接把 "写业务表" 和 "XADD Redis" 当作一个跨资源伪事务。`command_outbox` 是 PostgreSQL 内的生产者 outbox：业务表与 outbox 先在同一 PG 事务内 commit，dispatcher 之后才 `XADD`，因此正常路径不会出现"Redis 成功但业务 DB commit 失败"。outbox 实际解决的是两类问题：(1) DB 已提交但 Redis 暂不可用 / dispatcher 崩溃——pending 行由周期 dispatcher 重新投递；(2) `XADD` 成功但 outbox `sent` 标记失败——靠 `attempt_id` 幂等做 at-least-once 重发收敛。实现不得据此去做"先写 Redis 再写 DB"的跨资源伪事务。agent 能看到的最终调度入口仍然只有 Redis command stream。

### 幂等

`attempt_id` 是 agent 侧执行幂等键。

agent 重复读到同一个 `run` command 时：

- 如果本地已有同一 `attempt_id` 的状态文件，不得重复启动任务。
- 应重新发送当前 attempt 状态事件。
- 可以 `XACK` 该重复 command。

server 消费状态事件时：

- 以 `event_id` 和 Redis stream message id 做去重，关键 terminal 事件需要在 PostgreSQL 中可追踪。
- 状态更新必须允许重复事件。
- terminal 状态不得被非 terminal 状态回退。
- server 推断的 `lost` 可被 agent 权威 terminal 覆盖；其他 terminal 到 terminal 的覆盖必须按事件来源可信度处理，agent > server。

### Pending command 恢复

agent 启动时必须处理 consumer group 的 pending entries：

- 先认领超时 pending command。
- 再读取新 command。
- 对每条 command 继续按 `attempt_id` 幂等处理。

这避免 agent 读到命令后崩溃导致任务永久卡住。

### Command outbox

server 必须维护 command outbox：

- outbox 与 `execution_attempt` 在同一个 PostgreSQL 事务内创建。
- outbox 至少包含 `command_id`、`agent_id`、`execution_id`、`attempt_id`、`type`、`payload`、`status`、`retry_count`、`last_error`。`status` 取值统一为 `pending` / `dispatching` / `sent` / `failed_retryable` / `failed` / `canceled`：`dispatching` 表示某条投递路径已取走该行、正在 `XADD` 的瞬时态（coalesce 判定"未终结"时计入），`XADD` 成功转 `sent`、失败转 `failed_retryable` 或 `failed`。
- dispatcher 周期性扫描 `pending` / `failed_retryable` outbox。
- Redis `XADD` 成功后将 outbox 标记为 `sent`，并记录 Redis stream message id。该 command-stream message id 仅作审计/对账，不参与重发判定（重发唯一依赖 `attempt_id`）；它与"幂等"节里用于 dedupe 的 `agent-events` message id 是不同 stream、不同用途，不要混用。
- dispatcher 重发是预期的 at-least-once 行为。若 dispatcher 在 `XADD` 成功后、标记 outbox sent 前崩溃，重启后允许重发同一 command；重复投递由 agent 端 `attempt_id` 幂等和本地状态文件兜住。
- `command_id` 是 outbox 对账键/行标识，不是 agent 执行幂等键。agent 执行幂等唯一依赖 `attempt_id`。
- agent 接管 `attempt_id` 前必须获得本地互斥锁，避免 pending 认领、重复 command 或多 worker 竞争导致同一 attempt 重复启动。
- 手动/同步 run：先提交 execution + attempt + command_outbox，然后请求内同步 `try_dispatch` 这一条 outbox。`XADD` 失败（命令未进入 Redis）则 execution、attempt、outbox 标 `failed`，错误原因 `dispatch_unavailable`，返回 503，不做物理回滚/删除。`XADD` 成功则 outbox 标 `sent` 并返回成功。关键边界：一旦 `XADD` 成功，命令已进入 Redis、agent 可能已经启动任务，API 不得再返回"未投递"语义——若紧接着的 `sent` 标记 DB 更新失败，必须返回 202 `dispatch_unknown`（或等价"已投递、确认结果未知"状态）而非 503，并由 dispatcher / reconcile 依据 `attempt_id` 幂等收敛（重发同一 command 不会重复启动）。`dispatch_unknown` 时 execution 维持 `queued` / attempt 维持 `pending`（不标 failed、不提前标 running），由 agent 后续 `attempt.running` 事件经 event consumer 收敛回 running；该行有 `expire_at` / `give_up_at` 兜底终态，不违反"不得留下无终态 pending 行"。手动 outbox 行同样必须写入 `max_retry` / `expire_at` / `give_up_at`（可用比定时触发更短的窗口），不得留下无终态的 pending 行。
- 定时/异步触发：允许创建 queued execution + pending outbox；outbox 必须包含 `max_retry`、`expire_at`、`give_up_at` 或等价字段。超限后 attempt/execution 转 failed，原因 `dispatch_timeout`。
- 手动 run 与定时/异步触发共用 outbox 模型；差别只在手动 run 会在请求内等待首次 dispatch 结果。手动 run 请求内 `try_dispatch` 失败标 `failed` 后，若该 outbox 行因 server 在标 `failed` 前崩溃等原因残留为 `pending` 而被周期 dispatcher 异步接管，dispatcher 在 `XADD` 前必须按 execution 当前 status 短路：execution 已 `failed`/`canceled` 则丢弃该行、不得二次实际启动；仅当 execution 仍处可投递态时才允许重投，重投成功后由 agent 的 `attempt.running` 事件把 execution 收敛回 running。
- 取消 queued execution 时，server 必须先用 CAS 将所有未 sent 的 outbox 行置为 `canceled`。任何投递路径——包括周期 dispatcher 与手动 run 请求内的同步 `try_dispatch`——在每次 `XADD` 前都必须重读 outbox status，已 `canceled` 的 command 一律不得投递。但"未 sent"不等于"命令一定未离开 server"：`dispatch_unknown`（`XADD` 已成功但 `sent` 标记失败）下命令可能已进入 Redis、agent 可能已起任务。因此取消一个未 sent / `dispatch_unknown` 的 attempt 时，仅靠"阻止后续投递"不足以收敛，server 必须同时向 agent command stream 投递 `stop`（按 `attempt_id`，幂等，**`intent=cancel`**）。**cancel intent 下 agent 的权威回复统一是 `attempt.canceled`**：无论 agent 杀掉了仍在跑的进程、还是发现进程/状态文件已不在，都回 `attempt.canceled`（**而非 `attempt.lost`**），它作为 agent 权威 terminal 覆盖此前任何 server-lost 并记 `reconciled_from=lost`，server 据此把 execution 终结为 `canceled`。这样既避免"execution 标 canceled 而 agent 仍在跑"的僵尸，也避免"取消却因 agent 回 `lost(process_missing)` 被 rollup（`failed > lost > canceled`）成 `lost`"——cancel 路径不产生 `lost`。
- 定时任务必须做 coalesce 抑制：同一 schedule 已有未终结 execution，包括 outbox pending/dispatching 状态时，跳过本周期或合并为一次触发，避免 Redis 长时间不可用后堆积多条同源 queued command。

### 日志 offset

日志最终权威仍在 server：

- `execution_log_files.last_pulled_offset` 记录 server 已处理到的 agent 逻辑字节 offset，而不是 server 文件物理大小。
- log event 的 `offset` 必须是 agent 本地日志文件的字节偏移。
- server 只追加 `offset == last_pulled_offset` 的日志片段。
- `offset < last_pulled_offset` 的重复片段直接丢弃。
- `offset > last_pulled_offset` 表示日志缺片。server 必须标记该 attempt 日志完整性为 `partial`，记录 expected/actual offset，在 server 日志文件中插入可见 gap marker，然后写入当前片段，并把 `last_pulled_offset` 推进到 `offset + size_bytes`。
- gap 后到达的连续片段可以继续按 `offset == last_pulled_offset` 追加写入；`partial` 是黏性完整性标记，不会因为后续连续而自动恢复为 `complete`。
- 每个 attempt 的日志片段必须由 agent 端单一顺序生产者按 offset 严格递增发布。包含 outbox 重放在内，同一 attempt 的 log events 必须按 offset 排序后发布。server 对同一 attempt 的 log events 串行处理，避免乱序片段造成虚假 gap。agent 侧的 log outbox 与状态事件 outbox 是两条相互独立的 outbox，各自只需自链内有序（log 按 offset、event 按 `attempt_id` 单调幂等），不要求跨两条 outbox 的全局顺序；terminal event 与尾段 log 的跨链乱序由日志清理流程的 bounded drain 窗口吸收。
- `final_offset` 表示 server 日志文件的物理大小，包含可见 gap marker。需要 agent 逻辑最终 offset 时，继续使用 `last_pulled_offset` 或新增独立逻辑 offset 字段，不得混用。

由于本次重构不保留 HTTP tail 兜底，server 长停超过 Redis log stream 保留窗口时，日志可能不可恢复。该行为是已接受的 RPO：日志缺片必须显式暴露给 API/Web/审计，但不得让 execution 永久卡在 running/finalizing。

### 日志保留与裁剪

日志 stream 采用有限保留，而不是无限增长：

- Redis log stream 使用容量和时间窗口双约束，例如 `stream_maxlen_logs` + `log_retention_seconds`。
- 裁剪可以使用近似 `MAXLEN ~`，但生产配置必须按峰值日志量预留足够窗口。
- 一旦 server 消费发现 offset gap，不再尝试回拉 agent HTTP tail，也不要求 agent 补发已被裁剪的片段。
- gap 后到达的连续片段可以继续写入 server 文件，但该 log file 完整性保持 `partial`，不能标为完整 `complete`。
- execution/attempt 的业务状态与日志完整性状态分离：任务可以 `complete`，日志可以 `partial`。
- `execution_log_files.status` 继续表达日志生命周期，例如 `active` / `finalizing` / `complete` / `missing` / `expired`。新增独立 `log_integrity` 列表达完整性，例如 `complete` / `partial` / `missing` / `expired`，避免生命周期和完整性混用。

### 状态事件可靠性

日志允许窗口性丢失，但状态事件不应静默丢失。

agent 必须为状态事件维护本地 outbox：

- `attempt.accepted` / `attempt.running` / terminal 事件先写本地 outbox。
- Redis `XADD` 成功后再标记 outbox 项已发送。
- agent 重启后重放未确认 outbox 项。
- 重放事件由 server 幂等处理。

server 侧必须有对账 loop：

- 如果 agent heartbeat 超时，且该 agent 上存在 running attempt，server 可以将 attempt 标记为 `lost`，reason=`heartbeat_timeout`。
- 如果 attempt 长时间无状态事件且 heartbeat 仍正常，server 触发 operator-visible `stalled` 告警。`stalled` 是一次性告警/观测状态，不是 attempt terminal 状态；持续超过阈值后才可由对账 loop 转为 `lost`。
- 如果 event stall 持续超过丢失阈值，server 可以将 attempt 标记为 `lost`，reason=`event_stall`。
- 两条 lost 路径对 agent 真实进程的处理不同。`event_stall` 的前提是 agent heartbeat 仍正常、即 agent 与其子进程很可能仍在运行，server 标 `lost(event_stall)` 时必须同时向该 agent command stream 投递一条 `stop` command（`intent=reclaim`，按 `attempt_id`）尝试终止真实进程；agent 收到后若进程仍在则 kill 以回收资源、attempt 维持 `lost`（reclaim 不改判为 `canceled`；若 agent 能观察到真实终态则按 agent>server 覆盖），若进程已不在则幂等忽略。`heartbeat_timeout` 的前提是 agent 不可达、无法投递 stop，只标 server 侧状态，待 agent 恢复后由日志清理节的 reconcile 路径收敛（进程仍在则先 stop）。两条路径都不得让 server 判 lost 后在 agent 侧留下无人回收的僵尸进程。agent 主动上报的三类 lost 中，`process_missing` / `runner_recovered_unknown` 已隐含进程不在、server 无需再投 stop；`state_missing` 走 reconcile 路径按"进程仍在则先 stop"处理。
- `attempt.lost` 可以由 agent 主动上报，也可以由 server 对账 loop 生成；server 生成时必须记录 reason。
- 生成 server-lost 前必须短路检查 attempt 是否已经 terminal；已 terminal 的 attempt 不得再写 server-lost。
- server-lost 按 `attempt_id` upsert，不能因为不同 `event_id` 产生重复 lost 事件。
- agent 后续上报真实 terminal 时，必须允许覆盖 server-lost，并记录 `reconciled_from=lost`。

### 日志清理

agent 不得因为日志写入 Redis 成功就删除本地日志。

清理流程：

1. agent 发送 terminal 状态事件；`eof=true` 日志事件可作为优化信号，但不是清理前置条件。
2. server 收到 terminal 状态事件后进入 bounded drain 窗口，消费当前可见的日志事件并完成落盘。
3. drain timeout 或 EOF 信号到达后，server 将日志生命周期更新为 `complete`，并将完整性更新为 `complete` 或 `partial`。
4. server 向 agent command stream 写入 `cleanup_logs` command。
5. agent 删除本地日志和状态文件。

对 server-reconciled lost 的 attempt，如果 agent 当时不可达，server 保留待清理记录，但**不得在 agent 一恢复 heartbeat 就直接下发 `cleanup_logs`**——agent 失联期间原进程可能仍在运行，直接 cleanup 会删掉仍活跃 attempt 的日志/状态文件。agent 恢复后必须先对这些 attempt 做 reconcile，并**用已有 event stream 表达本地真实状态，不新增 agent→server 通道**，按以下映射处理（同时也定义了 reconcile 三态与 agent-lost reason 的对应）：

- **进程仍在** → 重发 `attempt.running`；server 收到后先投递 `stop`（`intent=reclaim`），待真实 terminal 事件或 drain timeout 后再下发 `cleanup_logs`。**该 stop 由 server 本地状态门控**——仅对处于"server-reconciled-lost 且待清理"集合（agent 曾失联）的 attempt 触发，正常运行期幂等重发的 `attempt.running`（见幂等节）不进入此分支、不会被误 stop。
- **本地有真实终态** → 由 event outbox 补发对应 `attempt.finished` / `attempt.failed` / `attempt.canceled`（agent 权威 terminal，按 agent>server 覆盖先前 server-lost），随后 drain + `cleanup_logs`。
- **状态文件/进程都不在、无法判定** → 发 `attempt.lost`，reason 取 `state_missing` 或 `process_missing`；进程既已不在，server 直接进入 drain + `cleanup_logs`，无需再投 stop。

agent 启动时也应对超过 TTL 的孤儿 attempt 日志执行本地 GC。

## 健康检查

agent 周期性调用 server API：

```text
POST /api/v1/agents/{agent_id}/heartbeat
```

请求体示例：

```json
{
  "agent_id": "agent-01",
  "version": "0.1.0",
  "capabilities": {
    "scrapy": true,
    "script": false,
    "docker": false
  },
  "load": {
    "running_attempts": 2
  },
  "detail": {
    "scrapyd": {
      "running": true,
      "port": 6801,
      "pid": 1234
    }
  },
  "reported_at": "2026-06-19T00:00:00Z"
}
```

server 侧节点健康判断：

```text
healthy = now - nodes.last_seen_at <= heartbeat_timeout_seconds
```

如果 heartbeat 超时，即使 Redis 可用，server 也不应继续向该 agent 投递新任务。

## 配置建议

server:

```toml
[redis]
url = "redis://localhost:6379/0"
stream_maxlen_commands = 100000
stream_maxlen_events = 100000
stream_maxlen_logs = 1000000
log_retention_seconds = 86400
consumer_name = "server-1"
require_aof = true

[agents]
heartbeat_timeout_seconds = 30
stalled_attempt_seconds = 300
lost_after_stalled_seconds = 900
# 阶段 2.2.3：单一机器令牌，同时认证 server↔agent 两个方向；与每个 agent
# [agent].agent_token 同值。admin_api_token 仅管理员、绝不下发给 agent。
agent_token = "change-me-agent-token"

[logs]
log_drain_timeout_seconds = 30
```

agent:

```toml
[redis]
url = "redis://redis:6379/0"
command_block_ms = 5000
pending_idle_ms = 30000
event_outbox_dir = "/agent-data/outbox"

[agent]
agent_id = "agent-01"
server_url = "http://server:5000"
heartbeat_interval_seconds = 10
# 阶段 2.2.3：单一机器令牌，同时认证 server↔agent 两个方向；与 server
# [agents].agent_token 同值（原拆分的 server_shared_token 已删除）。
agent_token = "change-me-agent-token"
```

Redis 部署要求：

- 生产环境启用 Redis AUTH/ACL。
- 生产环境启用 AOF，降低命令和状态事件在 Redis 重启时丢失的概率。
- 当前仍按单 server 实例设计；Redis 的引入不表示支持多 server active-active。

## 代码改动范围

### protocol

新增共享消息 schema：

```text
packages/protocol/dopilot_protocol/streams.py
```

建议包含：

- `AgentCommand`
- `AgentCommandType`
- `AgentEvent`
- `AgentEventType`
- `AgentLogEvent`
- `AgentHeartbeatRequest`
- `AgentHeartbeatResponse`

`AgentHeartbeatRequest.capabilities` 应复用 `CapabilitySet`，避免与现有能力字段产生两套同形 schema。

既有 `AgentRunRequest` / `AgentStatusResponse` / `TailRequest` / `TailResponse` 属于 HTTP server -> agent 旧主路径契约。破坏性重构后，它们不得继续作为 server 调度、状态或日志主路径依赖。可以在迁移提交中删除，或保留为内部兼容/测试遗留类型，但文档和代码入口必须明确标为 legacy，不再代表当前通信协议。

既有 "agent stateless w.r.t. log offsets" 的协议注释也需要改写：agent 仍不持有 server 最终 offset 权威，但 agent 会主动发布带逻辑 byte offset 的 log events；server 的 `last_pulled_offset` 仍是最终消费进度权威。

### server

新增 Redis stream 基础设施：

```text
apps/server/dopilot_server/redis/
  client.py
  streams.py
  commands.py
  consumers.py
```

新增或改造服务：

- command producer：写入 agent command stream。
- command outbox：与 execution/attempt 同事务保存待投递命令。
- command dispatcher：扫描 outbox 并向 Redis Streams 投递 command。
- event consumer：消费 `dopilot:server:agent-events`，更新 execution/attempt。
- log consumer：消费 `dopilot:server:logs`，写日志文件并更新 `execution_log_files`。
- heartbeat API：接收 agent heartbeat 并更新 nodes。
- node selection：只选择 heartbeat 健康的 agent。
- reconcile loop：不再轮询 agent HTTP status；只负责 heartbeat 超时、事件停滞、running attempt 超时等 server 侧对账。
- event dedupe store：新增 PostgreSQL 表记录关键事件处理结果，至少包含 stream、Redis message id、event_id、attempt_id、processed_at 和 outcome；terminal/lost 覆盖必须可审计。

既有模型和迁移需要显式改造，而不是只新增 Redis 目录：

- `nodes.last_seen_at` 语义从 server 轮询 agent `/health` 写入，改为 agent heartbeat API 写入。
- `execution_log_files.status` 继续表达生命周期；新增 `log_integrity` 表达 `complete` / `partial` / `missing` / `expired`。
- 新增 gap 记录字段，例如 `gap_count`、`first_gap_expected_offset`、`first_gap_actual_offset`，或独立 gap 明细表。
- 明确 `final_offset` 为 server 文件物理大小；agent 逻辑消费进度继续使用 `last_pulled_offset`。
- `execution_attempts` 新增 `reconciled_from` 列，用于记录 agent 权威 terminal 覆盖 server-lost 等场景。
- attempt 状态机需放开 `lost → {finished, failed, canceled}` 的软 terminal 覆盖出边（现有 `is_valid_attempt_transition` 在 `old ∈ TERMINAL` 时只允许 `old == new`，会静默拒绝该覆盖使 `lost` 永久粘住）；覆盖仅在记 `reconciled_from=lost` 的审计下发生，`finished`/`failed`/`canceled` 之间仍不可互转。
- lost reason 需要持久化，可作为 `error_code`/`error_detail` 的结构化内容，或新增独立 `lost_reason` 列；API/Web 必须能区分 server 推断的 `heartbeat_timeout` / `event_stall` 与 agent 上报的 `state_missing` / `process_missing` / `runner_recovered_unknown` 等本地恢复失败成因。
- 新增 `command_outbox` 表，承载 command 投递状态、Redis message id、retry/expire/give_up 元数据。
- 新增 event dedupe / event audit 表，承载 Redis event 消费幂等和 terminal/lost 覆盖审计。
- 新增 Alembic `0003+` 迁移，不得把这些变化隐式塞进既有 `0001` / `0002`。

需要移除或停止使用：

- server 主动调用 agent `/run`。
- server 主动轮询 agent `/status`。
- server 主动调用 agent `/logs/tail`。
- 依赖 HTTP tail 的 `AgentTailLogSource` 主路径。

### agent

新增 Redis command worker：

```text
apps/agent/dopilot_agent/redis/
  client.py
  commands.py
  events.py
  logs.py
```

新增后台任务：

- command consumer：读取 `dopilot:agent:{agent_id}:commands`。
- status publisher：写 `dopilot:server:agent-events`。
- log publisher：tail 本地日志并写 `dopilot:server:logs`。
- heartbeat worker：周期性 POST server heartbeat API。
- event outbox worker：保证状态事件 at-least-once 投递到 Redis。
- attempt lock：按 `attempt_id` 维护进程内互斥锁，防止同进程并发重复接管。
- state file CAS：spawn 子进程前必须原子创建 attempt 状态文件，例如 `O_CREAT|O_EXCL` 或等价 CAS。该状态文件是跨重启防重复启动的权威，分两阶段：CAS 创建时先置 `reserved`，子进程 spawn 成功后再翻为 `started`。agent 重启后按状态文件分支处理：`started` 但进程已不在 → 按既有重发/对账逻辑处理；`reserved` 但无活进程（"已占位、未真正 spawn"的崩溃孤儿）→ 判定该 attempt 启动失败，发 `attempt.failed`（reason=`spawn_aborted`）而不是重发 `accepted`，避免永久卡在 accepted；已存在且进程在跑的，只重发当前状态事件，不重复启动。

需要移除或停止使用：

- agent `/run` 作为调度入口。
- agent `/status` 作为 server 状态来源。
- agent `/logs/tail` 作为 server 日志来源。

agent `/health` 可保留为容器本地 healthcheck，但不再作为 server 节点发现和健康判断来源。

## 迁移步骤

本次是破坏性重构，不要求同时兼容旧 HTTP agent 调度链路。

推荐实现顺序：

1. 添加 Redis 依赖、配置和连接管理。
2. 添加 protocol stream schema。
3. 新增 heartbeat API 和 agent heartbeat worker。
4. node selection 改为基于 heartbeat。
5. server 新增 command outbox、command producer 和 dispatcher。
6. agent 新增 command consumer，并接入现有 `ScrapyRunner`。
7. agent 新增 event outbox 和 event publisher。
8. server 新增 event consumer，替代 status poll 更新 attempt 状态。
9. server reconcile loop 改为 heartbeat/event 对账，不再访问 agent HTTP status。
10. agent 新增 log publisher。
11. server 新增 log consumer，替代 HTTP tail pull。
12. server executor 从 HTTP agent client 改为写 command stream。该步骤必须晚于 log publisher/consumer 上线，避免经 Redis 执行的 attempt 没有日志承载链路。
13. 删除或隔离旧的 server -> agent HTTP 调度、状态、日志主路径。
14. 更新部署配置，docker compose 增加 Redis 服务，并启用 Redis AUTH/AOF。
15. 更新测试：覆盖 command ack、pending 恢复、幂等、日志 offset、heartbeat 健康判断。

## 测试要求

必须覆盖：

- server 写入 `run` command 后 agent 能消费并启动任务。
- agent 重复收到同一 `attempt_id` 不会重复启动。
- agent 读 command 后崩溃，pending command 可被恢复处理。
- agent status event 重复投递不会导致状态回退。
- terminal event 后 execution rollup 正确。
- log event 按 offset 追加写入 server 文件。
- 重复 log event 被丢弃。
- log offset gap 被显式标记为 `partial`，且不阻塞 execution 进入 terminal 状态。
- gap 后的后续连续 log event 能继续落盘，`last_pulled_offset` 推进到 agent 逻辑 offset，`log_integrity` 保持 `partial`。
- heartbeat 超时后 node 不再被选择。
- heartbeat 超时后，server 对账 loop 能将相关 running attempt 标记为 `lost`。
- server-lost 可被 agent 后续真实 terminal 覆盖，并记录 `reconciled_from=lost`。
- lost reason 区分 server 推断（`heartbeat_timeout` / `event_stall`）与 agent 上报（`state_missing` / `process_missing` / `runner_recovered_unknown`）。
- server-reconciled lost 的 attempt，agent 恢复后先 reconcile 重发 `attempt.running` 则 server 先 stop、再 drain + cleanup，不会在进程仍活时删其日志/状态文件。
- 手动 run `XADD` 成功但 `sent` 标记 DB 更新失败时返回 202 `dispatch_unknown`（不返回未投递语义），execution 维持 `queued`、由 agent 后续 `attempt.running` 收敛回 running。
- 取消处于 `dispatch_unknown`（或任意未 sent 但可能已投递）的 attempt 时，server 投 `stop(intent=cancel)`，agent 无论进程是否仍在都回 `attempt.canceled`（不回 `lost`），execution 终结为 `canceled`、不被 rollup（`failed > lost > canceled`）成 `lost`，且不留"canceled 而 agent 仍在跑"的僵尸。
- agent 主动上报的 lost（`state_missing` / `process_missing` / `runner_recovered_unknown`）是软 terminal，可被同一 attempt 后续 agent 真实 terminal 覆盖并记 `reconciled_from=lost`。
- 同一 attempt 的 log events 由单一顺序生产者按 offset 严格递增发布；乱序/重放不得制造虚假 gap。
- queued execution 取消会取消 pending outbox；任何投递路径（周期 dispatcher 与手动 run 请求内同步 `try_dispatch`）都不会在取消后投递 command。
- 定时任务在已有未终结 execution/outbox 时 coalesce，不会在 Redis 不可用窗口内无限堆积同源 queued command。
- agent 重复 command 在同进程并发和跨重启场景下都不会重复启动同一 attempt。
- agent 状态事件 Redis `XADD` 失败后进入 outbox，并在 Redis 恢复后重放。
- Redis 不可用时，手动 run 请求内首次 dispatch 失败会将 execution/attempt/outbox 标 failed `dispatch_unavailable` 并返回 503。
- Redis 不可用时，定时/异步触发创建可恢复的 pending outbox；超过 `max_retry` / `expire_at` 后转 failed，原因 `dispatch_timeout`。
- 手动 run 请求内 dispatch 失败后残留的 pending outbox 被异步 dispatcher 接管时，若 execution 已 `failed`/`canceled` 则丢弃、不二次实际启动。
- server 标 `lost(event_stall)` 时向 agent 投递 `stop`；agent 进程仍在则 kill 并补发真实 terminal 覆盖该 lost，进程已不在则幂等忽略。
- agent 在状态文件 `reserved` 后、spawn 子进程前崩溃，重启后发 `attempt.failed(spawn_aborted)`，不会永久卡在 `accepted`。
- terminal status event + drain timeout 能触发 `cleanup_logs`，不依赖有损 `eof` log event。

## 风险

- Redis Streams retention 配置过小会导致 server 恢复后缺失日志片段。
- `XACK` 时机过早可能导致命令丢失；过晚可能造成重复执行压力。
- agent 幂等实现不完整会导致同一 attempt 被重复启动。
- 日志事件量较大，必须控制 batch、maxlen 和消费延迟。
- server 当前单实例约束仍然存在；引入 Redis 不等于立即支持多 server 实例。
- 破坏性删除 HTTP 主路径后，Redis 成为关键基础设施，部署和监控必须同步补齐。
- 已接受日志 RPO 非 0：server 长停或 Redis 裁剪会导致日志 partial，这是设计内行为，不是可自动修复故障。

## 最终取舍

- command stream：按 agent 单独 stream，形如 `dopilot:agent:{agent_id}:commands`。
- event stream：所有 agent 写统一 `dopilot:server:agent-events`。
- log stream：所有 agent 写统一 `dopilot:server:logs`。
- 日志内容：使用 base64 bytes，保持 byte offset 语义。
- Redis stream 裁剪：允许有损裁剪，接受长停日志 partial；生产配置需给足保留窗口。
- 事件去重：关键状态事件，尤其 terminal 事件，需要在 PostgreSQL 中可追踪；非关键重复 running 事件可依赖状态单调幂等。
- 日志完整性建模：新增独立 `execution_log_files.log_integrity` 列；不把 partial/gap 混入生命周期 `status`。
- `stalled`：作为一次性告警/观测状态，不作为 attempt terminal 状态。
- Redis 不可用策略：手动/同步 run 也走 outbox，请求内同步 `try_dispatch`，失败标 failed `dispatch_unavailable` 并返回 503；定时/异步触发 queued + outbox pending，超限后 failed `dispatch_timeout`。
- lost reason：`lost` 必须带 reason。server 推断至少包含 `heartbeat_timeout` / `event_stall`，agent 上报至少包含 `state_missing` / `process_missing` / `runner_recovered_unknown`，避免把 agent 不可达、事件停滞和本地恢复失败混为同一种故障。
- heartbeat 鉴权：拆分 agent -> server token，不复用 server -> agent 旧 token；Redis 使用 AUTH/ACL。
- Redis 部署：单 Redis 实例可接受，符合当前单 server 约束；生产启用 AOF，后续如需要 HA 再单独设计。
