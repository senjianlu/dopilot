# dopilot —— Docker 化部署与数据持久化

> **【scrapydweb 参考边界】** scrapydweb 仅作**功能层/行为参考**与**测试 oracle**;其代码写法、目录结构、模块划分、命名、依赖、配置形态**一律不得作为 dopilot 的设计依据**。dopilot 为 greenfield、按 `apps/`+`packages/` 自有领域 structure-first 设计(权威布局见 `05-dev-setup-and-known-issues.md` §1),**不对 scrapydweb 做改名/git mv**。详见 `00-requirements.md` 决策表。

> 面向 dopilot 改造工程师。本文区分「现状事实」（基于 scrapydweb 1.6.0 真实代码，引用 `file:line`，仅作行为参考）与「dopilot 实现建议 / 开放问题」。
> dopilot 计划分 **server**（Web 控制台 + 调度中枢）与 **agent**（执行器）两种 Docker 角色部署，单管理员，执行能力分期推进 scrapy egg → python 脚本 → docker 长连接。
> 关联文档：`docs/dopilot/01-gap-executors.md`（执行器）、`docs/dopilot/02-gap-scheduling-nodes-push.md`（调度/节点/推送）、`docs/architecture/01-bootstrap-and-config.md`（启动与配置加载）。

> **⚠️【阶段 2.1 前端部署模型已更新】** 自**阶段 2.1**起前端为 **Next.js 静态导出**（`output: export` + `trailingSlash`，产物 `apps/web/out`：每路由一个 HTML + `_next/` 资源 + `404.html`），由 **dopilot-server 同源托管**（`DOPILOT_WEB_DIST=/app/web`，`/api/*` 不被改写为 HTML）；**无 `next start`、无 Node 生产运行时、无独立 Web 容器**。镜像 web 构建阶段执行 `pnpm --filter web build` 并将 `apps/web/out` 拷入 `/app/web`。下文涉及前端构建/静态资源/Web 容器/开发代理的旧 Vue/Vite 描述一律以阶段 2.1 为准；权威说明见 `docs/dopilot/06-frontend-rewrite.md` 顶部对照表与 `docs/phases/phase-2.1/01-claude-implementation-report.md`。

---

## dopilot 目标决策（当前版本）

> **【superseded-by】** server↔agent 通信模型已被 `docs/refactor/00-redis-streams-agent-communication.md` 破坏性翻案为 **Redis Streams 总线**（server→agent 命令 stream、agent→server 事件/日志 stream + agent 主动 POST heartbeat），删除 server→agent HTTP run/status/tail 主路径与 `AgentTailLogSource`。下表「日志链路」「单实例硬约束」「认证」行已按新模型同步；以该 refactor 文档为唯一真相，细节去看它。

| 项 | 决策 |
| --- | --- |
| 后端运行时 | `apps/server` 使用 **FastAPI + ASGI**，生产固定 uvicorn 且 `workers=1`。 |
| 数据库 | **PostgreSQL 是唯一持久化数据库**。不再提供 SQLite 作为 dopilot 正式运行路径；reference 的 SQLite 行为仅供理解 scrapydweb。**Redis 是消息总线/瞬时传输，非 dopilot 数据库、不持久化业务真相；agent 经 Redis 不直连 PostgreSQL。** |
| ORM / migration | SQLAlchemy + **裸 Alembic**（FastAPI 无 Flask app，**不是 Flask-Migrate**）；迁移目录在 `apps/server/migrations/`。 |
| 日志正文存储 | **日志正文写本地文件卷** `/server-data/logs/YYYY/MM/{execution_id}/{attempt_id}.{stream}.log`（`stream=log` 时即 `{attempt_id}.log`）。**PostgreSQL 不存日志正文。** |
| 日志索引存储 | PostgreSQL 表 `execution_log_files`，主键 `(execution_id, attempt_id, stream)`，存 `storage_path / size_bytes / last_pulled_offset / final_offset / status / log_integrity / gap 字段 / started_at / finished_at / retained_until`。`last_pulled_offset` 是 server 已消费的 **agent 逻辑 byte offset** 权威；`final_offset` 是 **server 文件物理大小**（含 gap marker），两者不混用；`log_integrity`（complete/partial/missing/expired）与生命周期 `status` 分离。 |
| server 数据边界 | 只有 server 连接 PostgreSQL；agent 和 web 不直连数据库。 |
| 日志链路 | **agent 经 Redis log stream 主动推增量，server 消费后落盘**：agent tail 本地 `job.log` 按字节 offset `XADD dopilot:server:logs`（base64 字节）→ server log consumer 写 `/server-data/logs` 正文 + 更新 PG 索引/offset → 经 **SSE** 单向推给 web。四个不变量保留：**第一版完全不使用 WebSocket、server→web SSE、正文落 `/server-data/logs`、PG 只存索引/offset/状态**。日志 RPO≠0（server 长停或 Redis 裁剪致 partial，详见 `docs/refactor/00-redis-streams-agent-communication.md`）。 |
| 单实例硬约束 | server = 单容器 + **uvicorn workers=1** + 单 APScheduler 实例。**不支持多副本/多 worker，未来也不做** —— 不引入 Redis 做多副本 HA/fan-out/选主/分布式锁；server→web SSE fan-out 仍在单进程内存完成。**显式允许 Redis 作单实例 server↔agent 通信总线**（命令/事件/日志三条 stream + heartbeat HTTP，详见 `docs/refactor/00-redis-streams-agent-communication.md`）。 |
| 认证 | **Web 管理员认证 fail-closed（阶段 2.2）**：经 `load_settings()` 启动时 `admin_username + admin_password + token_secret` 三者必须齐全且非空，否则抛 `ConfigError` 拒绝启动；开发环境如需匿名管理员模式，必须显式设 `DOPILOT_AUTH_DISABLED=true`（不再以"缺配置即静默关闭"进入匿名）。**server↔agent 机器认证（阶段 2.2.3）用单一 `agent_token` 同时认证两个方向（非空才校验、非空须 >=16 字符；不再拆分、不从 admin token 回退）。阶段 2.2.4 在 server 运行时边界放宽为：配置了 `agent_token`，或 server 自动生成并持久化到 `<server.data_dir>/secrets/agent-token` 的令牌即视为 ON（生成仅 server 端、`load_settings()` 无副作用），Redis 启用 AUTH/ACL**；`admin_api_token` 仅管理员、仅 server 端，绝不下发给 agent；SSE `stream_token` 仅在 Web 认证开启时需要。内网防误操作策略，非互联网零信任；Token 认证不是传输加密，跨主机加密仍需 TLS/VPN/私有网络。 |

---

## 0. TL;DR（先读这里）

| 关键点 | 现状事实 | 影响 |
|--------|----------|------|
| 启动期清目录 | `vars.py:59-66` 每次进程启动会**清空** `PARSE_PATH` / `DEPLOY_PATH` / `SCHEDULE_PATH` 下的 `*.*` 文件（仅保留 `ScrapydWeb_demo.log`） | 这三个目录**不能**当作持久化卷期望它保留内容；容器重启即清空 |
| SQLite 数据 | scrapydweb reference 默认全部落在 `DATABASE_PATH = DATA_PATH/database/`（`vars.py:51`） | **仅为 reference 行为**；dopilot 正式版本不使用 SQLite，统一使用 PostgreSQL |
| APScheduler jobstore | reference 默认 SQLite jobstore；dopilot 使用 PostgreSQL-backed jobstore 或自有 scheduler 表 | 定时任务必须落 PostgreSQL，并受 Alembic/迁移策略管理 |
| 进程内调度器 | `BackgroundScheduler`，进程内线程，`scheduler.start(paused=True)`（`scheduler.py:45,90`） | 单进程单实例假设；**多副本会重复触发**定时任务 |
| 后台子进程 | LogParser 与 Poll 两个 `Popen` 子进程，靠 `prctl(PR_SET_PDEATHSIG)` 跟随父进程退出（`sub_process.py`） | 与容器「单进程」哲学冲突；属 server 角色，不应进 agent 镜像 |
| 配置文件 | （scrapydweb 行为参考）文件名硬编码 `scrapydweb_settings_v11.py`（`vars.py:29`），从 `os.getcwd()` 加载（`run.py:37,124`） | dopilot **不沿用**此形态：dopilot 以 toml 配置经自有加载器读取；Docker 镜像内置 server/agent 角色默认配置路径，部署配置主要用 `DOPILOT_*` 环境变量覆盖，无 cwd 硬编码文件名约束 |

---

## 1. 现状事实：数据目录与数据库路径

### 1.1 DATA_PATH 与子目录常量（`vars.py`）

`vars.py:42-57` 定义了所有数据路径，根目录 `DATA_PATH` 的取值优先级见 `vars.py:45-49`：

```python
# vars.py:45-49
DATA_PATH = default_data_path or custom_data_path   # 环境变量 DATA_PATH > 配置文件 DATA_PATH
if DATA_PATH:
    DATA_PATH = os.path.abspath(DATA_PATH)
else:
    DATA_PATH = os.path.join(ROOT_DIR, 'data')       # 否则落在包目录 scrapydweb/data
```

- `default_data_path` 来自 `default_settings.py:376`：`DATA_PATH = os.environ.get('DATA_PATH', '')` —— **可通过环境变量 `DATA_PATH` 注入**（容器化关键）。
- `custom_data_path` 来自配置文件 `scrapydweb_settings_v11.py` 的 `DATA_PATH`（`vars.py:37`）。

子目录常量（`vars.py:51-57`）：

| 常量 | 路径（相对 DATA_PATH） | 内容 | 谁在写 |
|------|----------------------|------|--------|
| `DATABASE_PATH` | `database/` | 4 个 SQLite DB + APScheduler jobstore | `setup_database.py` / SQLAlchemy / APScheduler |
| `DEMO_PROJECTS_PATH` | `demo_projects/` | 内置演示项目 | 打包自带 |
| `DEPLOY_PATH` | `deploy/` | 部署用 egg / 压缩包（构建中转） | `deploy.py:313,331,335,346` |
| `HISTORY_LOG` | `history_log/` | `run_spider_history.log` / `timer_tasks_history.log` | `vars.py:68-69` / `scheduler.py:19` |
| `PARSE_PATH` | `parse/` | 用户上传待解析的日志 | `parse.py:49,73` |
| `SCHEDULE_PATH` | `schedule/` | Run Spider 表单的 `*.pickle` 中转缓存 | `schedule.py:277,379,609` |
| `STATS_PATH` | `stats/` | LogParser 统计 json 备份 | `log.py:288,293-294` |

### 1.2 四个 SQLite 数据库的物理位置（`setup_database.py:53-61`）

未配置 `DATABASE_URL` 时（默认走 SQLite 分支）：

```python
# setup_database.py:55-61  —— 全部落在 DATABASE_PATH 下
APSCHEDULER_DATABASE_URI = 'sqlite:///' + database_path + '/apscheduler.db'
SQLALCHEMY_DATABASE_URI  = 'sqlite:///' + database_path + '/timer_tasks.db'
SQLALCHEMY_BINDS = {
    'metadata': 'sqlite:///' + database_path + '/metadata.db',
    'jobs':     'sqlite:///' + database_path + '/jobs.db',
}
```

| DB 文件 | 绑定 | 存什么 | 丢失后果 |
|---------|------|--------|----------|
| `apscheduler.db` | APScheduler jobstore（`scheduler.py:32`） | 持久化的定时任务触发器 | 所有 Timer Task 丢失，不再触发 |
| `timer_tasks.db` | `SQLALCHEMY_DATABASE_URI`（`__init__.py:112`） | `Task` / `TaskResult` / `TaskJobResult`（`models.py:89-179`） | 任务定义与执行历史丢失 |
| `metadata.db` | bind `metadata`（`models.py:18`、`__init__.py:113`） | `Metadata`：main_pid、各子进程 pid、用户名密码、scheduler_state、分页设置等（`models.py:16-39`） | 后台 UI 偏好、调度器开关状态丢失 |
| `jobs.db` | bind `jobs`（`models.py:46`） | 各 Scrapyd 节点的 Jobs 快照表（动态建表，`create_jobs_table`，`models.py:43-73`） | Jobs 历史快照丢失 |

> 这两类（jobstore 的 `apscheduler.db` + 三个业务 DB）都在 `DATABASE_PATH`，且 `DATABASE_PATH` **不在** `vars.py:63` 的清空名单内，所以它们天然可持久化 —— 前提是把 `database/` 目录挂到卷上。

### 1.3 配置文件加载（`run.py`）

```python
# run.py:37  默认期望配置文件在当前工作目录
app.config['SCRAPYDWEB_SETTINGS_PY_PATH'] = os.path.join(os.getcwd(), SCRAPYDWEB_SETTINGS_PY)
# run.py:124  实际查找
path = find_scrapydweb_settings_py(SCRAPYDWEB_SETTINGS_PY, os.getcwd())
```

- 文件名硬编码 `SCRAPYDWEB_SETTINGS_PY = 'scrapydweb_settings_v11.py'`（`vars.py:29`）。
- 找不到时会尝试把 `default_settings.py` 复制为该文件并 `sys.exit`（`run.py:130-150`）—— 容器里这会导致**启动即退出**，所以必须预先把配置文件挂进去。

### 1.4 dopilot 日志存储模型（v1 已锁定，非 scrapydweb 行为）

> **【superseded-by】** 通信/日志链路已被 `docs/refactor/00-redis-streams-agent-communication.md` 翻案：由「server 主动 pull agent HTTP tail」改为「agent 经 Redis log stream 主动 `XADD` 增量、server 消费后落盘」，`LogSource` 抽象保留、实现由 `AgentTailLogSource` 换为 `RedisLogSource`。落盘/索引/SSE/无 WebSocket 四不变量与下文一致。本节文字按新模型同步。

dopilot **不**沿用 scrapydweb 的本机 logparser + SQLite 路线，采用 **agent 经 Redis 推增量 + server 消费落文件 + 索引落 PG** 的分离模型：

- **正文存储**：server 本地文件卷 `/server-data/logs/YYYY/MM/{execution_id}/{attempt_id}.{stream}.log`（`stream=log` 时即 `{attempt_id}.log`）。这是**重要持久化卷**，必须挂卷并纳入备份。
- **索引存储**：PostgreSQL 表 `execution_log_files`，**不存日志正文**。

| 列 | 说明 |
|----|------|
| 主键 `(execution_id, attempt_id, stream)` | 一个 attempt 的一条 stream 一行 |
| `storage_path` | 正文文件相对/绝对路径 |
| `size_bytes` / `final_offset` | 当前大小 / `final_offset` = server 日志文件物理大小（含可见 gap marker），非 agent 逻辑 offset |
| `last_pulled_offset` | **agent 逻辑 byte offset 权威**：server 已消费到的 agent 本地日志文件字节偏移；只追加 `offset == last_pulled_offset` 的片段，`offset > last_pulled_offset` 标 gap |
| `log_integrity`（新增列） | `complete` / `partial` / `missing` / `expired`，与生命周期 `status` 分离；offset gap → `partial` 黏性标记 |
| `status` | `active` / `finalizing` / `complete` / `missing` / `expired`（日志生命周期，不混入完整性） |
| `started_at` / `finished_at` / `retained_until` | 时间与保留期 |
| `created_at` / `updated_at` | 审计 |

- **stream 取值**：schema/API 从第一版即支持 `log` / `stdout` / `stderr` / `system`；scrapy/scrapyd 只产生 `stream=log`（单一 `job.log`，不天然拆 stdout/stderr），脚本阶段才用 `stdout`/`stderr`。
- **日志推送**（参数见 `[redis]` / `[logs]` 配置）：agent log publisher tail 本地 `job.log`，按字节 offset 把增量 `XADD dopilot:server:logs`（base64 字节，带 `offset`/`size_bytes`/`eof`）；server log consumer 消费后落盘 + 更新索引。日志事件量大时控制 batch/maxlen/消费延迟；offset 顺序由 agent 端单一顺序生产者保证。
- **结束检测**：由 agent 经 `dopilot:server:agent-events` 主动推 terminal 状态事件（`attempt.finished/failed/canceled`），server event consumer 消费收敛（**不再轮询 agent status API**）；terminal 后进入 bounded drain 窗口（`eof=true` log event 是优化信号、非前置条件）→ drain timeout 或 EOF → 生命周期 `complete`、完整性 `complete`/`partial`。随后 server 向 agent command stream 投 `cleanup_logs` 命令，agent 删除本地 `job.log` 与状态文件。
- **SSE 推送**：server → web 单向 SSE（fan-out 仍在 server 单进程内存完成）。Web 认证开启时用短期 `stream_token`（POST 换取、TTL 60s、只校验建连、连接最长寿命如 30min、`id:<seq>` + `Last-Event-ID` 支持重连补洞）；多窗口看同一 execution 复用同一 log consumer 投喂 + SSE fan-out。**第一版完全不使用 WebSocket。**

---

## 2. 镜像设计：server 与 agent 两种角色

### 2.1 角色边界（事实 + 建议）

| 能力 | server 角色 | agent 角色 | 依据 |
|------|:----------:|:----------:|------|
| FastAPI Web API | ✓ | ✗ | dopilot 决策：`apps/server` 提供 `/api/v1/*` JSON/SSE API |
| 进程内 APScheduler（定时任务） | ✓ | ✗ | `scheduler.py:90`（仅 server 持有调度权） |
| LogParser 子进程 | ✓（可选） | —— | `sub_process.py:53起 init_logparser`；agent 端日志解析见下文建议 |
| Poll/监控子进程 | ✓（可选） | —— | `sub_process.py:85起 init_poll` |
| PostgreSQL | ✓（唯一数据库连接持有者） | ✗ | dopilot 决策：agent/web 不直连数据库 |
| 实际执行爬虫/脚本 | ✗（转发给 agent） | ✓ | dopilot 规划，见 `01-gap-executors.md` |

> **现状事实**：上游 scrapydweb 把"执行"交给远端 **Scrapyd**（`SCRAPYD_SERVERS`），自身没有独立的 agent 进程。dopilot 的 agent 是**新增角色**（分期替换 Scrapyd：scrapy egg → python 脚本 → docker 长连接）。server 与 agent 使用同一个应用镜像，通过启动命令选择角色。

### 2.2 镜像分层策略（多阶段构建）

```
统一应用镜像：
  阶段 1  web-build : 构建 apps/web（阶段 2.1：Next.js 静态导出 `pnpm --filter web build` → apps/web/out；历史为 Vue/Vite SPA）
  阶段 2  py-deps   : 构建 protocol/server/agent wheels
  阶段 3  runtime   : slim 基础镜像 + server/agent + scrapy/scrapyd + Alembic + Web 静态产物（apps/web/out → /app/web）
```

分层要点：
- 依赖层与代码层分离，最大化 layer 缓存（依赖变动少、代码变动多）。
- **统一应用镜像**：`rabbir/dopilot:latest` 同时包含 server、agent、protocol、Scrapy/scrapyd 运行时、Alembic 迁移资源，以及构建后的 Web 静态产物（阶段 2.1：Next.js 静态导出 `apps/web/out`，历史为 Vue SPA）。
- **启动命令选择角色**：server 容器运行 `dopilot-server` 并**同源托管** Web UI（静态文件，无独立 Web 容器）；agent 容器运行 `dopilot-agent` 并管理本机 scrapyd；migrate 容器运行 `alembic upgrade head`。
- `.dockerignore` 排除 `reference/`（防御性保留，本仓库已无该目录）、`.venv/`、`docs/`、`**/tests/`、`*.pyc` 等（dopilot 自有数据目录由卷管理，不进镜像）。

### 2.3 统一 Dockerfile

```dockerfile
# deploy/docker/Dockerfile
# 1. node:22-slim 构建 apps/web（阶段 2.1：pnpm --filter web build → apps/web/out 静态导出；历史为 Vite dist）
# 2. python:3.12-slim 构建 protocol/server/agent wheels
# 3. runtime 安装 server + agent + scrapy/scrapyd，复制 Alembic 迁移和 Web 静态产物（apps/web/out → /app/web）
#
# 默认 CMD 为 server 模式：
CMD ["dopilot-server", "-b", "0.0.0.0", "-p", "5000"]
```

完整实现以仓库中的 `deploy/docker/Dockerfile` 为准。server 模式会读取 `DOPILOT_WEB_DIST=/app/web`，托管 web 构建阶段拷入的静态产物（阶段 2.1：Next.js 静态导出 `apps/web/out`——每路由一个 HTML + `_next/` 资源 + `404.html`；历史为 Vue/Vite `dist` + `index.html` SPA fallback）；`/api/*` 始终保留为 API 路径，**不被改写为 HTML**。

### 2.4 agent 角色（执行器，分期）

agent 使用同一个 `rabbir/dopilot:latest` 镜像，不单独发布 `rabbir/dopilot-agent`。agent 容器只跑 worker 执行器 + 本机 scrapyd + Redis consumer/producer + heartbeat worker。**agent 主动**经 Redis consumer group 消费命令、主动 `XADD` 推状态/日志、主动 POST heartbeat（破坏性翻案，详见 `docs/refactor/00-redis-streams-agent-communication.md`）；**仍不使用 WebSocket**，server→agent HTTP run/status/tail 主路径已删除。

启动命令：

```bash
dopilot-agent -b 0.0.0.0 -p 6800
```

> **dopilot 实现建议**：agent 与 server 用**不同的依赖声明**（各自的 `pyproject.toml`；agent 不需要 FastAPI server、SQLAlchemy/Alembic、前端或 logparser）。第一版正式架构中：
> - **子进程拓扑**：agent 进程作为 PID 1（`init: true`/tini），以子进程方式拉起**本机 scrapyd**；scrapyd 只监听容器内部端口（如 `6801`，仅本机可见），对外不再暴露 server→agent 调度端口。现成 Scrapyd 镜像只作为本地 spike/连通性验证，不进入第一版目标形态。
> - **agent Redis 工作线程（主动消费 + 主动推，无 WebSocket）**：
>   - command consumer：consumer group 消费 `dopilot:agent:{agent_id}:commands`（`run`/`stop`/`cleanup_logs`；`stop` 带 `intent=cancel|reclaim`），按 `attempt_id` 幂等接管后 `XACK`；启动先认领超时 pending command。
>   - status publisher：`XADD dopilot:server:agent-events` 推 `attempt.accepted/running/finished/failed/canceled/lost`，经 event outbox 保证 at-least-once。
>   - log publisher：tail `job.log` 按字节 offset `XADD dopilot:server:logs`（base64 字节、带 `offset`/`size_bytes`/`eof`），单一顺序生产者按 offset 严格递增。
>   - heartbeat worker：周期 `POST /api/v1/agents/{agent_id}/heartbeat` 汇报健康/能力/负载；server 据此判健康。
> - **offset 权威**：`last_pulled_offset` 仍是 server 侧已消费的 agent **逻辑 byte offset** 权威；agent 主动发布带逻辑 byte offset 的 log events，offset 顺序由 agent 端单一顺序生产者保证。agent 重启后 event/log outbox 重放未确认项，由 server 幂等收敛。
> - **state 映射 / 防重启重复**：agent 在 `/agent-data/state/executions/{attempt_id}.json` 持久化 `execution_id ↔ scrapyd job_id ↔ log_path` 映射；spawn 前两阶段 CAS（`reserved`→`started`）防重复启动，重启后据状态文件分支恢复。
> - **日志清理**：由 server 在 drain 完成后投 `cleanup_logs` 命令触发；agent 另有 TTL 兜底（completed 3 天 / orphan 7 天）。server-reconciled lost 的 attempt，agent 恢复后必须先 reconcile（经 event stream 表达真实状态），不得一恢复 heartbeat 就直接 cleanup。

### 2.5.a 开发环境最小容器

本地日常开发不要求把所有角色都容器化。推荐最小模式只启动 PostgreSQL 与 Redis 容器，`server` / `web` / `agent` 在宿主机运行：

- `server`：宿主机运行 FastAPI/uvicorn，连接 `localhost:5432` 的 PostgreSQL。
- `web`：宿主机运行前端 dev server（阶段 2.1：`next dev`；历史为 Vite dev server），通过 proxy 访问 server `/api/v1` 与 SSE。生产形态为 Next.js 静态导出，由 dopilot-server 同源托管，无独立 Web 容器、无 Node 生产运行时。
- `agent`：宿主机运行 dopilot-agent，阶段 1 可在本机拉起 scrapyd 子进程，经 Redis 消费命令 + 推事件/日志、并向 server POST heartbeat（不再对外暴露 server→agent 调度 API；`-p 6800` 仅用于容器本地 `/health` healthcheck）。
- `db` / `redis`：本地开发的基础依赖；Redis 是 server↔agent 通信总线，不是业务数据库。

默认 compose 栈是**面向用户的一键部署路径**：直接拉取 CI 构建的 `rabbir/dopilot` 镜像（**无 `build:`**），拉起 server + Web UI + 三个 Scrapy agent + PostgreSQL + Redis 通信总线，可在 `deploy/docker` 下用 `docker compose pull && docker compose up -d` 启动，无需本地构建。本地源码构建/smoke 用 `docker-compose.build.yml` 覆盖文件叠加（见 §7.3）。可执行版本以仓库内 `deploy/docker/docker-compose.yml` 为准；文档只保留关键结构，避免复制后遗漏迁移、健康检查或 compose 网络配置。

### 2.5 docker-compose 示例

镜像默认 `${DOPILOT_IMAGE:-rabbir/dopilot:latest}`；三个 agent（`scrapy-agent-1/2/3`）对称，仅 `AGENT_ID` 与数据卷不同，共用同一镜像内置的 `/app/configs/agent.toml`（compose env 覆盖 `AGENT_ID` 等字段）。默认配置已**烤进镜像**（`/app/configs/server.toml`、`/app/configs/agent.toml`），默认路径**无需挂载 host 配置**；要定制时把自有 toml 挂到这些路径即可。仅 `scrapy-agent-1` 发布 `6800`（smoke/调试），scrapyd 的 `6801` **永不**发布到 host。

```yaml
# 共享 agent 定义；三个 agent 仅 AGENT_ID + 数据卷不同。
x-agent: &agent
  image: ${DOPILOT_IMAGE:-rabbir/dopilot:latest}
  command: ["dopilot-agent", "-b", "0.0.0.0", "-p", "6800"]
  init: true
  depends_on:
    redis:
      condition: service_healthy
  healthcheck:
    test: ["CMD", "python3", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:6800/health', timeout=3).status==200 else 1)"]
  restart: unless-stopped

services:
  db:
    image: postgres:16
    environment:
      POSTGRES_DB: dopilot
      POSTGRES_USER: dopilot
      POSTGRES_PASSWORD: dopilot
    volumes:
      - dopilot-db:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U dopilot -d dopilot"]
    restart: unless-stopped

  redis:
    image: redis:7
    command: ["redis-server", "--appendonly", "yes", "--requirepass", "${REDIS_PASSWORD:-change-me-redis-pass}"]
    volumes:
      - dopilot-redis:/data
    healthcheck:
      test: ["CMD", "redis-cli", "--no-auth-warning", "-a", "${REDIS_PASSWORD:-change-me-redis-pass}", "ping"]
    restart: unless-stopped

  migrate:
    image: ${DOPILOT_IMAGE:-rabbir/dopilot:latest}
    command: ["alembic", "upgrade", "head"]
    environment:
      DOPILOT_DATABASE_URL: postgresql+psycopg://dopilot:dopilot@db:5432/dopilot
    depends_on:
      db:
        condition: service_healthy
    restart: "no"

  scrapy-agent-1:
    <<: *agent
    environment:
      AGENT_ID: scrapy-agent-1
      AGENT_WORKDIR: /agent-data
      DOPILOT_REDIS_URL: redis://:${REDIS_PASSWORD:-change-me-redis-pass}@redis:6379/0
      DOPILOT_AGENT_TOKEN: ${DOPILOT_AGENT_TOKEN:-change-me-agent-token}
    volumes:
      - dopilot-agent1-data:/agent-data
    ports:
      - "6800:6800"   # 仅 scrapy-agent-1 发布 HTTP；scrapyd 6801 永不发布

  scrapy-agent-2:
    <<: *agent
    environment:
      AGENT_ID: scrapy-agent-2
      AGENT_WORKDIR: /agent-data
      DOPILOT_REDIS_URL: redis://:${REDIS_PASSWORD:-change-me-redis-pass}@redis:6379/0
      DOPILOT_AGENT_TOKEN: ${DOPILOT_AGENT_TOKEN:-change-me-agent-token}
    volumes:
      - dopilot-agent2-data:/agent-data

  scrapy-agent-3:
    <<: *agent
    environment:
      AGENT_ID: scrapy-agent-3
      AGENT_WORKDIR: /agent-data
      DOPILOT_REDIS_URL: redis://:${REDIS_PASSWORD:-change-me-redis-pass}@redis:6379/0
      DOPILOT_AGENT_TOKEN: ${DOPILOT_AGENT_TOKEN:-change-me-agent-token}
    volumes:
      - dopilot-agent3-data:/agent-data

  server:
    image: ${DOPILOT_IMAGE:-rabbir/dopilot:latest}
    command: ["dopilot-server", "-b", "0.0.0.0", "-p", "5000"]
    init: true
    environment:
      DOPILOT_DATABASE_URL: postgresql+psycopg://dopilot:dopilot@db:5432/dopilot
      DOPILOT_REDIS_URL: redis://:${REDIS_PASSWORD:-change-me-redis-pass}@redis:6379/0
      DOPILOT_ADMIN_PASSWORD: ${DOPILOT_ADMIN_PASSWORD:-change-me}
      DOPILOT_ADMIN_API_TOKEN: ${DOPILOT_ADMIN_API_TOKEN:-change-me-admin-api-token}
      DOPILOT_AGENT_TOKEN: ${DOPILOT_AGENT_TOKEN:-change-me-agent-token}
    volumes:
      - dopilot-server-data:/server-data
    ports:
      - "5000:5000"
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_healthy
      migrate:
        condition: service_completed_successfully
      scrapy-agent-1:
        condition: service_healthy
      scrapy-agent-2:
        condition: service_healthy
      scrapy-agent-3:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "python3", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:5000/api/v1/health', timeout=3).status==200 else 1)"]
    # 单实例硬约束：server 不做多副本/多 worker（uvicorn workers=1 + 单 APScheduler）。
    restart: unless-stopped

volumes:
  dopilot-server-data:
  dopilot-agent1-data:
  dopilot-agent2-data:
  dopilot-agent3-data:
  dopilot-redis:
  dopilot-db:
```

默认配置已烤进镜像；要覆盖时把自有 toml 只读挂到 `/app/configs/*.toml`。Docker 网络内服务名使用 `db`、`redis`、`server`、`scrapy-agent-1/2/3`。dopilot 配置形态为 toml（dopilot 自有领域键名，不照搬 scrapydweb 的 Python settings 形态）：

```toml
# configs/server.docker.toml（节选）
[server]
host = "0.0.0.0"
port = 5000
public_url = "http://localhost:5000"

[database]
url = "postgresql+psycopg://dopilot:dopilot@db:5432/dopilot"

# [auth] fail-closed（阶段 2.2）：load_settings() 启动时三者必须齐全且非空，否则
# 抛 ConfigError 拒绝启动。开发环境如需匿名管理员模式，显式设 DOPILOT_AUTH_DISABLED=true。
# 多数标量/密钥可被 DOPILOT_* 环境变量覆盖（env 优先于 TOML），例如：
#   DOPILOT_ADMIN_PASSWORD / DOPILOT_ADMIN_API_TOKEN（静态 admin API token，非空须 >= 16 字符）
#   DOPILOT_AGENT_TOKEN（唯一 server↔agent 机器令牌，非空须 >= 16 字符）
#   DOPILOT_SERVER_PORT / DOPILOT_SCHEDULER_ENABLED / DOPILOT_AUTH_DISABLED …
# 例外（阶段 2.2.2）：token_secret 仅 TOML 可配、无 env 覆盖；它是登录/SSE 的 HMAC 签名密钥，
#   不作为机器令牌来源；旧的 DOPILOT_ADMIN_API_SECRET 已移除、无兼容别名、无任何作用。
# 单一机器令牌（阶段 2.2.3）：[agents].agent_token 是唯一机器令牌，同时认证 server↔agent
# 两个方向（server→agent 部署 egg、agent→server heartbeat）；与每个 agent [agent].agent_token
# 同值。admin_api_token 仅管理员、仅 server 端，绝不下发给 agent、也不充当机器令牌；旧的拆分令牌
# （[agent_auth].shared_token / [agents].server_shared_token 及 DOPILOT_AGENT_SHARED_TOKEN /
# DOPILOT_SERVER_SHARED_TOKEN）已删除、无任何作用。Token 认证不是传输加密，跨主机加密仍需 TLS/VPN/私有网络。
[auth]
admin_username = "admin"
admin_password = "change-me"
# 内部签名密钥，仅 TOML、无 env 覆盖；镜像内置生成的长随机值（非用户专属密钥），高安全部署可挂载自有 TOML 覆盖。
token_secret = "shLv5qNwC3aViZQYr08x3yfaY6yGZACB6ujydXiVaGnb7OdOflc91xVLyXBoeRDL"
# 静态 admin API token：可直接作 Bearer 认证 admin；仅管理员、仅 server 端，绝不充当机器令牌；compose 经 DOPILOT_ADMIN_API_TOKEN 注入。
admin_api_token = ""
access_token_ttl_minutes = 720
# SSE 短期建连凭证：仅在 Web 认证开启时需要；POST 换取、TTL 60s、只校验建连、连接最长寿命如 30min
stream_token_ttl_seconds = 60

[nodes]
# 节点不再靠 server 轮询 /health 发现/判健康；改为 agent 主动 POST heartbeat，server 以 last_seen_at 判健康。
# agents 仅作为尚未 heartbeat 的节点占位/提示保留；不再作为 server 主动 poll 的目标。
agents = []

[redis]
# server↔agent 通信总线（命令/事件/日志三条 stream）；非 dopilot 数据库、不持久化业务真相
url = "redis://:change-me-redis-pass@redis:6379/0"
stream_maxlen_commands = 100000
stream_maxlen_events = 100000
stream_maxlen_logs = 1000000
log_retention_seconds = 86400               # log stream 时间窗口；超窗 + server 长停 → 日志 partial（RPO≠0）
consumer_name = "server-1"
require_aof = true                          # 生产启用 AOF

[agents]
heartbeat_timeout_seconds = 30              # now - last_seen_at 超此值判 agent 不健康，不再投递新任务
stalled_attempt_seconds = 300              # heartbeat 正常但 attempt 长时间无状态事件 → operator-visible stalled 告警
lost_after_stalled_seconds = 900           # event_stall 持续超此值 → 对账 loop 转 lost（同时投 stop intent=reclaim）
agent_token = ""  # 唯一 server↔agent 机器令牌（阶段 2.2.3，认证两个方向）；compose 经 DOPILOT_AGENT_TOKEN 注入，与 agent 同值

[scheduler]
enabled = true
timezone = "Asia/Shanghai"

[logs]
# 日志正文落本地文件卷 /server-data/logs/YYYY/MM/{execution_id}/{attempt_id}.{stream}.log；PG 只存 execution_log_files 索引
root_dir = "/server-data/logs"
background_drain_interval_seconds = 30
realtime_drain_interval_seconds = 1
status_poll_interval_seconds = 5
max_tail_bytes_per_pull = 262144            # 历史命名；现在用于读取 server 本地日志文件的分块大小，不再向 agent tail/pull
eof_stable_seconds = 3
final_drain_hard_timeout_seconds = 30
log_drain_timeout_seconds = 30              # terminal 事件后 bounded drain 窗口；超时即定稿 complete/partial
unreachable_lost_seconds = 120
retention_days = 30
first_screen_max_lines = 2000
first_screen_max_bytes = 1048576

[i18n]
locale = "zh"
timezone = "Asia/Shanghai"
```

> ⚠️ 重构后 server 不再用静态 `[nodes].agents` 地址主动 poll/connect agent；该列表仅作为尚未 heartbeat 的节点占位/提示保留。节点健康由 agent 主动 heartbeat 注册/续期（`nodes.last_seen_at`）与 Redis 可达性聚合而来，调度按 `[agents].heartbeat_timeout_seconds` 过滤健康节点。

agent 侧配置（节选；agent 经 Redis 主动消费命令 + 推事件/日志 + 主动 POST heartbeat，仍不直连 PostgreSQL）：

```toml
# configs/agent.example.toml（节选）
[redis]
url = "redis://:change-me-redis-pass@redis:6379/0"   # 消费 dopilot:agent:{agent_id}:commands + 推事件/日志
command_block_ms = 5000                          # command consumer XREADGROUP 阻塞时长
pending_idle_ms = 30000                          # 认领超时 pending command 的空闲阈值
event_outbox_dir = "/agent-data/outbox"          # 状态事件/日志 outbox（at-least-once 重放）

[agent]
agent_id = "agent-01"                            # 稳定标识；command stream 路由 / heartbeat 携带
server_url = "http://server:5000"                # 主动 POST heartbeat 的目标
heartbeat_interval_seconds = 10                  # 周期 POST /api/v1/agents/{agent_id}/heartbeat
# 阶段 2.2.3：唯一机器令牌，同时认证 server↔agent 两个方向；与 server [agents].agent_token 同值。
# compose 经 DOPILOT_AGENT_TOKEN 注入；agent 绝不接收 DOPILOT_ADMIN_API_TOKEN。
agent_token = ""
```


### 2.5.b 拆分部署：server-only / agent-only 与自动生成机器令牌（阶段 2.2.4）

阶段 2.2.4 在不改变阶段 2.2.3 双令牌模型的前提下，降低 **server 先行部署** 的摩擦：

- **三种 compose 文件**（均在 `deploy/docker/`）：
  - `docker-compose.yml`：**一体栈**（db + redis + migrate + server + 三个 agent）。因为 server 与 agent 同时启动，仍用显式共享 `${DOPILOT_AGENT_TOKEN:-change-me-agent-token}` 注入到 server 与每个 agent（不能靠生成，否则 agent 拿不到同值）。
  - `docker-compose.server.yml`：**server-only 栈**（db + redis + migrate + server，无 agent 服务）。`DOPILOT_AGENT_TOKEN` **可省略**：省略时 server 在首次启动时**生成并持久化**机器令牌到数据卷 `/server-data/secrets/agent-token`，重启复用。Redis 端口对外发布（`6379`）供远端 agent 接入。
  - `docker-compose.agent.yml`：**agent-only 接入栈**（仅 agent，无 db/redis/migrate/server）。**必须**由运维提供 `DOPILOT_AGENT_TOKEN`（无开发回退）与 Redis 接入信息（`DOPILOT_REDIS_URL`，或 `REDIS_PASSWORD` + `REDIS_HOST` 现场拼装）；**绝不**注入 `DOPILOT_ADMIN_API_TOKEN`。

- **server 自动生成机器令牌**（仅 server 端，agent 永不生成）：
  - 新增 `[server].data_dir`（默认 `/server-data`，env `DOPILOT_SERVER_DATA_DIR`）作为 server 私有数据根——**令牌持久化锚点**，刻意与 `logs.root_dir` / `artifacts.root_dir` 分离。
  - 解析优先级：**配置非空 `agent_token` 优先**（不读写生成文件）→ 否则读已持久化的 `<data_dir>/secrets/agent-token` → 否则 `secrets.token_urlsafe(32)` 生成、原子写、`0600`。
  - 机器认证语义更新：不再是严格 "config-present-or-off"，而是 **「配置了 `agent_token`，或 server 在运行时边界生成/读出持久化令牌」即 ON**。生成是运行时步骤（`dopilot_server.agent_token`），**`load_settings()` 保持无副作用**（不建文件、不生成令牌）。

- **取令牌**（server-only 部署后，配置 agent 用）：
  ```bash
  docker compose -f docker-compose.server.yml exec server dopilot-server agent-token print           # DOPILOT_AGENT_TOKEN=<token> + 提示
  docker compose -f docker-compose.server.yml exec server dopilot-server agent-token print --quiet   # 仅打印裸令牌
  ```
  该 CLI 用与 `run()` 相同的默认配置路径加载 settings，**不需要 DB/Redis/ASGI 启动**，读或生成持久化令牌后打印。把打印出的值设为每个 agent 的 `DOPILOT_AGENT_TOKEN` 即可接入。

- **Token 认证不是传输加密**：一体栈在单 Docker 网络内自洽；拆分部署下 agent→server 的 Redis 与 heartbeat 端口跨主机，加密传输仍需 TLS/VPN/私有网络。

> 实现要点：`create_app(settings)` 会把传入的 settings 注入 `Depends(get_settings)` 依赖路径，确保**出站 `AgentClient`** 与**入站 heartbeat 鉴权**看到同一个（已写入生成令牌的）settings 对象，避免「egg 部署用生成令牌、heartbeat 仍认为机器认证关闭」的错配。

### 2.6 第一版运行参数校对清单

第一版运行参数控制在最小闭环：引入 **Redis 作单实例 server↔agent 通信总线**（命令/事件/日志三条 stream + heartbeat），但**不引入 Redis 做多副本 HA/fan-out/选主**；不引入 NATS/K8s/mTLS/docker.sock，也不做多 server 副本。

| 容器 | 必要参数 | 说明 |
| --- | --- | --- |
| `server` | 角色默认配置路径 `/app/configs/server.toml`（烤进 `dopilot-server` 入口） | compose 不需要配置路径环境变量；常规部署通过 `DOPILOT_*` 覆盖，进阶部署可把自有 toml 挂载到该默认路径；不使用 cwd 魔法。 |
| `server` | `DOPILOT_ADMIN_PASSWORD` / `DOPILOT_ADMIN_API_TOKEN` / `DOPILOT_AGENT_TOKEN` | Web 管理员密码 + 静态 admin API token（可直接作 Bearer 认证 admin，非空须 >= 16 字符）+ 唯一 server↔agent 机器令牌（非空须 >= 16 字符）。`DOPILOT_ADMIN_API_TOKEN` 仅管理员、仅 server 端；`DOPILOT_AGENT_TOKEN` 注入 server 与每个 agent。登录/SSE 签名密钥 `token_secret` 仅 TOML、无 env、已烤进镜像。 |
| `server` | `DOPILOT_DATABASE_URL=postgresql+psycopg://...` | 指向 PostgreSQL；可覆盖 toml `[database].url`。 |
| `server` | `5000:5000` | API/SSE 入口，并**同源托管** Web 静态产物（阶段 2.1：Next.js 静态导出 `/app/web`，无独立 Web 容器）；外层用户托管层（可选反代）也通过该地址访问 `/api/v1`。 |
| `server` | 内置 `/app/configs/server.toml`（烤进镜像，源自 `configs/server.docker.toml`） | compose 网络配置；默认无需挂载，要定制时把自有 toml 只读挂到该路径。 |
| `server` | `dopilot-server-data:/server-data` | **重要持久化卷**：日志正文 `/server-data/logs`（PG 只存索引/offset）+ 上传中转/导出物。必须挂卷并纳入备份。 |
| `server` | `DOPILOT_REDIS_URL=redis://:...@redis:6379/0` | 接通信总线：写 command stream、消费 agent-events / logs stream。 |
| `server` | `init: true`（建议） | 更好处理信号转发与子进程回收。 |
| `db` | `POSTGRES_DB/USER/PASSWORD` | 第一版 compose 内置 PostgreSQL；生产密码走 `.env` 或 secret。 |
| `db` | `dopilot-db:/var/lib/postgresql/data` | PostgreSQL 核心数据卷（业务表 + `execution_log_files` 索引 + APScheduler jobstore；**不含日志正文**）。 |
| `redis` | `--requirepass ...` + `--appendonly yes` | server↔agent 通信总线；启用 AUTH + AOF。**非 dopilot 数据库、不持久化业务真相**。 |
| `redis` | `dopilot-redis:/data` | AOF 数据卷；瞬时传输介质，丢失只影响在途消息（日志 RPO≠0 已接受）。 |
| `scrapy-agent-1/2/3` | `DOPILOT_REDIS_URL=redis://:...@redis:6379/0` | 消费 `dopilot:agent:{agent_id}:commands` + 推 agent-events / logs。 |
| `scrapy-agent-1/2/3` | 内置 `/app/configs/agent.toml`（烤进镜像） | 默认无需挂载；`[agent].server_url = "http://server:5000"` 是主动 POST heartbeat 的目标。要定制时把自有 toml 挂到该路径。 |
| `scrapy-agent-1/2/3` | `init: true` | agent 作 PID 1，收割 scrapyd 子进程；本机 scrapyd 内部端口（如 6801）仅本机可见，不再对外暴露 server→agent 调度端口（仅 `scrapy-agent-1` 发布 6800 供 smoke/调试）。 |
| `scrapy-agent-1/2/3` | `dopilot-agent{1,2,3}-data:/agent-data` | 每个 agent 各自的数据卷：scrapyd `job.log` + `/agent-data/state/executions/{attempt_id}.json` 映射 + Redis event/log outbox；server drain 完成前不得删 `job.log`。 |

三个对称 agent（`scrapy-agent-1/2/3`，阶段 1 即落地）共用镜像内置的 `/app/configs/agent.toml`（由 `dopilot-agent` 入口的角色默认路径读取，compose 不再注入 `DOPILOT_CONFIG`），仅 `AGENT_ID` 与数据卷不同；compose 为每个 agent 注入稳定 `AGENT_ID`、`AGENT_WORKDIR`、`DOPILOT_REDIS_URL`、`DOPILOT_AGENT_TOKEN`（唯一机器令牌）。heartbeat 目标从 `[agent].server_url` 读取，当前提交未通过 `DOPILOT_SERVER_URL` 环境变量注入；agent 绝不接收 `DOPILOT_ADMIN_API_TOKEN`。

> 重构后 server↔agent 经 **Redis 通信总线**：agent 主动消费命令、主动 `XADD` 推状态/日志，并**主动 POST heartbeat**。agent 启动必须携带稳定 `agent_id`（环境变量 `AGENT_ID` 或 `configs/agent.toml`），server 据 heartbeat 写入 `nodes.last_seen_at` 并判健康（不再轮询 `/health`）。机器鉴权（阶段 2.2.3）用**单一** `agent_token` 同时认证 server↔agent 两个方向（config-present-or-off：非空才校验），**不复用** Web 管理员账号密码、也绝不下发 `admin_api_token` 给 agent；agent 仍不直连 PostgreSQL。

### 2.7 egg 上传部署链路（第一版仅支持已构建 egg）

第一版**只支持上传已构建 egg**，不做本地/源码/Git/CI 构建。部署链路：

```
用户上传 egg → server（/api/v1 接收）→ 转发 agent（egg 部署仍走 HTTP /addversion.json 转发，不经 Redis command stream；refactor/00 命令类型仅 run/stop/cleanup_logs）→ agent 调本机 scrapyd /addversion.json
```

> server→agent 已无 HTTP 主路径，部署投递与 run/stop/cleanup_logs 一样经 `dopilot:agent:{agent_id}:commands` 下发，命令类型细化待 `01-gap-executors.md` 与 `docs/refactor/00-redis-streams-agent-communication.md` 对齐。server 与 agent 均不在镜像内构建 egg；scrapyd 仅由 agent 子进程在容器内拉起（内部端口如 6801）。

### 2.8 可选反代（SSE 必须关闭缓冲）

dopilot 第一版不内置 nginx，反向代理是用户的可选部署层。若用户在外层接反向代理（nginx 等）统一域名或 TLS，server→web 的 SSE 路径必须关闭缓冲，否则事件被缓冲、日志窗口看不到实时增量：

```nginx
location /api/v1/ {
    proxy_pass http://server:5000;
    proxy_http_version 1.1;
    proxy_buffering off;          # SSE 必须关闭缓冲
    proxy_read_timeout 1h;        # SSE 长连接（连接最长寿命如 30min）
}
```

FastAPI 侧的 SSE 响应须带 `X-Accel-Buffering: no` + `Cache-Control: no-cache`（双保险：即便经过未显式关闭 buffering 的代理也不被缓冲）。

---

## 3. 【关键坑】启动期清目录 与 持久化卷的冲突

这是 Docker 化最容易踩的坑，单独展开。

### 3.1 冲突的根源

```python
# vars.py:59-66
for path in [DATA_PATH, DATABASE_PATH, DEMO_PROJECTS_PATH, DEPLOY_PATH,
             HISTORY_LOG, PARSE_PATH, SCHEDULE_PATH, STATS_PATH]:
    if not os.path.isdir(path):
        os.mkdir(path)
    elif path in [PARSE_PATH, DEPLOY_PATH, SCHEDULE_PATH]:   # ← 仅这三个会被清
        for file in glob.glob(os.path.join(path, '*.*')):
            if not os.path.split(file)[-1] in ['ScrapydWeb_demo.log']:
                os.remove(file)
```

**事实**：`vars.py` 是模块级代码，`import scrapydweb` 时就执行 —— 即**每次进程/容器启动都跑一遍**。它对 `PARSE_PATH`、`DEPLOY_PATH`、`SCHEDULE_PATH` 三个目录执行 `os.remove`，删掉所有带扩展名（`*.*`）的文件，只放过 `ScrapydWeb_demo.log`。

这与"把整个 `DATA_PATH` 挂成持久化卷、期望全部内容跨重启保留"的直觉**直接冲突**：把卷挂在 `/data` 上没问题，但这三个子目录的内容**每次重启都会被应用自己删掉**，不是卷的问题，是代码行为。

### 3.2 逐目录裁决：哪些可清、哪些必须随卷持久化

| 目录 | 启动清空？ | 内容性质 | 是否必须持久化 | 结论 |
|------|:---------:|----------|:--------------:|------|
| `database/` | **否** | reference 的 4 个 SQLite + APScheduler jobstore | reference 必须 | 仅说明 scrapydweb 行为；dopilot 核心数据进入 PostgreSQL |
| `history_log/` | 否 | run_spider / timer_tasks 历史日志（`vars.py:123-138` 启动时若不存在才重建） | 建议持久 | 审计/排错价值；挂卷可保留 |
| `stats/` | 否 | LogParser 统计 json 备份（`BACKUP_STATS_JSON_FILE=True`，`default_settings.py:123`） | 建议持久 | 删了原 logfile 后仍能看 stats，挂卷可保留 |
| `demo_projects/` | 否 | 打包自带演示项目 | 否 | 镜像内置即可，无需卷 |
| `deploy/` | **是** | egg / 压缩包**构建中转**（`deploy.py:313` 等：打好 egg → 上传 Scrapyd → 不再读取） | 否（设计上即临时） | **不要**指望它持久；天然可清 |
| `parse/` | **是** | 用户上传的待解析日志（`parse.py:49`），解析后即用即弃 | 否 | 临时缓存，天然可清 |
| `schedule/` | **是** | Run Spider 表单 `*.pickle`（`schedule.py:277`），check→run 单次流程内的中转 | 否 | 临时缓存，天然可清 |

**关键判断**：被清空的三个目录（`deploy/parse/schedule`）在设计上就是**进程内瞬态中转**，不是持久状态：
- `deploy/`：egg 打完即上传到执行端（Scrapyd/agent），本地副本无长期价值。
- `parse/`：用户上传日志 → 解析展示 → 丢弃。
- `schedule/`：表单 pickle 是 "check" 预览与 "run" 提交之间的临时载体，单请求生命周期。

对 scrapydweb reference 而言，真正需要跨重启活下来的是 **`database/`**（含 APScheduler jobstore `apscheduler.db`、定时任务定义/历史 `timer_tasks.db`、Jobs 快照 `jobs.db`、metadata `metadata.db`），其次是审计类的 `history_log/`、`stats/`。对 dopilot 而言，核心状态统一进入 PostgreSQL，容器卷只承载非数据库文件。

### 3.3 推荐的卷布局

```
卷 dopilot-data  挂到  /data    （= DATA_PATH）
└── database/        ← 必须持久（已天然保留）
└── history_log/     ← 建议持久（已天然保留）
└── stats/           ← 建议持久（已天然保留）
└── deploy/  parse/  schedule/   ← 每次启动被清；落在卷上无害，但别依赖其内容
└── demo_projects/   ← 镜像自带，可不挂
```

scrapydweb reference 整卷挂 `/data` 即可；dopilot 不依赖 `/data/database`，核心数据统一由 PostgreSQL 持久化。

> **dopilot 实现建议**：dopilot 在自有 `config`/path 层（`apps/server/dopilot_server/config/`）全新设计路径布局时，将瞬态中转目录（部署 egg / 解析 / 调度缓存）规划到 tmpfs（`/tmp/dopilot` 或容器可写层），持久数据（database / 历史）落 `/data`，从而把"瞬态"与"持久"物理隔离，语义更清晰，也避免误把临时文件当数据备份。这是 dopilot 新代码的设计选择——**不是去改 scrapydweb 的 `vars.py`**；scrapydweb 的"启动清目录"行为（见 §3.1）仅作为"移植该缓存目录语义时需要知道的约束"保留引用。

### 3.4 多副本下的"清目录"次生风险

如果 server 横向扩容到多副本且共享同一个 `/data`（NFS/RWX 卷），**每个副本启动都会跑 `vars.py:59-66` 去删 `deploy/parse/schedule`** —— 副本 A 正在用的 pickle/egg 可能被副本 B 启动时删掉，引发竞态。结论：**server 不应在共享卷上多副本运行**（另见 §4）。

### 3.5 PostgreSQL 持久化策略

`default_settings.py:387` 支持 `DATABASE_URL`（环境变量可注入），`setup_database.py:34-37` 按 DB scheme 分派，由 `setup_mysql`(:80)/`setup_postgresql`(:120) 实际执行 `CREATE DATABASE`，创建 4 个独立库（库名常量 `setup_database.py:7-11`：`scrapydweb_apscheduler/timertasks/metadata/jobs`）。

```bash
DATABASE_URL=postgresql://dopilot:dopilot@db:5432
```

dopilot 正式版本中，业务表、scheduler jobstore（APScheduler jobstore 落 PostgreSQL）、执行记录、以及**日志索引表 `execution_log_files`（offset/状态，不含正文）**都进入 PostgreSQL；**日志正文不落 PG，落 server 本地文件卷 `/server-data/logs`**（见 §1.4）。SQLite 仅作为 scrapydweb reference 行为说明，不作为 dopilot 运行模式；删库重建仅是 scrapydweb reference 行为，**不作为 dopilot 正式迁移策略**（dopilot 用裸 Alembic）。

> **备份必须同时覆盖两处**：PostgreSQL（业务/索引/jobstore）+ `/server-data/logs` 卷（日志正文）。只备份其一会丢失日志正文或丢失索引/调度。**Redis 不是备份目标**：它是消息总线/瞬时传输，非 dopilot 数据库、不持久化业务真相，丢失只影响在途消息（日志 RPO≠0 已接受，详见 `docs/refactor/00-redis-streams-agent-communication.md`）。

---

## 4. 容器重启 / 多副本 对 进程内 APScheduler 与 三个后台子进程 的影响

### 4.1 进程内 APScheduler（BackgroundScheduler）

事实链：
- `scheduler.py:45` `scheduler = BackgroundScheduler(...)` —— **进程内线程**，不是独立服务。
- `scheduler.py:90` `scheduler.start(paused=True)` —— import 即启动（暂停态）。
- `check_app_config.py:288-289` 按 `metadata.scheduler_state` 决定是否 `resume()`。
- jobstore `default` = `SQLAlchemyJobStore(apscheduler.db)`（`scheduler.py:32`），**持久**；而 `jobs_snapshot` / `delete_task_result` 两个内务任务用 `jobstore='memory'`（`check_app_config.py:309,332`），**非持久**。

| 场景 | 行为 | 说明 |
|------|------|------|
| 单容器重启 | 定时任务从 `apscheduler.db` 恢复；内务任务（memory）重新 add | 只要 `database/` 持久化，定时任务不丢；`misfire_grace_time=60`（`check_app_config.py:309`）决定错过窗口内是否补跑 |
| 重启后调度器状态 | 由 `metadata.scheduler_state` 决定 resume 与否（`check_app_config.py:288`） | 状态本身存 `metadata.db`，持久则保留开/关 |
| **多副本（同一 jobstore）** | **每个副本各跑一个 BackgroundScheduler，都会触发同一批定时任务** → **重复执行** | APScheduler 进程内调度**无分布式锁**，scrapydweb 假设单实例 |

> **结论（v1 硬约束）**：server **固定单容器 + uvicorn workers=1 + 单 APScheduler 实例**，**不支持多副本/多 worker，未来也不做**。单实例约束本身不变——多副本下"每个副本各跑一个 BackgroundScheduler 重复触发"的风险在 v1 通过"单实例"直接规避，而非靠 HA 改造解决。重构后已**引入 Redis 作单实例 server↔agent 通信总线**（命令/事件/日志 stream），但**不引入 Redis 做多副本 HA/fan-out/选主/分布式锁**；server→web SSE fan-out 仍在单进程内存完成（不依赖 Redis pub/sub），同样不引入 NATS/PG LISTEN-NOTIFY 这类多副本分布式 fan-out。scrapydweb 上游的相关行为（`scheduler.py:45,90` 无分布式锁）仅作约束说明。

### 4.2 三个"后台执行单元"

scrapydweb 的后台执行分两类，共 3 个单元：

| 单元 | 类型 | 入口 | 何时启动 | 跟随父进程退出机制 |
|------|------|------|----------|---------------------|
| APScheduler 调度线程 | **进程内线程** | `scheduler.py:45,90` | import 时 | `atexit.register(shutdown_scheduler)`（`scheduler.py:111`） |
| LogParser | **子进程 Popen** | `sub_process.py:53起 init_logparser` | `ENABLE_LOGPARSER=True` 时（`check_app_config.py:485`） | `preexec_fn=prctl(PR_SET_PDEATHSIG, SIGKILL)`（`sub_process.py:72-73`）+ `atexit.kill_child`（`:57`） |
| Poll（监控/告警） | **子进程 Popen** | `sub_process.py:85起 init_poll` | `ENABLE_MONITOR=True` 时（`check_app_config.py:491`） | 同上（`sub_process.py:115-116`、`:89`） |

容器化影响：

1. **PID 跟随依赖 `libc prctl`**：`on_parent_exit` 用 `cdll['libc.so.6'].prctl(PR_SET_PDEATHSIG)`（`sub_process.py:38`）—— **仅 Linux 有效**，要求基础镜像含 `libc.so.6`（`python:3.12-slim` 满足；Alpine 的 musl **不满足**，会落到 `except` 分支用裸 `Popen`，失去父死子亡保护，可能产生孤儿进程）。**建议基础镜像用 glibc 系（slim/debian），不要用 Alpine。**
2. **子进程 pid 写库**：`init_subprocess` 把 pid 写进 `metadata`（`check_app_config.py:489,495`）。容器重启后 pid 会变，旧 pid 残留无害（每次启动覆盖），但跨容器无意义。
3. **PID 1 信号问题**：容器里 `scrapydweb` 若是 PID 1，子进程的 `atexit` 在收到 `docker stop`（SIGTERM）时**不保证执行**（Flask dev server + werkzeug 的退出路径），可能留下未清理子进程。**建议用 `tini`/`--init` 作为 PID 1 转发信号并收割僵尸进程**：

```yaml
    server:
      init: true     # docker-compose 启用 tini，正确转发 SIGTERM、收割子进程
```

4. **角色归属**：LogParser、Poll、APScheduler 都属于 **server** 行为，**不应**进 agent 镜像。LogParser 还依赖 `LOCAL_SCRAPYD_LOGS_DIR`（`sub_process.py:67`）读本机 Scrapyd 日志 —— 在 server/agent 分离架构下，server 容器并没有 agent 的日志盘，所以容器化时建议 **`ENABLE_LOGPARSER=False`**，让日志解析跑在 agent 侧（dopilot 改造点，见 `03-gap-realtime-logs.md`）。

### 4.3 重启行为速查

| 重启什么 | 定时任务 | Jobs 快照 | 子进程 | 前提 |
|----------|:--------:|:---------:|:------:|------|
| server 容器（卷持久） | 自动恢复 | 保留 | 重新拉起 | `database/` 在卷上 |
| server 容器（PostgreSQL 持久） | 不丢 | 不丢 | 重新拉起 | 数据在 PostgreSQL；容器卷只影响非数据库文件 |
| server 多副本 | **重复触发** | 各写各的 | 各自一份 | 不支持，需单副本 |
| agent 容器 | 不涉及 | 不涉及 | 不涉及 | agent 不持调度权 |

---

## 5. 改造清单（可落地动作）

| 优先级 | 动作 | 关联事实 |
|:------:|------|----------|
| P0 | server 配置 `DOPILOT_DATABASE_URL` 指向 PostgreSQL；compose/k8s 提供 PostgreSQL 或外部托管实例 | dopilot 决策 10 |
| P0 | dopilot toml 配置由镜像内 server/agent 角色默认路径读取，compose 常规部署通过 `DOPILOT_*` 覆盖；进阶部署可把自有 toml 只读挂载到默认路径 | （对比 scrapydweb cwd 硬编码加载 `vars.py:29`、`run.py:37,124`，dopilot 不沿用） |
| P0 | server 固定**单容器 + uvicorn workers=1 + 单 APScheduler 实例**（不支持多副本/多 worker，未来也不做）；compose 加 `init: true` | `scheduler.py:45,90`、`sub_process.py:38`；v1 单实例硬约束 |
| P0 | 基础镜像用 glibc 系（slim/debian），禁用 Alpine | `sub_process.py:38` prctl 依赖 `libc.so.6` |
| P0 | `/server-data/logs`（日志正文）作为重要持久化卷挂载；备份**同时**覆盖 PostgreSQL + `/server-data/logs` | v1 正文存储/备份约束 |
| P1 | 容器内 `ENABLE_LOGPARSER=False` / `ENABLE_MONITOR=False`（除非已规划其落点） | `check_app_config.py:485,491`、`sub_process.py:67` |
| P1 | **裸 Alembic** migration（非 Flask-Migrate）纳入 server 启动/发布流程，禁止运行时隐式 `create_all` 代替迁移；APScheduler jobstore 落 PostgreSQL | dopilot 决策 10/数据库 spec |
| P0 | compose 新增 `redis` 服务（AUTH + AOF）作单实例 server↔agent 通信总线；server/agent 配 `DOPILOT_REDIS_URL`，agent 通过 `[agent].server_url` 配置 heartbeat 目标 | refactor §配置/部署 |
| P1 | 第一版落地自有 `dopilot-agent`：子进程拉起本机 scrapyd（scrapyd 内部端口如 6801 仅本机），运行 **Redis command consumer + status/log publisher + heartbeat worker**（主动消费命令、主动 `XADD` 推状态/日志、主动 POST heartbeat，无 WebSocket）；不再对外暴露 server→agent 调度端口；server 据 heartbeat `last_seen_at` 判健康，调度只选健康 agent | dopilot 决策 11/12 |
| P1 | server 侧实现 Redis producer/consumer + reconcile：command outbox/producer/dispatcher 写 command stream；event consumer 消费 `agent-events` 更新 attempt（替代 status poll）；log consumer 消费 `logs` stream 落 `/server-data/logs` + 更新 `execution_log_files`（含 `log_integrity`/gap）→ SSE fan-out；reconcile loop 走 heartbeat/event 对账（lost/stalled），不再访问 agent HTTP | 决策 #11/#12 新文本 |
| P1 | heartbeat API：server 实现 `POST /api/v1/agents/{agent_id}/heartbeat` 写 `nodes.last_seen_at`；机器鉴权用单一 `agent_token`（阶段 2.2.3，认证 server↔agent 两个方向）；删除 server→agent HTTP run/status/tail 主路径与 `AgentTailLogSource` 主路径 | 决策 #12 新文本 |
| P1 | egg 上传部署链路：用户上传已构建 egg → server → 转发 agent（egg 部署仍走 HTTP `/addversion.json`，**不经 Redis command stream**）→ agent 调本机 scrapyd `/addversion.json`；第一版**不做**本地/源码/Git/CI 构建 | v1 egg spec |
| P1 | dopilot 镜像不内置 nginx；若用户自行加反代，SSE 路径必须关闭 buffering；FastAPI SSE 响应加 `X-Accel-Buffering: no` + `Cache-Control: no-cache` | v1 反代 spec |
| P2 | dopilot 缓存目录设计：在自有 `config`/path 层把 deploy/parse/schedule 类瞬态目录指向 tmpfs，与 database 持久目录隔离（dopilot 新代码，非改 scrapydweb） | （清目录语义参考 scrapydweb `vars.py:51-66`） |
| P2 | 生产使用 uvicorn，固定 `workers=1`，并明确 scheduler 单实例策略 | dopilot FastAPI 决策 |

---

## 6. 开放问题

1. **配置路径加载**（已决，非开放问题）：dopilot 用 toml 配置 + 环境变量覆盖；Docker 镜像内置 server/agent 角色默认配置路径，compose 无需配置路径变量，进阶部署可把自有 toml 挂载到默认路径；无 cwd 硬编码约束。对比之下 scrapydweb 基线把文件名硬编码 `scrapydweb_settings_v11.py` 且只从 `os.getcwd()` 找（`vars.py:29`、`run.py:124`），dopilot 不沿用该形态。
2. **单实例约束（已定，非开放问题）**：v1 锁定 server = 单容器 + **uvicorn workers=1** + 单 APScheduler 实例，**不做多副本/多 worker，未来也不做**。不把 scheduler 拆成独立服务、不引入分布式锁/选主或 NATS/PG LISTEN-NOTIFY 多副本 fan-out；**Redis 仅作单实例 server↔agent 通信总线**，不用于多副本 HA/fan-out/选主，server→web SSE fan-out 仍单进程内存完成。
3. **agent 协议范围**（已定方向，已翻案为 Redis）：server↔agent 经 **Redis 通信总线**——agent 主动消费命令（`run`/`stop`/`cleanup_logs`）、主动 `XADD` 推状态/日志、主动 POST heartbeat，**不使用 WebSocket**；server→agent HTTP run/status/tail 主路径已删除。仍需在 `packages/protocol/.../streams.py` 细化 `AgentCommand`/`AgentEvent`/`AgentLogEvent`/`AgentHeartbeatRequest/Response` 与错误码（既有 tail/status schema 标 legacy；详见 `docs/refactor/00-redis-streams-agent-communication.md`、`01-gap-executors.md` / `03-gap-realtime-logs.md`）。
4. **通信鉴权边界**（阶段 2.2.3 收敛为单令牌）：server↔agent 机器认证用**单一** `agent_token` 同时认证两个方向（config-present-or-off：非空才校验）；`admin_api_token` 仅管理员、绝不下发给 agent；Redis 启用 AUTH/ACL；agent 仍不直连 PostgreSQL。Token 认证不是传输加密：跨主机加密需把 Redis/heartbeat 端口置于 TLS/VPN/私有网络之后（v1 定位为内网防误操作，非互联网零信任）。
5. **stream 拆分落地**：scrapy/scrapyd 只产 `stream=log`；脚本阶段 `stdout`/`stderr` 如何在 agent 侧采集并各自维护 offset，待 `03-gap-realtime-logs.md` 细化。
6. **日志回流打通**（已定方向，已翻案为 Redis）：日志由 **agent tail 本地 `job.log` 按字节 offset `XADD dopilot:server:logs`（base64 字节）、server log consumer 消费后落盘**，正文落 server `/server-data/logs`、索引落 PG `execution_log_files`（含 `log_integrity`/gap），web 经 SSE 看；不依赖共享卷。多 agent 各自 publish 到同一 logs stream，server 统一消费聚合。日志 RPO≠0：server 长停或 Redis 裁剪致 partial 是已接受行为、不阻塞业务状态收敛。

---

## 7. 镜像命名、构建与推送（决策 7 / 决策 8）

> 对应 `00-requirements.md` §4 决策 7（镜像发布到 `rabbir/dopilot`）、决策 8（server + agent monorepo）。本节为**改造草案**：当前仓库尚无 Dockerfile/CI，待阶段 0 落地。Dockerfile 落在 `deploy/docker/`，CI workflow 落在 `.github/workflows/`，均非仓库根级。

### 7.1 镜像命名约定

| 角色 | Docker Hub 镜像 | 启动命令 | Dockerfile |
|------|----------------|----------|-----------|
| server（调度中心 + API/SSE + 内置 Web UI） | **`rabbir/dopilot:latest`** | `dopilot-server -b 0.0.0.0 -p 5000` | `deploy/docker/Dockerfile` |
| agent（worker 执行器） | **`rabbir/dopilot:latest`** | `dopilot-agent -b 0.0.0.0 -p 6800` | `deploy/docker/Dockerfile` |
| migrate（一次性迁移） | **`rabbir/dopilot:latest`** | `alembic upgrade head` | `deploy/docker/Dockerfile` |

统一约定：只发布一个应用镜像 `rabbir/dopilot:latest`。镜像内包含 server、agent、protocol、Scrapy/scrapyd 运行时、Alembic 迁移资源，以及构建后的 Web 静态产物（阶段 2.1：Next.js 静态导出 `apps/web/out` → `/app/web`，由 server 同源托管；历史为 Vue SPA）；容器启动时通过 command 选择运行模式。

约定：
- **命名空间区分**：git `origin` = `senjianlu/dopilot`（源码托管），镜像命名空间 = `rabbir`（Docker Hub 账号，对应 `rabbirbot00@gmail.com`）。两者**互不等同**，CI/文档里不要把 `senjianlu` 当镜像前缀。
- 发布 tag：`latest`（滚动）+ 建议附带不可变 tag（`rabbir/dopilot:<git-short-sha>` 或语义版本 `:1.6.0-dopilot.0`），便于回滚。
- 单镜像**同源单仓**（monorepo）：同一次提交产出一个镜像，靠启动命令区分 server / agent / migrate 角色（构建上下文为仓库根）。

### 7.2 monorepo 构建布局（决策 8）

server 与 agent 同仓开发（dopilot 为 greenfield 全新搭建，**不是 scrapydweb 改名而来**），构建上下文统一在仓库根。权威布局（见 `05-dev-setup-and-known-issues.md` §1）：

```text
dopilot/                                  # 仓库根 = Docker 构建上下文(origin: senjianlu/dopilot;镜像命名空间 rabbir)
├── apps/
│   ├── server/                           # 调度中心:API、DB、APScheduler、认证、节点管理、日志聚合
│   │   ├── dopilot_server/
│   │   │   ├── api/v1/                    # FastAPI /api/v1/* JSON + SSE(server→web) + agent heartbeat API;server→agent 经 Redis stream(无 WebSocket)
│   │   │   ├── redis/                      # server↔agent Redis 总线:client/streams/commands/consumers(command outbox/dispatcher/event+log consumer)
│   │   │   ├── auth/  scheduler/  nodes/  logs/  models/  repositories/  services/  config/
│   │   │   ├── executors/                 # 缝① BaseExecutor + EXECUTOR_REGISTRY(run_on_node 改 XADD command;get_status 改消费 agent-events)
│   │   │   │   ├── base.py  scrapyd.py  script.py  docker.py
│   │   │   └── app.py
│   │   ├── migrations/  tests/  pyproject.toml
│   ├── agent/                            # worker 执行节点:经 Redis 主动消费命令 + 推事件/日志 + POST heartbeat,实际跑 Scrapy/Python/Docker
│   │   ├── dopilot_agent/
│   │   │   ├── api/
│   │   │   ├── redis/                     # client/commands/events/logs:command consumer + status/log publisher + event outbox
│   │   │   ├── runners/                   # base.py scrapyd.py script.py docker.py
│   │   │   ├── logs/  workspace/  heartbeat/  config/  main.py
│   │   ├── tests/  pyproject.toml
│   └── web/                              # 前端(greenfield,直连 /api/v1)。阶段 2.1:Next.js 静态导出(output: export + trailingSlash) + shadcn/ui + Recharts + react-i18next + TS,产物 apps/web/out;历史为 Vue3 + Element Plus + Vite SPA
│       ├── (阶段 2.1: app/ 或 src/ 路由 + components/ + 静态导出产物 out/)  public/
│       ├── package.json  next.config.* (历史: vite.config.ts)
├── packages/
│   ├── protocol/                         # server↔agent 共享协议 schema(dopilot_protocol/streams.py: AgentCommand/AgentEvent/AgentLogEvent/AgentHeartbeat*;旧 AgentRunRequest/AgentStatusResponse/Tail* 标 legacy)
│   └── client/                           # 可选:Redis 总线/heartbeat 客户端 SDK
├── deploy/{docker/{Dockerfile.base,Dockerfile,docker-compose.yml},k8s/}
├── configs/{server.example.toml,agent.example.toml}   # dopilot 自有 toml 配置(容器内按角色默认路径读取,不继承 scrapydweb 硬编码 settings)
├── scripts/  docs/
│   # 上游 scrapydweb 仅作外部行为参考，本仓库已移除本地 reference/scrapydweb/ 快照（MIT 开源）
├── README.md  pyproject.toml  pnpm-workspace.yaml  .dockerignore
```

要点：
- server / agent 依赖各自声明在 `apps/server/pyproject.toml` / `apps/agent/pyproject.toml`（含 FastAPI/SQLAlchemy/Alembic/PostgreSQL driver 等依赖；`setuptools<81` 仅用于 reference 环境，见 05 §4.1），**不用根级 `requirements.txt`**。
- 统一 Dockerfile 与 compose 都在 `deploy/docker/`，构建上下文仍为仓库根；`Dockerfile.base` 构建 Python/Web 依赖基础镜像，`Dockerfile` 复用基础镜像并构建 web、server wheel、agent wheel，runtime 通过 command 选择角色。
- `09-package-rename.md` 是 scrapydweb 行为参考与移植注意事项，**不是**对 dopilot 的改名步骤——dopilot 不对 scrapydweb 做改名/git mv。

> ⚠️ `.dockerignore` **保留排除 `reference/`** 作防御项（本仓库已移除该本地快照）；上游 scrapydweb 代码绝不被 dopilot 拉取/内置/import，也绝不进入构建上下文。

### 7.3 本地构建与推送（手动）

默认部署路径**拉取 CI 镜像**，不在本地构建：

```bash
cd deploy/docker
docker compose pull
docker compose up -d
```

要用本地源码构建（而非拉取），叠加 build 覆盖文件 `docker-compose.build.yml`。其 build args 默认指向**公共 CI 依赖基础镜像**（`rabbir/dopilot-py-base:latest`、`rabbir/dopilot-web-base:latest`），无需本地先构建 base 镜像（可用 `DOPILOT_PY_BASE_IMAGE` / `DOPILOT_WEB_BASE_IMAGE` 覆盖）：

```bash
cd deploy/docker
docker compose -f docker-compose.yml -f docker-compose.build.yml build
docker compose -f docker-compose.yml -f docker-compose.build.yml up -d --build
```

手动构建并推送统一应用镜像（构建上下文为仓库根，Dockerfile 在 deploy/docker/）：

```bash
# 在仓库根，先登录 Docker Hub（rabbir 账号）
docker login -u rabbir

docker build \
  --build-arg DOPILOT_PY_BASE_IMAGE=rabbir/dopilot-py-base:latest \
  --build-arg DOPILOT_WEB_BASE_IMAGE=rabbir/dopilot-web-base:latest \
  -f deploy/docker/Dockerfile \
  -t rabbir/dopilot:latest \
  -t rabbir/dopilot:$(git rev-parse --short HEAD) \
  .
docker push rabbir/dopilot:latest
docker push rabbir/dopilot:$(git rev-parse --short HEAD)

# 多架构（可选，amd64 + arm64）：
# 先为目标平台构建/推送基础镜像，再用对应 build-arg 构建应用镜像。
```

### 7.4 CI 自动构建推送（GitHub Actions）

源码在 GitHub（`senjianlu/dopilot`），Actions 推送到 Docker Hub `rabbir`。仓库内已提供 `.github/workflows/docker.yml`，触发条件为：

- push 到 `main` / `master`；
- push `v*` tag；
- 手动 `workflow_dispatch`。

CI 不直接依赖 `rabbir/dopilot-*-base:latest` 构建应用镜像，而是先计算依赖输入 hash，再用 hash tag 固定应用镜像所依赖的 base 镜像。

流水线分三段：

1. **计算依赖 hash**
   - 输入：
     - `deploy/docker/Dockerfile.base`
     - `pnpm-lock.yaml`
     - `pnpm-workspace.yaml`
     - `apps/web/package.json`
     - `apps/server/pyproject.toml`
     - `apps/agent/pyproject.toml`
     - `packages/protocol/pyproject.toml`
   - 产出短 hash，例如 `13689cffa291`。

2. **确保 base 镜像存在**
   - 检查：
     - `rabbir/dopilot-py-base:<deps-hash>`
     - `rabbir/dopilot-web-base:<deps-hash>`
   - 若不存在，则分别从 `deploy/docker/Dockerfile.base` 构建并推送：
     - target `py-runtime` -> `rabbir/dopilot-py-base:<deps-hash>`
     - target `web-deps` -> `rabbir/dopilot-web-base:<deps-hash>`
   - 可额外推送 `:latest` 作为人工查看入口，但应用镜像构建必须使用 `<deps-hash>`，不能使用 `:latest`。
   - workflow 对同一个 `<deps-hash>` 设置 `concurrency`，避免多个运行同时写同一个 base tag。
   - 如果 `DOCKER_PLATFORMS` 包含多个平台，存在性检查要求目标 tag 的 manifest 覆盖全部平台，否则会补建。

3. **构建应用镜像**
   - 从 `deploy/docker/Dockerfile` 构建统一镜像。
   - 显式传入 build args：
     - `DOPILOT_PY_BASE_IMAGE=rabbir/dopilot-py-base:<deps-hash>`
     - `DOPILOT_WEB_BASE_IMAGE=rabbir/dopilot-web-base:<deps-hash>`
   - 推送：
     - `rabbir/dopilot:<git-sha-or-release-tag>`
     - `rabbir/dopilot:latest`（仅主干或 release tag 允许覆盖）

关键约束：

- `:<deps-hash>` 是应用镜像的固定依赖输入；`base:latest` 不参与可重复构建。
- base 镜像检查不能只看 workflow 的 `paths` 触发。即使手动触发、tag 触发或 registry 中 base tag 被清理，CI 也必须能按当前 hash 自动补建。
- 如果启用多架构，base 的存在性检查必须确认目标平台完整存在，不能只检查 tag 是否存在。否则曾经只推过 `linux/amd64` 的 hash tag 会导致后续 `linux/arm64` 被静默跳过。
- 并发场景下，多个 workflow 可能同时构建同一个 `<deps-hash>`。当前 workflow 用 base job 的 `concurrency` 串行化同一 hash，避免相同 tag 被不同构建覆盖。
- `:latest` 只能在主干或 release tag 构建中推送；feature branch / PR 不允许覆盖 app 或 base 的 `:latest`。

GitHub 配置：

- Required secret：`DOCKERHUB_TOKEN`。
- Required secret：`DOCKERHUB_USERNAME`。镜像命名空间固定使用该值，例如 `rabbir/dopilot`、`rabbir/dopilot-py-base`、`rabbir/dopilot-web-base`。
- Optional variable：`DOCKER_PLATFORMS`，默认 `linux/amd64`；多架构可设为 `linux/amd64,linux/arm64`，但 arm64 经 QEMU 构建会明显变慢。

后续加固项：

- 当前 `Dockerfile.base` 的 Python 依赖写在 Dockerfile 内，`apps/*/pyproject.toml` 也声明依赖。正式 CI 前需要决定依赖真相来源：要么让 base 依赖从 pyproject/lock 生成，要么增加检查确保 base 覆盖 pyproject 的运行时依赖，避免 `--no-deps` 安装应用 wheel 时漏装新依赖。
- Python 依赖目前仍有范围版本（如 `fastapi>=0.110`、`redis>=5,<9`），相同 `<deps-hash>` 在不同日期可能解析出不同实际版本。若要强可重复构建，应引入 Python lock/constraints，并将其纳入 hash。
- CI 版 base 构建用 `docker/build-push-action` + buildx 推送 `rabbir/dopilot-*-base`（`Dockerfile.base` + `scripts/docker-deps-hash.sh` 计算 deps-hash）。本地源码构建不再单独构建 base 镜像，而是经 `docker-compose.build.yml` 直接复用公共 CI base 镜像（默认 `:latest`）。

落地前置：

- Docker Hub 创建 `rabbir/dopilot`、`rabbir/dopilot-py-base`、`rabbir/dopilot-web-base` 仓库。
- 阶段 0/1 代码已由统一镜像覆盖；后续阶段 2/3 在同一 agent 包内继续扩展 script/docker runner，仍复用 `rabbir/dopilot` 镜像，通过 command 选择角色。
