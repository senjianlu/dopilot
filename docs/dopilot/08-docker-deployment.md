# dopilot —— Docker 化部署与数据持久化

> **【scrapydweb 参考边界】** scrapydweb 仅作**功能层/行为参考**与**测试 oracle**;其代码写法、目录结构、模块划分、命名、依赖、配置形态**一律不得作为 dopilot 的设计依据**。dopilot 为 greenfield、按 `apps/`+`packages/` 自有领域 structure-first 设计(权威布局见 `05-dev-setup-and-known-issues.md` §1),**不对 scrapydweb 做改名/git mv**。详见 `00-requirements.md` 决策表。

> 面向 dopilot 改造工程师。本文区分「现状事实」（基于 scrapydweb 1.6.0 真实代码，引用 `file:line`，仅作行为参考）与「dopilot 实现建议 / 开放问题」。
> dopilot 计划分 **server**（Web 控制台 + 调度中枢）与 **agent**（执行器）两种 Docker 角色部署，单管理员，执行能力分期推进 scrapy egg → python 脚本 → docker 长连接。
> 关联文档：`docs/dopilot/01-gap-executors.md`（执行器）、`docs/dopilot/02-gap-scheduling-nodes-push.md`（调度/节点/推送）、`docs/architecture/01-bootstrap-and-config.md`（启动与配置加载）。

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
| 认证 | **config-present-or-off**：`admin_username + admin_password + token_secret` 三者齐全且非空才启用 Web 认证；**agent→server heartbeat 用独立 `server_shared_token`（不复用旧 server→agent token），Redis 启用 AUTH/ACL**；SSE `stream_token` 仅在 Web 认证开启时需要。内网防误操作策略，非互联网零信任。 |

---

## 0. TL;DR（先读这里）

| 关键点 | 现状事实 | 影响 |
|--------|----------|------|
| 启动期清目录 | `vars.py:59-66` 每次进程启动会**清空** `PARSE_PATH` / `DEPLOY_PATH` / `SCHEDULE_PATH` 下的 `*.*` 文件（仅保留 `ScrapydWeb_demo.log`） | 这三个目录**不能**当作持久化卷期望它保留内容；容器重启即清空 |
| SQLite 数据 | scrapydweb reference 默认全部落在 `DATABASE_PATH = DATA_PATH/database/`（`vars.py:51`） | **仅为 reference 行为**；dopilot 正式版本不使用 SQLite，统一使用 PostgreSQL |
| APScheduler jobstore | reference 默认 SQLite jobstore；dopilot 使用 PostgreSQL-backed jobstore 或自有 scheduler 表 | 定时任务必须落 PostgreSQL，并受 Alembic/迁移策略管理 |
| 进程内调度器 | `BackgroundScheduler`，进程内线程，`scheduler.start(paused=True)`（`scheduler.py:45,90`） | 单进程单实例假设；**多副本会重复触发**定时任务 |
| 后台子进程 | LogParser 与 Poll 两个 `Popen` 子进程，靠 `prctl(PR_SET_PDEATHSIG)` 跟随父进程退出（`sub_process.py`） | 与容器「单进程」哲学冲突；属 server 角色，不应进 agent 镜像 |
| 配置文件 | （scrapydweb 行为参考）文件名硬编码 `scrapydweb_settings_v11.py`（`vars.py:29`），从 `os.getcwd()` 加载（`run.py:37,124`） | dopilot **不沿用**此形态：dopilot 以 toml 配置（`configs/server.toml`）经自有加载器读取，容器内通过 `DOPILOT_CONFIG` 环境变量（或挂载 `configs/`）指定路径，无 cwd 硬编码文件名约束 |

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
  阶段 1  web-build : 构建 apps/web Vue SPA
  阶段 2  py-deps   : 构建 protocol/server/agent wheels
  阶段 3  runtime   : slim 基础镜像 + server/agent + scrapy/scrapyd + Alembic + Web dist
```

分层要点：
- 依赖层与代码层分离，最大化 layer 缓存（依赖变动少、代码变动多）。
- **统一应用镜像**：`rabbir/dopilot:latest` 同时包含 server、agent、protocol、Scrapy/scrapyd 运行时、Alembic 迁移资源，以及构建后的 Vue SPA。
- **启动命令选择角色**：server 容器运行 `dopilot-server` 并托管 Web UI；agent 容器运行 `dopilot-agent` 并管理本机 scrapyd；migrate 容器运行 `alembic upgrade head`。
- `.dockerignore` 排除 `reference/`、`.venv/`、`docs/`、`**/tests/`、`*.pyc` 等（dopilot 自有数据目录由卷管理，不进镜像）。

### 2.3 统一 Dockerfile

```dockerfile
# deploy/docker/Dockerfile
# 1. node:22-slim 构建 apps/web -> dist
# 2. python:3.12-slim 构建 protocol/server/agent wheels
# 3. runtime 安装 server + agent + scrapy/scrapyd，复制 Alembic 迁移和 Web dist
#
# 默认 CMD 为 server 模式：
CMD ["dopilot-server", "-b", "0.0.0.0", "-p", "5000"]
```

完整实现以仓库中的 `deploy/docker/Dockerfile` 为准。server 模式会读取 `DOPILOT_WEB_DIST=/app/web`，当存在 `index.html` 时由 FastAPI 直接托管 Vue SPA；`/api/*` 始终保留为 API 路径，不做 SPA fallback。

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

本地日常开发不要求把所有角色都容器化。推荐最小模式只启动 PostgreSQL 容器，`server` / `web` / `agent` 在宿主机运行：

- `server`：宿主机运行 FastAPI/uvicorn，连接 `localhost:5432` 的 PostgreSQL。
- `web`：宿主机运行 Vite dev server，通过 proxy 访问 server `/api/v1` 与 SSE。
- `agent`：宿主机运行 dopilot-agent，阶段 1 可在本机拉起 scrapyd 子进程，经 Redis 消费命令 + 推事件/日志、并向 server POST heartbeat（不再对外暴露 server→agent 调度 API；`-p 6800` 仅用于容器本地 `/health` healthcheck）。
- `db`：唯一必须容器化的开发依赖。

下面的 compose 示例是**本地完整试用闭环**（server+Web UI + agent + PostgreSQL + Redis 通信总线），用于集成验收、镜像构建验证和部署演练。

### 2.5 docker-compose 示例

```yaml
version: "3.8"

services:
  server:
    build:
      context: .
      dockerfile: deploy/docker/Dockerfile
    image: rabbir/dopilot:latest
    command: ["dopilot-server", "-b", "0.0.0.0", "-p", "5000"]
    init: true                        # tini 作 PID 1，转发 SIGTERM、收割子进程
    ports:
      - "5000:5000"
    environment:
      DOPILOT_CONFIG: /app/configs/server.toml
      DOPILOT_DATABASE_URL: postgresql+psycopg://dopilot:dopilot@db:5432/dopilot
      DOPILOT_REDIS_URL: redis://:change-me-redis@redis:6379/0   # server↔agent 通信总线（命令/事件/日志三条 stream）；启用 AUTH
    volumes:
      # 重要持久化卷：日志正文 /server-data/logs（PG 只存索引/offset，不存正文），以及上传中转/导出文件
      - dopilot-server-data:/server-data
      # 只读挂载 dopilot toml 配置；路径由 DOPILOT_CONFIG 指向，无 cwd 硬编码文件名约束
      - ./configs/server.toml:/app/configs/server.toml:ro
    depends_on:
      - db
      - redis
      - agent
    # 单实例硬约束：server 不做多副本/多 worker（uvicorn workers=1 + 单 APScheduler）；不要加 deploy.replicas
    restart: unless-stopped

  agent:
    build:
      context: .
      dockerfile: deploy/docker/Dockerfile
    image: rabbir/dopilot:latest
    command: ["dopilot-agent", "-b", "0.0.0.0", "-p", "6800"]
    # 第一版正式形态使用自有 dopilot-agent（子进程拉起本机 scrapyd）；现成 scrapyd 镜像仅可作为本地 spike，不作为目标架构
    init: true                            # tini 作 PID 1，收割 scrapyd 子进程
    # agent 主动经 Redis 消费命令、推状态/日志，主动 POST heartbeat；不再被动暴露 server→agent 调度端口
    # 本机 scrapyd 内部端口（如 6801）不对外暴露；如需容器本地 healthcheck 可保留 /health，但 server 健康判断走 heartbeat
    environment:
      DOPILOT_CONFIG: /app/configs/agent.toml
      AGENT_ID: scrapy-agent-1            # 容器重启不变；server 以此路由 command stream / upsert nodes 表
      AGENT_WORKDIR: /agent-data
      DOPILOT_REDIS_URL: redis://:change-me-redis@redis:6379/0   # 消费命令 + 推状态/日志
      DOPILOT_SERVER_URL: http://server:5000                     # 主动 POST heartbeat 的目标
    volumes:
      - dopilot-agent-data:/agent-data    # scrapyd job.log + /agent-data/state 映射 + Redis event/log outbox
      - ./configs/agent.toml:/app/configs/agent.toml:ro
    depends_on:
      - redis
    restart: unless-stopped

  redis:
    image: redis:7
    # 单实例 server↔agent 通信总线；启用 AUTH + AOF（降低命令/状态事件在 Redis 重启时丢失概率）
    command: ["redis-server", "--requirepass", "change-me-redis", "--appendonly", "yes"]
    volumes:
      - dopilot-redis:/data
    restart: unless-stopped

  db:
    image: postgres:16
    environment:
      POSTGRES_DB: dopilot
      POSTGRES_USER: dopilot
      POSTGRES_PASSWORD: dopilot
    volumes:
      - dopilot-db:/var/lib/postgresql/data
    restart: unless-stopped

volumes:
  dopilot-server-data:
  dopilot-agent-data:
  dopilot-redis:
  dopilot-db:
```

配置文件里必须把 server 指向 agent 容器名（Docker 网络内可用服务名解析）。dopilot 配置形态为 toml（dopilot 自有领域键名，不照搬 scrapydweb 的 Python settings 形态）：

```toml
# configs/server.toml（节选）
[server]
host = "0.0.0.0"
port = 5000
public_url = "http://localhost:5000"

[database]
url = "postgresql+psycopg://dopilot:dopilot@db:5432/dopilot"

[auth]
# config-present-or-off：三者齐全且非空才启用 Web 认证；任一为空则 Web 认证关闭（内网防误操作策略，非互联网零信任）
admin_username = "admin"
admin_password = "change-me"
token_secret = "change-me"
access_token_ttl_minutes = 720
# SSE 短期建连凭证：仅在 Web 认证开启时需要；POST 换取、TTL 60s、只校验建连、连接最长寿命如 30min
stream_token_ttl_seconds = 60

[agent_auth]
# shared_token 非空才启用 agent 认证；为空则不校验
shared_token = "change-me-agent-token"

[nodes]
# 节点不再靠 server 轮询 /health 发现/判健康；改为 agent 主动 POST heartbeat，server 以 last_seen_at 判健康
# 调度只选 healthy = now - nodes.last_seen_at <= [agents].heartbeat_timeout_seconds 的 agent
# 稳定 agent_id 由 agent heartbeat / command stream 路由携带

[redis]
# server↔agent 通信总线（命令/事件/日志三条 stream）；非 dopilot 数据库、不持久化业务真相
url = "redis://:change-me-redis@redis:6379/0"
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

[scheduler]
enabled = true
timezone = "Asia/Shanghai"

[logs]
# 日志正文落本地文件卷 /server-data/logs/YYYY/MM/{execution_id}/{attempt_id}.{stream}.log；PG 只存 execution_log_files 索引
log_drain_timeout_seconds = 30              # terminal 事件后 bounded drain 窗口；超时即定稿 complete/partial
retention_days = 30

[i18n]
locale = "zh"
timezone = "Asia/Shanghai"
```

> ⚠️ 重构后 server 不再用静态 `[nodes].agents` 地址主动连 agent；节点由 agent 主动 heartbeat 注册/续期（`nodes.last_seen_at`），调度按 `[agents].heartbeat_timeout_seconds` 过滤健康节点。启动连通性的可观测点改为 Redis 可达 + heartbeat 到达（scrapydweb `CHECK_SCRAPYD_SERVERS`，`default_settings.py:55,48-52` 仅作行为参考，dopilot 不沿用其静态地址元组形态）。

agent 侧配置（节选；agent 经 Redis 主动消费命令 + 推事件/日志 + 主动 POST heartbeat，仍不直连 PostgreSQL）：

```toml
# configs/agent.toml（节选）
[redis]
url = "redis://:change-me-redis@redis:6379/0"   # 消费 dopilot:agent:{agent_id}:commands + 推事件/日志
command_block_ms = 5000                          # command consumer XREADGROUP 阻塞时长
pending_idle_ms = 30000                          # 认领超时 pending command 的空闲阈值
event_outbox_dir = "/agent-data/outbox"          # 状态事件/日志 outbox（at-least-once 重放）

[agent]
agent_id = "agent-01"                            # 稳定标识；command stream 路由 / heartbeat 携带
server_url = "http://server:5000"                # 主动 POST heartbeat 的目标
heartbeat_interval_seconds = 10                  # 周期 POST /api/v1/agents/{agent_id}/heartbeat
# agent→server 鉴权独立 token，不复用旧 server→agent token
server_shared_token = "change-me-agent-server-token"
```


### 2.6 第一版运行参数校对清单

第一版运行参数控制在最小闭环：引入 **Redis 作单实例 server↔agent 通信总线**（命令/事件/日志三条 stream + heartbeat），但**不引入 Redis 做多副本 HA/fan-out/选主**；不引入 NATS/K8s/mTLS/docker.sock，也不做多 server 副本。

| 容器 | 必要参数 | 说明 |
| --- | --- | --- |
| `server` | `DOPILOT_CONFIG=/app/configs/server.toml` | 显式指定配置路径，不使用 cwd 魔法。 |
| `server` | `DOPILOT_DATABASE_URL=postgresql+psycopg://...` | 指向 PostgreSQL；可覆盖 toml `[database].url`。 |
| `server` | `5000:5000` | API/SSE 入口；Web 独立容器或用户托管层通过该地址访问 `/api/v1`。 |
| `server` | `./configs/server.toml:/app/configs/server.toml:ro` | 只读配置挂载。 |
| `server` | `dopilot-server-data:/server-data` | **重要持久化卷**：日志正文 `/server-data/logs`（PG 只存索引/offset）+ 上传中转/导出物。必须挂卷并纳入备份。 |
| `server` | `DOPILOT_REDIS_URL=redis://:...@redis:6379/0` | 接通信总线：写 command stream、消费 agent-events / logs stream。 |
| `server` | `init: true`（建议） | 更好处理信号转发与子进程回收。 |
| `db` | `POSTGRES_DB/USER/PASSWORD` | 第一版 compose 内置 PostgreSQL；生产密码走 `.env` 或 secret。 |
| `db` | `dopilot-db:/var/lib/postgresql/data` | PostgreSQL 核心数据卷（业务表 + `execution_log_files` 索引 + APScheduler jobstore；**不含日志正文**）。 |
| `redis` | `--requirepass ...` + `--appendonly yes` | server↔agent 通信总线；启用 AUTH + AOF。**非 dopilot 数据库、不持久化业务真相**。 |
| `redis` | `dopilot-redis:/data` | AOF 数据卷；瞬时传输介质，丢失只影响在途消息（日志 RPO≠0 已接受）。 |
| `agent` | `DOPILOT_REDIS_URL=redis://:...@redis:6379/0` | 消费 `dopilot:agent:{agent_id}:commands` + 推 agent-events / logs。 |
| `agent` | `DOPILOT_SERVER_URL=http://server:5000` | 主动 POST heartbeat 的目标（健康来源）。 |
| `agent` | `init: true`（建议） | agent 作 PID 1，收割 scrapyd 子进程；本机 scrapyd 内部端口（如 6801）仅本机可见，不再对外暴露 server→agent 调度端口。 |
| `agent` | `dopilot-agent-data:/agent-data` | scrapyd `job.log` + `/agent-data/state/executions/{attempt_id}.json` 映射 + Redis event/log outbox；server drain 完成前不得删 `job.log`。 |

agent（阶段 1 即落地）使用 `configs/agent.toml`；主 compose 示例已包含 `DOPILOT_CONFIG`、稳定 `AGENT_ID`、`AGENT_WORKDIR`、`DOPILOT_REDIS_URL`、`DOPILOT_SERVER_URL` 与只读配置挂载。

> 重构后 server↔agent 经 **Redis 通信总线**：agent 主动消费命令、主动 `XADD` 推状态/日志，并**主动 POST heartbeat**（`DOPILOT_SERVER_URL` 现为必需，不再"留后续"）。agent 启动必须携带稳定 `agent_id`（环境变量 `AGENT_ID` 或 `configs/agent.toml`），server 据 heartbeat 写入 `nodes.last_seen_at` 并判健康（不再轮询 `/health`）。agent→server 鉴权用独立 `server_shared_token`（config-present-or-off：非空才校验），**不复用** server→agent 旧 token、也不复用 Web 管理员账号密码；agent 仍不直连 PostgreSQL。

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
| P0 | dopilot toml 配置（`configs/server.toml`）经 `DOPILOT_CONFIG` 环境变量指定路径、只读挂载进容器 | （对比 scrapydweb cwd 硬编码加载 `vars.py:29`、`run.py:37,124`，dopilot 不沿用） |
| P0 | server 固定**单容器 + uvicorn workers=1 + 单 APScheduler 实例**（不支持多副本/多 worker，未来也不做）；compose 加 `init: true` | `scheduler.py:45,90`、`sub_process.py:38`；v1 单实例硬约束 |
| P0 | 基础镜像用 glibc 系（slim/debian），禁用 Alpine | `sub_process.py:38` prctl 依赖 `libc.so.6` |
| P0 | `/server-data/logs`（日志正文）作为重要持久化卷挂载；备份**同时**覆盖 PostgreSQL + `/server-data/logs` | v1 正文存储/备份约束 |
| P1 | 容器内 `ENABLE_LOGPARSER=False` / `ENABLE_MONITOR=False`（除非已规划其落点） | `check_app_config.py:485,491`、`sub_process.py:67` |
| P1 | **裸 Alembic** migration（非 Flask-Migrate）纳入 server 启动/发布流程，禁止运行时隐式 `create_all` 代替迁移；APScheduler jobstore 落 PostgreSQL | dopilot 决策 10/数据库 spec |
| P0 | compose 新增 `redis` 服务（AUTH + AOF）作单实例 server↔agent 通信总线；server/agent 配 `DOPILOT_REDIS_URL`，agent 配 `DOPILOT_SERVER_URL` | refactor §配置/部署 |
| P1 | 第一版落地自有 `dopilot-agent`：子进程拉起本机 scrapyd（scrapyd 内部端口如 6801 仅本机），运行 **Redis command consumer + status/log publisher + heartbeat worker**（主动消费命令、主动 `XADD` 推状态/日志、主动 POST heartbeat，无 WebSocket）；不再对外暴露 server→agent 调度端口；server 据 heartbeat `last_seen_at` 判健康，调度只选健康 agent | dopilot 决策 11/12 |
| P1 | server 侧实现 Redis producer/consumer + reconcile：command outbox/producer/dispatcher 写 command stream；event consumer 消费 `agent-events` 更新 attempt（替代 status poll）；log consumer 消费 `logs` stream 落 `/server-data/logs` + 更新 `execution_log_files`（含 `log_integrity`/gap）→ SSE fan-out；reconcile loop 走 heartbeat/event 对账（lost/stalled），不再访问 agent HTTP | 决策 #11/#12 新文本 |
| P1 | heartbeat API：server 实现 `POST /api/v1/agents/{agent_id}/heartbeat` 写 `nodes.last_seen_at`；agent→server 用独立 `server_shared_token` 鉴权（不复用旧 token）；删除 server→agent HTTP run/status/tail 主路径与 `AgentTailLogSource` 主路径 | 决策 #12 新文本 |
| P1 | egg 上传部署链路：用户上传已构建 egg → server → 转发 agent（egg 部署仍走 HTTP `/addversion.json`，**不经 Redis command stream**）→ agent 调本机 scrapyd `/addversion.json`；第一版**不做**本地/源码/Git/CI 构建 | v1 egg spec |
| P1 | dopilot 镜像不内置 nginx；若用户自行加反代，SSE 路径必须关闭 buffering；FastAPI SSE 响应加 `X-Accel-Buffering: no` + `Cache-Control: no-cache` | v1 反代 spec |
| P2 | dopilot 缓存目录设计：在自有 `config`/path 层把 deploy/parse/schedule 类瞬态目录指向 tmpfs，与 database 持久目录隔离（dopilot 新代码，非改 scrapydweb） | （清目录语义参考 scrapydweb `vars.py:51-66`） |
| P2 | 生产使用 uvicorn，固定 `workers=1`，并明确 scheduler 单实例策略 | dopilot FastAPI 决策 |

---

## 6. 开放问题

1. **配置路径加载**（已决，非开放问题）：dopilot 用 toml 配置 + 环境变量/CLI（`DOPILOT_CONFIG`）显式指定路径，容器内挂载 `configs/server.toml` 即可，无 cwd 硬编码约束。对比之下 scrapydweb 基线把文件名硬编码 `scrapydweb_settings_v11.py` 且只从 `os.getcwd()` 找（`vars.py:29`、`run.py:124`），dopilot 不沿用该形态。
2. **单实例约束（已定，非开放问题）**：v1 锁定 server = 单容器 + **uvicorn workers=1** + 单 APScheduler 实例，**不做多副本/多 worker，未来也不做**。不把 scheduler 拆成独立服务、不引入分布式锁/选主或 NATS/PG LISTEN-NOTIFY 多副本 fan-out；**Redis 仅作单实例 server↔agent 通信总线**，不用于多副本 HA/fan-out/选主，server→web SSE fan-out 仍单进程内存完成。
3. **agent 协议范围**（已定方向，已翻案为 Redis）：server↔agent 经 **Redis 通信总线**——agent 主动消费命令（`run`/`stop`/`cleanup_logs`）、主动 `XADD` 推状态/日志、主动 POST heartbeat，**不使用 WebSocket**；server→agent HTTP run/status/tail 主路径已删除。仍需在 `packages/protocol/.../streams.py` 细化 `AgentCommand`/`AgentEvent`/`AgentLogEvent`/`AgentHeartbeatRequest/Response` 与错误码（既有 tail/status schema 标 legacy；详见 `docs/refactor/00-redis-streams-agent-communication.md`、`01-gap-executors.md` / `03-gap-realtime-logs.md`）。
4. **通信鉴权边界**（已翻案）：agent→server heartbeat 用独立 `server_shared_token`（config-present-or-off：非空才校验），**不复用** server→agent 旧 token；Redis 启用 AUTH/ACL；agent 仍不直连 PostgreSQL。跨主机部署时 Redis/heartbeat 端口前是否再加 TLS/网络隔离仍待评估（v1 定位为内网防误操作，非互联网零信任）。
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

统一约定：只发布一个应用镜像 `rabbir/dopilot:latest`。镜像内包含 server、agent、protocol、Scrapy/scrapyd 运行时、Alembic 迁移资源，以及构建后的 Vue SPA；容器启动时通过 command 选择运行模式。

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
│   └── web/                              # Vue3 + Element Plus + Vite + TS SPA(greenfield,直连 /api/v1)
│       ├── src/{api,pages,components,layouts,stores,router,i18n}/  public/
│       ├── package.json  vite.config.ts
├── packages/
│   ├── protocol/                         # server↔agent 共享协议 schema(dopilot_protocol/streams.py: AgentCommand/AgentEvent/AgentLogEvent/AgentHeartbeat*;旧 AgentRunRequest/AgentStatusResponse/Tail* 标 legacy)
│   └── client/                           # 可选:Redis 总线/heartbeat 客户端 SDK
├── deploy/{docker/{Dockerfile,docker-compose.yml},k8s/}
├── configs/{server.example.toml,agent.example.toml}   # dopilot 自有 toml 配置(经 DOPILOT_CONFIG 加载,不继承 scrapydweb 硬编码 settings)
├── scripts/  docs/
├── reference/scrapydweb/                 # 只读行为参考,绝不进构建上下文/不被 import/不改名
├── README.md  pyproject.toml  pnpm-workspace.yaml  .dockerignore
```

要点：
- server / agent 依赖各自声明在 `apps/server/pyproject.toml` / `apps/agent/pyproject.toml`（含 FastAPI/SQLAlchemy/Alembic/PostgreSQL driver 等依赖；`setuptools<81` 仅用于 reference 环境，见 05 §4.1），**不用根级 `requirements.txt`**。
- 统一 Dockerfile 与 compose 都在 `deploy/docker/`，构建上下文仍为仓库根；Dockerfile 同时构建 web、server wheel、agent wheel，runtime 通过 command 选择角色。
- `09-package-rename.md` 是 scrapydweb 行为参考与移植注意事项，**不是**对 dopilot 的改名步骤——dopilot 不对 scrapydweb 做改名/git mv。

> ⚠️ `.dockerignore` **务必排除 `reference/`**，否则会把整份 scrapydweb 参考代码打进构建上下文，拖慢构建且可能误拷；scrapydweb 参考代码绝不被 dopilot import。

### 7.3 本地构建与推送（手动）

```bash
# 在仓库根，先登录 Docker Hub（rabbir 账号）
docker login -u rabbir

# 构建并推送统一应用镜像（构建上下文为仓库根，Dockerfile 在 deploy/docker/）
docker build -f deploy/docker/Dockerfile -t rabbir/dopilot:latest -t rabbir/dopilot:$(git rev-parse --short HEAD) .
docker push rabbir/dopilot:latest
docker push rabbir/dopilot:$(git rev-parse --short HEAD)

# 多架构（可选，amd64 + arm64）：
# docker buildx build --platform linux/amd64,linux/arm64 -f deploy/docker/Dockerfile \
#   -t rabbir/dopilot:latest --push .
```

### 7.4 CI 自动构建推送（GitHub Actions 草案）

源码在 GitHub（`senjianlu/dopilot`），用 Actions 在 push/tag 时构建并推到 Docker Hub `rabbir`：

```yaml
# .github/workflows/docker.yml（草案）
name: build-and-push
on:
  push:
    branches: [master]
    tags: ['v*']
jobs:
  image:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: docker/setup-buildx-action@v3
      - uses: docker/login-action@v3
        with:
          username: rabbir
          password: ${{ secrets.DOCKERHUB_TOKEN }}   # 在仓库 Secrets 配置 Docker Hub access token
      - uses: docker/build-push-action@v6
        with:
          context: .
          file: deploy/docker/Dockerfile
          push: true
          tags: |
            rabbir/dopilot:latest
            rabbir/dopilot:${{ github.sha }}
          cache-from: type=gha
          cache-to: type=gha,mode=max
```

落地前置：
- 在 Docker Hub 创建 `rabbir/dopilot` 仓库 + access token；在 GitHub 仓库加 `DOCKERHUB_TOKEN` secret。
- 阶段 0/1 代码已由统一镜像覆盖；后续阶段 2/3 在同一 agent 包内继续扩展 script/docker runner，仍复用 `rabbir/dopilot` 镜像，通过 command 选择角色。
