---
status: approved
task: log-flood-guard-and-notifications
date: 2026-08-22
approved_at: 2026-08-22 23:08
plan_review_max_rounds: 25
impl_fix_max_rounds: 25
---

# 方案:日志洪泛防护、既有膨胀清理、连续出错自动禁用与消息中心

> **评审轮次授权记录**:默认上限为 3 轮。第 3 轮 plan 评审 fail 后已停下交用户;
> 用户于 2026-08-22 本任务对话中明确指示「plan 和改修都调整为最大 15 轮」,第 13 轮
> fail 后再次明确指示「plan 和改修的轮数上升到最大 25 轮」,据此在 frontmatter 写入
> `plan_review_max_rounds: 25` / `impl_fix_max_rounds: 25`,并将在方案摘要与实现记录
> 中声明。非用户提出不得写入该字段。

## 背景与目标

2026-08-21 生产 console 卡死事故(调查与证据见
`.ai/2026-08-22/redis-log-stream-oom-investigation/investigation.md`)的根因链:

1. steammarket-spider 因表结构变更每批 flush 报 `InvalidColumnReference`,每条
   ERROR 含 1.15MB 的 INSERT 原文;一个执行 40 分钟产出 3GB 日志;
2. agent `LogPublisher` 对 scrapyd 运行**无字节上限、无限速**(`max_job_log_bytes`
   只对 python_wheel 生效),把日志按 256KB/条灌进 `dopilot:server:logs`;
3. 流的 `MAXLEN=100000` 按条数算,在 256KB/条时等效上限 ≈ 35GB;server 的
   100MiB 落盘上限是"消费后丢弃",字节已在 Redis 内存中;
4. 生产 compose 落后仓库,无 `--maxmemory`/容器内存限制;AOF + `restart:
   unless-stopped` 让 Redis 每次重启重放 7GB 再被杀,399 次 OOM kill 拖死宿主机;
5. scrapyd 1.x 不暴露退出码,pipeline 全部报错的爬虫终态仍是 `finished`,
   现有状态机把事故爬虫记为"成功",无从告警。

目标(与用户对齐后的口径):

- **G1 启动清理**:server/agent 启动即清理既有超长超大日志(Redis 日志流超出字节
  预算、server-data 与 agent 本地超过上限的 job.log、旧 agent id 残留命令流),并
  给出本次生产现场的恢复 runbook。
- **G2 防再次膨胀(内存 + 硬盘)**:agent 侧 scrapyd 运行按字节上限强制终止 +
  推送限速;日志流按字节预算裁剪并保证收敛;server 截断后反压 agent 停止 tail;
  server logs 目录总预算为**写入准入硬界**(不是事后淘汰);生产 compose 同步硬限;
  Redis 启动加载超限只杀容器不杀宿主。默认值取"紧"档:agent 每执行日志上限
  32MiB、推送限速 2MiB/s/agent、日志流预算 256MB、server 每文件上限 32MiB、
  logs 目录总预算 20GB、Redis `maxmemory 512mb` + 容器 `1g`。
- **G3 连续出错自动禁用 + 消息中心**:按 **Schedule** 计数(`schedule_timer`
  与 `schedule_trigger_now` 来源的 task 都计入),"出错" = 终态 failed/lost,或
  finished 但 scrapy stats `log_count/ERROR > 0` / `finish_reason ≠ finished`,
  或日志被截断/洪泛终止;连续 5 次(可配置)自动 `enabled=false` 并记录原因;
  web 顶栏铃铛数字小标 + 下拉列表展示"调度因连续出错被禁用"与资源告警
  (日志截断、日志流超预算裁剪、logs 目录超预算、旧命令流清理)。

不在本方案范围:steammarket-spider 仓库自身的 ON CONFLICT 修复;Prometheus
redis-exporter 接入(监控侧运维,另行处理);python_wheel 运行日志上限语义
(维持 0019:超限截断、进程继续)。

## 改动范围

按三个工作包(WP)组织,仅作为实现记录的章节结构;**一个 implementation round
实现完整 plan**(符合 rawf-implement 轮次语义),评审 fail 后的修复轮只修
blocker/major。预计触及文件约 75(含测试),**> 10,需走 plan 评审**。

### WP-A 既有问题清理(启动 + 定期)

| 文件 | 改动 |
|---|---|
| `apps/server/dopilot_server/redis/stream_guard.py`(新) | `StreamGuardLoop`:启动立即 + 每 `stream_guard_interval_seconds`(30s)执行 `enforce_once()`。度量 = `MEMORY USAGE <stream> SAMPLES 0`(精确遍历,100k 条流毫秒级);超过 `stream_max_bytes_logs` 时**迭代收敛**:`target = floor(len × budget/usage × 0.8)`,`XTRIM MAXLEN = target`(**精确**,不带 `~`),重测 usage,最多 8 轮;若两轮之间 usage 下降 < 5%(条目极不均匀/近似失效)或 8 轮后仍超限 → **升级**:`XTRIM MAXLEN 0` 清空流(流是瞬态总线,0008;日志 RPO 非零是既有设计),并写 `redis_stream_over_budget` 通知(severity error,dedupe_key `cleared:<小时桶>`,payload 含 `cleared=true`);正常裁剪写 warning 通知(dedupe_key `trim:<小时桶>`)。返回 `{trimmed, iterations, cleared, final_bytes}` |
| `apps/server/dopilot_server/redis/client.py` | 新增 `memory_usage(key, samples=0)`、`scan_keys(pattern)`、`delete(key)`;`xtrim` 已支持 `approximate=False`。fake 替身同步补(`memory_usage` 以各 entry 字段字节和 + 每条 64B 开销估算) |
| `apps/server/dopilot_server/services/maintenance.py` | `truncate_oversized_log_files`:**只处理已封口的日志**(`status == complete` 且 `final_offset` 非空),逐行 `SELECT task FOR UPDATE` → `SELECT log_file FOR UPDATE` 后再核对状态,在 `gauge.writer()` 临界区内物理截断到 cap + 标记并按实测差值扣减 gauge(同一临界区),`log_integrity=truncated`、**`truncation_reason='maintenance'`**、`size_bytes`/`final_offset` 更新;**该截断不参与出错判定**(`execution_is_erroneous` 只认 `size-cap`/`dir-budget`),因此已记录的结果不受影响、无需失效重算——与结果相关的完整性在封口后确实不再变化,启动时 reconcile 先于 retention 首轮也不产生竞态;`evict_logs_dir_to_budget`:`logs.max_total_bytes` > 0 时调用 `gauge.calibrate()`,按 `finished_at` 最老的 terminal 任务起复用 `cleanup_terminal_data` 两阶段删除直至预算内——**eligibility 收紧为该 task 全部日志已封口**(`cleanup_terminal_data` 同步收紧,并在删除前按 task → log_file 顺序 `FOR UPDATE`;其 unlink 与 gauge 扣减同在 `gauge.writer()` 临界区),仍处于 drain 窗口(active/finalizing)的 terminal 任务跳过;**无法恢复(剩余全为活动日志)→ 写 `logs_dir_over_budget` error 通知并交由准入硬界兜底(见 WP-B `services/logs.py`)**;统计结果写入 `LogsDirGauge`(内存计数器,供准入判断);`delete_stale_command_streams`:`SCAN dopilot:agent:*:commands`,对每个 agent_id 同时满足才 `DEL`:① nodes 表无该 agent_id,**或**该节点 `deleted_at` 非空(软删,`node.py:60`),**或** `last_seen_at` 早于 `stale_command_stream_days`;② 流最后 id 早于 `stale_command_stream_days`;③ 该 agent 无非终态 Execution;④ 该 agent 无 `pending/dispatching/sent/failed_retryable` outbox 行。健康或近期心跳的节点一律保留;写 info 通知 |
| `apps/server/dopilot_server/logs/dir_gauge.py`(新) | `LogsDirGauge`:进程内计数器,所有读改写都在**同一个 `asyncio.Lock`** 下完成(单进程、单事件循环):**串行化协议(一把 `asyncio.Lock`,`gauge.writer()` 上下文)**:LogConsumer 的每次落盘在该锁内完成整段「计算实际计划写入字节 `planned`(size-cap 下 = 能放下的正文前缀 + 标记;dir-budget 下 = 标记或 0)→ `value + planned ≤ budget` 判定 → 记 `before = stat(path).st_size`(不存在则 0)→ 线程池写入 → **无论成功或抛异常**都重新 `stat` 得 `after`,`value += after - before`」(部分写入、ENOSPC、flush/close 失败都按物理实测计入,永不低估);`calibrate()`(启动与每次 sweep)与维护侧的**「物理 truncate/unlink + 按 truncate 前后 `os.stat` 实测差值 `sub`」整段**也在同一把锁内执行(`async with gauge.writer(): 截断/删除 → 计算实际释放 → value -= 释放`,物理修改与扣减之间不可能插入校准),校准持锁跨越整个 `os.walk`(单进程、目录规模千级文件、秒级;LogConsumer 期间阻塞,消息不丢只是延后)。因此**任意时刻 value == 目录实际字节**(校准时精确相等、其后只有锁内的同步增减),不存在 pending/在途写入,无高估/低估问题。启动时先校准再启动消费者 |
| `apps/server/dopilot_server/retention.py` | sweep 已是启动立即执行(`retention.py:105-108`);tick 末尾追加 `truncate_oversized_log_files` → `evict_logs_dir_to_budget` → `delete_stale_command_streams` → `prune_notifications`,各自独立 try/except |
| `apps/server/dopilot_server/app.py` | lifespan **不做迁移**(schema 由独立 `migrate` 服务 / 运维前置 `alembic upgrade head` 保证,维持 Alembic 独占);consumers 启动前先 `StreamGuardLoop.enforce_once()` 与 `LogsDirGauge.calibrate()`,再启动 consumers 与各 loop;`LogsDirGauge` 单例挂在 `app.state`,consumer / maintenance / resource_stats 共用 |
| `apps/agent/dopilot_agent/janitor.py` | 新增步骤 C8「非活动超大 job.log 截断」,**只在能证明作业已停止时截断**,全部条件须同时成立:① execution 不在 consumer 的 active set 与 `_processing`;② state 存在且 `phase == done`,**或** state 缺失/损坏但 scrapyd `listjobs` 的 running/pending 都不含该 job(按路径 `{project}/{spider}/{job}.log` 反查)且文件 mtime 静默 ≥ `janitor_quiet_seconds`(默认 3600);③ 在该 execution 的 `execution_lock` 内二次校验 size/mtime 后才 `truncate` 到 cap + 标记。`phase == started` 的一律不碰(交给 WP-B 闸 1)。wheel workspace `job.log` 同规则(用既有 pgid 存活判定替代 listjobs)。启动即跑 |
| `docs/architecture/05-deployment.md` | 新增「事故恢复 runbook」(以 Compose project 名 `P`(= compose 目录名,生产为 `dopilot`)参数化,volume 名为 `${P}_dopilot-redis` / `${P}_dopilot-db`):**本次事故现场 server 已停、容器已删,从 ③ 开始;常规流程**:① server 仍在运行时,先在 web「一键停用全部调度」,然后分别查询 `GET /api/v1/tasks?status=queued`、`?status=running`、`?status=finalizing`(admin Bearer,`status` 只接受单值,`tasks.py:27-32`),等待三者响应的 `total` 都为 0(或对长期悬挂的任务用维护页「标记 lost」),使命令流不再有未接管命令;② 每台 agent 主机 `docker compose -f docker-compose.agent.yml down` 并 `docker compose ps` 确认无容器;然后 server 主机 `docker compose down`,`docker compose ps` 确认 server/redis/db 均已停止,`docker ps --filter volume=${P}_dopilot-redis` 为空;③ 在同一静止点**成对备份**(0007:索引与正文缺一不可):`docker run --rm -v ${P}_dopilot-db:/src -v /opt/backup:/dst alpine tar czf /dst/dopilot-db-$(date +%F).tgz -C /src .` 与 `docker run --rm -v ${P}_dopilot-server-data:/src -v /opt/backup:/dst alpine tar czf /dst/dopilot-server-data-$(date +%F).tgz -C /src .`;保留旧 compose 为 `docker-compose.yml.bak` 并记下旧镜像 digest;④ `docker volume rm ${P}_dopilot-redis`(流是瞬态总线,0008;未接管的 `sent` 命令由新版 dispatcher 的 sent 对账自动回退重投,queued task 不会悬挂);⑤ 用仓库 `deploy/docker/docker-compose.server.yml` 覆盖 `/opt/dopilot/docker-compose.yml`(.env 不动),`docker compose pull`;⑥ `docker compose up -d`(migrate 先跑完,server 依赖其 `service_completed_successfully`),`docker compose ps` 三服务 healthy、`curl -f http://localhost:5000/api/v1/health`;⑦ agent 主机拉新镜像后 `up -d`,web 节点页确认两 agent 心跳;⑧ 维护页资源面板确认 `redis.stream_bytes:logs` / `logs.dir_bytes` 在限内,任务页确认无悬挂 queued;⑨ steammarket 调度在爬虫仓库修好前保持禁用。**回滚**(顺序敏感):`docker compose down` → **仍用新 compose/新镜像**执行 `docker compose run --rm migrate alembic downgrade 0012`(旧镜像不含 0013,无法自行降级)→ 恢复 `docker-compose.yml.bak` 与旧镜像 digest → **成对恢复** ③ 的两份备份(先 `docker volume rm` 再 `tar xzf` 回两个 volume;新版本启动清理已截断/淘汰过 server-data,只恢复 DB 会得到索引与正文不一致)→ `up -d`。因 agent 在整个窗口内停机,不存在老 agent 收到 `stop_logs` 的毒消息问题 |

### WP-B 防再次膨胀

| 文件 | 改动 |
|---|---|
| `apps/agent/dopilot_agent/config/settings.py` / `config/loader.py` | `[agent] max_job_log_bytes` 默认 104857600 → **33554432**,语义扩展为"所有 runner 的每执行日志上限";`[agent] janitor_quiet_seconds = 3600`、`log_flood_kill_after_seconds = 30`(env `DOPILOT_AGENT_LOG_FLOOD_KILL_AFTER_SECONDS`);`[redis] log_publish_rate_bytes_per_second = 2097152`(0 = 不限速);env `DOPILOT_AGENT_MAX_JOB_LOG_BYTES`(已有)、`DOPILOT_AGENT_JANITOR_QUIET_SECONDS`、`DOPILOT_REDIS_LOG_PUBLISH_RATE_BYTES_PER_SECOND` |
| `apps/agent/dopilot_agent/redis/commands.py` | ① `_process` 把 `from_stream_entry` 解码移入 try:解码失败(未知 type / 坏 JSON)记 warning 并 XACK,不再成为毒消息(现状 `commands.py:377` 在 try 之外);② `max_job_log_bytes > 0` 时(**0 = 关闭,沿用既有语义**:不注入 `-s` cap、watchdog 与 LogPublisher 上限都不生效)`reconcile_started_attempts` 每 tick 对 scrapyd 运行 `getsize(state.log_path)`,≥ cap 且未标记 → `store.mark_log_flood(execution_id, bytes, requested_at)` + `runner.stop()`;**flood 后每 tick 持续处理直到作业不在 scrapyd running/pending**(此 watchdog 是第二道防线,第一道是进程内 sink,见 `logcap.py`;盲窗内写入已被 sink 界定为 ≤ cap + 一条记录 + 标记):(i) 把本地文件 `os.truncate` 回 cap + 标记(对绕过 FileHandler 的自定义日志兜底;scrapy 以 O_APPEND 写,截断后继续追加);(ii) 升级终止:每 tick 重发 `runner.stop()`(scrapyd cancel 幂等),`now - requested_at ≥ log_flood_kill_after_seconds`(默认 30)后改用 `signal=KILL` 的 cancel,再超过 2 倍时间仍存活且为**受管 scrapyd 模式** → **单 PID 精确终止**:扫描 `/proc/*/cmdline`,找到**同时**满足 argv 含 `scrapy`/`crawl` 与 `_job=<scrapyd_job_id>`、且 `/proc/<pid>/stat` 的 ppid == agent 所管理的 scrapyd 进程 pid(`scrapyd/process.py` 持有)的**唯一**进程(外部模式无该 pid → 跳过此级),对该 pid `os.kill(pid, SIGKILL)`(**绝不用 killpg**:scrapyd 以 `spawnProcess` 启动作业,不为作业建独立进程组,killpg 会连带 scrapyd 与其他 crawler);找到 0 或 >1 个候选则不杀、记 error 并继续每 tick 重发 cancel(磁盘仍由 (i) 截回有界);`stop()` 抛异常只记 warning,下 tick 重试;终态解析时 `log_flood=True` 的执行统一发 **`attempt.failed`,`error_code="log_flood"`,`error_detail={"log_bytes","cap","kill_escalation"}`**(覆盖 scrapyd 的 canceled/finished);③ `stop_logs` 命令 → `publisher.cap(execution_id)` |
| `apps/agent/dopilot_agent/logcap.py`(新)、`apps/agent/dopilot_logcap.pth`(新)、`apps/agent/pyproject.toml` | **受控日志 sink(进程内硬界)**:`.pth` 经 hatch `force-include` 装到 site-packages 根,解释器启动即 `import dopilot_agent.logcap`;该模块在导入时**只根据 `sys.argv` 判定 crawler 身份**:argv 须同时含 `crawl`、`_job=`(scrapyd 给 crawler 的作业参数)与 `-s DOPILOT_JOB_LOG_CAP_BYTES=<n>`(scrapyd 把 schedule 请求的 `setting` 原样作为 `-s k=v` 传给 crawler 命令行,因此**受管与外部 scrapyd 两种模式都生效**);缺任一条件或 n=0 → 立即返回、不打补丁(scrapyd 守护进程、agent、任何非 crawler 进程都不满足)。**不使用环境变量**作为激活来源。打补丁对象为 `logging.FileHandler`,且**只对 `baseFilename` 等于 argv 中 `-s LOG_FILE=<path>` 的那个 handler 实例生效**(crawler 的其他 FileHandler 不受影响)(scrapy 的 `LOG_FILE` 正是 `logging.FileHandler`,`scrapy/utils/log.py`):每个 handler 实例累计已写字节,达上限后写一次 `[dopilot:job-log-truncated reason=size-cap]` 标记、之后所有记录丢弃(不再写盘),并向自身进程发一次 `SIGTERM`(scrapy 优雅关闭,`finish_reason=shutdown`);可证明的最大写入量 = **cap + 一条记录 + 标记**,与 agent 轮询无关。非 scrapy 进程(agent 自身、未设环境变量)完全不受影响 |
| `apps/agent/dopilot_agent/runners/scrapyd.py`(schedule 注入) | `schedule()` 在既有 runtime-context settings 之外追加 `DOPILOT_JOB_LOG_CAP_BYTES=<max_job_log_bytes>`(走 scrapyd `schedule.json` 的 `setting` 参数,与 `_runtime_context_scrapy_settings` 同一通道),每个 job 的 crawler 进程 argv 即带该值 |
| `apps/agent/dopilot_agent/main.py`、`docs/architecture/04-configuration.md` | **外部 scrapyd 模式(`scrapyd.start=False`)的兼容路径**:硬界同样由 `.pth` 钩子 + `-s` 注入实现(两种模式完全同一机制,不依赖 scrapyd 进程环境),前提是外部 scrapyd 的 Python 环境安装了 `dopilot-agent` 包(`.pth` 随包安装),docs/04 写为该模式的必要条件;agent 启动时在该模式下记一条 warning 并在心跳 `detail.scrapyd.log_cap = "external"`;PID 升级终止在该模式下**禁用**(无已知 scrapyd 父 pid,候选校验必失败,绝不猜杀),cancel TERM/KILL 与每 tick 截回照常 |
| `apps/agent/dopilot_agent/state/store.py` | `AttemptState` 增 `log_flood: bool=False`、`log_flood_bytes: int=0`、`log_flood_requested_at: str|None=None`、`log_flood_escalation: str|None=None`(term/kill/pidkill)、`log_capped: bool=False`、`error_count: int|None=None`、`finish_reason: str|None=None`;`mark_log_flood()`、`mark_log_capped()`、`mark_stats()` |
| `apps/agent/dopilot_agent/redis/logs.py` | 每执行推送上限 = `max_job_log_bytes`(0 = 不限):达上限后只再发一条内容为截断标记的 entry 并 `mark_log_capped`,之后跳过该执行(done 时仍发 eof);全 agent 令牌桶限速(`log_publish_rate_bytes_per_second`,桶容量 = 2 秒配额,按单调时钟补充),本 tick 配额用尽则剩余执行留到下 tick,下 tick 从上次中断的执行开始轮转(不饿死);`cap(execution_id)` 供 `stop_logs` 调用 |
| `packages/protocol/dopilot_protocol/streams.py` | `AgentCommandType` 增 `stop_logs`;`AgentEvent` 增可选 `error_count: int|None`、`finish_reason: str|None`、`log_bytes: int|None`(默认 None,老 agent 事件仍可解析) |
| `apps/agent/dopilot_agent/scrapyd/stats.py`(新) | `parse_scrapy_stats(tail: bytes) -> ScrapyStats`:从日志末尾 64KB 解析 `'log_count/ERROR': N`、`'finish_reason': '...'`;无 stats 块 → 字段为 None |
| `apps/agent/dopilot_agent/runners/scrapyd.py`、`scrapyd/client.py` | `stop(..., signal="TERM"|"KILL")` 透传 scrapyd `cancel.json` 的 `signal` 参数;终态时读日志尾部解析 stats,写 state 并随 `emit_terminal` 上报 `error_count`/`finish_reason`/`log_bytes` |
| `apps/server/dopilot_server/config/settings.py` / `config/loader.py` | `[redis] stream_max_bytes_logs = 268435456`、`stream_guard_interval_seconds = 30`;`[logs] max_file_bytes` 104857600 → **33554432**、`max_total_bytes = 21474836480`;`[maintenance] stale_command_stream_days = 7`、`notification_retention_days = 30`、`notification_unread_max_days = 90`、`notification_max_rows = 2000`(env `DOPILOT_MAINTENANCE_NOTIFICATION_UNREAD_MAX_DAYS` / `DOPILOT_MAINTENANCE_NOTIFICATION_MAX_ROWS`);`[redis] sent_reconcile_interval_seconds = 300`、`sent_reconcile_min_age_seconds = 60`(env `DOPILOT_REDIS_SENT_RECONCILE_INTERVAL_SECONDS` / `DOPILOT_REDIS_SENT_RECONCILE_MIN_AGE_SECONDS`);`[scheduler] auto_disable_after_errors = 5`、`lost_outcome_grace_seconds = 86400`(env `DOPILOT_SCHEDULER_LOST_OUTCOME_GRACE_SECONDS`);env:`DOPILOT_REDIS_STREAM_MAX_BYTES_LOGS`、`DOPILOT_REDIS_STREAM_GUARD_INTERVAL_SECONDS`、`DOPILOT_LOG_MAX_FILE_BYTES`(已有,`loader.py:115`,沿用 `DOPILOT_LOG_` 前缀)、`DOPILOT_LOG_MAX_TOTAL_BYTES`(同前缀)、`DOPILOT_MAINTENANCE_STALE_COMMAND_STREAM_DAYS`、`DOPILOT_MAINTENANCE_NOTIFICATION_RETENTION_DAYS`、`DOPILOT_SCHEDULER_AUTO_DISABLE_AFTER_ERRORS` |
| `apps/server/dopilot_server/services/logs.py` | ① **目录预算准入硬界(含标记)**:在 `gauge.writer()` 锁内先算出本次实际计划写入 `planned`(见 `dir_gauge.py`),`value + planned > max_total_bytes` 则降级:正文不写,标记放得下才写标记;正文放不下 → 不写正文;标记也只在 `gauge + len(marker) ≤ max_total_bytes` 时落盘,**否则一个字节都不写**,仅置 DB 状态(`log_integrity=truncated`、新列 `truncation_reason='dir-budget'`,web 已按 `log_integrity` 显示截断态)+ 通知;因此目录字节数在任何执行数量下都 ≤ `max_total_bytes`;outcome `truncated_dropped`,之后同 size-cap 处理(仍消费 + ACK);② `truncated_now`(size-cap 或 dir-budget)时向该执行所属 agent 入队 `stop_logs` outbox 命令(`create_stop_logs_outbox`,按 execution 去重:已存在未终结行则不重复)并写 `log_truncated` 通知;③ gauge 按写前/写后 `stat` 差值累加(锁内,异常路径同样结算),不存在预留/回退两步;④ **非可写状态一律拒收**:只有 `status ∈ {active, finalizing}` 的 log file 接受增量;`complete`(记录器/`finalize_drained_logs` 封口)、`expired`(`cleanup_terminal_data` 第一阶段已提交)、`missing` 的增量一律不落盘、不创建文件、不改 `log_integrity`、outcome `OUTCOME_SEALED`,仍 ACK(现状 `apply_log_event` 不拒绝已 complete/expired 文件的晚到增量,会在 unlink 后重建孤儿文件);⑤ **行锁**:`get_log_file` 改为 `SELECT … FOR UPDATE`(`with_for_update()`),状态判断、落盘、`size_bytes`/`log_integrity` 更新都在持锁事务内,提交后释放——与记录器封口、维护截断/淘汰互斥,维持 `files.py:180-185` 单写者不变量(aiosqlite 下 `FOR UPDATE` 退化为无操作,并发用例只在 PostgreSQL 上跑) |
| `apps/server/dopilot_server/services/outbox.py` / `redis/dispatcher.py` | 新增 `create_stop_logs_outbox`;dispatcher 允许 `stop_logs`(投递路径同 `cleanup_logs`,无业务状态变更);**`sent` 行对账(at-least-once,0008)**:dispatcher 启动时与每 `sent_reconcile_interval_seconds`(默认 300)对 `status == sent` 且所属 task 非终态、`updated_at`(置 `sent` 时由 dispatcher 写入,`command_outbox.py:81`,不新增字段)早于 `sent_reconcile_min_age_seconds`(默认 60,覆盖 agent `command_block_ms` 5s 的数倍)的行,用 `XRANGE <agent 命令流> <redis_msg_id> <redis_msg_id>` 核对消息是否仍在流中;不在(流被清空/裁剪)→ 置回 `pending` 重投(agent 按 `execution_id` 幂等),记 warning 并计入 `notifications`(info,日桶)——覆盖 runbook 删除 Redis volume 的情形 |
| `apps/server/dopilot_server/services/events.py` | 终态事件把 `error_count`/`finish_reason`/`log_bytes` 落到 `Execution` 新列;终态 `error_code == log_flood` 时写 `log_flood` 通知(warning,dedupe_key = execution_id,payload = task_id/execution_id/agent_id/log_bytes/cap/kill_escalation);**不在此处做计数**(见 WP-C) |
| `apps/server/dopilot_server/models/execution.py` + `apps/server/migrations/versions/0013_log_guard_outcomes_notifications.py` | `Execution` 增 `error_count Integer null`、`finish_reason String null`、`log_bytes BigInteger null`;`Task` 增 `outcome_recorded_at DateTime null`、`outcome_erroneous Boolean null`(记录器写入,索引 `(status, outcome_recorded_at)`);`ExecutionLogFile` 增 `truncation_reason String null`(size-cap / dir-budget) |
| `deploy/docker/docker-compose.server.yml`、`docker-compose.yml` | redis 服务加 `mem_limit: 1g`、`memswap_limit: 1g`;server 加 `mem_limit: 2g`;注释说明"AOF 超过 maxmemory 时容器自毁重启但宿主无恙,反复发生请按 runbook 清空 volume";`docker-compose.agent.yml` 核对已有限制并补注释 |
| `configs/server.example.toml`、**`configs/server.docker.toml`**(生产镜像实际加载的文件,`deploy/docker/Dockerfile` 复制;现 `max_file_bytes = 104857600` 须改为 33554432 并补新项)、`configs/agent.example.toml`(`max_job_log_bytes` 同步改 33554432) | 新增/更新配置项与注释 |
| `apps/agent/pyproject.toml` | `dev` extra 加入 `hatchling`(供 TC-01i 离线构建 wheel;根 pyproject 不是可安装包,0005) |
| `apps/server/dopilot_server/resource_stats.py` | Redis scope 增 `redis.stream_bytes:logs`(limit = `stream_max_bytes_logs`);logs scope 增 `logs.dir_bytes`(取 `LogsDirGauge`,limit = `max_total_bytes`) |

### WP-C 连续出错自动禁用 + 消息中心

| 文件 | 改动 |
|---|---|
| `apps/server/dopilot_server/models/scheduling.py` + 迁移 0013 | `Schedule` 增 `consecutive_error_count Integer default 0`、`auto_disabled_at DateTime null`、`auto_disabled_reason JSON null`、`outcome_generation Integer default 0`;`Task` 增 `schedule_generation Integer null`(创建时固化;**迁移 0013 回填**:`UPDATE tasks SET schedule_generation = 0 WHERE schedule_id IS NOT NULL`,记录器对仍为 NULL 的行按 0 处理);新表 **`schedule_outcome_ledger`**(`id`、`schedule_id` FK ON DELETE CASCADE + 索引、`task_id`(唯一)、`generation Integer`、`finished_at`、`erroneous Boolean`、`recorded_at`):**独立于 Task 行的结果账本**,`cleanup_terminal_data` 删除 Task/Execution/日志行时不触碰它;记录器每次 insert 后按 schedule 只保留最新 `max(100, auto_disable_after_errors × 2)` 行(自修剪),保留期与 `logs.retention_days` 无关 |
| `apps/server/dopilot_server/models/notification.py`(新)+ 迁移 0013 | `notifications`:`id`、`type`(`schedule_auto_disabled` / `log_truncated` / `log_flood` / `redis_stream_over_budget` / `logs_dir_over_budget` / `stale_command_streams_deleted`)、`severity`(info/warning/error)、`payload JSON`、`dedupe_key String null`(活跃期唯一:同 key 未读则 `count+1`、`last_seen_at` 更新而不新建)、`count Integer default 1`、`read_at null`、`created_at`、`updated_at`、`last_seen_at`;索引 `(read_at, created_at)`;**部分唯一索引 `uq_notifications_active_dedupe` ON `(type, dedupe_key) WHERE read_at IS NULL`**(PostgreSQL 与 SQLite 均支持 partial unique index) |
| `apps/server/dopilot_server/services/notifications.py`(新) | `notify(session, *, type, severity, payload, dedupe_key=None)`:有 `dedupe_key` 时用方言 `insert(...).on_conflict_do_update(index_elements=[type, dedupe_key], index_where=read_at IS NULL, set_={count: count+1, last_seen_at, payload, severity})` 原子 upsert(PostgreSQL 与 SQLite 方言均支持 `index_where`),跨 session 并发只落一行;无 key 直接插入;`list_notifications(unread_only, limit, before)`、`unread_count`、`mark_read(ids)`、`mark_all_read`、`prune_notifications(settings)`(**有界,0019**):① 已读且早于 `notification_retention_days` 的删除;② **未读**且早于 `notification_unread_max_days`(默认 90)的删除;③ 总行数超过 `notification_max_rows`(默认 2000)时按 `created_at` 最老优先删除(先已读后未读)直至上限——三者叠加使表在无人处理时仍有界;upsert 的 `severity` 取 `max(existing, new)`(info<warning<error,只升不降),`payload` 中 `cleared`/`escalation` 等关键布尔字段 sticky(一旦 true 不回退) |
| `apps/server/dopilot_server/services/states.py` | `execution_is_erroneous(execution, log_file, settings)`:status ∈ {failed, lost} 或 `error_code == log_flood` 或(**仅当 status == finished**:`error_count > 0` 或 `finish_reason not in (None, "finished")`;`canceled` 的 `finish_reason=shutdown`/stats 不算出错)或(`log_file.log_integrity == truncated` 且 `truncation_reason ∈ {size-cap, dir-budget}`,`maintenance` 不算)或 **`logs.max_file_bytes > 0` 且 agent 上报 `execution.log_bytes ≥ logs.max_file_bytes`**(截断必然发生,不依赖 server 截断是否已落地;0 = 关闭时不判);`task_is_erroneous(task, executions, log_files)`:task.status ∈ {failed, lost} 或任一执行出错;无执行的终态 task(如调度期 no_target)按 task.status 判 |
| `apps/server/dopilot_server/services/outcomes.py`(新) | **唯一、幂等的"任务结果已最终确定"提交点** `record_task_outcomes(session, settings, now) -> list[schedule_id_disabled]`:选取 `status ∈ TASK_TERMINAL AND outcome_recorded_at IS NULL` 的 task,按 `finished_at, id` 升序;对每个 task 要求其全部 `ExecutionLogFile.status ∉ {active, finalizing}`(日志完整性已定稿,由 `reconcile.finalize_drained_logs` 推进),**或** `now - finished_at > log_drain_timeout_seconds + 60`(兜底,避免无日志/超时路径永不记录);**封口**:在同一事务把该 task 所有 log file 置 `status=complete`、`final_offset=size_bytes`(已 complete 的不变),之后 `apply_log_event` 对封口文件的增量一律丢弃(见 WP-B `services/logs.py` ④),因此记录后日志完整性不可再变;评估 `task_is_erroneous` → 写 `outcome_erroneous`、`outcome_recorded_at`;**锁序**(所有路径一致:`task` 行 → 该 task 的 `executions` 行 → `execution_log_files` 行 → `schedule` 行,均 `FOR UPDATE`;**所有 Execution/Task 终态写入者**——`events.apply_event`、`reconcile.mark_lost`(`reconcile.py:78`,现无锁选出 active execution)、`dispatcher._fail_execution_dispatch_timeout`(`dispatcher.py:139`)、`maintenance.mark_task_lost`、`services/cancel.py`——都改为先按该顺序 `FOR UPDATE` 再**重读 status 复核仍为 active/可覆盖**后才写,陈旧对象不再能覆盖已提交的权威终态):记录器对每个候选 task 先锁 task 行,再锁其全部 log file 行,**持锁后重新读取** status/`log_integrity`/`outcome_recorded_at` 再评估、封口、写账本;因此 LogConsumer 未提交的截断要么先提交(记录器读到 truncated),要么在记录器提交后才获得行锁(读到 complete → `sealed` 丢弃);`events._update_task` 在 rollup 前 `SELECT task FOR UPDATE`,lost→硬终态的覆盖要么先于记录器提交(记录器记录新状态),要么在记录器提交后看到 `outcome_recorded_at` 并清空它(触发重评)。**soft-lost 策略**:`status == lost` 的 task 只在下列情形记录:(a) 其 lost 执行已发过 reclaim(`outbox.reclaim_ever_issued`)且 drain 窗口已过;(b) 超过 `scheduler.lost_outcome_grace_seconds`(默认 86400)仍为 lost(有界兜底);纯 server-lost 且未到 (b) 的 task 不记录、不封口(与 `reconcile.py:226-229` "pure server-lost 留待 drain" 一致)。**可纠正账本**:`events._update_task` 把 task 从 `lost` 重新 rollup 为硬终态时(`events.py:144-153`),若 `outcome_recorded_at` 非空则将其与 `outcome_erroneous` 置 NULL(封口保持),记录器下个 tick 重新评估;若 `task.schedule_id` 且 `source ∈ {schedule_timer, schedule_trigger_now}`:`SELECT schedule FOR UPDATE`,**不做增量加减**,而是向 `schedule_outcome_ledger` 写入/更新该 task 的行(纠正时按 `task_id` upsert),再从账本**重算**:取该 schedule 的账本行按 `(finished_at DESC, id DESC)`,(仅 `generation == schedule.outcome_generation` 的行)数连续 `erroneous=true` 的前缀长度 → 写入 `consecutive_error_count`(账本不随 Task 保留期清理,长间隔调度的早期失败不会丢失;旧代际的行不参与)(因此同一 schedule 内无论各 task 定稿先后,计数始终等于按完成顺序的真实连续值:"失败 A 未定稿 → 成功 B 已定稿 → A 补记" 得 0;"B..E 已记失败 → A 补记失败" 得 5;lost 被纠正为 finished 后重算自动下降);达 `auto_disable_after_errors`(0 关闭)且 `enabled` → `enabled=false`、`auto_disabled_at`、`auto_disabled_reason={"consecutive_errors", "task_ids"(最近 n 个), "last_error"}`,写 `schedule_auto_disabled` 通知(error),收集 schedule_id 返回。**不经过事件路径的终态写入(dispatcher 超时 `dispatcher.py:139`、`reconcile.mark_lost`、`maintenance.mark_task_lost`、取消)全部被该轮询覆盖**,重复投递/重复 tick 因 `outcome_recorded_at` 幂等 |
| `apps/server/dopilot_server/redis/reconcile.py` | `RedisReconcileLoop._tick`(`reconcile.py:266`)在 `finalize_drained_logs` 之后调用 `record_task_outcomes`;**session.commit() 成功后**再对返回的非空列表调用注入的 `on_schedules_disabled()`(= `ScheduleRunner.reload`),commit 失败不回调 |
| `apps/server/dopilot_server/services/schedules.py` | `update_schedule` 把 `enabled` 置 true 时清零 `consecutive_error_count`、清除 `auto_disabled_*`,并 **`outcome_generation += 1`**(持久重置代际,迁移 0013 加列,默认 0);`fire_timer` / `trigger_now` 创建 task 时把当时的 `schedule.outcome_generation` **固化到 `Task.schedule_generation`**(创建即定,不随终态/`finished_at` 改写而变);记录器写账本行时带上该 generation,重算只统计 `generation == schedule.outcome_generation` 的行,因此重启用后计数从 0 起,重置前创建的旧任务(含迟到的 lost 纠正,即使其 `finished_at` 被 `_update_task` 改写为纠正时刻)永远留在旧代际、不跨越边界;`schedule_view` 输出四个新字段 |
| `apps/server/dopilot_server/api/v1/notifications.py`(新)、`router.py`、`schemas.py` | `GET /api/v1/notifications?unread_only=&limit=&before=`、`GET /api/v1/notifications/unread-count`、`POST /api/v1/notifications/read`(body ids)、`POST /api/v1/notifications/read-all`;admin 鉴权同其他 v1 路由 |
| `apps/server/dopilot_server/app.py` | 把 `schedule_runner.reload` 注入 `RedisReconcileLoop(on_schedules_disabled=…)` |
| `apps/web/lib/api/notifications.ts`(新)、`lib/api/types.ts`、`lib/api/schedules.ts` | 客户端封装与类型;`Schedule` 类型加三个字段 |
| `apps/web/components/layout/notification-bell.tsx`(新)、`components/layout/top-controls.tsx` | 铃铛(lucide `Bell`)+ 未读数徽标(>99 显示 `99+`),`DropdownMenu` 下拉:最近 20 条,按 `type` + `payload` 经 i18n 渲染标题/正文,未读加粗,点击条目 → 标已读并跳转(`schedule_auto_disabled` → `/schedules?highlight=<id>`,`log_*` → 既有静态详情路由 `/tasks/detail?id=<task_id>`),底部「全部已读」;每 30s 轮询 unread-count,打开下拉时拉列表 |
| `apps/web/app/(app)/schedules/page.tsx` | 列表行显示「已自动禁用」Badge(tooltip 展示原因与时间);重新打开沿用现有 `PUT /api/v1/schedules/{id}`(`schedules.py:121`,web `axios.put`) |
| `apps/web/lib/i18n/locales/en.ts`、`zh.ts` | `notifications.*`(每种 type 的标题/正文模板)、`schedules.autoDisabled*` |
| `docs/architecture/02-domain-model.md`、`03-execution-and-logs.md`、`04-configuration.md`、`06-web-frontend.md` | 回写新表与字段、洪泛防护/反压/字节预算/准入硬界/结果记录器、新配置项、消息中心 |
| `docs/decisions/0021-log-flood-guard-and-auto-disable.md`(新) | 记录决策:洪泛 = 失败;按字节而非条数约束日志流且不可收敛时清空;目录预算为写入准入硬界;出错口径含 scrapy stats;任务结果在日志定稿后由单一记录器幂等判定;按 Schedule 连续计数;消息中心单表 + 去重键 |

**明确不动**:python_wheel 日志截断语义(0019);Redis AOF 要求(`require_aof`,0008);
单实例/单管理员约束;MAXLEN 条数上限保留为次级约束;`cleanup_logs` 命令语义;
`events._update_task` 的 rollup 逻辑。

## 实现方案

### 1. 洪泛防护的闸门

```
scrapy 写 job.log ─► [闸 1a crawler 进程内] logcap FileHandler: 字节 ≥ cap ─► 停写 + 标记 + SIGTERM 自身
        │           [闸 1b agent watchdog] tick: size ≥ cap ─► cancel(TERM→KILL→单 PID)+ 每 tick 截回 ─► 终态 failed/log_flood
        └─► LogPublisher ─► [闸 2 agent] 推送字节 ≥ cap → 标记 entry、停止 tail(log_capped)
                            令牌桶 2MiB/s/agent ─► XADD(MAXLEN ~100000 次级)
server 消费: [闸 3] 文件 ≥ max_file_bytes 或 目录 gauge ≥ max_total_bytes → 不落盘、标记 truncated
             → 入队 stop_logs 反压 + log_truncated 通知
server 守卫: [闸 4] StreamGuard 30s: MEMORY USAGE > 256MB → 精确 XTRIM 迭代收敛,不收敛则清空 + 通知
```

- 闸 1 = **进程内受控 sink**(`logcap.py`,经 `.pth` 装入 scrapyd 环境,cap 经 scrapyd
  `-s` 设置进入 crawler argv,钩子只凭 argv 中的 crawler 身份激活,scrapyd 守护进程
  与 agent 进程永不被打补丁;受管/外部 scrapyd 同一机制):
  写入量硬界 = cap + 一条记录 + 标记,不依赖任何轮询;达限即 SIGTERM 自身。agent
  watchdog(每 tick 检查大小、截回、升级终止)是第二道防线,覆盖绕过 FileHandler
  的自定义日志。闸 2 是发布端兜底(配置被调宽、或文件在一个 tick 内暴涨)。终止则按 TERM → KILL →
  本地单 PID SIGKILL(ppid 校验,绝不 killpg)升级;即使进程无法定位,磁盘界仍由每
  tick 截回保证。
- 限速最坏情况:2 agent × 2MiB/s × 30s 守卫间隔 = 120MB < 256MB 预算,守卫只在
  异常时裁剪;正常 1-2KB/条日志不受影响。
- 闸 3 的目录预算是**硬界**:gauge 由启动校准 + 每次落盘前原子预留 + 删除扣减 +
  每小时 walk 重校准维护;正文与截断标记都要先在 gauge 上预留成功才落盘,放不下
  就一个字节都不写(只改 DB 状态),因此无论活动执行多少、来多少新执行,目录都
  不会越过 `max_total_bytes`;事后淘汰只负责"腾出空间"。
- 闸 4 的收敛:精确 `XTRIM MAXLEN`(非 `~`)+ 每轮重测 + 保守系数 0.8;条目极不
  均匀导致两轮间下降 < 5% 或 8 轮未达标 → 清空流并发 error 通知。
- `stop_logs` 反压覆盖"agent 上限配置比 server 宽"及目录预算触发的情形。
- 洪泛终止统一为 **failed + `log_flood`**,web 任务页已有 error_code 展示。

### 2. 出错口径与连续计数(单一提交点)

- agent 终态前读日志尾 64KB 解析 scrapy `Dumping Scrapy stats` 块:
  `'log_count/ERROR': (\d+)`、`'finish_reason': '([^']+)'`;解析失败 → None,
  server 侧 None 不视为出错(保守),但 `log_integrity == truncated` 与 `log_flood`
  必然命中。
- **所有终态写入路径**(事件 rollup、dispatcher 超时、reconcile/maintenance 的
  lost、取消)都不直接计数;计数只由 `outcomes.record_task_outcomes` 在
  `RedisReconcileLoop` 每 tick(`status_poll_interval_seconds`,5s)轮询完成,
  条件是日志文件已定稿(`finalize_drained_logs` 之后)或超过 drain 窗口 + 60s 兜底,
  因此"finished 事件先到、日志随后被标 truncated"的时序不会被记成成功。
- 幂等与不可失真:`Task.outcome_recorded_at` 非空即跳过;记录与封口在同一事务,
  封口后晚到增量被 `apply_log_event` 丢弃,`log_integrity` 不再变化,已记录结果不会
  被后到日志推翻;agent 上报的 `log_bytes` 进入判定,使"日志超限"不依赖 server
  截断先后。
- 顺序无关、保留期无关的计数:`consecutive_error_count` 不是增量计数器,而是每次
  记录/纠正后从独立账本 `schedule_outcome_ledger`(按 `finished_at` 倒序)重算的
  "连续出错前缀长度";账本不被 `cleanup_terminal_data` 清理(只按条数自修剪),因此
  日志定稿先后与 Task 保留期都不影响结果;Schedule 行 `FOR UPDATE` 串行重算。
- soft-lost:`lost` 只在 reclaim 已发且 drain 已过、或超过 24h 宽限后才记录;记录后
  若被 agent 的硬终态覆盖,`_update_task` 清除 `outcome_recorded_at` 触发重评与重算,
  已执行的自动禁用不回滚(`auto_disabled_reason` 留痕,用户手动重开)。
- 自动禁用后的 `ScheduleRunner.reload()` 只在 reconcile tick 的 `session.commit()`
  成功后调用(与 `api/v1/schedules.py:42-59` 先提交后 reload 的既有模式一致)。
- `auto_disable_after_errors = 0` 关闭;手动重新启用(现有 `PUT` 接口)清零计数、清除 `auto_disabled_*`
  并递增 `outcome_generation`;task 在创建时固化代际,重算只看当前代际的账本行,
  `finished_at` 被晚到终态改写也不影响归属。
- 并发正确性:三条路径(EventConsumer、LogConsumer、ReconcileLoop 记录器)与维护
  路径统一锁序 `task → execution_log_files → schedule`(`FOR UPDATE`),持锁后重读再
  决策;LogsDirGauge 在单进程内以一把 asyncio.Lock 串行并用 delta 合并校准。

### 3. 消息中心

- 单表 `notifications`,`dedupe_key` 让高频告警折叠为一条 `count` 递增的未读记录;
  已读后再次发生则新建。
- API 仅 admin;web 铃铛 30s 轮询未读数,下拉时拉列表;跳转目标由 `type`/`payload`
  决定;i18n 在前端按 type 渲染,server 不存自然语言。
- 首期类型与去重键:`schedule_auto_disabled`(schedule_id,error)、`log_flood`
  (execution_id,warning)、`log_truncated`(execution_id,warning)、
  `redis_stream_over_budget`(**裁剪与清空使用不同去重键** `trim:<小时桶>` warning / `cleared:<小时桶>` error,互不覆盖)、
  `logs_dir_over_budget`(日桶,error)、`stale_command_streams_deleted`(日桶,info)。

### 4. 启动清理与生产恢复

- server 启动顺序(schema 已由外部 `migrate` 服务就绪,lifespan 不迁移):
  `StreamGuardLoop.enforce_once()` → `LogsDirGauge` 校准 → consumers → 其余 loop;`RetentionSweepLoop` 启动立即 tick(含超大文件
  截断、目录淘汰、旧命令流、通知修剪)。
- agent 启动:janitor 立即 tick(含 C8,按"证明已停止"条件截断)。
- 生产恢复 runbook 见 docs/05(WP-A 表):全部停机 → 备份 → 删 Redis volume →
  新 compose/镜像 → server 起并健康 → agent 起;含回滚步骤。

### 5. 兼容性

- 协议字段全部可选、默认 None。新命令 `stop_logs` 对**老 agent** 是未知枚举值,
  现状会在 `_process` 解码处抛异常且不 ACK(毒消息);本任务修复解码容错,但修复
  只在新 agent 生效。runbook 在整个升级窗口内停掉 agent,且日常升级遵循 streams.py
  "lockstep version"(agent 与 server 同版本一起升),server 不做按版本门控。
- 迁移 0013 全部为加列/建表/建索引,`downgrade` 完整。
- `max_file_bytes`/`max_job_log_bytes` 默认值变更写入 docs/04(行为收紧,非接口变更)。

## 测试用例

全部 A 档(均可由 pytest / vitest / ruff / tsc / alembic / docker compose config
命令判定),C 档 0 条。A 档证据形态统一为:命令 + 完整 stdout/stderr + 退出码,
落 `evidence/tc-NN-*.txt`。

| 编号 | 档位 | 前置条件 | 步骤 | 预期结果 | 证据形态 |
|---|---|---|---|---|---|
| TC-01 | A | agent fixture:假 scrapyd、state started、log_path 指向临时文件 | 写入 cap+1 字节后 `reconcile_started_attempts`;再让假 scrapyd 把 job 列为 finished,再跑一次 | 第一次触发 `runner.stop` 且 state `log_flood=True`;第二次发出 `attempt.failed`、`error_code=log_flood`、`error_detail.log_bytes ≥ cap`;本地文件被截断为 cap + 标记 | pytest `apps/agent/tests/test_log_flood.py` |
| TC-01b | A | 同 TC-01,但假 scrapyd 的 cancel 第一次抛异常、之后始终把 job 列为 running;mock 单调时钟;假 `/proc` 目录含三个进程:目标 crawler(`_job=<id>`,ppid=scrapyd pid)、同 agent 另一 crawler(`_job=<other>`,同 ppid)、一个 argv 含 `_job=<id>` 但 ppid 不同的干扰进程 | 连续跑 reconcile:t=0、t=5、t=35、t=70,期间每次 tick 前再向文件追加 1MB | t=0 标记 flood、stop 异常只记 warning;t=5 再次 stop(TERM);t=35 stop(KILL);t=70 `os.kill(SIGKILL)` **恰对目标 pid 调用一次**(monkeypatch 记录所有 kill 调用:另一 crawler 与干扰进程从未被 kill,`os.killpg` 从未被调用);**每个 tick 后文件大小 ≤ cap + 标记长度**;escalation=pidkill 记入 state | pytest `test_log_flood.py` |
| TC-01c | A | 同 TC-01b,但假 `/proc` 中有两个进程都满足 `_job=<id>` 且 ppid 正确 | 跑到 t=70 | 不调用任何 kill、记 error、继续重发 cancel;文件仍 ≤ cap + 标记 | 同上 |
| TC-01d | A | `dopilot_agent.logcap` 进程内:monkeypatch `sys.argv` 为 crawler 形态(`scrapy crawl x -s LOG_FILE=<p> -s DOPILOT_JOB_LOG_CAP_BYTES=4096 -a _job=abc`)后 `install()`,创建指向 `<p>` 的 `logging.FileHandler` 与另一个指向其他路径的 FileHandler | 两个 handler 各连续 emit 5000 条 × 10KB;monkeypatch `os.kill` 记录调用 | `<p>` 文件 ≤ 4096 + 一条记录 + 标记,标记恰一次,`os.kill(os.getpid(), SIGTERM)` 恰一次;另一路径文件不受限;argv 为 scrapyd 守护进程形态(`scrapyd`,无 `-s`/`_job`)或 cap=0 时 `install()` 不打补丁、FileHandler 原样 | pytest `apps/agent/tests/test_logcap.py` |
| TC-01e | A | 子进程黑盒:`python script.py crawl x -s LOG_FILE=<p> -s DOPILOT_JOB_LOG_CAP_BYTES=65536 -a _job=abc`,脚本首行显式 `import dopilot_agent.logcap`(等价于 .pth 触发),用指向 `<p>` 的 `logging.FileHandler` 紧循环写 50MB | 子进程因 SIGTERM 退出(returncode == -15 或自行处理后退出)且文件 ≤ 65536 + 一条记录 + 标记;用时 < 10s | 同上 |
| TC-01f | A | 打包与注入接线 | (a) `ScrapydProcess.start()` 用 monkeypatch 的 `Popen` 捕获 kwargs;(b) 读取 `apps/agent/pyproject.toml` 与 `apps/agent/dopilot_logcap.pth`;(c) `ScrapyRunner.schedule()` 对假 scrapyd 客户端发出的 `setting` 列表 | (a) Popen 的 env 中**不含** `DOPILOT_JOB_LOG_CAP_BYTES`(守护进程不激活钩子);(b) `.pth` 内容为 `import dopilot_agent.logcap`,pyproject `force-include` 含该文件映射到 wheel 根;(c) 含 `DOPILOT_JOB_LOG_CAP_BYTES=<cap>` 且既有 runtime-context settings 仍在 | pytest `test_scrapyd_process.py` + `test_packaging.py` + `test_runner.py` |
| TC-01i | A | **`.pth` 生产接线黑盒**:`apps/agent` 的 `[project.optional-dependencies] dev` 加入 `hatchling`(随既有 `pip install -e apps/agent[dev]` 流程安装),测试内 `python -m pip wheel --no-deps --no-build-isolation apps/agent -w <tmp>` 构建 agent wheel,`python -m venv <tmp>/venv` 后 `pip install --no-deps <wheel>`(`logcap` 与 `dopilot_agent/__init__.py` 均只依赖标准库) | 用 `subprocess.run([venv/bin/python, script.py, "crawl", "x", "-s", "LOG_FILE=<p>", "-s", "DOPILOT_JOB_LOG_CAP_BYTES=65536", "-a", "_job=abc"])` **由真实命令行提供 argv**(与 scrapyd launcher 传给 crawler 的形态一致);脚本**不改 `sys.argv`、不 import dopilot_agent**,只用 `logging.FileHandler(<p>)` 紧循环写 50MB | venv 的 site-packages 含 `dopilot_logcap.pth`;子进程因 SIGTERM 退出(returncode == -15)且 `<p>` ≤ 65536 + 一条记录 + 标记;对照组(argv 为守护进程形态)写满 50MB 且正常退出 | pytest `apps/agent/tests/test_logcap_install.py`(无 hatchling 时 fail 而非 skip) |
| TC-01g | A | `logcap` 激活判定 | (a) 完整 crawler argv;(b) 有 `-s DOPILOT_JOB_LOG_CAP_BYTES` 但无 `_job=`;(c) 有 `_job=` 但无 cap 设置;(d) 环境变量设置了 cap 而 argv 不满足 | 仅 (a) 激活;(b)(c)(d) 不打补丁(环境变量不是激活来源) | pytest `test_logcap.py` |
| TC-01h | A | 外部 scrapyd 模式 `scrapyd.start=False`:flood 触发后 cancel 持续失败、job 始终 running,假 `/proc` 里存在唯一匹配 `_job=<id>` 的进程 | 跑到 t=70 | `ScrapydProcess.start` 未被调用;cancel TERM/KILL 照常重发;**不调用任何 `os.kill`**(无受管 scrapyd pid)并记 warning;文件仍 ≤ cap + 标记;`run_agent` 在该模式启动时记 warning,心跳 `detail.scrapyd.log_cap == "external"` | pytest `test_log_flood.py` + `test_main.py`/`test_heartbeat_worker.py` |
| TC-02 | A | 同上,文件 < cap | 跑 reconcile | 不调用 stop,终态沿用 scrapyd 结果(finished) | 同上 |
| TC-02b | A | `max_job_log_bytes = 0`(关闭):文件 100MB | 跑 reconcile、`publish_once`、`schedule()` | 不 stop、不标记 flood;LogPublisher 不封顶(全部推送);schedule 的 `setting` 不含 `DOPILOT_JOB_LOG_CAP_BYTES`;server 侧 `max_file_bytes = 0` 时 `execution_is_erroneous(finished, log_bytes=10**9)` 为 False 且 `apply_log_event` 不截断 | pytest `test_log_flood.py` + `test_states.py` + `test_log_consumer.py` |
| TC-03 | A | LogPublisher + fakeredis,`max_job_log_bytes=4096`,限速 0 | 写 10KB,`publish_once`;再写 10KB,`publish_once`;置 done 再 `publish_once` | 内容字节总和 ≤ 4096,最后一条内容 entry 为截断标记,`log_capped=True`;第二次不新增内容;第三次发 eof | pytest `test_log_publisher.py` |
| TC-04 | A | LogPublisher,3 个执行各 1MB,限速 256KB/s,mock 单调时钟 | `publish_once` ×3(每次 +1s) | 每次推送总字节 ≤ 256KB × 2(桶容量);三次后三个执行都有进度;累计等于已推字节 | pytest `test_log_publisher.py` |
| TC-05 | A | `parse_scrapy_stats` | 尾部含 `'log_count/ERROR': 91`、`'finish_reason': 'finished'`;被截断无 stats;`finish_reason: 'closespider_errorcount'` | (91, finished)、(None, None)、(0, closespider_errorcount) | pytest `apps/agent/tests/test_scrapyd_stats.py` |
| TC-06 | A | scrapyd runner 终态 | 假 scrapyd finished + 日志尾含 stats | `emit_terminal` 事件带 `error_count=91`、`finish_reason=finished`、`log_bytes` | pytest `test_command_consumer.py` |
| TC-06b | A | server `apply_event` + aiosqlite | 投递 `attempt.failed`、`error_code=log_flood`、`error_detail.log_bytes=40000000`;重复投递同一事件 | `notifications` 恰一条 `log_flood`(warning,dedupe_key=execution_id,payload 含 task_id/log_bytes);`Execution.log_bytes` 落库;`GET /api/v1/notifications` 能列出 | pytest `test_event_consumer.py` + `test_notifications.py` |
| TC-07 | A | protocol | 旧格式 `AgentEvent` JSON(无新字段)解析;`AgentCommand(type="stop_logs")` 往返 | 新字段 None;`stop_logs` 可编码/解码 | pytest `packages/protocol/tests/test_streams.py` |
| TC-08 | A | agent 命令消费 | 投递 `stop_logs` 给正在 tail 的执行 | `log_capped=True`,后续 `publish_once` 不再推内容 | pytest `test_command_consumer.py` |
| TC-09 | A | agent 命令消费 | 投递 `type="bogus"` 的 entry,随后一条正常 `run` | `_process` 不抛异常、记 warning、该 msg 被 XACK;后续 `run` 正常处理 | pytest `test_command_consumer.py` |
| TC-10 | A | server `apply_log_event`,`max_file_bytes=1024`,aiosqlite | 送入 2KB 增量;再送入 1KB | 文件 = 1024 + 标记;`log_integrity=truncated`;outbox 恰一条 `stop_logs`(第二次不再新增);`notifications` 一条 `log_truncated`;gauge 增量 = 实际落盘字节 | pytest `test_log_consumer.py` |
| TC-11b | A | `LogsDirGauge` 串行化(asyncio barrier):预算 10000,目录实有 6000,`calibrate()` 的 walk 替身在 barrier 处暂停 | walk 暂停期间并发发起一次 3000 字节的 `apply_log_event` 与一次维护截断(6000→5000) | 两者都**阻塞**到校准完成(时间戳断言),校准后 `value == 6000`;随后写入与截断依次执行,`value == 8000 == os.walk 实测`;再发起 2001 字节写入 → 正文被拒,实测 ≤ 10000;写入替身**先写 700 字节再抛异常**时 `value` 增加 700 == 实测;未写入即抛时不变 | pytest `apps/server/tests/test_dir_gauge.py` |
| TC-11c | A | 反向交错:维护截断替身在**物理 truncate 完成后、扣减前**的 barrier 暂停,同时发起 `calibrate()` | 放行 | `calibrate()` 阻塞到截断事务整段完成(截断与扣减在同一临界区,不存在"截断已完成、扣减未执行"的可观测中间态),随后校准结果 == 实测;全程 `value` 永不小于实测 | 同上 |
| TC-11 | A | `apply_log_event`,`max_total_bytes=3000`,gauge 预置 2500(全部视为活动日志) | (a) 送入 1KB 增量到执行 X;再送 1KB;(b) gauge 预置 2990(标记放不下),对 **5 个不同执行**各送 1KB;(c) `max_total_bytes=0` | (a) 不落正文,写 `reason=dir-budget` 标记(放得下),`log_integrity=truncated`、`truncation_reason=dir-budget`,outcome `truncated_dropped`,入队 `stop_logs`,`gauge.value == os.walk 实测`;第二次纯丢弃;(b) 五个执行**一个字节都不落盘**(os.walk 实测目录字节 == 2990 预置值),五行 DB 状态均为 truncated/dir-budget,五条 `stop_logs`,`logs_dir_over_budget` 通知一条(count 折叠);全程 `目录实测字节 ≤ 3000`;(c) 正常落盘;size-cap 情形(TC-10)下 gauge 增量 == 实际写入的前缀 + 标记字节 | pytest `test_log_consumer.py` |
| TC-12 | A | `StreamGuardLoop` + fake(`memory_usage` 按 entry 字节和估算) | (a) 均匀 300 条 × 2KB、预算 200KB;(b) 不均匀:5 条 × 200KB + 500 条 × 1KB、预算 300KB;(c) 替身 `memory_usage` 固定返回超预算值(模拟不收敛) | (a) 迭代 ≤ 8 轮后 usage ≤ 预算,返回 trimmed>0、cleared=false,通知 warning 一条,再跑返回 trimmed=0 且通知 count 不变;(b) 同样收敛 ≤ 预算;(c) 走升级路径:`XLEN=0`、cleared=true、通知 severity error | pytest `apps/server/tests/test_stream_guard.py` |
| TC-13 | A | maintenance:已封口 terminal 任务文件 5KB/1KB,terminal 但日志仍 active(drain 窗口内)任务 5KB,active 任务 5KB,`max_file_bytes=2048` | `truncate_oversized_log_files` | 仅已封口的 5KB 截为 2048+标记、行 `log_integrity=truncated`、`size_bytes`/`final_offset` 更新、gauge 扣减;1KB 不变;drain 中与 active 的 5KB 都不动 | pytest `test_maintenance.py` |
| TC-13c | A | PostgreSQL 真并发:`cleanup_terminal_data` 已把 log file 行改为 `expired` 并提交、在 unlink 前 barrier 暂停;LogConsumer 同时收到该执行的增量 | 放行 | 增量 outcome `sealed`、目录中**没有**重建文件、gauge 不变;unlink 完成后无孤儿文件、DB 行删除 | pytest `test_log_locking_pg.py` |
| TC-13b | A | **PostgreSQL(`scripts/dev-db`)真并发**,两个独立 session + asyncio barrier:session A 执行 `apply_log_event`(持 log_file 行锁、已写入增量、在 commit 前暂停);session B 同时跑 `truncate_oversized_log_files` / `evict_logs_dir_to_budget` | 释放 A 的 commit | B 在 A 提交前阻塞(以时间戳断言);A 提交后 B 重读状态:文件仍 active → 不截断不删除;随后记录器封口后再跑 B → 处理;最终 DB `size_bytes` == 物理大小,无孤儿文件 | pytest `apps/server/tests/test_log_locking_pg.py`(无 `DOPILOT_TEST_DATABASE_URL` 时 fail 而非 skip,evidence 必须来自 PostgreSQL 运行) |
| TC-14 | A | maintenance:3 个 terminal 任务各 10KB,`max_total_bytes=15KB` | `evict_logs_dir_to_budget` | 最老任务被删(文件 + 行),剩余 ≤ 预算;gauge 同步扣减;`max_total_bytes=0` 不删 | pytest `test_maintenance.py` |
| TC-15 | A | maintenance:3 个 **active** 任务各 10KB,`max_total_bytes=15KB` | `evict_logs_dir_to_budget` | 不删任何文件;返回 `recovered=false`;写 `logs_dir_over_budget` error 通知(日桶去重:再跑一次 count=2) | pytest `test_maintenance.py` |
| TC-16 | A | fakeredis 命令流:`ghost`(nodes 无行,最后 id 10 天前)、`retired`(nodes 行 `deleted_at` 非空、最后 id 10 天前)、`stale-hb`(nodes 行在、`last_seen_at` 30 天前、最后 id 10 天前、**但有一条 `sent` outbox**)、`old-active`(nodes 行 `last_seen_at` 30 天前、最后 id 10 天前、有一个 running execution)、`agent-01`(健康,`last_seen_at` 刚刚) | `delete_stale_command_streams` | 仅 `ghost` 与 `retired` 被删;`stale-hb`(未决 outbox)、`old-active`(非终态执行)、`agent-01` 保留;通知 info 一条列出被删 agent_id | pytest `test_maintenance.py` |
| TC-17 | A | agent janitor,cap 1MB,假 scrapyd listjobs 可控:(a) state done、3MB;(b) state started、3MB;(c) 无 state、3MB、listjobs 含该 job;(d) 无 state、3MB、listjobs 不含、mtime 10 分钟前(< quiet);(e) 无 state、3MB、listjobs 不含、mtime 2 小时前 | janitor tick | 仅 (a) 与 (e) 被截断为 1MB+标记;(b)(c)(d) 不动;(e) 截断发生在 execution_lock 内(用锁计数断言) | pytest `apps/agent/tests/test_janitor.py` |
| TC-18 | A | `states.execution_is_erroneous` / `task_is_erroneous` | failed;lost;finished+error_count=0;finished+error_count=3;finished+finish_reason=closespider_errorcount;finished+truncated(size-cap);finished+truncated(maintenance);finished+error_code=log_flood;**canceled+finish_reason=shutdown+error_count=2**;canceled+truncated(size-cap);无执行的 failed task | True/True/False/True/True/True/**False**/True/**False**/True/True | pytest `test_states.py` |
| TC-19 | A | `record_task_outcomes` + aiosqlite:Schedule(enabled,`auto_disable_after_errors=3`) | 造 3 个 `schedule_timer` 终态 failed task(日志文件 complete),跑记录器一次;再跑一次 | 第一次后三个 task `outcome_recorded_at` 非空、`outcome_erroneous=true`,Schedule `enabled=false`、`auto_disabled_at` 非空、`reason.consecutive_errors=3`、`task_ids` 长度 3,`schedule_auto_disabled` 通知一条,返回 `[schedule_id]`;第二次返回空且计数不变(幂等) | pytest `apps/server/tests/test_outcomes.py` |
| TC-19c | A | **stats 端到端**(aiosqlite,`auto_disable_after_errors=3`):经 `apply_event` 投递 3 个 `schedule_timer` task 的 `attempt.finished` 事件,分别带 `error_count=91`、`finish_reason=closespider_errorcount`、`error_count=1`;日志文件定稿;跑记录器 | 三个 `Execution` 行持久化了 `error_count`/`finish_reason`;三行账本 `erroneous=true`、计数 3、自动禁用、通知;随后再投递一个 `finished`+`error_count=0`+`finish_reason=finished` 的 task(手动重启用后)→ 账本 `erroneous=false`、计数 0 | pytest `test_outcomes.py` |
| TC-19b | A | 同 TC-19,但 3 个 task 的 `source=schedule_trigger_now`(经 `schedules.trigger_now` 产生) | 跑记录器 | 三行写入 `schedule_outcome_ledger`、计数 3、自动禁用、通知一条;混合 timer/trigger_now 交替失败同样累计 | pytest `test_outcomes.py` |
| TC-20 | A | 同上 | (a) 2 失败 → 1 finished(error_count=0)→ 2 失败;(b) `source=direct_artifact` 的失败 task;(c) `auto_disable_after_errors=0` 下 5 次失败;(d) 一个 task 两个 execution,其一 finished 其一 lost | (a) 计数 2→0→2 仍 enabled;(b) 不计入;(c) 仍 enabled;(d) task 记为出错并计数 1 | 同上 |
| TC-20b | A | 同上 | (a) 失败 A(日志未定稿)、成功 B(已定稿)→ 跑记录器 → A 定稿 → 再跑;(b) B..E 四次失败已记、A 最早的失败后定稿补记;(c) 任务 L 被 reconcile 标 lost(未 reclaim)→ 跑记录器;(d) L 已 reclaim 且过 drain → 记录为出错,随后 `apply_event` 投递 agent 的 `attempt.finished`(error_count=0)→ 再跑记录器;(e) L 纯 server-lost 超过 `lost_outcome_grace_seconds` | (a) 两次后计数都为 0;(b) 计数 5 并自动禁用;(c) 不记录、不封口;(d) 首次计数 1,覆盖后 `outcome_recorded_at` 被清空,再跑后 `outcome_erroneous=false`、计数重算为 0;(e) 记录为出错 | pytest `test_outcomes.py` |
| TC-20c | A | 账本独立于保留期:Schedule 阈值 5,造 3 个失败 task 并记录;随后用 `cleanup_terminal_data`(retention 0 天)把这 3 个 Task/Execution/日志行删除;再造 2 个失败 task 记录 | 删除后 `schedule_outcome_ledger` 仍有 3 行;第 5 次失败后计数 5、自动禁用;账本按 schedule 自修剪到上限行数(另造 150 行验证只留 `max(100, 10)` 行) | pytest `test_outcomes.py` |
| TC-20d | A | PostgreSQL 真并发,barrier 控制:(a) LogConsumer session 读到 log file active、写入截断内容、commit 前暂停;记录器 session 同时对该 task 记录;(b) 记录器先提交封口与"成功"结果;LogConsumer 随后提交;(c) 记录器已记录 lost 为出错、commit 前暂停;EventConsumer 同时投递 agent `finished` 覆盖;(d) 反向:EventConsumer 先持 task 锁覆盖为 finished、commit 前暂停,记录器同时运行 | 按 barrier 依次放行 | (a) 记录器阻塞至 LogConsumer 提交,随后记录为**出错**;(b) LogConsumer 的增量得 `sealed`、文件与完整性不变、结果保持成功且计数不变;(c) 事件路径阻塞至记录器提交,随后看到 `outcome_recorded_at` 并清空,下个 tick 重评为成功、计数重算;(d) 记录器阻塞至事件提交,直接记录 finished 为成功;四种情形账本与 Task 状态最终一致(finished ↔ erroneous=false) | pytest `apps/server/tests/test_outcomes_pg.py`(同 TC-13b 的 PostgreSQL 要求) |
| TC-20e | A | dispatcher `sent` 对账 + fakeredis:outbox 四行 `sent`(task 非终态):A `redis_msg_id` 仍在流、B 所在流已 `DEL` 且 `updated_at` 早于 min_age、C 所在流已 `DEL` 但 `updated_at` 刚刚(过新)、D task 已终态;mock 单调时钟 | (a) 直接 `reconcile_sent_once`;(b) 构造 `CommandDispatcher` 并 `start()`,推进时钟跨过 `sent_reconcile_interval_seconds`,用替身记录 `reconcile_sent_once` 调用 | (a) 仅 B 回到 `pending` 并在下个 dispatch tick 重新 XADD(新 msg id 记录),通知 info 一条;A、C、D 不动;时钟再过 min_age 后 C 也回退;(b) 启动时立即调用一次、之后按间隔再调用 | pytest `test_dispatcher.py` |
| TC-20f | A | PostgreSQL 真并发:(a) reconcile 已无锁选出 active execution 准备 `mark_lost`,barrier 暂停;EventConsumer 同时提交 agent `finished`;(b) dispatcher 超时路径与 `finished` 同样交错;(c) `maintenance.mark_task_lost` 与 `finished` 交错 | 放行 | 三种情形下后来者在行锁后重读到 `finished`,**不再写 lost**,Task 保持 complete,记录器记为成功(error_count=0);反向顺序(lost 先提交)则 finished 按既有覆盖语义生效并清空 `outcome_recorded_at` | pytest `test_outcomes_pg.py` |
| TC-21 | A | 终态写入路径与交错覆盖 | (a) 经 `dispatcher._fail_execution_dispatch_timeout` 置 failed 的 task;(b) finished 事件先落、随后 `apply_log_event` 把日志标 truncated、再 `finalize_drained_logs` 定稿;(c) task 终态但日志文件仍 active 且 `finished_at` 在 drain 窗口内;(d) 同 (c) 但超过 drain + 60s;(e) **记录器已记录(成功)后,晚到一条会超过 `max_file_bytes` 的增量**;(f) finished 事件带 `log_bytes = max_file_bytes + 1`,日志增量一条都没到 | (a) 记录为出错并计数;(b) 定稿前不记录,定稿后记录为出错;(c) 本 tick 不记录;(d) 兜底记录且 log file 被封口为 complete;(e) 增量 outcome 为 `sealed`、文件与 `log_integrity` 不变、`outcome_erroneous` 不变、计数不变;(f) 记录为出错(log_bytes 判定) | 同上 |
| TC-22 | A | `RedisReconcileLoop` + 注入 `on_schedules_disabled` 计数回调 + 真实 `ScheduleRunner`(AsyncIOScheduler,timezone UTC) | 造满足自动禁用条件的数据,跑一次 `_tick` | 回调在 `commit` 后恰被调用一次;新 session 读到 `enabled=false`;`runner.reload()` 后其 job 集合不含该 schedule;把 commit 替换为抛异常的替身再跑 → 回调不被调用、task 未被标记 | pytest `apps/server/tests/test_reconcile_outcomes.py` |
| TC-23 | A | 已自动禁用的 Schedule(账本头部 5 条失败,generation 0) | `PUT /api/v1/schedules/{id}` `enabled=true`(现有接口);随后 (a) 一个新 task(创建于 PUT 后,generation 1)失败并记录;(b) 一个 PUT 前创建、当时为 lost 且**尚未入账**的 task,在 PUT 后被 agent `finished` 覆盖(其 `finished_at` 被改写为覆盖时刻)并入账 | PUT 后 `consecutive_error_count=0`、`auto_disabled_at/reason` 为 null、`outcome_generation == 1`;(a) 计数为 **1**(不是 6)且未禁用;(b) 该账本行 `generation == 0`,当前代际计数不变;`schedule_view` 含四个字段 | pytest `test_schedules.py` + `test_outcomes.py` |
| TC-24 | A | notifications 服务与 API | `notify` 同 type+dedupe_key 两次 → 1 行 `count=2`;**同一 execution_id 先后产生 `log_truncated` 与 `log_flood`** → 两行各自独立(type 不同);**两个独立 session 对同一 key 并发 `notify`(`asyncio.gather`,PostgreSQL dev-db)→ 仍 1 行 `count=2`,且直接 `INSERT` 第二条未读同 key 行触发唯一约束错误**;`mark_read` 后再 `notify` → 新行;同 type+key 先 error 后 warning → 行保持 error 且 `cleared=true` sticky,先 warning 后 error → 升为 error(两种顺序);`redis_stream_over_budget` 的 trim 与 cleared 桶各自成行;`GET /notifications?unread_only=true`、`/unread-count`、`POST /read`、`/read-all`;无 admin token → 401;`prune_notifications`:已读超 30d 删、未读超 90d 删、造 2100 行(全部未读、从未处理)后裁到 2000 行且最老先删 | 各响应体与计数断言 | pytest `apps/server/tests/test_notifications.py` |
| TC-25 | A | alembic + 临时 PostgreSQL(`scripts/dev-db`),升级前先插入一条 `schedule_id` 非空、未终态的 task | `alembic upgrade head` → `downgrade -1` → `upgrade head`;随后把该 task 置 failed 终态并跑记录器 | 三步退出码 0;`notifications`/`schedule_outcome_ledger` 表与 `schedules`(含 `outcome_generation`)、`tasks`(含 `schedule_generation`,升级前的 task 回填为 0)/`executions`/`execution_log_files` 新列存在;升级前创建的 task 终态后正常入账、计数 1 | `evidence/tc-25-alembic.txt` |
| TC-26 | A | 配置加载(server + agent) | (a) 设置全部新 env 后 `load_settings`;(b) 不设置;(c) 用 `DOPILOT_CONFIG=configs/server.docker.toml` 加载生产 TOML;(d) 仅设旧名 `DOPILOT_LOG_MAX_FILE_BYTES=123` | (a) 取到 env 值;(b) 默认值 = 文中数值(32MiB、256MB、20GB、2MiB/s、3600、30s kill、5、86400、7、30d、90d、2000、300、60);(c) `logs.max_file_bytes == 33554432` 且新项齐全;(d) 旧 env 名仍生效 == 123 | pytest `test_config.py` ×2 |
| TC-27 | A | resource_stats + fakeredis + gauge | 采样 | 含 `redis.stream_bytes:logs`(limit 268435456)与 `logs.dir_bytes`(limit 21474836480) | pytest `test_resource_stats.py` |
| TC-28 | A | vitest,mock axios:unread-count=3,列表含 `schedule_auto_disabled` 与 `log_flood` | 渲染 `TopControls`,点开铃铛,点击 schedule 条目,再点开点击 `log_flood` 条目,点击「全部已读」;unread-count=120 再渲染 | 徽标 3;下拉两条且文案来自 i18n(en/zh 各渲染一次无缺失 key);点击 schedule 条目调用 `read` 并 `router.push('/schedules?highlight=…')`;点击 `log_flood` 条目 `router.push('/tasks/detail?id=<task_id>')`(与 `app/(app)/tasks/detail` 现有路由一致,另以 grep 断言该目录存在);全部已读后徽标消失;120 显示 `99+` | vitest `components/layout/__tests__/notification-bell.test.tsx` |
| TC-29 | A | vitest schedules 页,一条 `auto_disabled_at` 非空的调度 | 渲染 | 行内「已自动禁用」Badge,tooltip 含原因次数 | vitest `schedules/__tests__/schedules.test.tsx` |
| TC-32 | A | server 启动接线:`create_app` + `app.router.lifespan_context`,monkeypatch `StreamGuardLoop.enforce_once`、`LogsDirGauge.calibrate`、各 consumer/loop 的 `start` 为记录调用顺序的替身 | 进入 lifespan | 顺序记录为 `[stream_guard.enforce_once, logs_dir_gauge.calibrate, dispatcher.start, event_consumer.start, log_consumer.start, reconcile.start, retention.start, stream_guard.start, ...]`,且 `enforce_once`/`calibrate` 在任何 `start` 之前 **被 await 完成**(替身内 `await asyncio.sleep(0)` 并记录完成时刻) | pytest `apps/server/tests/test_app_startup.py` |
| TC-33 | A | agent 启动接线:`run_agent` + monkeypatch `Janitor.sweep_once` 与 `CommandConsumer.start`/`LogPublisher.start` 为顺序记录替身 | 启动 `run_agent`,等待后 stop | 记录顺序为 `janitor.sweep_once`(含 C8)先于 `command_consumer.start` 与 `log_publisher.start`;janitor 周期任务已启动 | pytest `apps/agent/tests/test_main.py` |
| TC-30 | A | 全量回归 | `ruff check apps packages`;`pytest`(根 testpaths);`corepack pnpm -C apps/web lint && typecheck && test` | 全部退出码 0 | `evidence/tc-30-*.txt` |
| TC-31c | A | runbook 静态校验 | grep `docs/architecture/05-deployment.md` | 备份与恢复命令同时出现 `${P}_dopilot-db` 与 `${P}_dopilot-server-data` 两个 volume(各至少一次 `tar czf` 与一次恢复),回滚段落含「成对恢复」 | `evidence/tc-31c-runbook-grep.txt` |
| TC-31b | A | runbook 前置检查可执行性:测试 app + admin token | 依次 `GET /api/v1/tasks?status=queued` / `running` / `finalizing`;再请求 `?status=queued,running` | 前三者 200 且响应含 `total` 字段;逗号多值返回 400 `task.invalid_status`(证明 runbook 写法正确、多值写法错误);docs/05 中的三条 URL 以 grep 断言与测试一致 | pytest `test_executions.py` + `evidence/tc-31b-runbook-api.txt` |
| TC-31 | A | compose 文件 | `docker compose -f deploy/docker/docker-compose.server.yml config` 与 `docker-compose.yml config`(必需 env 置占位值) | 退出码 0;输出含 redis `mem_limit`/`maxmemory 512mb` 与 server `mem_limit` | `evidence/tc-31-compose-config.txt` |

## 风险与回滚

| 风险 | 缓解 / 回滚 |
|---|---|
| 外部 scrapyd 环境未装 `dopilot-agent`(无 `.pth`)→ 进程内硬界缺失 | docs/04 把它列为外部模式必要条件;agent 启动 warning + 心跳 `log_cap=external` 在节点页可见;watchdog cancel + 每 tick 截回仍在 |
| `.pth` 钩子对所有同环境 Python 进程生效 | 模块在环境变量缺失/为 0 时立即返回不打补丁;agent 自身不设该变量;补丁只改 `FileHandler.emit` 且保留原行为直至达限;TC-01d 覆盖未设变量路径 |
| 32MiB 上限误伤正常但话痨的爬虫(被 `log_flood` 终止) | 上限可配(`DOPILOT_AGENT_MAX_JOB_LOG_BYTES`);终止前日志已含 32MiB 上下文;docs/04 给出调宽指引;回滚 = 调大配置 |
| "有 ERROR 即出错"对偶发网络错误敏感 | 连续 5 次且一次成功即清零;`auto_disable_after_errors=0` 可整体关闭;后续可加 `error_count` 阈值(本期不做) |
| 目录预算准入硬界下,大量活动执行同时写日志会让后到的执行日志被丢弃 | 默认 20GB 远大于正常量;每次触发发 error 通知;淘汰循环每小时腾空间;`max_total_bytes=0` 关闭 |
| StreamGuard 不收敛时清空整个日志流 | 只在 8 轮精确裁剪仍超预算(或降幅 < 5%)的异常情形触发;流本就是瞬态总线且日志 RPO 非零;发 error 通知 |
| agent janitor 误截正在写的日志 | 三重条件(不在活动集、state done 或 scrapyd 不列且静默 ≥ 1h、锁内复检);`phase=started` 永不碰;TC-17 覆盖 state 缺失但作业存活 |
| 记录器兜底(drain + 60s)时日志尚未定稿 | 兜底记录即封口,之后增量一律 `sealed` 丢弃,结果不会被后到日志推翻;"日志超限"由 agent 上报 `log_bytes` 判定,不依赖增量是否到达 |
| flood 作业不听从 scrapyd cancel | 每 tick 重发 cancel,30s 后 KILL,60s 后本地单 PID SIGKILL(ppid 校验、候选唯一才杀,绝不 killpg);定位失败也只是继续重发 cancel;期间每 tick 截回 cap,磁盘始终有界(TC-01b/01c) |
| `stop_logs` 对老版本 agent 是毒消息 | runbook 升级窗口内 agent 全停、与 server 同版本一起起;新 agent 解码失败改为记日志 + ACK(TC-09) |
| lost 24h 宽限后记为出错,agent 随后恢复并上报 finished | 账本纠正:`_update_task` 清空 `outcome_recorded_at` → 重评 → 重算计数;已执行的自动禁用保留并留痕,需人工重开(保守方向) |
| 行锁引入的死锁/延迟 | 全部路径固定锁序 task → log_file → schedule;持锁事务都很短(单文件 append / 单 task 评估);PostgreSQL 死锁检测会回滚一方,消费者按既有"失败不 ACK、下次重试"语义重放 |
| 迁移 0013 在生产 DB 上执行 | 仅加列/建表/建索引,`downgrade` 完整;runbook 要求先备份 db volume |
| 生产 Redis volume 清空丢失未接管命令 | runbook 先停全部调度并等活动任务清零;新版 dispatcher 的 `sent` 对账把流中已不存在的命令回退 `pending` 重投(agent 按 execution_id 幂等);`pending/failed_retryable` 行本就重投 |
| 新 compose `mem_limit 1g` 下 Redis 加载旧的 7.9GB AOF 会进入容器级重启循环 | 不伤宿主;runbook 的清空 volume 步骤是正确路径,docs 写明 |
