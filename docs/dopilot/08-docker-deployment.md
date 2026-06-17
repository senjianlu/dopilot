# dopilot —— Docker 化部署与数据持久化

> 面向 dopilot 改造工程师。本文区分「现状事实」（基于 scrapydweb 1.6.0 真实代码，引用 `file:line`）与「改造建议 / 开放问题」。
> dopilot 计划分 **server**（Web 控制台 + 调度中枢）与 **agent**（执行器）两种 Docker 角色部署，单管理员，执行能力分期推进 scrapy egg → python 脚本 → docker 长连接。
> 关联文档：`docs/dopilot/01-gap-executors.md`（执行器）、`docs/dopilot/02-gap-scheduling-nodes-push.md`（调度/节点/推送）、`docs/architecture/01-bootstrap-and-config.md`（启动与配置加载）。

---

## 0. TL;DR（先读这里）

| 关键点 | 现状事实 | 影响 |
|--------|----------|------|
| 启动期清目录 | `vars.py:59-66` 每次进程启动会**清空** `PARSE_PATH` / `DEPLOY_PATH` / `SCHEDULE_PATH` 下的 `*.*` 文件（仅保留 `ScrapydWeb_demo.log`） | 这三个目录**不能**当作持久化卷期望它保留内容；容器重启即清空 |
| SQLite 数据 | 全部落在 `DATABASE_PATH = DATA_PATH/database/`（`vars.py:51`），**不在**清空列表里 | 这是**必须持久化**的核心目录（含 APScheduler jobstore、定时任务、Jobs 快照、metadata） |
| APScheduler jobstore | `SQLAlchemyJobStore(url=APSCHEDULER_DATABASE_URI)`，默认 `sqlite:///.../database/apscheduler.db`（`scheduler.py:32`、`setup_database.py:55`） | 定时任务持久化在此 DB；卷丢了 = 定时任务全没 |
| 进程内调度器 | `BackgroundScheduler`，进程内线程，`scheduler.start(paused=True)`（`scheduler.py:45,90`） | 单进程单实例假设；**多副本会重复触发**定时任务 |
| 后台子进程 | LogParser 与 Poll 两个 `Popen` 子进程，靠 `prctl(PR_SET_PDEATHSIG)` 跟随父进程退出（`sub_process.py`） | 与容器「单进程」哲学冲突；属 server 角色，不应进 agent 镜像 |
| 配置文件 | 文件名硬编码 `scrapydweb_settings_v11.py`（`vars.py:29`），从 `os.getcwd()` 加载（`run.py:37,124`） | 需作为只读配置挂载进容器 |

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

---

## 2. 镜像设计：server 与 agent 两种角色

### 2.1 角色边界（事实 + 建议）

| 能力 | server 镜像 | agent 镜像 | 依据 |
|------|:----------:|:----------:|------|
| Flask Web UI / API | ✓ | ✗ | `run.py:119` `app.run(...)` |
| 进程内 APScheduler（定时任务） | ✓ | ✗ | `scheduler.py:90`（仅 server 持有调度权） |
| LogParser 子进程 | ✓（可选） | —— | `sub_process.py:53起 init_logparser`；agent 端日志解析见下文建议 |
| Poll/监控子进程 | ✓（可选） | —— | `sub_process.py:85起 init_poll` |
| SQLite/外部 DB | ✓（拥有数据） | ✗ | `setup_database.py` |
| 实际执行爬虫/脚本 | ✗（转发给 agent） | ✓ | dopilot 规划，见 `01-gap-executors.md` |

> **现状事实**：上游 scrapydweb 把"执行"交给远端 **Scrapyd**（`SCRAPYD_SERVERS`），自身没有独立的 agent 进程。dopilot 的 agent 是**新增角色**（分期替换 Scrapyd：scrapy egg → python 脚本 → docker 长连接），下面的 agent Dockerfile 是**改造草案**，尚无对应代码。

### 2.2 镜像分层策略（多阶段构建）

```
阶段 1  frontend-builder  : node 构建前端产物（仅 server 需要；见 06-frontend-rewrite.md）
阶段 2  py-deps           : 安装 Python 依赖到 wheelhouse / venv（server 与 agent 各自一份依赖清单）
阶段 3  runtime           : slim 基础镜像 + 拷贝依赖 + 拷贝代码（+ server 拷前端产物）
```

分层要点：
- 依赖层与代码层分离，最大化 layer 缓存（依赖变动少、代码变动多）。
- agent 镜像**不含** Flask/前端/调度依赖，只装执行器运行时（分期：scrapy → 纯 python → docker client）。
- `.dockerignore` 排除 `.venv/`、`scrapydweb/data/`、`screenshots/`、`docs/`、`tests/`、`*.pyc`。

### 2.3 server Dockerfile 草案

```dockerfile
# ---------- 阶段 1：前端产物（dopilot 前端重写后启用，见 06-frontend-rewrite.md）----------
FROM node:20-slim AS frontend-builder
WORKDIR /web
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build          # 产物输出到 /web/dist

# ---------- 阶段 2：Python 依赖 ----------
FROM python:3.12-slim AS py-deps
WORKDIR /app
# 已知坑：APScheduler 3.6.0 依赖 pkg_resources，需 setuptools<81（见 05-dev-setup-and-known-issues.md §4.1）
RUN pip install --no-cache-dir "setuptools<81" wheel
COPY requirements.txt ./
RUN pip wheel --no-cache-dir --wheel-dir=/wheels -r requirements.txt

# ---------- 阶段 3：运行时 ----------
FROM python:3.12-slim AS runtime
WORKDIR /app
COPY --from=py-deps /wheels /wheels
RUN pip install --no-cache-dir "setuptools<81" /wheels/*

COPY scrapydweb/ ./scrapydweb/
COPY setup.py ./
RUN pip install --no-cache-dir --no-deps -e .
# server 专属：放入前端构建产物（路径按前端重写后的 static/ 约定调整）
COPY --from=frontend-builder /web/dist ./scrapydweb/static/dist

# 数据目录由 DATA_PATH 环境变量统一指向 /data（务必挂卷，见 §3）
ENV DATA_PATH=/data
# 配置文件由外部挂载到工作目录（vars.py:29 / run.py:37,124）
WORKDIR /app/instance
VOLUME ["/data"]
EXPOSE 5000

# 入口：scrapydweb 会在 cwd 找 scrapydweb_settings_v11.py
ENTRYPOINT ["scrapydweb"]
CMD ["-b", "0.0.0.0", "-p", "5000"]
```

> 入口说明：`WORKDIR /app/instance` 是为了让 `os.getcwd()`（`run.py:37,124`）指向挂载配置文件的位置；也可改用 `--bind/--port` 之外暂无"指定配置路径"的 CLI 参数（**开放问题**，见 §6）。

### 2.4 agent Dockerfile 草案（执行器，分期）

agent 不跑 Flask，只跑一个"执行器"。按 dopilot 三期演进，入口命令不同：

```dockerfile
FROM python:3.12-slim AS runtime
WORKDIR /agent

# 依赖随分期变化：
#   期 1（scrapy egg）：scrapy + scrapyd（或自研 egg runner）
#   期 2（python 脚本）：仅 python 运行时 + 任务拉取客户端
#   期 3（docker 长连接）：docker SDK，agent 作为 docker host 上的执行代理
COPY agent/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY agent/ ./

# 执行产物（egg 解包、临时工作区、日志）建议挂卷，但与 server 的 /data 分离
ENV AGENT_WORKDIR=/agent-data
VOLUME ["/agent-data"]
EXPOSE 6800

# 期 1 示例：以 scrapyd 兼容协议提供执行端点
ENTRYPOINT ["python", "-m", "agent.run"]
```

> **改造建议**：agent 与 server 用**不同的 requirements**（agent 不需要 Flask/flask-sqlalchemy/flask-compress/logparser）。期 1 可直接复用现成 Scrapyd 镜像作为 agent，server 仍按 `SCRAPYD_SERVERS` 连过去，零代码改动即可先跑通"双角色部署"。

### 2.5 docker-compose 示例

```yaml
version: "3.8"

services:
  server:
    build:
      context: .
      dockerfile: Dockerfile.server
    image: dopilot-server:dev
    ports:
      - "5000:5000"
    environment:
      DATA_PATH: /data
      # 可选：用外部 DB 替代 SQLite（见 §3.5 与 default_settings.py:387）
      # DATABASE_URL: postgresql://dopilot:dopilot@db:5432
    volumes:
      # 必须持久化：所有 SQLite / jobstore / 历史日志（见 §3）
      - dopilot-data:/data
      # 只读挂载配置文件到 cwd（/app/instance），文件名硬编码 scrapydweb_settings_v11.py
      - ./deploy/scrapydweb_settings_v11.py:/app/instance/scrapydweb_settings_v11.py:ro
    depends_on:
      - agent
    restart: unless-stopped

  agent:
    build:
      context: .
      dockerfile: Dockerfile.agent
    image: dopilot-agent:dev
    # 期 1 也可直接用：image: vimagick/scrapyd 之类的 Scrapyd 镜像
    ports:
      - "6800:6800"
    volumes:
      - dopilot-agent-data:/agent-data
    restart: unless-stopped

  # 可选：外部数据库（生产建议，规避 SQLite 并发 + 文件锁）
  # db:
  #   image: postgres:16
  #   environment:
  #     POSTGRES_USER: dopilot
  #     POSTGRES_PASSWORD: dopilot
  #   volumes:
  #     - dopilot-db:/var/lib/postgresql/data

volumes:
  dopilot-data:
  dopilot-agent-data:
  # dopilot-db:
```

配置文件里必须把 server 指向 agent 容器名（Docker 网络内可用服务名解析）：

```python
# deploy/scrapydweb_settings_v11.py（节选）
SCRAPYD_SERVERS = ['agent:6800']     # 容器内用服务名，而非 127.0.0.1
DATA_PATH = ''                        # 留空，交给环境变量 DATA_PATH 控制（vars.py:45 优先级）
DATABASE_URL = ''                     # 留空走 SQLite；或注入外部 DB
ENABLE_LOGPARSER = False              # 见 §4 子进程讨论
ENABLE_MONITOR = False
```

> ⚠️ `default_settings.py:48-52` 自带一个无效的元组型 `SCRAPYD_SERVERS` 示例，配置文件里务必覆盖为真实 agent 地址，否则 `CHECK_SCRAPYD_SERVERS`（`default_settings.py:55`）会在启动时报连接失败。

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
| `database/` | **否** | 4 个 SQLite + APScheduler jobstore | **必须** | 核心数据，挂卷即持久；`vars.py:63` 不动它 |
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

真正需要跨重启活下来的是 **`database/`**（含 APScheduler jobstore `apscheduler.db`、定时任务定义/历史 `timer_tasks.db`、Jobs 快照 `jobs.db`、metadata `metadata.db`），其次是审计类的 `history_log/`、`stats/`。这些都**不在**清空名单里，所以挂卷即可安全持久。

### 3.3 推荐的卷布局

```
卷 dopilot-data  挂到  /data    （= DATA_PATH）
└── database/        ← 必须持久（已天然保留）
└── history_log/     ← 建议持久（已天然保留）
└── stats/           ← 建议持久（已天然保留）
└── deploy/  parse/  schedule/   ← 每次启动被清；落在卷上无害，但别依赖其内容
└── demo_projects/   ← 镜像自带，可不挂
```

整卷挂 `/data` 即可：被清的三目录虽在卷里，但每次启动被应用删空属预期行为，不影响核心数据。

> **改造建议**：若想把"瞬态中转目录"与"持久数据"物理隔离，可在 dopilot 改 `vars.py`，让 `DEPLOY_PATH/PARSE_PATH/SCHEDULE_PATH` 指向 `/tmp/dopilot`（tmpfs / 容器可写层），而 `DATABASE_PATH` 留在 `/data`。这样"启动清目录"作用在临时盘上，语义更清晰，也避免误把临时文件当数据备份。

### 3.4 多副本下的"清目录"次生风险

如果 server 横向扩容到多副本且共享同一个 `/data`（NFS/RWX 卷），**每个副本启动都会跑 `vars.py:59-66` 去删 `deploy/parse/schedule`** —— 副本 A 正在用的 pickle/egg 可能被副本 B 启动时删掉，引发竞态。结论：**server 不应在共享卷上多副本运行**（另见 §4）。

### 3.5 用外部数据库彻底绕开 SQLite 持久化

`default_settings.py:387` 支持 `DATABASE_URL`（环境变量可注入），`setup_database.py:34-37` 按 DB scheme 分派，由 `setup_mysql`(:80)/`setup_postgresql`(:120) 实际执行 `CREATE DATABASE`，创建 4 个独立库（库名常量 `setup_database.py:7-11`：`scrapydweb_apscheduler/timertasks/metadata/jobs`）。

```bash
DATABASE_URL=postgresql://dopilot:dopilot@db:5432
```

此时 jobstore 与业务表都进外部 DB，`database/` 目录不再承载关键数据 —— `/data` 卷只剩 `history_log/`、`stats/` 需要考虑。**生产推荐**，同时规避 SQLite 在容器/网络盘上的文件锁问题（`run.py:106` 注释已点名 "database is locked"）。

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

> **结论 / 改造建议**：server **当前必须单副本**。若 dopilot 需要 server 高可用，需把调度从"进程内 APScheduler"抽离为独立调度服务或加分布式锁/选主（详见 `02-gap-scheduling-nodes-push.md`），否则多副本=定时任务多次触发。

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
| server 容器（无卷） | **全丢** | **全丢** | 重新拉起 | jobstore=SQLite 落在容器可写层 |
| server 多副本 | **重复触发** | 各写各的 | 各自一份 | 不支持，需单副本 |
| agent 容器 | 不涉及 | 不涉及 | 不涉及 | agent 不持调度权 |

---

## 5. 改造清单（可落地动作）

| 优先级 | 动作 | 关联事实 |
|:------:|------|----------|
| P0 | server 用环境变量 `DATA_PATH=/data` + 挂卷 `dopilot-data:/data` | `default_settings.py:376`、`vars.py:45` |
| P0 | 配置文件 `scrapydweb_settings_v11.py` 只读挂到 cwd | `vars.py:29`、`run.py:37,124` |
| P0 | server 固定**单副本**；compose 加 `init: true` | `scheduler.py:45,90`、`sub_process.py:38` |
| P0 | 基础镜像用 glibc 系（slim/debian），禁用 Alpine | `sub_process.py:38` prctl 依赖 `libc.so.6` |
| P1 | 容器内 `ENABLE_LOGPARSER=False` / `ENABLE_MONITOR=False`（除非已规划其落点） | `check_app_config.py:485,491`、`sub_process.py:67` |
| P1 | 生产用外部 DB：`DATABASE_URL=postgresql://...` | `default_settings.py:387`、`setup_database.py:34-37,80,120`、`run.py:106` |
| P1 | agent 期 1 直接复用 Scrapyd 镜像，server 经 `SCRAPYD_SERVERS=['agent:6800']` 连接 | `default_settings.py:48` |
| P2 | 改 `vars.py`：把 `DEPLOY/PARSE/SCHEDULE_PATH` 指向 tmpfs，与 `DATABASE_PATH` 物理隔离 | `vars.py:51-66` |
| P2 | dev 用 Flask server（`run.py:119`），生产前替换为 gunicorn/uwsgi（注意与进程内调度/子进程的 worker 模型冲突） | `run.py:117` 注释 |

---

## 6. 开放问题

1. **配置文件路径不可配**：文件名硬编码 `scrapydweb_settings_v11.py` 且只从 `os.getcwd()` 找（`vars.py:29`、`run.py:124`）。容器里只能靠 `WORKDIR` + 挂载到 cwd 来满足，缺少 `--config /path` 之类的 CLI/env 入口。**是否在 dopilot 加配置路径参数？**
2. **生产 WSGI 与进程内组件的矛盾**：`run.py:119` 是 Flask 内置 dev server。换 gunicorn 多 worker 时，每个 worker 会各 import 一次 `scrapydweb` → 各起一个 APScheduler（重复触发，同 §4.1）+ 各跑一次 `vars.py` 清目录（同 §3.4）。**生产 WSGI 方案需要先解决调度单例化。**
3. **agent 协议未定**：期 1（scrapy egg）可借 Scrapyd 协议；期 2（python 脚本）、期 3（docker 长连接）的 server↔agent 协议、鉴权、日志回传尚未设计（见 `01-gap-executors.md` / `03-gap-realtime-logs.md`）。
4. **server↔agent 鉴权**：compose 内网用服务名直连，跨主机部署时 agent（6800）的访问控制（上游靠 `SCRAPYD_SERVERS` 里的 `username:password`，`default_settings.py:39-47`）是否够用？
5. **LogParser 在分离架构下的落点**：它读**本机**日志（`LOCAL_SCRAPYD_LOGS_DIR`），server/agent 分离后日志在 agent 侧，是把 LogParser 移进 agent 镜像，还是改为 agent 主动回传？（`03-gap-realtime-logs.md`）
6. **多 agent 的日志/产物卷**：每个 agent 自己的 `/agent-data` 如何与 server 的展示打通（共享卷 vs API 拉取）？
