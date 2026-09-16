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
`stop(intent=cancel)`——agent 无论进程是否仍在都回 `attempt.canceled`，但
**不再是即时回**:agent 先确认进程真的退出（见「停止状态机」），最迟在
`stop_confirm_timeout_seconds`（默认 120s）后无条件上报。

## 状态事件与对账

- agent 状态事件经本地 event outbox at-least-once 重放;server 以
  `event_id` + stream message id 去重（PostgreSQL 事件去重/审计表），状态
  更新单调，terminal 不被非 terminal 回退。
- `attempt.finished/failed/canceled` 是 agent 权威 terminal;
  `attempt.lost` 是**软 terminal**，可被后续权威 terminal 覆盖并记
  `reconciled_from=lost`。lost 必须带 reason:server 推断
  `heartbeat_timeout` / `event_stall`，agent 上报 `state_missing` /
  `process_missing` / `runner_recovered_unknown`。
- **运行期存活心跳（attempt.heartbeat）**:agent 的 reconcile 循环在确认
  attempt 进程真的活着时（scrapyd `listjobs` 仍列出该 job / wheel 子进程
  `returncode` 为 None），按 `attempt_heartbeat_interval_seconds`（默认
  60s）限频重发 `attempt.heartbeat`。server 收到后仅刷新
  `last_event_at`、清 `stalled_at`——不进状态机、不写事件审计表;心跳
  **直接 XADD、不走 agent 持久 event outbox**（瞬时信号,断连期间落盘重放
  无意义且会挤占 outbox 容量上限）。scrapyd 不可达（status unknown）或
  进程已退出时**不发**——心跳的语义是「我确认它还活着」。心跳还**携带
  `log_bytes`**（该 tick 读到的 job.log 大小;读不到则为 `None`），这是
  server 唯一的「在干活」证据,见下条。
- **「还活着」不等于「在干活」(无进度探测)**:scrapyd 会一直把卡在关闭阶段
  的 spider 列为 running,心跳因此永远为真——2026-09-15 一个 SWAPGG job 就
  这样占着调度唯一的并发槽两小时。故 server 把**进度**与**存活**分成两套时钟:
  `last_progress_at`（日志真的变长,或来了真实生命周期事件）与
  `last_progress_sample_at`（最近一次拿到**任何**日志大小读数）。仅当采样仍
  新鲜（`no_progress_sample_max_age_seconds`，默认 300s）且空转超过
  `no_progress_stall_seconds`（默认 1800s，0=关闭）时,才打一次性标记
  `no_progress_at` 并发 `attempt_no_progress` 通知。
  **这条链只告警、绝不判 lost**:`last_event_at` 与 reclaim 链一行未改,所以
  长时间安静的正常任务最坏只收到一条通知。`auto_stop_on_no_progress`（默认
  **false**）才会真的下发取消。`no_progress_at` 不被心跳清除（只有真实进度会
  清），这是通知与自动取消各只发一次的依据——`notify` 的去重只作用于未读行,
  用户读过就会再插一条。
- **停止状态机(agent)**:`stop` 不在命令消费者里等待——那是串行的,一批取消
  会冻结所有执行的心跳与刷屏检查。改为先把意图落盘（`_process` 即使处理器抛异常
  也会 XACK,没落盘的意图就永远没人推进），再由 tick 循环推进
  TERM → `stop_kill_after_seconds`(默认 10s) → `signal=KILL` → 确认退出。
  确认用的是**只问死活的 `is_job_alive`**,不是 `status`:后者在 TERM 之后会把
  离开列表的 job 报成 `canceled`（那是 agent 自己造的,不是权威终态,reclaim 若
  据此上报就会把 lost 覆盖掉）,且对「已取消、无日志的 pending job」同样返回
  `unknown`。收尾严格按 intent 分叉:`cancel` 报权威 `canceled`,`reclaim`
  保持 lost 且不发任何事件。
- **终态有界,回收不封顶**:硬期限只约束**终态上报**;到点进程仍活着时,终态照
  报,但 `kill_pending` 与 scrapyd job 映射都保留,由回收看门狗按
  `kill_retry_interval_seconds`（默认 60s）持续重发 KILL 并记 WARNING,直到确认
  退出。**先删映射再谈回收就等于亲手制造一个没人看得见的残留进程**,那正是本机制
  要消灭的东西。同理,停止/回收期间到达的 `cleanup_logs` 只记 `cleanup_pending`,
  等进程确认退出、终态确认交付后才真正清理。
- server reconcile loop 只做 heartbeat/event 对账（不访问 agent HTTP）:
  heartbeat 超时 → 相关 running attempt 标 `lost(heartbeat_timeout)`;
  事件停滞先出 operator 可见的 `stalled` 告警（非 terminal），持续超阈值
  转 `lost(event_stall)` 并投 `stop(intent=reclaim)` 回收真实进程。有了
  运行期心跳,`stalled` / `lost(event_stall)` 的含义从「久无状态转换事件」
  收敛为「agent 在线但持续无法确认该 attempt 存活」——
  `lost_after_stalled_seconds`（默认 3600）**不再是任务运行时长上限**,
  健康长任务可运行任意时长。
- **task 收敛与 roll-up**:event consumer 应用事件后,只要该 task 名下**任一
  execution 离开了 `pending`**(收到 `running`,或 `running` 事件丢失后直接
  收到终态),仍为 `queued` 的 task 先收敛到 `running`(`started_at` 取
  executions 最早的 `started_at`),再按 executions 全终态 roll-up。task 状态机
  不放宽:`queued` 没有到 `complete` 的边,必须经 `running`——2026-08-26 事故
  中 `running` 事件丢失、终态直达时,旧的"仅 running 事件收敛"逻辑让 roll-up
  被状态机拒绝,task 永久停在 `queued`。
- **task 级孤儿修复**:reconcile loop 每 tick 在 execution 对账之后,再扫一遍
  「活动态 task 且名下**没有任何活动 execution**」(`status IN active AND NOT
  EXISTS`,候选只有个位数量级的活动态行),在 task 行锁下复核后修复:executions
  全终态 → 收敛 + roll-up 到真实终态(时间线取自 executions);零 execution 且
  创建超过 `lost_after_stalled_seconds` → `lost(no_execution)`(与维护页
  「标记 lost」对零 execution 的处置一致)。修复写入
  `status_detail.reconcile_repair`(from/to/原因/时间)并记一行 warning 日志,
  不发通知;修复后的终态 task 在同一 tick 进入结果记录。这是 execution 驱动
  对账之外唯一的 task 级一致性出口,也是 0022 并发闸不被卡死任务永久占额度的
  保证。
- agent 恢复后先 reconcile（进程仍在 → 重发 `attempt.running`，server 先
  stop 再清理;有真实终态 → outbox 补发;无法判定 → 上报 lost），避免删掉
  仍活跃 attempt 的日志/状态文件。心跳到达 server 侧已标 `lost` 的
  execution 时同样触发该保护:状态保持 lost,并投递
  `stop(intent=reclaim)`（按「曾投递过即不再投」持久去重,每 execution
  终生至多一条）。该去重事实与任务同寿命:outbox 保留清扫
  (`prune_resolved_outbox`) 永不删除 `stop(intent=reclaim)` 行,它们只随
  任务经 `cleanup_terminal_data` 删除。
- **事件消费者毒丸容错**:server event consumer 对无法解析的事件条目
  （如版本偏斜下的未知事件类型）记 warning 后 XACK 跳过,不让单条坏消息
  卡死整条事件流。注意这只保护新版 server;升级顺序约束见
  [05-deployment](05-deployment.md)。

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
  （默认 32MiB,日志洪泛防护后与 agent `max_job_log_bytes` 一致）后停止追加正文但**继续消费 + ACK**（消费不失速），写一行
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

### 日志洪泛防护（log-flood guard，决策 0021）

2026-08-21 事故(一条爬虫 40 分钟写 3GB 日志,agent 以 256KB/条推进
`dopilot:server:logs`,`MAXLEN=100000` 按条数等效上限 ≈35GB,Redis 7.8GB 被
OOM 反复杀死拖死宿主机)之后,日志链路多了四道闸门与一个结果记录器:

```text
crawler 进程内 ─[闸 1a logcap .pth]─ 字节 ≥ cap → 停写 + 标记 + SIGTERM 自身
agent          ─[闸 1b watchdog]─ job.log ≥ cap → cancel(TERM→KILL→单 PID)+ 每 tick 截回 → 终态 failed/log_flood
agent          ─[闸 2 LogPublisher]─ 每执行推送 ≥ cap → 一条标记 entry 后停止 tail;agent 级令牌桶限速
server 消费    ─[闸 3 apply_log_event]─ 文件 ≥ max_file_bytes 或 目录 gauge ≥ max_total_bytes → 不落盘
               → 截断标记 + log_integrity=truncated + stop_logs 反压 + log_truncated 通知
server 守卫    ─[闸 4 StreamGuardLoop]─ MEMORY USAGE > stream_max_bytes_logs → 精确 XTRIM 迭代收敛,不收敛则清空
```

- **闸 1a(进程内硬界)**:agent 随 wheel 安装 `dopilot_logcap.pth`,解释器
  启动即 `import dopilot_agent.logcap`;模块**只凭 argv**(`crawl` + `_job=` +
  `-s DOPILOT_JOB_LOG_CAP_BYTES=<n>` + `-s LOG_FILE=<p>`,由 agent 的
  `ScrapyRunner.schedule()` 注入 scrapyd `setting`)判定自己是一个 crawler,
  然后只给写 `LOG_FILE` 的那个 `logging.FileHandler` 实例加上限:达限写一次
  `[dopilot:job-log-truncated ... reason=size-cap]`、丢弃后续记录、向自身发一次
  SIGTERM(scrapy 优雅关闭)。可证明的写入上限 = cap + 一条记录 + 标记,与
  任何轮询无关;受管/外部 scrapyd 同一机制(外部模式要求该环境装有
  `dopilot-agent` 包)。scrapyd 守护进程、agent 自身永不被打补丁。
- **闸 1b(watchdog)**:`CommandConsumer.reconcile_started_attempts` 每 tick
  检查 started 的 scrapyd 执行本地 `job.log` 大小,≥ `max_job_log_bytes` 即
  `mark_log_flood` + cancel;之后每 tick把文件截回 cap + 标记(scrapy O_APPEND
  写,截断后继续追加,磁盘始终 ≤ cap + 标记 + 一个 tick),并升级终止:
  `log_flood_kill_after_seconds` 后 `cancel signal=KILL`,再 2 倍后对**唯一**
  匹配 `_job=<id>` 且 ppid == 受管 scrapyd 的 crawler 进程 `SIGKILL`(绝不
  killpg;候选 0 或 >1 不杀;外部模式禁用此级)。被 flood 终止的执行一律上报
  `attempt.failed` / `error_code=log_flood`。
- **闸 2**:`LogPublisher` 每执行推送上限同 cap(达限发一条标记 entry、持久化
  `log_capped`、不再 tail;终态仍发 eof);agent 级令牌桶
  `log_publish_rate_bytes_per_second`(桶 = 2 秒配额;正文与截断标记一律
  记账、额度不足时标记等下一 tick),扫描起点轮转不饿死。
  server 的 `stop_logs` 命令走同一 `cap()` 入口(反压)。
- **闸 3**:`apply_log_event` 对 `execution_log_files` 行 `FOR UPDATE`,只有
  `status ∈ {active, finalizing}` 才接收增量(封口/过期/缺失一律 `sealed` 丢弃,
  不落盘、不建文件、不改完整性);在 `LogsDirGauge.writer()` 一把锁内完成
  「计划写入字节 → 单文件 cap 与目录预算判定 → 写入 → 按写前/写后 `stat` 差值
  结算 gauge」。目录预算是**准入硬界**:放不下正文只写标记,标记也放不下就一个
  字节不写(仅 DB 状态 `truncated` / `truncation_reason=dir-budget`)。任一截断
  → 入队 `stop_logs` 反压(按执行去重)+ `log_truncated` 通知。
- **闸 4**:`StreamGuardLoop` 启动时(消费者之前)与每
  `stream_guard_interval_seconds` 用 `MEMORY USAGE ... SAMPLES 0` 测日志流字节,
  超 `stream_max_bytes_logs` 则按 `floor(len × budget/usage × 0.8)` **精确**
  `XTRIM MAXLEN` 迭代(≤8 轮、每轮重测);降幅 <5% 或 8 轮仍超限则清空流
  (瞬态总线,0008)。裁剪 → warning 通知(`trim:<小时>`),清空 → error 通知
  (`cleared:<小时>`)。
- **`LogsDirGauge`**:进程内精确计数器;写入、截断/删除(维护)、`calibrate()`
  (启动与每次 sweep,持锁跨越整个 `os.walk`)共用一把 `asyncio.Lock`,任意时刻
  `value == 目录实际字节`。
- **`sent` 对账**:dispatcher 启动与每 `sent_reconcile_interval_seconds` 用
  `XRANGE id id` 核对 `sent` 行的消息是否仍在命令流(流被清空 / 裁剪 / volume
  清除),不在则回退 `pending` 重投(at-least-once,0008),并重开 give-up
  窗口(900s)与重试额度——原 `give_up_at` 在长停机后早已过期,不重开会在同一
  tick 被判 `dispatch_timeout` 而非重投。

### 任务结果记录与调度自动禁用

scrapyd 1.x 不暴露退出码:pipeline 全部报错的爬虫终态仍是 `finished`。因此
agent 在终态时解析日志尾 64KB 的 scrapy stats(`log_count/ERROR`、
`finish_reason`;只取最后一个 `Dumping Scrapy stats` 块内的字典行,业务日志
打印同名字段不会伪造 stats;无块或块被截断到该键之前 → `None`)并连同本地
日志大小随事件上报(`AgentEvent.error_count / finish_reason / log_bytes`,均
可选),server 落到 `executions` 新列。

**唯一提交点**是 `services/outcomes.record_task_outcomes`,由
`RedisReconcileLoop` 每 tick 在 `finalize_drained_logs` 之后轮询:任何终态写入
路径(事件 rollup、dispatcher 超时、reconcile/maintenance `mark_lost`、取消)都
不直接计数。对每个 `status ∈ 终态 且 outcome_recorded_at IS NULL` 的 task:

1. 按固定锁序 `task → executions → execution_log_files → schedule` `FOR UPDATE`
   并在锁内重读(所有终态写入者遵循同一锁序并在锁内复核状态,陈旧对象不能
   覆盖已提交的权威终态);
2. 等日志定稿(drain 窗口后 `finalize_drained_logs`),或 drain + 60s 兜底;
   `lost` 只在 reclaim 已发且 drain 已过、或超过 `lost_outcome_grace_seconds`
   后记录(纯 server-lost 留待 agent 覆盖);
3. **封口**日志(`complete` + `final_offset`),之后晚到增量一律 `sealed`;
   按 `states.task_is_erroneous` 判定:failed/lost、`error_code=log_flood`、
   (仅 finished)`error_count>0` / `finish_reason≠finished`、`size-cap`/
   `dir-budget` 截断、agent 上报 `log_bytes ≥ max_file_bytes`;维护截断
   (`maintenance`)永不算;
4. 来自 `schedule_timer` / `schedule_trigger_now` 的 task 写入独立账本
   `schedule_outcome_ledger`(按 `task_id` upsert,不随 Task 保留期清理,按条数
   自修剪),并**重算**该 schedule 当前代际的"连续出错前缀长度"→
   `consecutive_error_count`;达 `auto_disable_after_errors` 即 `enabled=false`
   + `auto_disabled_at/reason` + `schedule_auto_disabled` 通知,tick 提交后再
   `ScheduleRunner.reload()`。

纠正:`lost` 被 agent 硬终态覆盖时 `_update_task` 清空 `outcome_recorded_at`,
记录器下个 tick 重评并更新账本行。手动重启用(`PUT /schedules/{id}`
`enabled=true`)递增 `outcome_generation`、清零计数;task 在创建时固化
`schedule_generation`,旧代际的行(含迟到纠正)永不跨越重置边界。
