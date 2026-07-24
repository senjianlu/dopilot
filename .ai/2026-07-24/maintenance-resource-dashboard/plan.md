---
status: approved
task: maintenance-resource-dashboard
date: 2026-07-24
approved_at: 2026-07-24 (用户对话确认)
plan_review_max_rounds: 12
# 上限放宽授权:用户于 2026-07-24 本任务对话中两次明确授权——第 3 轮达
# 默认上限后选择"放宽到 10 轮";第 10 轮用尽后选择"再放宽 2 轮跑确认
# 评审"(均经 AskUserQuestion 征询,用户选定)。
impl_fix_max_rounds: 10
# 代码评审修复轮上限放宽授权(用户于 2026-07-24 对话中三次明确授权):
# 第 3 轮 fail 后选"放宽到 6 轮";第 6 轮 fail 后选"放宽到 10 轮"
# (均经 AskUserQuestion 征询,用户选定)。
---

# 方案:运维清理页面重写为实时资源仪表盘(含安全操作三件套)

## 背景与目标

上一任务(`resource-hard-limits`, commit a19985d)为所有无界增长面加了硬上限与
自动清理,但运维者仍看不到"当前值 vs 临界值"。本任务把 `/maintenance`
(运维清理)页面重写为资源仪表盘:

1. **量化展示**:server 磁盘 / PostgreSQL 表 / Redis 内存与流 / 每个 agent 的
   磁盘占用,逐项显示当前值、上限(来自上一任务落地的配置项)与
   ok/warn/critical 等级,约 10s 轮询刷新。
2. **安全操作三件套**(用户已确认范围):
   - 立即保留清扫(手动触发一次 retention sweep 的三个步骤);
   - 手动终态清理(保留现有 dry-run 预览 + 确认执行流,融入新页面);
   - Redis `BGREWRITEAOF`(立即回收 AOF)。
   `VACUUM FULL` 仅页面文案提示(指向生产收缩 runbook),不做按钮;
   Agent 端"立即清扫"命令本期不做(用户已确认)。

底稿:`.ai/2026-07-24/resource-hard-limits/assets/audit-inventory.md` Sub-task D。
硬约束:零 Alembic 迁移、零协议破坏性变更(心跳 `detail` 为自由 dict,
`packages/protocol` 不动)、采样绝不阻塞事件循环、绝不逐请求跑昂贵目录遍历、
Redis/PG 故障只降级对应板块不搞垮整个端点。

## 改动范围

预计 **28 个文件**(> 10,须走 plan 评审闸)。

### Server(12)

| 文件 | 改动 |
|---|---|
| `apps/server/dopilot_server/config/settings.py` | `MaintenanceSettings` 新增 `stats_interval_seconds: int = 60`(0 = 关闭采样 loop;端点**永不**按需采样,无快照时返回"未采样"空响应) |
| `apps/server/dopilot_server/config/loader.py` | 新增 env 覆盖 `DOPILOT_MAINTENANCE_STATS_INTERVAL_SECONDS` |
| `apps/server/dopilot_server/redis/client.py` | `RedisStreamClient` 协议 + `RedisStreams` 适配器新增 `info(section)`、`xinfo_stream(stream)`(length + first-entry id)、`bgrewriteaof()` |
| `apps/server/dopilot_server/resource_stats.py`(新) | 快照采集函数 + `ResourceStatsLoop`(仿 `retention.py` 的 loop 骨架) |
| `apps/server/dopilot_server/services/maintenance.py` | `trim_log_streams` 返回**结构化逐流结果**(`{stream: {"trimmed": n} \| {"error": msg}}`,不再吞失败信息);`cleanup_terminal_data` 调用侧统一 `retention_days=0` = 关闭语义(见 §3) |
| `apps/server/dopilot_server/retention.py` | `sweep_once`:`retention_days=0` 时跳过终态清理步骤(与 event_audit/流 trim 既有的 0=关闭语义对齐);适配 trim 新返回结构 |
| `apps/server/dopilot_server/api/v1/maintenance.py` | 新增 `GET /maintenance/resource-stats`、`POST /maintenance/sweep-now`、`POST /maintenance/redis-rewrite-aof`(均 admin 认证);现有 `POST /maintenance/terminal-cleanup` 不动 |
| `apps/server/dopilot_server/api/v1/schemas.py` | 新增 `ResourceStatsResponse`/`ResourceStatEntry`、`SweepNowResponse`、`RewriteAofResponse` |
| `apps/server/dopilot_server/app.py` | lifespan 里 wire `ResourceStatsLoop`(`stats_interval_seconds > 0` 时),挂 `app.state.resource_stats` |
| `apps/server/tests/test_resource_stats.py`(新) | 服务/端点/loop 测试 |
| `configs/server.example.toml`、`configs/server.docker.toml` | 同步 `[maintenance].stats_interval_seconds` |

### Agent(6)

| 文件 | 改动 |
|---|---|
| `apps/agent/dopilot_agent/deps.py` | 新增共享 `DiskStatus` 采样对象(仿 `redis_status`,deps.py:91),入 `AgentRuntime`,传给 `HeartbeatWorker` |
| `apps/agent/dopilot_agent/janitor.py` | `sweep_once` 末尾在 `asyncio.to_thread` 里采集磁盘样本(复用 `_tree_size`/`_safe_size` 与 `_sweep_cache` 已算出的 total),写入 `DiskStatus` |
| `apps/agent/dopilot_agent/redis/heartbeat.py` | `build_request` 附 `detail["disk"] = disk_status.snapshot()`(样本缺失时不加 key) |
| `apps/agent/dopilot_agent/main.py` | janitor 构造时传入 `runtime.disk_status` |
| `apps/agent/tests/test_heartbeat_worker.py` | 心跳含 disk 样本的用例 |
| `apps/agent/tests/test_resource_limits.py` | janitor 磁盘采样用例(假 workdir 树) |

### Web(8)

| 文件 | 改动 |
|---|---|
| `apps/web/app/(app)/maintenance/page.tsx` | 整页重写:按 scope 分组的指标卡(Server 磁盘 / PostgreSQL / Redis / 每 Agent)+ 操作卡(三件套)+ VACUUM FULL 文案提示;10s `setInterval` 轮询(`useEffect` 清理),显示 `sampled_at` 年龄 |
| `apps/web/lib/api/maintenance.ts` | 新增 `getResourceStats()`、`sweepNow()`、`rewriteAof()`;`terminalCleanup` 保留 |
| `apps/web/lib/api/types.ts` | 新增对应响应类型 |
| `apps/web/lib/i18n/locales/en.ts`、`zh.ts` | 替换/扩充 `maintenance.*` 键块(保留 cleanup 相关键,新增指标/操作键) |
| `apps/web/components/ui/progress.tsx`(新) | shadcn Progress(用量条;遵守项目 `shadcn` skill 约定) |
| `apps/web/lib/format.ts` | `formatBytes` 扩展 GB/TB 档 |
| `apps/web/app/(app)/maintenance/__tests__/maintenance.test.tsx`(新) | 页面测试(仿 nodes 测试的 `vi.mock` 模式) |

### 文档(2)

| 文件 | 改动 |
|---|---|
| `docs/architecture/04-configuration.md` | `[maintenance].stats_interval_seconds` 配置项 |
| `docs/architecture/06-web-frontend.md` | maintenance 页面职责更新(仪表盘 + 安全操作) |

### 明确不动

- `packages/protocol/`:`AgentHeartbeatRequest.detail` 是自由 `dict[str, Any]`
  (streams.py:251),`detail["disk"]` 直接透传,零协议改动。
- 数据库 schema:`nodes.health` 已是 JSON/JSONB 全量透传
  (nodes/service.py:168、models/node.py:39-43),零迁移。
- `POST /maintenance/terminal-cleanup` 端点行为、SSE、调度器。
  (`RetentionSweepLoop` 仅两处小改:`retention_days=0` 短路 + trim 新
  返回结构适配,其余逻辑不动。)
- 导航项 `nav.maintenance`(components/layout/nav.ts:28)保留原位与图标。

## 实现方案

### 1. Agent 磁盘样本(D1,零协议改动)

- `deps.py` 新增 `DiskStatus`:线程安全的单值容器(`update(sample: dict)` /
  `snapshot() -> dict | None`),在 `build_runtime` 创建(与 `redis_status`
  同缝,deps.py:91),加入 `AgentRuntime` dataclass,并作为新 kwarg 传入
  `HeartbeatWorker`(deps.py:114-121)。
- `AgentJanitor` 构造新增 `disk_status` 可选参数;`sweep_once` 末尾在
  `asyncio.to_thread` 中采集固定形状小样本(只有计数/字节,无逐文件列表):

```python
{
  "sampled_at": "<iso8601>",
  "interval_seconds": settings.agent.janitor_interval_seconds,  # 供 server 判陈旧
  "workspaces": {"count": n, "bytes": b},
  "cache": {"bytes": b, "limit": settings.agent.artifact_cache_max_bytes},
  "scrapyd": {"bytes": b},          # {workdir}/scrapyd/{logs,items,eggs,dbs}
  "outbox": {"files": n, "bytes": b, "limit": settings.redis.event_outbox_max_files},
  "state": {"executions": n, "logpos": n},
  "volume": {"total": t, "used": u, "free": f},   # shutil.disk_usage(workdir)
}
```

  cache bytes 直接复用 `_sweep_cache` 已计算的 `total`(janitor.py:242),
  避免重复遍历。采样任一子项失败只置该子项为 None,不影响 sweep 本体。
- `HeartbeatWorker.build_request`(heartbeat.py:54-80)在
  `detail["redis"]` 同款位置追加 `detail["disk"]`;样本为 None 时不加 key。
  心跳节奏(10s)不变,采样节奏 = janitor 间隔(600s)——心跳只读缓存,
  **绝不在心跳路径遍历文件系统**。

### 2. Server 采样快照(D2)

新模块 `dopilot_server/resource_stats.py`:

- `async def collect_snapshot(sessionmaker, settings, redis) -> dict`:逐板块
  采集,每板块独立 try/except,失败板块 status=unavailable,其余照常返回。
  **涉库板块的事务隔离**(评审 R-01):函数收 `sessionmaker` 而非单个
  session,server(`MAX(size_bytes)` 等 SQL)/postgres/agents 三个涉库板块
  **各开各的 session**(`async with sessionmaker() as s`),失败先 rollback
  再降级——真实 PG 中一条 SQL 失败会使事务 aborted,共享 session 会让后续
  板块连带失败:
  - **server**:日志目录字节走 **`settings.logs.root_dir`**、artifacts
    目录字节走 **`settings.artifacts.root_dir`**(均为权威配置,不写死
    `/server-data/*`;`asyncio.to_thread` 走 `os.walk`,沿 `logs/files.py`
    的下沉 idiom);volume 条目对 `server.data_dir`、`logs.root_dir`、
    `artifacts.root_dir` 三根按 `os.stat().st_dev` 去重后逐卷
    `shutil.disk_usage`;**最大单日志文件字节**(SQL `MAX(size_bytes)`
    over `execution_log_files`,零遍历)对 `[logs].max_file_bytes` 同量纲
    比较;
  - **postgres**:五张表(`tasks`/`executions`/`execution_log_files`/
    `command_outbox`/`event_audit`)行数;**最老可清理终态任务年龄**与
    **最老 event_audit 行年龄**对各自保留窗口——**时间谓词与清扫函数
    严格同源**(评审 R-02):终态任务取
    `MIN(COALESCE(tasks.finished_at, tasks.created_at))` where status ∈
    终态,与 `cleanup_terminal_data` 的 effective-time 谓词
    (services/maintenance.py:77 附近)共享同一表达式帮助函数;
    event_audit 取 `MIN(processed_at)`,与 `prune_event_audit` 的删除列
    一致——保留清扫失效时这两项变红,且清扫一跑即可消红;`session.bind.dialect.name ==
    "postgresql"` 时(idiom:services/stats.py:77)另跑
    `pg_total_relation_size(to_regclass(:qualified_name))`(**参数化**
    绑定;`to_regclass` 返回 regclass 匹配函数签名,表不存在返回 NULL →
    条目 unknown)与 `pg_database_size(current_database())`(表名取自
    模型 `__tablename__` 白名单,不拼接外部输入);SQLite(测试)行数/
    年龄照常、字节为 null;
  - **redis**:`INFO memory`(`used_memory`/`maxmemory`)、
    `INFO persistence`(`aof_current_size`,AOF 关闭时为 null)、
    `XINFO STREAM`(新封装,一次拿 `length` + `first-entry` id;**空流
    语义**:适配器把 `ERR no such key` 映射为 `length=0、first-entry=None`
    ——新部署/无日志/节点尚无命令都是正常态,不得降级 scope;其他 Redis
    异常仍按板块故障处理,评审 R-01):
    `LOG_STREAM`、`EVENT_STREAM`(streams.py:52-54)出**长度对
    `stream_maxlen_*`** 与**首条目年龄对 `log_retention_seconds`**
    (从 stream id 毫秒时间戳折算,XTRIM 失效时变红——这两条流正是
    `trim_log_streams` 的清理对象);nodes 表每个 agent 的
    `command_stream(agent_id)` **只出长度条目对
    `stream_maxlen_commands`,不出年龄条目**——命令流没有按时间的清理
    策略(旧条目可能是待投递事实),年龄告警会成为三件套无法消除的
    死红(评审 R-01);
  - **agents**:nodes 表逐行取 `health["disk"]` 与 `last_seen_at`;节点
    可用性**不读持久化 `status`**(它只在收到心跳时写入,断联后不会自行
    翻转),而是复用现有**动态聚合**
    `_aggregate_node_status(node, now, heartbeat_timeout_seconds)`
    (nodes/service.py:73-80,与 `GET /nodes` 同一判定路径),按当前时间
    与配置的心跳超时实时计算。**防御性解析**(评审 R-01,
    `health["disk"]` 是自由 dict,可能含旧版本/人工写入/畸形数据):
    server 端经专用解析函数逐字段校验后才使用——`sampled_at` 必须可
    `fromisoformat`、`interval_seconds` 必须为正数(非法则视同无法判
    stale,该 scope 记 `unavailable`)、嵌套 bytes/count/limit 必须为非负
    数值(非法/缺失字段 → 对应条目省略或 `unknown`);**解析失败按单个
    agent 隔离**:整样本不可解析 → 仅该 agent scope=`unavailable`,其他
    agent 与其他板块照常,快照本轮正常更新。
- **统一状态契约(scope 级 + 条目级两层)**:
  - **scope.status ∈ `ok | stale | unavailable`**:采集失败的板块(如 redis
    连接异常)→ `unavailable`(条目为空);agent scope 以
    `_aggregate_node_status(node, now, ...)` 的**动态结果**
    (`healthy | degraded | unhealthy | unknown`)判定——动态结果 ∈
    `{unhealthy, unknown}`(含"持久化 status=healthy 但 `last_seen_at`
    已超时"的断联节点)或 `health["disk"]` 缺失 → `unavailable`(附
    `last_seen_at`);动态结果 ∈ `{healthy, degraded}` 且样本年龄
    `now − sample.sampled_at > 2 × sample.interval_seconds` → `stale`
    (陈旧样本仍展示但明确标注);其余 → `ok`。server/postgres/redis 三个
    scope 的 `sampled_at` 即 server 快照时间,agent scope 的 `sampled_at`
    取样本自带时间,另带 `last_seen_at`。
  - **entry.level ∈ `ok | warn | critical | unknown`**,`kind ∈ bytes |
    count | age`(age 单位秒),分两套规则:
    - **占比类**(bytes/count,limit = 上限):warn ≥ 70%、critical ≥
      90%;volume 条目(limit = 总量)按 used/total 同阈值;null-limit
      条目恒 ok;
    - **年龄类**(kind=age,limit = 保留窗口秒数):稳态下最老记录年龄
      本就贴近窗口,占比阈值不适用。定义 `grace = 2 ×
      sweep_interval_seconds`(redis 流年龄的 grace 同理取 2 × sweep
      间隔),分段**互斥、按序判定**(评审 R-01,兼容 `grace > limit`
      的合法配置):`critical_at = max(2 × limit, limit + grace)`;
      `age > critical_at` → critical(清扫持续失效);否则
      `age > limit + grace` → warn;否则 → ok;
    - `value` 为 null(如 AOF 关闭、PG 专有字节在 SQLite 下缺失、空表无
      最老行)→ `unknown`(空表年龄条目省略,不出 unknown 噪音);
    - **明确关闭的上限不误报**:对应 retention 旋钮为 0
      (`logs.retention_days=0` / `event_audit_retention_days=0` /
      `log_retention_seconds=0`)时,该年龄条目 `limit=null`、按
      null-limit 规则恒 ok(当前值仍展示)。0 = 关闭在**清扫行为侧同步
      统一**(§3:sweep-now 与自动 loop 对 `retention_days=0` 短路跳过,
      与另两个旋钮 service 层既有的 0=关闭一致),展示与行为不再冲突;
      `maintenance.enabled=false` 时年龄条目照常计算(如实反映积压),
      但响应顶层加 `sweep_enabled: false`,前端在相应卡片附注"自动清扫
      已关闭"。
    limit 来源:`logs.max_file_bytes`、`logs.retention_days`、
    `maintenance.event_audit_retention_days`、`redis.log_retention_seconds`、
    `artifacts.max_total_bytes`、redis `maxmemory`(取自 INFO,反映真实
    部署)、`stream_maxlen_*`、agent 样本自带的 cache/outbox limit。
- `ResourceStatsLoop`:骨架照抄 `RetentionSweepLoop`(retention.py:98-125),
  间隔 `maintenance.stats_interval_seconds`(默认 60),启动即先采一次、之后
  每 tick 采一次,缓存 `self.snapshot`;采样失败只记 warning 不死循环。
  app.py lifespan 在 `owns_runtime` 且间隔 > 0 时启动,挂
  `app.state.resource_stats`。

### 3. API(D3 + 操作三件套)

`api/v1/maintenance.py` 新增(全部 `Depends(get_current_admin)`):

- `GET /maintenance/resource-stats` → `ResourceStatsResponse`:

```json
{
  "sampled_at": "<iso8601> | null",
  "sweep_enabled": "bool",
  "scopes": [
    {
      "scope": "server | postgres | redis | agent:<id>",
      "status": "ok | stale | unavailable",
      "sampled_at": "<iso8601> | null",
      "last_seen_at": "<iso8601> | null",
      "entries": [
        {"key": "...", "kind": "bytes | count | age",
         "value": "int | null", "limit": "int | null",
         "level": "ok | warn | critical | unknown"}
      ]
    }
  ]
}
```

  **端点只读缓存,绝不在请求路径采样**(硬约束,评审 R-01):返回
  `app.state.resource_stats.snapshot`;无快照(loop 关闭 / 启动后首采未完成
  / ASGITransport 测试未注入)→ 返回 200、`sampled_at: null`、`scopes: []`
  (前端呈"首次采样中");`stats_interval_seconds = 0` 时同此语义。测试用
  计数 stub 断言该路径零目录遍历。
- `POST /maintenance/sweep-now` → `SweepNowResponse`:用请求 session 跑
  `cleanup_terminal_data`(cutoff = now − `logs.retention_days`,非 dry-run)、
  `prune_event_audit`、`trim_log_streams`(redis 取 `app.state.redis`)三步,
  **步骤级故障隔离与 `RetentionSweepLoop.sweep_once` 同契约**:每步独立
  try/except,前一步抛错(rollback 请求 session 后)不阻断后续步骤。
  **retention 旋钮 0 = 关闭的统一语义**(评审 R-03):
  `logs.retention_days=0` 时 cleanup 步 `skipped`(自动 loop 同步加同一
  短路——当前 0 会算出 cutoff=now 而立删全部终态数据,必须堵住),
  `event_audit_retention_days=0` / `log_retention_seconds=0` 沿用 service
  既有的 0=关闭行为并记 `skipped`;redis 缺失时 trim 记 `skipped`。
  **trim 失败可见**(评审 R-02):`trim_log_streams` 现在内部逐流吞异常、
  调用者无从得知失败,改为返回结构化逐流结果
  `{stream: {"trimmed": n} | {"error": "<msg>"}}`(自动 loop 兼容,仅记
  日志);端点聚合:任一流带 `error` → `stream_trim.status=failed`,响应
  附逐流明细。响应始终 HTTP 200(操作已被执行),按步汇报:

```json
{
  "steps": {
    "cleanup":     {"status": "ok|failed|skipped", "result": "<TerminalCleanupResponse 同形> | null"},
    "event_audit": {"status": "ok|failed|skipped", "pruned": "int | null"},
    "stream_trim": {"status": "ok|failed|skipped", "streams": "{stream: {trimmed} | {error}} | null"}
  }
}
```

  三步与 `RetentionSweepLoop.sweep_once` 复用同一批 service 函数,不复制
  逻辑(各 service 自持提交语义:cleanup 两阶段提交、prune 分批提交)。
- `POST /maintenance/redis-rewrite-aof` → `{started: true}`:调
  `app.state.redis.bgrewriteaof()`;redis 不可用(state 缺失或调用异常)抛
  `ApiError(503, "maintenance.redis_unavailable", ...)`。

`redis/client.py` 增两个薄封装:`info(section: str) -> dict`、
`bgrewriteaof() -> Any`;测试双胞(现有自定义 fake)同步补齐。

### 4. Web 页面重写(D4)

- 数据流:`getResourceStats()` 首载 + `setInterval` 10s 轮询(`useEffect`
  cleanup 清定时器;仿 dashboard 的 `active` 标志防 setState-after-unmount);
  加载态用 `Skeleton`;整体失败显示 `Alert` + 保留上次数据。
- 布局:顶部标题 + server 快照 `sampled_at` 年龄(`formatDateTime`)+ 手动
  刷新按钮(仅重新 GET 缓存快照);`sampled_at` 为 null 时整页呈"首次采样
  中"骨架。四组 `Card`(Server 磁盘 / PostgreSQL / Redis / Agents,每个
  agent 一张子卡):
  - **scope 级**:卡头按 `status` 呈现——`unavailable` → 灰 badge + 占位
    文案(离线节点显示 `last_seen_at`);`stale` → 琥珀 badge + 样本时间;
    `ok` → 正常渲染;
  - **条目级**:行 = 指标名(i18n)、当前值(`formatBytes`/计数)、上限
    (null 显 "—")、`Progress` 用量条、`ToneBadge` 等级映射
    ok→green / warn→amber / critical→red / **unknown→gray**(复用现有
    4 tone,不加新 tone)。
- 操作卡:三个操作各带 `useConfirm` 确认(terminal-cleanup 沿用现有
  dry-run 预览 → destructive 确认流与 `maintenance-days`/`maintenance-preview`
  /`maintenance-run` testid;sweep-now 与 rewrite-aof 各一个确认按钮),结果
  以内联 `Alert`/summary 呈现(沿用项目内联 Alert 惯例,不引入 toast)。
  卡底注明:容器日志大小由 Docker daemon 托管无法在应用内测量;PG 磁盘立即
  回收需按生产收缩 runbook 执行 `VACUUM FULL`(纯文案)。
- `components/ui/progress.tsx` 按 shadcn(new-york/radix-ui umbrella)加入,
  遵守项目内建 `shadcn` skill 约定;`formatBytes` 扩展 GB/TB(现仅 KB/MB,
  format.ts:22-29)。
- i18n:`maintenance.*` 键块重构(en.ts:226-247 / zh.ts:222-243),保留
  cleanup 流键,新增指标名/scope/操作/staleness 键,`nav.maintenance` 不动。

### 5. 回写文档

04-configuration 增配置项;06-web-frontend 更新页面职责。不新增决策记录
(资源上限决策 0019 已覆盖动机,本任务是其可观测性延伸,不改架构边界)。

## 测试用例

| 编号 | 档位 | 前置条件 | 步骤 | 预期结果 | 证据形态 |
|---|---|---|---|---|---|
| TC-01 | A | server 测试环境(aiosqlite);`logs.root_dir`/`artifacts.root_dir` 配置为与 `server.data_dir` **不同**的临时目录 | pytest 跑 `collect_snapshot` 单测:种入 tasks/executions/log 行,SQLite 方言 | 日志/artifacts 字节取自配置根目录(而非 data_dir 推导路径),证明配置生效;postgres scope 出行数、字节条目 value 为 null 且 level=unknown;响应形状符合 scopes/entries 两层契约 | evidence/ 内命令+完整输出+退出码 |
| TC-02 | A | 同上 | level 边界参数化单测:占比类 limit=100,value∈{69,70,89,90,100};年龄类两组:G<W 时 age∈{W+G, W+G+1, 2W, 2W+1},**G>W 时**(如 W=100、G=200)age∈{W+G, W+G+1}(此时 critical_at=W+G);limit=null 时 volume free 比例分档;**谓词反例**:种入 created_at 很老但 finished_at 新的终态任务、created_at 很老但 processed_at 新的 event_audit 行;**关闭语义**:各 retention 旋钮置 0、`maintenance.enabled=false` | 占比:69→ok、70→warn、89→warn、90→critical;年龄 G<W 组:W+G→ok、W+G+1→warn、2W+1→critical;年龄 G>W 组:W+G→ok、W+G+1→critical(区间无重叠、判定唯一);反例两行按 effective-time(finished_at/processed_at)计龄不误报红;旋钮 0 → 条目 limit=null 恒 ok;enabled=false → 响应 `sweep_enabled:false` 且年龄条目照常计算 | 同上 |
| TC-03 | A | fake redis 双胞补 `info`/`xinfo_stream`/`bgrewriteaof` | redis scope 单测:正常返回 used_memory/maxmemory/aof/流长度与首条目年龄;**再测空流:全部流不存在(空 Redis)与仅部分 command stream 不存在(`no such key`)两种**;再令 fake redis 抛异常;再令 AOF 字段缺失;**再注入 postgres 板块 SQL 抛错(patch 涉库查询)** | 正常时条目齐全,memory level 按 maxmemory、log/event 流长度按 `stream_maxlen_*`、首条目年龄按 `log_retention_seconds` 计算,命令流仅长度条目、断言**无**年龄条目;空流两种场景 scope=ok 且对应条目 length=0/年龄条目省略(不降级);整板块异常时 redis scope status=unavailable 且 entries 为空、其余 scope 照常;单指标缺失(AOF)时仅该条目 value=null/level=unknown;**PG 板块故障时 postgres scope=unavailable 而 server/redis/agents 三 scope 照常有值**(独立 session 隔离回归) | 同上 |
| TC-04 | A | ASGITransport app + admin token,快照经注入的 loop 缓存提供 | `GET /maintenance/resource-stats`:无 token 401;有 token 200;nodes 表种入六类节点(可用性走**动态聚合**而非持久化 status):healthy+新鲜样本 / degraded+新鲜样本 / healthy+过期样本(age>2×interval_seconds) / unhealthy / healthy 无 disk 样本 / **持久化 status=healthy 但 `last_seen_at` 已超心跳超时**;**再种一组畸形样本节点**:`sampled_at` 非法日期 / `interval_seconds` 为 0、负数、非数值 / 嵌套 bytes 为字符串或负数 / 部分字段缺失(与一个合法样本节点共存);另测无快照场景(不注入缓存),并用计数 stub 断言请求路径零采样 | 401/200;六类 agent scope 分别 status=ok/ok/stale/unavailable/unavailable/**unavailable(断联回归)**;畸形组:整样本不可解析的节点 scope=unavailable、字段级非法仅该条目省略/unknown,**同快照中合法节点与其他板块照常有值、快照正常更新**,stale 附样本 `sampled_at`、unavailable 附 `last_seen_at`;cache 条目 level 由 agent 上报的 limit 计算;无快照时 200 + `sampled_at:null` + `scopes:[]` 且 collect 计数为 0 | 同上 |
| TC-05 | A | 种入过期终态任务 + event_audit 旧行 + fake redis 流 | `POST /maintenance/sweep-now`:**无 token → 401**;有 admin token 全成功一遍;再分别注入 cleanup 抛错 / prune 抛错 / **单流 XTRIM 抛错(另一流正常)** / 无 redis / `retention_days=0` 五种场景各跑一遍 | 全成功:200,三步 status=ok、计数与实际删除一致;cleanup 失败:prune 与 trim 仍执行且 status=ok,cleanup status=failed;prune 失败:trim 仍执行;单流失败:`stream_trim.status=failed` 且逐流明细一流 `{trimmed}` 一流 `{error}`(部分成功如实呈现);无 redis:stream_trim=skipped;`retention_days=0`:cleanup=skipped 且**未删除任何终态数据**、其余两步照常;全部场景 HTTP 200 且响应逐步如实汇报 | 同上 |
| TC-06 | A | fake redis 记录调用 | `POST /maintenance/redis-rewrite-aof`:**无 token → 401**;有 redis / 无 redis / **redis 存在但 `bgrewriteaof()` 抛错** 三分支 | 401;有:200 `{started:true}` 且 fake 记录到 bgrewriteaof;无 redis 与调用抛错:均 503 错误信封 `maintenance.redis_unavailable` | 同上 |
| TC-07 | A | — | `ResourceStatsLoop` 单测:start 后立即首采、tick 后 snapshot 缓存;注入采样异常再 tick;`stats_interval_seconds=0` 时 app 不启 loop;另测 `RetentionSweepLoop.sweep_once` 在 `retention_days=0` 时的短路 | loop 不死、异常后下 tick 恢复;=0 时端点仍 200 返回 `sampled_at:null` 空响应且零采样(计数 stub);retention sweep 0 值跳过终态清理(不删数据)、event_audit 与流 trim 照常 | 同上 |
| TC-08 | A | — | server/agent 配置单测:TOML + env(`DOPILOT_MAINTENANCE_STATS_INTERVAL_SECONDS`)覆盖 | 字段生效,默认 60 | 同上 |
| TC-09 | A | 假 workdir 树(已知大小的 workspaces/cache/scrapyd/outbox/logpos/state) | agent janitor 采样单测:`sweep_once` 后读 `DiskStatus.snapshot()` | 各计数/字节与树一致;样本含固定 keys 与 `sampled_at`;单子项故障(如 scrapyd 目录不可读)只置 null 不炸 sweep | 同上 |
| TC-10 | A | 同上 | 心跳单测:`build_request` 在有/无样本两态 | 有:`detail["disk"]` 等于缓存样本(断言心跳路径未触发遍历——用计数 stub 采样函数);无:不含 `disk` key;`detail["redis"]`/`scrapyd` 原样保留 | 同上 |
| TC-11 | A | server 心跳 API 测试环境 | 端到端:带 `detail["disk"]`(含 `sampled_at`/`interval_seconds`)的心跳打入 → `GET /nodes` → 触发一次 loop 采样 → `GET /maintenance/resource-stats` | `nodes.health` 原样含 disk;resource-stats 折出对应 agent scope(status=ok)及条目 | 同上 |
| TC-12 | A | vitest + mocked `lib/api/maintenance` | 页面测试:mock resource-stats 载荷渲染四 scope;条目 level→`data-tone` 映射(ok→green/warn→amber/critical→red/unknown→gray);scope status 渲染(stale→琥珀标注+样本时间、unavailable→灰占位+`last_seen_at`);null-limit 显 "—";`sampled_at` 呈现,`sampled_at:null` 载荷显"首次采样中"骨架;三操作各走 confirm 弹窗→接受→对应 api 调用、取消→不调用;cleanup dry-run 摘要渲染 | 断言全过 | 同上 |
| TC-13 | A | vitest fake timers | 轮询测试:advance 10s → 第二次 `getResourceStats` 调用;unmount 后再 advance → 无新调用 | 定时器正确清理 | 同上 |
| TC-14 | A | — | `formatBytes` 扩展单测(GB/TB 档 + 既有 KB/MB 不回归) | 断言全过 | 同上 |
| TC-15 | A | 全仓 | `pytest apps/server/tests apps/agent/tests packages/protocol/tests` + `ruff check apps packages` + `corepack pnpm --filter web test` + `corepack pnpm --filter web lint` + `corepack pnpm --filter web exec tsc --noEmit` | 全绿 / clean / 0 exit | 同上 |
| TC-16 | B | 实现完成 | 核对文档与配置样例回写 | 04-configuration、06-web-frontend、两份 server toml 均含新内容 | `文件:行号` 引用清单 |
| TC-17 | A | docker 可用(本机已确认 daemon 29.x) | 真 PostgreSQL 集成:evidence 脚本起一次性 postgres 容器(`docker run` 官方镜像,随机端口)→ `alembic upgrade head` → 以 `DOPILOT_TEST_PG_URL` 环境变量运行 test_resource_stats.py 中 PG-gated 用例(无该 env 时自动 skip,不影响 TC-15 全量套件)→ 拆容器 | 对迁移后的五张表真实执行 `pg_total_relation_size`/`pg_database_size`/行数/年龄采集:字节为非负整数、行数与种入一致、postgres scope status=ok 而非 unavailable;脚本全程无人工交互 | evidence/ 内脚本 + 命令 + 完整输出 + 退出码 |

C 档 0 条(无人工交互项)。异常/边界路径:TC-02(占比与年龄双规则边界)、
TC-03(redis 整板块/单指标故障降级)、TC-04(陈旧样本/离线节点/缺样本/
无快照零采样)、TC-05(sweep-now 步骤级故障隔离)、TC-06(503)、TC-07
(loop 容错/关闭)、TC-09(子项故障)、TC-13(卸载清理)。

## 风险与回滚

- **采样开销**:`/server-data/logs` 与 agent workdir 的目录遍历在大树上可能
  慢——全部下沉 `asyncio.to_thread`,server 侧每 60s 一次、agent 侧每 600s
  一次(随 janitor),心跳与 HTTP 请求路径零遍历;慢 tick 只是快照变旧,
  页面靠 `sampled_at` 如实呈现。
- **心跳载荷增长**:`detail["disk"]` 固定形状、仅计数/字节,每次心跳原样
  写入 `nodes.health`(JSONB 单行 upsert),量级几百字节,可控。
- **`INFO persistence` 字段差异**:AOF 关闭或不同 Redis 版本字段缺失 → 条目
  值置 null,不报错。
- **fakeredis/自定义 fake 与真 Redis 的 INFO 差异**:测试断言走自定义 fake;
  真实兼容性靠薄封装(只取两个众所周知字段)控制面。
- **PG 专有 SQL**(`pg_total_relation_size` 等):方言分流沿
  services/stats.py:77 idiom,表名取自模型常量白名单;SQLite 分支由
  TC-01 覆盖,**PG 真值路径由 TC-17 用一次性 postgres 容器 A 档覆盖**
  (签名/标识符/返回类型/权限问题都会在该用例暴露)。
- **sweep-now 是真删除**:与自动 sweep 同一 cutoff(`retention_days`),前端
  destructive 确认;误触后果等价于等一小时自动 sweep,无新增风险面。
- **回滚**:无迁移、无协议变更、端点纯新增;回退 = 回退镜像(旧页面静态
  产物随旧镜像回来),新配置项缺省即无行为差异。
