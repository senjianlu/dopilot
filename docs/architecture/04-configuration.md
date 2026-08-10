# 配置与认证

> 决策依据:[0015 TOML 配置](../decisions/0015-toml-config-no-scrapydweb-quirks.md)、
> [0011 认证边界](../decisions/0011-auth-boundaries.md)。

## 配置形态

- TOML 配置经 `DOPILOT_CONFIG` 显式指定路径加载;样例在
  `configs/server.example.toml` / `configs/agent.example.toml`
  （`configs/server.docker.toml` 是烤进镜像的容器默认配置源）。
- Docker 镜像内置角色默认配置路径 `/app/configs/server.toml` /
  `/app/configs/agent.toml`;常规部署用 `DOPILOT_*` 环境变量覆盖
  （env 优先于 TOML），进阶部署把自有 TOML 只读挂载到默认路径。
- 本地开发不 `DOPILOT_CONFIG` 也可用 `DOPILOT_DATABASE_URL` /
  `DOPILOT_REDIS_URL` 等覆盖关键连接。
- `load_settings()` 无副作用:不建文件、不生成密钥。

### 环境变量命名:`DOPILOT_` 前缀无例外

**所有面向部署的环境变量一律以 `DOPILOT_` 开头**,包括只在 compose
变量替换层消费、不进容器的那些(`DOPILOT_REDIS_PASSWORD`、
`DOPILOT_REDIS_HOST`)。不带前缀的通用名(`REDIS_PASSWORD`、`AGENT_ID` 之类)
会被宿主机上其他服务、K8s 同 Pod sidecar 或 CI runner 的同名变量静默继承,
从而串改 Redis 连接串或 agent 身份,故一律不用、也不留旧名兜底。

不受此约束的三类(经核实):Next.js 强制前缀的 `NEXT_PUBLIC_*`、
GitHub Actions 作用域内的 CI 变量、以及 `E2E_*` 等测试专用变量。

agent 侧身份与工作目录的 env 覆盖为 `DOPILOT_AGENT_ID` /
`DOPILOT_AGENT_WORKDIR`(后者也是镜像 `ENV` 的烤入名)。其中
`DOPILOT_AGENT_ID` **刻意与** `dopilot_protocol.execution` 交给用户工作负载的
runtime context 键**同名**:二者表达同一事实("本 agent 的 id"),且由构造
必然相等——agent 只消费寻址到自己 id 的命令流;子进程侧仍取 runtime context
的值(wheel runner 在合并子进程环境时最后覆盖)。

> **升级注意**:改名无兜底。只更新 compose/清单而不拉新镜像时,旧镜像的代码
> 只认旧名,`agent_id` 会静默回落到烤进镜像的 TOML 值,导致一体栈三个 agent
> 共用同一 id(症状隐蔽,探针不报错)。改名与 `docker compose pull` 必须同批做。

关键配置段（键名以 `configs/*.toml` 为准）:

| 端 | 段 | 要点 |
|---|---|---|
| server | `[server]` | `host`/`port`/`public_url`;`data_dir`（默认 `/server-data`，生成令牌的持久化锚点） |
| server | `[database]` | PostgreSQL URL（env `DOPILOT_DATABASE_URL`） |
| server | `[auth]` | `admin_username`/`admin_password`/`token_secret`（仅 TOML）/`admin_api_token`/`access_token_ttl_minutes`/`stream_token_ttl_seconds` |
| server | `[redis]` | `url`、三条 stream 的 maxlen（`stream_maxlen_logs` 默认 100000）、`log_retention_seconds`（由保留清扫实装为定时 `XTRIM MINID`）、`consumer_name`、`require_aof` |
| server | `[agents]` | `heartbeat_timeout_seconds`/`stalled_attempt_seconds`/`lost_after_stalled_seconds`（默认 3600;有运行期心跳后仅约束「agent 在线但存活不可确认」,不是任务时长上限）/`agent_token` |
| server | `[scheduler]` | `enabled`（in-process runner 开关）、`timezone` |
| server | `[logs]` | `root_dir=/server-data/logs`、drain/保留窗口参数、`retention_days`（默认 30,自动保留清扫的 cutoff;**0 = 关闭终态清理**,而非 cutoff=now 立删全部）、`max_file_bytes`（单执行日志硬上限，默认 100MiB，超限置 `log_integrity=truncated`） |
| server | `[maintenance]` | 自动保留清扫:`enabled`（默认 true）、`sweep_interval_seconds`（默认 3600）、`event_audit_retention_days`（默认 30）、`event_audit_delete_batch`;资源仪表盘采样:`stats_interval_seconds`（默认 60,env `DOPILOT_MAINTENANCE_STATS_INTERVAL_SECONDS`,0 关闭采样 loop） |
| server | `[artifacts]` | `root_dir`、`max_upload_bytes`（单次上传上限 413，默认 200MiB）、`max_total_bytes`（聚合配额 507，默认 20GiB） |
| server | `[nodes]` | `agents` 仅作未 heartbeat 节点的占位提示（不再是 poll 目标） |
| server | `[i18n]` | `locale`（默认 `zh`）、`timezone` |
| agent | `[redis]` | `url`/`command_block_ms`/`pending_idle_ms`/`event_outbox_dir`、`maxlen_logs`/`maxlen_events`（XADD 近似上限，默认 100000，env `DOPILOT_REDIS_STREAM_MAXLEN_LOGS/EVENTS`）、`event_outbox_max_files`（outbox 文件数上限，默认 100000） |
| agent | `[agent]` | `agent_id`（env `DOPILOT_AGENT_ID`）/`workdir`（env `DOPILOT_AGENT_WORKDIR`）/`server_url`/`heartbeat_interval_seconds`/`attempt_heartbeat_interval_seconds`（attempt 级存活心跳限频，默认 60，须远小于 server `stalled_attempt_seconds`，0 关闭）/`agent_token`、`janitor_interval_seconds`（本地 janitor 周期）、`completed_log_ttl_days`（终态 3 天）/`orphan_log_ttl_days`（孤儿 7 天）、`max_job_log_bytes`（job.log 硬上限，默认 100MiB）、`artifact_cache_max_bytes`（缓存 LRU 上限，默认 2GiB） |
| agent | `[scrapyd]` | `start`/`host`/`port`、`jobs_to_keep`（默认 5）/`finished_to_keep`（默认 100，写入生成的 scrapyd.conf） |

### 资源硬上限（防磁盘/内存膨胀）

长运行部署曾因日志/磁盘无界增长导致宿主机卡死;各增长面均有可配置硬上限
与安全默认值,过期由后台自动执行(不依赖手动运维)。要点:

- **部署层**:三份 compose 每个 service 均设 json-file 日志轮转
  (`max-size=10m`,`max-file=3`);Redis 设 `--maxmemory`(默认 512mb,env
  `DOPILOT_REDIS_MAXMEMORY`)+ `noeviction`(XADD 满则响亮报错而非静默丢流)
  + AOF 自动重写阈值。详见 [05-deployment](05-deployment.md)。
- **server**:单执行日志 100MiB 上限(超限继续消费/ACK,置
  `log_integrity=truncated`);`RetentionSweepLoop` 每小时按 `retention_days`
  自动清理终态数据(失败安全两阶段:先标 `expired` 提交、再删正文、再删行)、
  按窗删 `event_audit`、对日志/事件流 `XTRIM MINID`;上传 413/聚合 507 配额;
  SSE 订阅队列有界(满则断开重连)。
- **agent**:`AgentJanitor` 周期 GC 终态/孤儿 workspace + `.logpos` + state
  (三重安全判定:内存活跃集、`job.pgid` 存活、树静默期);job.log 100MiB 上限
  (PIPE+drain,永不背压阻塞子进程);artifact/wheel 缓存按 LRU 淘汰;event
  outbox 文件数上限(超限丢最旧)。janitor 每轮 sweep 顺带采集本机磁盘样本
  (workspaces/缓存/scrapyd/outbox/state/卷),经心跳 `detail["disk"]` 上报,
  供运维仪表盘展示。

### 资源仪表盘(可观测面)

运维清理页(`/maintenance`)展示各增长面的**当前值 vs 上限**与 ok/warn/
critical 等级,约 10s 轮询。数据由 server `ResourceStatsLoop` 每
`stats_interval_seconds` 采一次快照缓存于内存,`GET /maintenance/resource-stats`
只读缓存、**绝不在请求路径遍历文件系统**。快照覆盖:server 磁盘(日志/制品
目录字节、最大单日志文件 vs `max_file_bytes`、卷用量)、PostgreSQL(五表行数
与真实字节、库大小、最老终态任务/最老 event_audit 行的年龄 vs 保留窗口——
时间谓词与清扫函数同源)、Redis(内存 vs maxmemory、AOF、log/event 流长度与
首条目年龄、每 agent 命令流长度)、每 agent 磁盘(经心跳上报)。年龄类指标
的上限为对应保留窗口,旋钮为 0(关闭)时不告警。页面另提供三个安全操作:
立即保留清扫(`POST /maintenance/sweep-now`,逐步汇报、步骤级故障隔离)、
终态清理(沿用 `terminal-cleanup` 的 dry-run 预览+确认)、Redis
`BGREWRITEAOF`(`POST /maintenance/redis-rewrite-aof`);均需 admin 认证。
`VACUUM FULL` 仅页面文案提示,指向生产收缩 runbook。
- 决策见 [0019 资源硬上限](../decisions/0019-resource-hard-limits.md)。

## 认证体系

| 凭证 | 谁用 | 语义 |
|---|---|---|
| `admin_username` + `admin_password` | 管理员登录 | **fail-closed**:与 `token_secret` 任一缺失即拒绝启动;唯一逃生舱 `DOPILOT_AUTH_DISABLED=true` |
| opaque access token | Web/API 会话 | 登录签发，无 refresh token;由 `token_secret` HMAC 签名 |
| `stream_token` | SSE 建连 | POST 换取、TTL 60s、只校验建连 |
| `admin_api_token`（`DOPILOT_ADMIN_API_TOKEN`） | 自动化/CI | 静态 Bearer，直接认证 admin;**仅管理员、仅 server 端，绝不下发给 agent** |
| `agent_token`（`DOPILOT_AGENT_TOKEN`） | agent 出站调用 | 唯一机器令牌（heartbeat + artifact/wheel 拉取）;server 与每个 agent 同值;非空须 ≥16 字符;未配置时 server 运行时自动生成并持久化到 `<data_dir>/secrets/agent-token`（`dopilot-server agent-token print` 读取） |

Token 认证不是传输加密——跨主机部署把 Redis 与 server HTTP 置于
TLS/VPN/私有网络之后。Redis 自身启用 AUTH（compose 中 `--requirepass`）。
