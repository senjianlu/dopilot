# dopilot —— Docker 化部署与数据持久化

> **【scrapydweb 参考边界】** scrapydweb 仅作**功能层/行为参考**与**测试 oracle**;其代码写法、目录结构、模块划分、命名、依赖、配置形态**一律不得作为 dopilot 的设计依据**。dopilot 为 greenfield、按 `apps/`+`packages/` 自有领域 structure-first 设计(权威布局见 `05-dev-setup-and-known-issues.md` §1),**不对 scrapydweb 做改名/git mv**。详见 `00-requirements.md` 决策表。

> 面向 dopilot 改造工程师。本文区分「现状事实」（基于 scrapydweb 1.6.0 真实代码，引用 `file:line`，仅作行为参考）与「dopilot 实现建议 / 开放问题」。
> dopilot 计划分 **server**（Web 控制台 + 调度中枢）与 **agent**（执行器）两种 Docker 角色部署，单管理员，执行能力分期推进 scrapy egg → python 脚本 → docker 长连接。
> 关联文档：`docs/dopilot/01-gap-executors.md`（执行器）、`docs/dopilot/02-gap-scheduling-nodes-push.md`（调度/节点/推送）、`docs/architecture/01-bootstrap-and-config.md`（启动与配置加载）。

---

## dopilot 目标决策（当前版本）

| 项 | 决策 |
| --- | --- |
| 后端运行时 | `apps/server` 使用 **FastAPI + ASGI**，生产固定 uvicorn 且 `workers=1`。 |
| 数据库 | **PostgreSQL 是唯一数据库**。不再提供 SQLite 作为 dopilot 正式运行路径；reference 的 SQLite 行为仅供理解 scrapydweb。 |
| ORM / migration | SQLAlchemy + **裸 Alembic**（FastAPI 无 Flask app，**不是 Flask-Migrate**）；迁移目录在 `apps/server/migrations/`。 |
| 日志正文存储 | **日志正文写本地文件卷** `/server-data/logs/YYYY/MM/{execution_id}/{attempt_id}.{stream}.log`（`stream=log` 时即 `{attempt_id}.log`）。**PostgreSQL 不存日志正文。** |
| 日志索引存储 | PostgreSQL 表 `execution_log_files`，主键 `(execution_id, attempt_id, stream)`，存 `storage_path / size_bytes / last_pulled_offset / final_offset / status / started_at / finished_at / retained_until`。offset 权威在 server（`last_pulled_offset`）。 |
| server 数据边界 | 只有 server 连接 PostgreSQL；agent 和 web 不直连数据库。 |
| 日志链路 | **server 主动 pull**：server 按 offset 从 agent HTTP tail API 拉增量 → 写 `/server-data/logs` 正文 + 更新 PG 索引/offset → 经 **SSE** 单向推给 web。**第一版完全不使用 WebSocket，agent 不主动推。** |
| 单实例硬约束 | server = 单容器 + **uvicorn workers=1** + 单 APScheduler 实例。**不支持多副本/多 worker，未来也不做** —— 不引入 Redis/NATS/PG LISTEN-NOTIFY fan-out。 |
| 认证 | **config-present-or-off**：`admin_username + admin_password + token_secret` 三者齐全且非空才启用 Web 认证；agent `shared_token` 非空才启用 agent 认证；SSE `stream_token` 仅在 Web 认证开启时需要。内网防误操作策略，非互联网零信任。 |

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

dopilot **不**沿用 scrapydweb 的本机 logparser + SQLite 路线，采用 **server 主动 pull + 正文落文件 + 索引落 PG** 的分离模型：

- **正文存储**：server 本地文件卷 `/server-data/logs/YYYY/MM/{execution_id}/{attempt_id}.{stream}.log`（`stream=log` 时即 `{attempt_id}.log`）。这是**重要持久化卷**，必须挂卷并纳入备份。
- **索引存储**：PostgreSQL 表 `execution_log_files`，**不存日志正文**。

| 列 | 说明 |
|----|------|
| 主键 `(execution_id, attempt_id, stream)` | 一个 attempt 的一条 stream 一行 |
| `storage_path` | 正文文件相对/绝对路径 |
| `size_bytes` / `final_offset` | 当前大小 / 收尾后的最终 offset |
| `last_pulled_offset` | **offset 权威**：server 下次从 agent tail 的起点（agent 无状态、无 ack/去重队列） |
| `status` | `active` / `finalizing` / `complete` / `missing` / `expired` |
| `started_at` / `finished_at` / `retained_until` | 时间与保留期 |
| `created_at` / `updated_at` | 审计 |

- **stream 取值**：schema/API 从第一版即支持 `log` / `stdout` / `stderr` / `system`；scrapy/scrapyd 只产生 `stream=log`（单一 `job.log`，不天然拆 stdout/stderr），脚本阶段才用 `stdout`/`stderr`。
- **拉取频率**（参数见 `[logs]` 配置）：active execution 后台 reconcile loop 每 `30s` 低频 drain；打开 Web 日志窗口该 execution 升到 `1s`，关窗降回低频；结束做 final drain；单次最多 256KB。
- **结束检测**：server 轮询 agent status API（**不依赖 agent 回调**）；`finished/failed/canceled` → `finalizing` → final drain → EOF 稳定（默认 3s）或 hard timeout（30s）→ `complete`。complete 后 server 调 agent cleanup API 删除 `job.log`。
- **SSE 推送**：server → web 单向 SSE。Web 认证开启时用短期 `stream_token`（POST 换取、TTL 60s、只校验建连、连接最长寿命如 30min、`id:<seq>` + `Last-Event-ID` 支持重连补洞）；多窗口看同一 execution 复用一个 pull loop + SSE fan-out。**第一版完全不使用 WebSocket。**

---

## 2. 镜像设计：server 与 agent 两种角色

### 2.1 角色边界（事实 + 建议）

| 能力 | server 镜像 | agent 镜像 | 依据 |
|------|:----------:|:----------:|------|
| FastAPI Web API | ✓ | ✗ | dopilot 决策：`apps/server` 提供 `/api/v1/*` JSON/SSE API |
| 进程内 APScheduler（定时任务） | ✓ | ✗ | `scheduler.py:90`（仅 server 持有调度权） |
| LogParser 子进程 | ✓（可选） | —— | `sub_process.py:53起 init_logparser`；agent 端日志解析见下文建议 |
| Poll/监控子进程 | ✓（可选） | —— | `sub_process.py:85起 init_poll` |
| PostgreSQL | ✓（唯一数据库连接持有者） | ✗ | dopilot 决策：agent/web 不直连数据库 |
| 实际执行爬虫/脚本 | ✗（转发给 agent） | ✓ | dopilot 规划，见 `01-gap-executors.md` |

> **现状事实**：上游 scrapydweb 把"执行"交给远端 **Scrapyd**（`SCRAPYD_SERVERS`），自身没有独立的 agent 进程。dopilot 的 agent 是**新增角色**（分期替换 Scrapyd：scrapy egg → python 脚本 → docker 长连接），下面的 agent Dockerfile 是**改造草案**，尚无对应代码。

### 2.2 镜像分层策略（多阶段构建）

```
server 镜像（【无】前端阶段——SPA 由独立 Web 容器运行，其构建/生产托管不在本文范围）：
  阶段 1  py-deps   : 安装 Python 依赖到 wheelhouse（server 与 agent 各自一份依赖清单）
  阶段 2  runtime   : slim 基础镜像 + 拷贝依赖 + 拷贝 server 代码（【不】拷前端产物）
```

分层要点：
- 依赖层与代码层分离，最大化 layer 缓存（依赖变动少、代码变动多）。
- **server 镜像不含前端**：server 只提供 `/api/v1` + SSE；SPA 由独立 Web 容器运行（决策 #14），其构建与生产托管属用户部署层，本文不规定。
- agent 镜像**不含** FastAPI server/前端/调度依赖，只装执行器运行时（分期：scrapy → 纯 python → docker client）。
- `.dockerignore` 排除 `reference/`、`.venv/`、`docs/`、`**/tests/`、`*.pyc` 等（dopilot 自有数据目录由卷管理，不进镜像）。

### 2.3 server Dockerfile 草案

```dockerfile
# server 镜像【不】构建、也【不】托管 SPA：前端是独立 Web 容器（决策 #14），server 只提供 /api/v1 + SSE。
# 故 server Dockerfile 无前端构建阶段、不 COPY 前端产物。
# ---------- 阶段 1：Python 依赖 ----------
FROM python:3.12-slim AS py-deps
WORKDIR /app
RUN pip install --no-cache-dir wheel
# dopilot server 依赖声明在 apps/server/pyproject.toml；若依赖 packages/protocol，一并放入构建上下文
COPY apps/server/ ./apps/server/
COPY packages/protocol/ ./packages/protocol/
RUN pip wheel --no-cache-dir --wheel-dir=/wheels ./apps/server

# ---------- 阶段 2：运行时 ----------
FROM python:3.12-slim AS runtime
WORKDIR /app
COPY --from=py-deps /wheels /wheels
RUN pip install --no-cache-dir /wheels/*
# 注意：server 镜像【不含】前端产物——SPA 在独立 Web 容器（决策 #14）；server 不托管 SPA、不内置 nginx

# dopilot 配置经 DOPILOT_CONFIG 指向挂载进来的 toml（见 §2.5），无 cwd 硬编码文件名约束；数据库经 DOPILOT_DATABASE_URL 指向 PostgreSQL
ENV DOPILOT_CONFIG=/app/configs/server.toml
ENV DOPILOT_DATABASE_URL=postgresql+psycopg://dopilot:dopilot@db:5432/dopilot
VOLUME ["/server-data"]
EXPOSE 5000

# 入口：dopilot server 自有入口，按 DOPILOT_CONFIG 读取 toml 配置
ENTRYPOINT ["python", "-m", "dopilot_server.app"]  # 或 console_script: dopilot-server
CMD ["-b", "0.0.0.0", "-p", "5000"]
```

> 入口说明：dopilot server 由 `dopilot_server.app`（或等价 console_script）启动，配置路径由 `DOPILOT_CONFIG` 环境变量显式给出，无需为满足 scrapydweb 的 cwd 硬编码加载而设置 `WORKDIR /app/instance` 这类 hack。（对比 scrapydweb 基线 `vars.py:29` / `run.py:37,124` 的 cwd 加载行为，dopilot 不沿用。）

### 2.4 agent Dockerfile 草案（执行器，分期）

agent 不跑 server API，只跑 worker 执行器 + 本机 scrapyd + HTTP tail/status/cleanup 服务端。**agent 完全不主动推日志**（无 WebSocket）：它只被动响应 server 的 HTTP pull。按 dopilot 三期演进，入口命令不同：

```dockerfile
FROM python:3.12-slim AS runtime
WORKDIR /app

# dopilot agent 依赖声明在 apps/agent/pyproject.toml，随分期演进：
#   期 1（scrapy egg）：dopilot-agent + 本机 scrapyd 子进程；agent 调本机 scrapyd API、tail job.log，提供 HTTP tail/status/cleanup
#   期 2（python 脚本）：仅 python 运行时 + stdout/stderr 采集
#   期 3（docker 长连接）：docker SDK，agent 作为 docker host 上的执行代理
COPY apps/agent/ ./apps/agent/
COPY packages/protocol/ ./packages/protocol/
RUN pip install --no-cache-dir ./apps/agent

# 执行链路（期 1）：agent 子进程拉起本机 scrapyd；scrapyd 监听容器内部端口（如 6801，仅本机可见），
# 对外 6800 = agent HTTP API（tail/status/cleanup/health）。基础镜像须为 glibc（slim/debian），不要 Alpine。
ENV AGENT_WORKDIR=/agent-data
VOLUME ["/agent-data"]      # 存 scrapyd job.log + state 映射（见 §2.4 说明），server final drain 完成前不得删 job.log
EXPOSE 6800                 # 仅 agent API 对外；scrapyd 内部端口（6801）不对外暴露

# 入口：dopilot agent 自有入口（init:true/tini 作 PID 1，转发信号、收割 scrapyd 子进程）
ENTRYPOINT ["python", "-m", "dopilot_agent.main"]
```

> **dopilot 实现建议**：agent 与 server 用**不同的依赖声明**（各自的 `pyproject.toml`；agent 不需要 FastAPI server、SQLAlchemy/Alembic、前端或 logparser）。第一版正式架构中：
> - **子进程拓扑**：agent 进程作为 PID 1（`init: true`/tini），以子进程方式拉起**本机 scrapyd**；scrapyd 只监听容器内部端口（如 `6801`，仅本机可见），对外只暴露 **6800 = agent HTTP API**。现成 Scrapyd 镜像只作为本地 spike/连通性验证，不进入第一版目标形态。
> - **agent HTTP API（被动 pull，无 WebSocket）**：
>   - `GET /logs/tail?execution_id&attempt_id&stream&offset` → 返回 `{start_offset, end_offset, content, eof, finished}`，单次最多 256KB（`max_tail_bytes_per_pull=262144`）。
>   - status API：供 server 轮询判定 `finished/failed/canceled`（server **不依赖** agent 回调）。
>   - cleanup API：`POST /executions/{attempt_id}/logs/cleanup`，server 标记 complete 后调用。
>   - `GET /health`：供 server 轮询健康、调度只选健康 agent。
> - **agent 无状态化 offset**：offset 权威在 server（PG `last_pulled_offset`）；agent 无 ack/去重队列。agent 重启后只要 `/agent-data` 的 `job.log` 还在，server 按 offset 继续拉。
> - **state 映射**：agent 在 `/agent-data/state/executions/{attempt_id}.json` 持久化 `execution_id ↔ scrapyd job_id ↔ log_path` 映射，重启后据此恢复。
> - **日志清理**：agent TTL 兜底（completed 3 天 / orphan 7 天）；但在 server final drain 完成前**不得删** `job.log`。

### 2.5.a 开发环境最小容器

本地日常开发不要求把所有角色都容器化。推荐最小模式只启动 PostgreSQL 容器，`server` / `web` / `agent` 在宿主机运行：

- `server`：宿主机运行 FastAPI/uvicorn，连接 `localhost:5432` 的 PostgreSQL。
- `web`：宿主机运行 Vite dev server，通过 proxy 访问 server `/api/v1` 与 SSE。
- `agent`：宿主机运行 dopilot-agent，阶段 1 可在本机拉起 scrapyd 子进程并暴露 `6800` agent API。
- `db`：唯一必须容器化的开发依赖。

下面的 compose 示例是**后端执行闭环**（server + agent + PostgreSQL），用于集成验收、镜像构建验证和部署演练；Web 仍按决策 #14 作为独立容器/托管层，本文只给出接入约束，不把 Web 镜像发布策略绑定进 server/agent compose。

### 2.5 docker-compose 示例

```yaml
version: "3.8"

services:
  server:
    build:
      context: .
      dockerfile: deploy/docker/Dockerfile.server
    image: rabbir/dopilot:latest      # Docker Hub 发布名（见 §7）；本地开发可另打 dopilot-server:dev tag
    init: true                        # tini 作 PID 1，转发 SIGTERM、收割子进程
    ports:
      - "5000:5000"
    environment:
      DOPILOT_CONFIG: /app/configs/server.toml
      DOPILOT_DATABASE_URL: postgresql+psycopg://dopilot:dopilot@db:5432/dopilot
    volumes:
      # 重要持久化卷：日志正文 /server-data/logs（PG 只存索引/offset，不存正文），以及上传中转/导出文件
      - dopilot-server-data:/server-data
      # 只读挂载 dopilot toml 配置；路径由 DOPILOT_CONFIG 指向，无 cwd 硬编码文件名约束
      - ./configs/server.toml:/app/configs/server.toml:ro
    depends_on:
      - db
      - agent
    # 单实例硬约束：server 不做多副本/多 worker（uvicorn workers=1 + 单 APScheduler）；不要加 deploy.replicas
    restart: unless-stopped

  agent:
    build:
      context: .
      dockerfile: deploy/docker/Dockerfile.agent
    image: rabbir/dopilot-agent:latest   # 自有 agent 镜像（阶段 1 起）；见 §7
    # 第一版正式形态使用自有 dopilot-agent（子进程拉起本机 scrapyd）；现成 scrapyd 镜像仅可作为本地 spike，不作为目标架构
    init: true                            # tini 作 PID 1，收割 scrapyd 子进程
    ports:
      - "6800:6800"                       # 仅 agent HTTP API 对外；本机 scrapyd 内部端口（如 6801）不对外暴露
    environment:
      DOPILOT_CONFIG: /app/configs/agent.toml
      AGENT_ID: scrapy-agent-1            # 容器重启不变；server 以此 upsert nodes 表
      AGENT_WORKDIR: /agent-data
    volumes:
      - dopilot-agent-data:/agent-data    # scrapyd job.log + /agent-data/state 映射
      - ./configs/agent.toml:/app/configs/agent.toml:ro
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
# 第一版初始发现地址；地址指向 agent HTTP API（非裸 scrapyd），用容器内服务名而非 127.0.0.1
# server 轮询 agent GET /health，读取稳定 agent_id 后 upsert nodes 表；调度只选健康 agent
agents = ["agent:6800"]

[scheduler]
enabled = true
timezone = "Asia/Shanghai"

[logs]
# 日志正文落本地文件卷 /server-data/logs/YYYY/MM/{execution_id}/{attempt_id}.{stream}.log；PG 只存 execution_log_files 索引
background_drain_interval_seconds = 30      # active execution 后台 reconcile loop 低频 drain
realtime_drain_interval_seconds = 1         # 打开 Web 日志窗口该 execution 升到 1s，关窗降回低频
max_tail_bytes_per_pull = 262144            # 单次 tail 最多 256KB
eof_stable_seconds = 3                      # finalizing 后 EOF 稳定阈值
final_drain_hard_timeout_seconds = 30       # final drain 硬超时
retention_days = 30

[i18n]
locale = "zh"
timezone = "Asia/Shanghai"
```

> ⚠️ dopilot 节点配置（`[nodes].agents`）务必填真实 agent 地址，并在启动时做连通性检查（行为参考 scrapydweb `CHECK_SCRAPYD_SERVERS`，`default_settings.py:55`：未配置/不可达会启动报连接失败）。dopilot 全新实现该检查逻辑，不沿用 scrapydweb 的元组型示例形态（`default_settings.py:48-52` 仅作行为参考）。


### 2.6 第一版运行参数校对清单

第一版运行参数控制在最小闭环，不引入 Redis/NATS/K8s/mTLS/docker.sock，也不做多 server 副本。

| 容器 | 必要参数 | 说明 |
| --- | --- | --- |
| `server` | `DOPILOT_CONFIG=/app/configs/server.toml` | 显式指定配置路径，不使用 cwd 魔法。 |
| `server` | `DOPILOT_DATABASE_URL=postgresql+psycopg://...` | 指向 PostgreSQL；可覆盖 toml `[database].url`。 |
| `server` | `5000:5000` | API/SSE 入口；Web 独立容器或用户托管层通过该地址访问 `/api/v1`。 |
| `server` | `./configs/server.toml:/app/configs/server.toml:ro` | 只读配置挂载。 |
| `server` | `dopilot-server-data:/server-data` | **重要持久化卷**：日志正文 `/server-data/logs`（PG 只存索引/offset）+ 上传中转/导出物。必须挂卷并纳入备份。 |
| `server` | `init: true`（建议） | 更好处理信号转发与子进程回收。 |
| `db` | `POSTGRES_DB/USER/PASSWORD` | 第一版 compose 内置 PostgreSQL；生产密码走 `.env` 或 secret。 |
| `db` | `dopilot-db:/var/lib/postgresql/data` | PostgreSQL 核心数据卷（业务表 + `execution_log_files` 索引 + APScheduler jobstore；**不含日志正文**）。 |
| `agent` | `6800:6800` | dopilot-agent HTTP API（tail/status/cleanup/health）对外端口；本机 scrapyd 内部端口（如 6801）仅本机可见，生产默认不对外暴露。 |
| `agent` | `init: true`（建议） | agent 作 PID 1，收割 scrapyd 子进程。 |
| `agent` | `dopilot-agent-data:/agent-data` | scrapyd `job.log` + `/agent-data/state/executions/{attempt_id}.json` 映射；server final drain 完成前不得删 `job.log`。 |

agent（阶段 1 即落地）使用 `configs/agent.toml`；主 compose 示例已包含 `DOPILOT_CONFIG`、稳定 `AGENT_ID`、`AGENT_WORKDIR` 与只读配置挂载。

> 第一版 server↔agent 为 **server 主动 pull**（HTTP），agent 不需要 `DOPILOT_SERVER_URL` 主动回连（agent 主动 heartbeat 留后续）。agent 启动必须携带稳定 `agent_id`（例如环境变量 `AGENT_ID` 或 `configs/agent.toml`），server 通过 `/health` 读取后 upsert `nodes` 表。agent 认证使用 `configs/agent.toml` 内的 `shared_token`（config-present-or-off：非空才校验），不要复用 Web 管理员账号密码。

### 2.7 egg 上传部署链路（第一版仅支持已构建 egg）

第一版**只支持上传已构建 egg**，不做本地/源码/Git/CI 构建。部署链路：

```
用户上传 egg → server（/api/v1 接收）→ 转发 agent（6800 API）→ agent 调本机 scrapyd /addversion.json
```

server 与 agent 均不在镜像内构建 egg；scrapyd 仅由 agent 子进程在容器内拉起（内部端口如 6801）。

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

> **备份必须同时覆盖两处**：PostgreSQL（业务/索引/jobstore）+ `/server-data/logs` 卷（日志正文）。只备份其一会丢失日志正文或丢失索引/调度。

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

> **结论（v1 硬约束）**：server **固定单容器 + uvicorn workers=1 + 单 APScheduler 实例**，**不支持多副本/多 worker，未来也不做**——因此不引入 Redis/NATS/PG LISTEN-NOTIFY 这类分布式 fan-out 或分布式锁/选主。多副本下"每个副本各跑一个 BackgroundScheduler 重复触发"的风险在 v1 通过"单实例"直接规避，而非靠 HA 改造解决。scrapydweb 上游的相关行为（`scheduler.py:45,90` 无分布式锁）仅作约束说明。

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
| P1 | 第一版落地自有 `dopilot-agent`：子进程拉起本机 scrapyd（scrapyd 内部端口如 6801 仅本机、6800=agent API）、tail `job.log`，提供 **HTTP tail/status/cleanup/health API（被动 pull，无 WebSocket）**；`[nodes].agents = ["agent:6800"]` 指向 agent API 而非裸 scrapyd；server 轮询 health，调度只选健康 agent | dopilot 决策 11/12 |
| P1 | server 侧实现 pull/drain loop：按 PG `last_pulled_offset` 从 agent tail 拉增量 → 写 `/server-data/logs` 正文 + 更新 `execution_log_files` → SSE fan-out；offset 权威在 server，agent 无状态 | 决策 #11 新文本 |
| P1 | egg 上传部署链路：用户上传已构建 egg → server → 转发 agent → agent 调本机 scrapyd `/addversion.json`；第一版**不做**本地/源码/Git/CI 构建 | v1 egg spec |
| P1 | dopilot 镜像不内置 nginx；若用户自行加反代，SSE 路径必须关闭 buffering；FastAPI SSE 响应加 `X-Accel-Buffering: no` + `Cache-Control: no-cache` | v1 反代 spec |
| P2 | dopilot 缓存目录设计：在自有 `config`/path 层把 deploy/parse/schedule 类瞬态目录指向 tmpfs，与 database 持久目录隔离（dopilot 新代码，非改 scrapydweb） | （清目录语义参考 scrapydweb `vars.py:51-66`） |
| P2 | 生产使用 uvicorn，固定 `workers=1`，并明确 scheduler 单实例策略 | dopilot FastAPI 决策 |

---

## 6. 开放问题

1. **配置路径加载**（已决，非开放问题）：dopilot 用 toml 配置 + 环境变量/CLI（`DOPILOT_CONFIG`）显式指定路径，容器内挂载 `configs/server.toml` 即可，无 cwd 硬编码约束。对比之下 scrapydweb 基线把文件名硬编码 `scrapydweb_settings_v11.py` 且只从 `os.getcwd()` 找（`vars.py:29`、`run.py:124`），dopilot 不沿用该形态。
2. **单实例约束（已定，非开放问题）**：v1 锁定 server = 单容器 + **uvicorn workers=1** + 单 APScheduler 实例，**不做多副本/多 worker，未来也不做**。不把 scheduler 拆成独立服务、不引入分布式锁/选主或 Redis/NATS/PG LISTEN-NOTIFY fan-out。
3. **agent 协议范围**（已定方向）：第一版 server↔agent 全部走 **HTTP（server 主动 pull）**——agent 提供 tail/status/cleanup/health，**不使用 WebSocket、agent 不主动推**。仍需在 `packages/protocol` 细化 tail/status/cleanup 的请求/响应 schema 与错误码（见 `01-gap-executors.md` / `03-gap-realtime-logs.md`）。
4. **server↔agent 鉴权**（已定 config-present-or-off）：agent `shared_token` 非空才校验；compose 内网用服务名直连。跨主机部署时是否需在 6800 前再加 TLS/网络隔离仍待评估（v1 定位为内网防误操作，非互联网零信任）。
5. **stream 拆分落地**：scrapy/scrapyd 只产 `stream=log`；脚本阶段 `stdout`/`stderr` 如何在 agent 侧采集并各自维护 offset，待 `03-gap-realtime-logs.md` 细化。
6. **日志拉取打通**（已定方向）：日志由 **server 按 offset 主动 pull agent tail API**，正文落 server `/server-data/logs`、索引落 PG `execution_log_files`，web 经 SSE 看；不依赖共享卷。多 agent 时各 agent 的 `/agent-data` 仅本机持有 `job.log` + state 映射，server 逐 agent 拉取聚合。

---

## 7. 镜像命名、构建与推送（决策 7 / 决策 8）

> 对应 `00-requirements.md` §4 决策 7（镜像发布到 `rabbir/dopilot`）、决策 8（server + agent monorepo）。本节为**改造草案**：当前仓库尚无 Dockerfile/CI，待阶段 0 落地。Dockerfile 落在 `deploy/docker/`，CI workflow 落在 `.github/workflows/`，均非仓库根级。

### 7.1 镜像命名约定

| 角色 | Docker Hub 镜像 | 何时发布 | Dockerfile |
|------|----------------|----------|-----------|
| server（调度中心 + API/SSE，**不托管 SPA**） | **`rabbir/dopilot:latest`** | 阶段 0 起 | `deploy/docker/Dockerfile.server`（§2.3 草案） |
| agent（worker 执行器） | **`rabbir/dopilot-agent:latest`** | 阶段 1 起；内置/管理本机 scrapyd，后续扩展脚本与 Docker runner | `deploy/docker/Dockerfile.agent`（§2.4 草案） |

> Web 为独立容器（决策 #14），其镜像/构建/生产托管属用户部署层，本文不规定。

约定：
- **命名空间区分**：git `origin` = `senjianlu/dopilot`（源码托管），镜像命名空间 = `rabbir`（Docker Hub 账号，对应 `rabbirbot00@gmail.com`）。两者**互不等同**，CI/文档里不要把 `senjianlu` 当镜像前缀。
- 发布 tag：`latest`（滚动）+ 建议附带不可变 tag（`rabbir/dopilot:<git-short-sha>` 或语义版本 `:1.6.0-dopilot.0`），便于回滚。
- 两个镜像**同源单仓**（monorepo）：同一次提交可产出 server / agent 两个镜像，靠不同 Dockerfile 区分（构建上下文都是仓库根）。

### 7.2 monorepo 构建布局（决策 8）

server 与 agent 同仓开发（dopilot 为 greenfield 全新搭建，**不是 scrapydweb 改名而来**），构建上下文统一在仓库根。权威布局（见 `05-dev-setup-and-known-issues.md` §1）：

```text
dopilot/                                  # 仓库根 = Docker 构建上下文(origin: senjianlu/dopilot;镜像命名空间 rabbir)
├── apps/
│   ├── server/                           # 调度中心:API、DB、APScheduler、认证、节点管理、日志聚合
│   │   ├── dopilot_server/
│   │   │   ├── api/v1/                    # FastAPI /api/v1/* JSON + SSE(server→web);server→agent 走 HTTP pull(无 WebSocket)
│   │   │   ├── auth/  scheduler/  nodes/  logs/  models/  repositories/  services/  config/
│   │   │   ├── executors/                 # 缝① BaseExecutor + EXECUTOR_REGISTRY
│   │   │   │   ├── base.py  scrapyd.py  script.py  docker.py
│   │   │   └── app.py
│   │   ├── migrations/  tests/  pyproject.toml
│   ├── agent/                            # worker 执行节点:收 server push,实际跑 Scrapy/Python/Docker
│   │   ├── dopilot_agent/
│   │   │   ├── api/
│   │   │   ├── runners/                   # base.py scrapyd.py script.py docker.py
│   │   │   ├── logs/  workspace/  heartbeat/  config/  main.py
│   │   ├── tests/  pyproject.toml
│   └── web/                              # Vue3 + Element Plus + Vite + TS SPA(greenfield,直连 /api/v1)
│       ├── src/{api,pages,components,layouts,stores,router,i18n}/  public/
│       ├── package.json  vite.config.ts
├── packages/
│   ├── protocol/                         # server↔agent 共享协议 schema(protocol/python/;前端也消费可并列 protocol/typescript/)
│   └── client/                           # 可选:server→agent 客户端 SDK
├── deploy/{docker/{Dockerfile.server,Dockerfile.agent,docker-compose.yml},k8s/}
├── configs/{server.example.toml,agent.example.toml}   # dopilot 自有 toml 配置(经 DOPILOT_CONFIG 加载,不继承 scrapydweb 硬编码 settings)
├── scripts/  docs/
├── reference/scrapydweb/                 # 只读行为参考,绝不进构建上下文/不被 import/不改名
├── README.md  pyproject.toml  pnpm-workspace.yaml  .dockerignore
```

要点：
- server / agent 依赖各自声明在 `apps/server/pyproject.toml` / `apps/agent/pyproject.toml`（含 FastAPI/SQLAlchemy/Alembic/PostgreSQL driver 等依赖；`setuptools<81` 仅用于 reference 环境，见 05 §4.1），**不用根级 `requirements.txt`**。
- 两个 Dockerfile（server/agent）与 compose 都在 `deploy/docker/`，构建上下文仍为仓库根，各 Dockerfile 只 `COPY` 自己需要的 `apps/*` 子目录。
- `09-package-rename.md` 是 scrapydweb 行为参考与移植注意事项，**不是**对 dopilot 的改名步骤——dopilot 不对 scrapydweb 做改名/git mv。

> ⚠️ `.dockerignore` **务必排除 `reference/`**，否则会把整份 scrapydweb 参考代码打进构建上下文，拖慢构建且可能误拷；scrapydweb 参考代码绝不被 dopilot import。

### 7.3 本地构建与推送（手动）

```bash
# 在仓库根，先登录 Docker Hub（rabbir 账号）
docker login -u rabbir

# 构建并推送 server 镜像（构建上下文为仓库根，Dockerfile 在 deploy/docker/）
docker build -f deploy/docker/Dockerfile.server -t rabbir/dopilot:latest -t rabbir/dopilot:$(git rev-parse --short HEAD) .
docker push rabbir/dopilot:latest
docker push rabbir/dopilot:$(git rev-parse --short HEAD)

# 多架构（可选，amd64 + arm64）：
# docker buildx build --platform linux/amd64,linux/arm64 -f deploy/docker/Dockerfile.server \
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
  server:
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
          file: deploy/docker/Dockerfile.server
          push: true
          tags: |
            rabbir/dopilot:latest
            rabbir/dopilot:${{ github.sha }}
          cache-from: type=gha
          cache-to: type=gha,mode=max
```

落地前置：
- 在 Docker Hub 创建 `rabbir/dopilot` 仓库 + access token；在 GitHub 仓库加 `DOCKERHUB_TOKEN` secret。
- 阶段 0 需先搭建 `apps/server` 骨架并移植基线行为（参考 `09-package-rename.md` 的行为参考与移植注意事项，**非改名步骤**）、在 `apps/server/pyproject.toml` 固定依赖（选择 APScheduler>=3.10,<4 并配置 PostgreSQL，见 `05-dev-setup-and-known-issues.md` §4.1）、补 `.dockerignore`，Dockerfile 才能真正 build 通过。
- agent 镜像加一个并列 job（`deploy/docker/Dockerfile.agent` → `rabbir/dopilot-agent:latest`），阶段 1 起启用；阶段 2/3 在同一 agent 内继续扩展 script/docker runner。
