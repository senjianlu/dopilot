# 数据模型与持久化

> **【scrapydweb 行为参考·边界】** 本文描述 **scrapydweb 现状行为/语义**，作为 dopilot 的**功能层参考**；其代码写法、目录结构、模块划分**不得作为 dopilot 设计依据**。文中 `file:line` 路径均**相对上游 scrapydweb 1.6.0 / commit `1341cf9`**（如 `scrapydweb/run.py` 即上游 `scrapydweb/run.py`；本仓库不保留本地快照，上游只读、不被拉取/内置/import、不参与构建）。任何"改造切入点/复用/保留"类措辞，一律理解为"dopilot 需在 `apps/` 下**全新复刻其行为语义**"，而非改动或照搬 scrapydweb 文件。详见 `../dopilot/00-requirements.md` 决策表。

> 适用版本：scrapydweb `__version__ = '1.6.0'`（见 `scrapydweb/__version__.py:4`）
> 本文面向 dopilot 工程师，将 scrapydweb 持久化行为作为功能层参考，分两条线索叙述：
> - **现状事实**：scrapydweb 当前代码就是这么写的，标注 `file:line`。
> - **dopilot 复刻建议 / 开放问题**：dopilot 在 `apps/` 下全新复刻其行为语义时需要扩展的方向，明确标记为「建议」「开放问题」，不要与现状混淆。

---

## 0. 一句话总览

scrapydweb 的持久化层 = **Flask-SQLAlchemy（单一 `db` 实例，多 bind 多库）** + **APScheduler 的 `SQLAlchemyJobStore`（第二套、独立持久化）**。
两套持久化互不相通，仅靠「APScheduler job.id == `str(Task.id)`」软关联，没有外键。

```
                          ┌──────────────────────────────────────────────┐
                          │         一个进程，一个全局 db 实例              │
                          │   db = SQLAlchemy(...)   models.py:11          │
                          └───────────────┬──────────────────────────────┘
                                          │ 多 bind 路由 (__bind_key__)
        ┌─────────────────┬───────────────┼───────────────────┬──────────────────┐
        ▼                 ▼               ▼                   ▼                  ▼
  (默认 URI)         bind='metadata'   bind='jobs'      [无 bind，落默认]   [无 bind，落默认]
  timertasks 库      metadata 库       jobs 库           timertasks 库      timertasks 库
  ┌──────────┐       ┌──────────┐      ┌──────────────┐  ┌──────────────┐   ┌──────────────┐
  │  task    │       │ metadata │      │ <每节点一张> │  │ task_result  │   │task_job_result│
  └──────────┘       └──────────┘      │ 127_0_0_1_..│  └──────────────┘   └──────────────┘
                                       └──────────────┘
        ▲ ORM (db.create_all 管理)
        │
        │  软关联：job.id == str(Task.id)，无外键
        ▼
  ┌─────────────────────────────────────────────┐
  │  APScheduler SQLAlchemyJobStore（第二套）     │  scheduler.py:32
  │  apscheduler 库 → apscheduler_jobs 表         │  （序列化的可执行 job）
  │  由 APScheduler 自管，与上面 ORM 无任何外键    │
  └─────────────────────────────────────────────┘
```

合计 **四个逻辑库**（SQLite 下是 4 个 `.db` 文件；MySQL/PostgreSQL 下是 4 个命名数据库），见第 3 节。

---

## 1. 关键文件速查表

| 文件 | 角色 |
|---|---|
| `scrapydweb/models.py` | 全部 ORM 模型：`Metadata`、动态 `Job`（`create_jobs_table` 工厂）、`Task`、`TaskResult`、`TaskJobResult`；全局 `db` 实例在此创建（`models.py:11`） |
| `scrapydweb/utils/setup_database.py` | 决定后端与 URI/BINDS；定义 4 个逻辑库名；MySQL/PostgreSQL 下 `CREATE DATABASE` 建库，SQLite 下建目录与文件 |
| `scrapydweb/vars.py` | 计算 `DATABASE_PATH`（`data/database`）并调用 `setup_database()`，导出 `APSCHEDULER_DATABASE_URI` / `SQLALCHEMY_DATABASE_URI` / `SQLALCHEMY_BINDS` |
| `scrapydweb/__init__.py` | `handle_db(app)`：注入配置、`db.init_app(app)`、`db.create_all()` 建表、`teardown_request` 收尾、首次插入 `Metadata` 行 |
| `scrapydweb/utils/scheduler.py` | APScheduler `BackgroundScheduler` 配置；`jobstores['default'] = SQLAlchemyJobStore(...)`（第二套持久化）+ `memory` jobstore + `ThreadPoolExecutor(20)` |
| `scrapydweb/common.py` | `handle_metadata(key, value)`：读写 `Metadata` 单行的统一入口 |
| `scrapydweb/views/operations/schedule.py` | 定时任务写入：`db_insert_update_task` / `db_process_task` 写 `Task` 表；`add_update_task` 调 `scheduler.add_job(execute_task, ...)` |
| `scrapydweb/views/operations/execute_task.py` | `execute_task(task_id)` 调度回调；`TaskExecutor` 把执行结果写 `TaskResult` / `TaskJobResult` |
| `scrapydweb/views/dashboard/jobs.py` | `create_table()`：按节点动态建 `Job` 表，缓存在 `jobs_table_map` |
| `scrapydweb/utils/check_app_config.py` | 启动时为每个 `SCRAPYD_SERVER` 建 jobs 表，并注册 `jobs_snapshot` / `delete_task_result` 两个内置周期任务 |
| `scrapydweb/default_settings.py` | `DATABASE_URL` / `DATA_PATH` 默认值、`JOBS_SNAPSHOT_INTERVAL` 等 |

---

## 2. 全部表 / 模型字段表

> 类型一栏使用 SQLAlchemy 列类型；「约定」一栏标注实际存储的隐式约定（重要，dopilot 实现自有数据模型时易踩坑）。

### 2.1 `Metadata` 表（应用级元数据 / 配置，单行表）

- 定义：`models.py:16-39`
- `__tablename__='metadata'`，`__bind_key__='metadata'` → **metadata 库**
- **实际是单行配置表**，用 `version`（= scrapydweb `__version__`）唯一标识。

| 列 | 类型 | 可空 | 默认 | 说明 / 约定 |
|---|---|---|---|---|
| `id` | Integer PK | — | — | 主键 |
| `version` | String(20) **unique** | 否 | — | = `__version__`，单行唯一键（`models.py:21`） |
| `last_check_update_timestamp` | Float | 是 | `time.time` | 上次检查更新时间戳 |
| `main_pid` | Integer | 是 | — | 主进程 pid |
| `logparser_pid` | Integer | 是 | — | logparser 子进程 pid |
| `poll_pid` | Integer | 是 | — | poll 子进程 pid |
| `pageview` | Integer | 否 | 0 | 页面浏览计数 |
| `url_scrapydweb` | Text | 否 | `http://127.0.0.1:5000` | 本服务基址 |
| `url_jobs` | String(255) | 否 | `/1/jobs/` | jobs 路由（供周期任务拼 URL） |
| `url_schedule_task` | String(255) | 否 | `/1/schedule/task/` | 下发任务的路由 |
| `url_delete_task_result` | String(255) | 否 | `/1/tasks/xhr/delete/1/1/` | 删结果路由 |
| `username` | String(255) | 是 | — | basic auth 账号 |
| `password` | String(255) | 是 | — | basic auth 口令（明文，见 gotchas） |
| `scheduler_state` | Integer | 否 | `STATE_RUNNING` | 调度器状态（`vars.py` 引入 APScheduler 状态常量） |
| `jobs_per_page` | Integer | 否 | 100 | jobs 分页 |
| `tasks_per_page` | Integer | 否 | 100 | tasks 分页 |
| `jobs_style` | String(8) | 否 | `database` | jobs 展示风格，可选 `classic` |

读写统一走 `handle_metadata(key, value)`（`common.py:83-95`），全程在 `db.app.app_context()` 内：`key=None` 返回整行 dict，否则 `setattr + commit`（失败 `rollback`）。

### 2.2 `Job` 表（每个 scrapyd 节点一张，运行时动态创建）

- 定义：工厂函数 `create_jobs_table(server)`（`models.py:43-78`）
- `__tablename__ = server`（节点名经规整），`__bind_key__='jobs'` → **jobs 库**
- 唯一约束 `(project, spider, job)`（`models.py:49`）

| 列 | 类型 | 可空 | 默认 | 说明 / 约定 |
|---|---|---|---|---|
| `id` | Integer PK | — | — | 主键 |
| `project` | String(255) | 否 | — | 项目名 |
| `spider` | String(255) | 否 | — | 爬虫名 |
| `job` | String(255) | 否 | — | scrapyd jobid |
| `status` | String(1) **index** | 否 | — | `'0'` 待定 / `'1'` 运行 / `'2'` 完成（字符串，非整数） |
| `deleted` | String(1) **index** | 否 | `'0'` | 删除标记（软删除） |
| `create_time` | DateTime | 否 | `datetime.now` | 真 DateTime 类型 |
| `update_time` | DateTime | 否 | `datetime.now` | 真 DateTime 类型 |
| `pages` | Integer | 是 | — | 抓取页数（由 logparser 填） |
| `items` | Integer | 是 | — | item 数 |
| `pid` | Integer | 是 | — | 运行态进程 pid |
| `start` | DateTime **index** | 是 | — | 开始时间 |
| `runtime` | String(20) | 是 | — | 运行时长（文本） |
| `finish` | DateTime **index** | 是 | — | 完成时间 |
| `href_log` | Text | 是 | — | 日志链接 |
| `href_items` | Text | 是 | — | items 链接 |

> 注意：`Job` 表与 `Task` / `TaskResult` 体系**无外键关联**，是另一条独立数据线，由 `jobs_snapshot` 周期任务填充（见 4.5）。

### 2.3 `Task` 表（定时任务定义）—— **dopilot 全新复刻时的重点参考对象**

- 定义：`models.py:89-128`
- `__tablename__='task'`，**无 `__bind_key__`** → 落默认 URI（**timertasks 库**）

| 列 | 类型 | 可空 | 说明 / 约定（重点） |
|---|---|---|---|
| `id` | Integer PK | — | 主键；与 APScheduler job.id 软关联（`str(id)`） |
| `name` | String(255) | 是 | 任务名，None 时回退 `task_<id>`（`schedule.py:460`） |
| `trigger` | String(8) | 否 | `cron` / `interval` / `date`（`models.py:94`） |
| `create_time` | DateTime | 否 | 真 DateTime |
| `update_time` | DateTime | 否 | 真 DateTime |
| `project` | String(255) | **否** | scrapyd 项目名——**强绑 scrapyd 语义** |
| `version` | String(255) | **否** | egg 版本——**强绑 scrapyd 语义** |
| `spider` | String(255) | **否** | 爬虫名——**强绑 scrapyd 语义** |
| `jobid` | String(255) | **否** | jobid——**强绑 scrapyd 语义** |
| `settings_arguments` | Text | **否** | scrapyd 的 settings/args，**JSON 串**（`schedule.py:423` 用 `json_dumps` 写，`:103`/`:639` 用 `json.loads` 读） |
| `selected_nodes` | Text | **否** | 选中节点列表，**`str(list)` repr 写、`json.loads` 读**（见 gotchas，存在不一致风险） |
| `year` | String(255) | 否 | cron：年 |
| `month` | String(255) | 否 | cron：月 |
| `day` | String(255) | 否 | cron：日 |
| `week` | String(255) | 否 | cron：周 |
| `day_of_week` | String(255) | 否 | cron：星期（如 `mon-fri,sun`，`schedule.py:138` 用逗号 split） |
| `hour` | String(255) | 否 | cron：时 |
| `minute` | String(255) | 否 | cron：分 |
| `second` | String(255) | 否 | cron / interval：秒 |
| `start_date` | String(19) | 是 | **文本** `'2019-01-01 00:00:01'`，**非 DateTime**（`models.py:114`） |
| `end_date` | String(19) | 是 | 同上，文本 |
| `timezone` | String(255) | 是 | 时区名 |
| `jitter` | Integer | 否 | 抖动秒数 |
| `misfire_grace_time` | Integer | 是 | 误触发宽限秒数 |
| `coalesce` | String(5) | 否 | **字符串** `'True'` / `'False'`（`schedule.py:443`，注释明确 bool True 会被存成 1） |
| `max_instances` | Integer | 否 | 最大并发实例 |
| `results` | relationship | — | → `TaskResult`，`cascade='all, delete-orphan'`（`models.py:123`，删 Task 级联删结果） |

这些 cron/interval/date 字段**直接映射 APScheduler `add_job` 的 trigger 参数**（`schedule.py:481` 的 `**self.task_data`）。

### 2.4 `TaskResult` 表（一次执行的汇总）

- 定义：`models.py:131-144`
- `__tablename__='task_result'`，无 bind → **timertasks 库**

| 列 | 类型 | 可空 | 说明 |
|---|---|---|---|
| `id` | Integer PK | — | 主键 |
| `task_id` | Integer FK→`task.id` **index** | 否 | 外键（同库内有效） |
| `execute_time` | DateTime | 否 | 本次执行时刻 |
| `fail_count` | Integer | 否 | 失败节点数（默认 0，`execute_task.py:144`） |
| `pass_count` | Integer | 否 | 成功节点数（默认 0，`execute_task.py:145`） |
| `results` | relationship | — | → `TaskJobResult`，`cascade='all, delete-orphan'` |

### 2.5 `TaskJobResult` 表（执行明细，每节点一条）

- 定义：`models.py:147-179`
- `__tablename__='task_job_result'`，无 bind → **timertasks 库**

| 列 | 类型 | 可空 | 说明 / 约定 |
|---|---|---|---|
| `id` | Integer PK | — | 主键 |
| `task_result_id` | Integer FK→`task_result.id` **index** | 否 | 外键 |
| `run_time` | DateTime | 否 | 该节点执行时刻 |
| `node` | Integer **index** | 否 | **节点序号（1-based 索引）**，非 host:port（`execute_task.py:115`） |
| `server` | String(255) | 否 | `'127.0.0.1:6800'`，从 URL 正则提取（`execute_task.py:116`） |
| `status_code` | Integer | 否 | `200`（成功）/ `-1`（异常，`execute_task.py:101`） |
| `status` | String(9) | 否 | `ok` / `error` / `exception` |
| `result` | Text | 否 | `jobid` 或 `message` 或 `exception`（`execute_task.py:119`，按优先级取一） |

---

## 3. 多 bind / 多库与 DB 文件位置

### 3.1 四个逻辑库与 bind 路由

| 逻辑库（常量名） | SQLite 文件 | MySQL/PG 库名 | 配置项 | 谁落在这里 |
|---|---|---|---|---|
| `DB_APSCHEDULER` | `apscheduler.db` | `scrapydweb_apscheduler` | `APSCHEDULER_DATABASE_URI` | APScheduler 自管的 `apscheduler_jobs` 表（**非 ORM**） |
| `DB_TIMERTASKS` | `timer_tasks.db` | `scrapydweb_timertasks` | `SQLALCHEMY_DATABASE_URI`（默认 URI） | `Task` / `TaskResult` / `TaskJobResult`（无 bind_key） |
| `DB_METADATA` | `metadata.db` | `scrapydweb_metadata` | `SQLALCHEMY_BINDS['metadata']` | `Metadata`（`__bind_key__='metadata'`） |
| `DB_JOBS` | `jobs.db` | `scrapydweb_jobs` | `SQLALCHEMY_BINDS['jobs']` | 每节点一张 `Job` 表（`__bind_key__='jobs'`） |

- 库名常量：`setup_database.py:7-11`
- SQLite 文件名拼接：`setup_database.py:55-61`（注释「db names for backward compatibility」说明文件名与库名故意不同）
- MySQL/PG URI 拼接：`setup_database.py:47-52`

```
  SQLite (默认)                              MySQL / PostgreSQL
  data/database/                             单台 DB 服务器上 4 个数据库
  ├── apscheduler.db   (DB_APSCHEDULER)      ├── scrapydweb_apscheduler
  ├── timer_tasks.db   (DB_TIMERTASKS)       ├── scrapydweb_timertasks
  ├── metadata.db      (DB_METADATA)         ├── scrapydweb_metadata
  └── jobs.db          (DB_JOBS)             └── scrapydweb_jobs
```

> **重要约束**：跨 bind / 跨库**不能用外键 JOIN**。`TaskResult.task_id`→`Task.id`、`TaskJobResult.task_result_id`→`TaskResult.id` 这两个外键之所以有效，是因为三者都在 **timertasks 同一个库**。`Metadata`（metadata 库）、`Job`（jobs 库）、APScheduler（apscheduler 库）之间彼此都无法用外键关联。

### 3.2 数据路径与计算

- `DATA_PATH`：优先 `default_settings.DATA_PATH` → 自定义设置 → 否则 `<package>/data`（`vars.py:45-49`）
- `DATABASE_PATH = DATA_PATH/database`（`vars.py:51`），启动时若不存在自动 `mkdir`（`vars.py:59-62`）
- `DATABASE_URL` 取值优先级：自定义设置 → `default_settings.DATABASE_URL`（默认空串 `os.environ.get('DATABASE_URL','')`，`default_settings.py:387`）→ 回退 `'sqlite:///' + DATABASE_PATH`（`vars.py:72`）
- 自定义设置文件名：`scrapydweb_settings_v11.py`（`vars.py:29`），从 cwd 导入

### 3.3 后端选择（SQLite / MySQL / PostgreSQL）

- 正则匹配：`PATTERN_MYSQL` / `PATTERN_POSTGRESQL` / `PATTERN_SQLITE`（`setup_database.py:13-15`）
- `setup_database()` 据此分派 `setup_mysql` / `setup_postgresql` / SQLite 建目录（`setup_database.py:27-44`）
- **建库时机**：
  - MySQL：`CREATE DATABASE ... CHARACTER SET 'utf8' COLLATE 'utf8_general_ci'`（`setup_database.py:110`），已存在则忽略
  - PostgreSQL：`CREATE DATABASE ... ENCODING 'UTF8'`（`setup_database.py:157`），失败回退裸 `CREATE DATABASE`
  - SQLite：仅 `os.mkdir(database_path)`，文件由 SQLAlchemy 首次连接时生成

### 3.4 DB 文件 / 表创建的完整时机链路

```
import scrapydweb.vars
   └─ setup_database()  ── 建库目录 / CREATE DATABASE，返回 4 个 URI/BINDS   [vars.py:73]
create_app()
   └─ handle_db(app)                                                       [__init__.py:110]
        ├─ app.config['SQLALCHEMY_DATABASE_URI'] = ...                     [__init__.py:112]
        ├─ app.config['SQLALCHEMY_BINDS']        = ...                     [__init__.py:113]
        ├─ db.init_app(app)                                                [__init__.py:124]
        ├─ db.create_all()  ── 一次性建出 Metadata/Task/TaskResult/TaskJobResult [__init__.py:125]
        │                       （注意：此时 Job 表还建不出来，因为节点未知）
        └─ 首次插入 Metadata(version=__version__) 行                        [__init__.py:135-138]
check_app_config(config)
   └─ 为每个 SCRAPYD_SERVER：create_jobs_table(...) + db.create_all(bind='jobs')  [check_app_config.py:110-114]
   └─ scheduler.add_job('jobs_snapshot', ..., jobstore='memory')          [check_app_config.py:306]
   └─ scheduler.add_job('delete_task_result', ..., jobstore='memory')     [check_app_config.py:329]
运行期：用户访问 JobsView
   └─ create_table()：未缓存则 create_jobs_table + db.create_all(bind='jobs')  [jobs.py:176-186]
```

> `db.create_all()` 语义是 **CREATE TABLE IF NOT EXISTS**，只新建、绝不 ALTER。Job 表既在启动时（`check_app_config.py:114`）建、又在运行期（`jobs.py:183`）建，SQLite 下可能出现「table already exists」，靠 `IF NOT EXISTS` 与 try/except 容错（代码注释 `jobs.py:182` 已说明）。

---

## 4. 数据流：定时任务的两套并行持久化

这是理解本子系统的核心。**定时任务定义（ORM `Task` 表）** 与 **可执行调度对象（APScheduler jobstore）** 是两套数据，由两次写入产生。

```
用户在 ScheduleView 提交定时任务  (POST /N/schedule/task/)
        │
        ├─(1)─► db_insert_update_task / db_process_task        [schedule.py:399-444]
        │        写入 Task 行（任务定义）到 timertasks 库
        │        - settings_arguments = json_dumps(...)         [schedule.py:423]
        │        - selected_nodes     = str(self.selected_nodes)[schedule.py:424]
        │        - coalesce           = 'True'/'False'          [schedule.py:443]
        │
        └─(2)─► add_update_task                                 [schedule.py:447-482]
                 scheduler.add_job(func=execute_task,
                                   kwargs={'task_id': id},
                                   id=str(task_id),
                                   replace_existing=True,
                                   **task_data)                 [schedule.py:481]
                 ► APScheduler 序列化 job 存入 SQLAlchemyJobStore
                   (apscheduler 库 / apscheduler_jobs 表)
                   软关联：job.id == str(Task.id)，无外键
        ▼
触发时（cron/interval 到点）
        │
        └─► execute_task(task_id)                              [execute_task.py:150]
              task = Task.query.get(task_id)                   [execute_task.py:152]
              若 task 不存在 → apscheduler_job.remove()（兜底） [execute_task.py:154-156]
              否则 TaskExecutor 向各 selected_nodes 的 scrapyd 下发
                ├─ 写 1 行 TaskResult（汇总 fail/pass）        [execute_task.py:66-70, 144-146]
                └─ 每节点写 1 行 TaskJobResult（明细）          [execute_task.py:113-121]
```

### 4.1 第一套：ORM `Task` 表（任务定义）

- 写入：`db_process_task()`（`schedule.py:416-444`），insert 走 `db.session.add + commit`（`schedule.py:411-412`），update 复用同一行再在 `add_update_task` 里 commit/rollback。

### 4.2 第二套：APScheduler `SQLAlchemyJobStore`（可执行 job）

- 配置：`jobstores['default'] = SQLAlchemyJobStore(url=APSCHEDULER_DATABASE_URI)`（`scheduler.py:32`）
- 表 `apscheduler_jobs` 由 APScheduler 自管，**与上面 ORM 模型互不相通**，仅 `job.id == str(Task.id)` 软关联。
- 调度器：`BackgroundScheduler`，`executors['default']=ThreadPoolExecutor(20)`，`job_defaults={'coalesce':True,'max_instances':1}`，启动即 `scheduler.start(paused=True)`（`scheduler.py:45,90`）。

### 4.3 两套之间的删除一致性（gotcha）

- 删 `Task` **不会自动删** apscheduler job（无外键、不同库）。
- 兜底机制：下次 `execute_task` 触发时若发现 `Task` 已不存在，调 `apscheduler_job.remove()`（`execute_task.py:154-156`）。

### 4.4 结果写入

- `TaskResult`：`TaskExecutor.execute()` 先 add 一行（`execute_task.py:66-70`），跑完更新 `fail_count`/`pass_count`（`execute_task.py:144-146`）。
- `TaskJobResult`：每节点一行（`execute_task.py:113-121`）。`node` 存的是**节点序号**，`server` 存 `host:port`。

### 4.5 两个内置周期任务（注册在 `memory` jobstore，非持久化）

| 内置任务 id | 函数 | 默认间隔 | jobstore | 作用 |
|---|---|---|---|---|
| `jobs_snapshot` | `create_jobs_snapshot` | `JOBS_SNAPSHOT_INTERVAL=300s`（`default_settings.py:134`） | **`memory`** | 抓各节点作业写入对应 `Job` 表 |
| `delete_task_result` | `delete_task_result` | `CHECK_TASK_RESULT_INTERVAL=300s`（默认 `check_app_config.py:311`） | **`memory`** | 清理历史 `TaskResult` |

- 注册：`check_app_config.py:306-309` 与 `:329-332`，均 `jobstore='memory'`。
- **现状事实（易被误解）**：只有**用户自定义的定时任务**进入 `default`（持久化）jobstore；这两个内置任务进入 `memory` jobstore，进程重启后由 `check_app_config` 重新注册，不依赖持久化。

---

## 5. 迁移现状与局限（gotchas，dopilot 必读）

| # | 现状事实 | 影响 / dopilot 复刻注意 |
|---|---|---|
| G1 | **scrapydweb 无任何数据库迁移机制**。`models.py:14` 顶部就是 `# TODO: Database Migrations`，没有 Alembic / Flask-Migrate。 | **现状（reference）**：建表全靠 `db.create_all()`（只 CREATE IF NOT EXISTS，绝不 ALTER）；给现有模型加/改列，旧库不会自动升级，scrapydweb 只能**手动迁移或删库重建**——这是 scrapydweb reference 行为，**不是 dopilot 策略**。**dopilot**：从阶段 0 起就以**裸 Alembic**（FastAPI 无 Flask app，不能用 Flask-Migrate）做版本化迁移，扩展 `Task` 走 revision，不删库（见 §7.1）。 |
| G2 | **两套互不相通的持久化**：ORM（`Metadata`/`Task`/`TaskResult`/`TaskJobResult`/`Job`）与 APScheduler `SQLAlchemyJobStore`（`apscheduler_jobs`）。 | 仅 `job.id == str(Task.id)` 软关联，无外键。删 Task 不会删 apscheduler job（靠 `execute_task.py:155` 兜底）。 |
| G3 | **多库多 bind**：`metadata` / `jobs` bind 路由到独立库；`Task`/`TaskResult`/`TaskJobResult` 落默认 timertasks 库。 | 跨 bind 不能 JOIN / 外键。SQLite 下 4 个 `.db` 文件，MySQL/PG 下 4 个数据库。 |
| G4 | `Job` 表**运行时按节点动态建表**，表名 = server 名经 `STRICT_NAME_PATTERN`（`vars.py:81`，非 `[0-9A-Za-z_]` 替换为 `_`），如 `127.0.0.1:6800` → `127_0_0_1_6800`。 | 同名 `Job` 类反复定义会触发 `SAWarning`（`models.py:74` 注释），靠 `jobs_table_map` 缓存避免。**新增/删除 scrapyd 节点只会新增表、不会删旧表**。 |
| G5 | `Metadata` 是**单行配置表**，用 `version`(=`__version__`) 唯一键过滤。 | 升级 `__version__` 会**插入新行而非更新旧行**，旧配置不自动迁移（`__init__.py:135-138`）。 |
| G6 | 字段类型有隐式约定：`coalesce` 存字符串 `'True'/'False'`（`schedule.py:443`）；`selected_nodes` 存 `str(list)` **repr** 写、`json.loads` 读（`schedule.py:424` vs `:99`）；`start_date`/`end_date` 是 `String(19)` **文本**非 DateTime。 | `selected_nodes` 是 int 列表时 `str([1,2])=='[1, 2]'` 恰好是合法 JSON，故现状能跑；一旦存非数字内容（如节点名字符串），repr 的单引号会让 `json.loads` 失败——**dopilot 应改为统一 `json.dumps`/`json.loads`**。 |
| G7 | `SQLALCHEMY_ECHO=True` **硬编码开启**（`__init__.py:115`）。 | 生产环境会把所有 SQL 打到日志，量大且泄露细节。dopilot 复刻时应关掉或改为可配置。 |
| G8 | `Metadata.password` 明文存储（`models.py:32`）。 | 安全隐患，dopilot 实现自有数据模型时建议加密或外置密钥管理（开放问题）。 |
| G9 | `create_table` 的 `db.create_all(bind='jobs')` 与启动建表在 SQLite 下可能报 `table already exists`。 | 靠 `IF NOT EXISTS` 与 try/except 容错（`jobs.py:182` 注释已说明），现状无功能影响。 |

---

## 6. dopilot 复刻定制点（针对 dopilot 三类被调度对象）

> 全部为**dopilot 复刻建议 / 开放问题**，不是 scrapydweb 现状；指 dopilot 在 `apps/` 下全新复刻其行为语义时的取舍。

### 6.1 新增被调度对象类型（Docker 常驻爬虫、Python 一次性脚本）

**现状约束**：`Task` 当前**强绑 scrapyd 语义**——`project` / `version` / `spider` / `jobid` 均 `nullable=False`（`models.py:98-101`）；`settings_arguments` / `selected_nodes` 为 Text。

**建议方向**（任选其一或组合）：

| 方案 | 做法 | 代价 |
|---|---|---|
| A. 加 `task_type` 列 + 放宽 nullable | 给 `Task` 加 `task_type`（`scrapy`/`docker`/`script`），把 `project`/`version`/`spider`/`jobid` 改 nullable，按类型存不同语义字段 | 改动集中但语义混杂；需迁移——dopilot 走 Alembic revision（G1，非删库重建） |
| B. 新建独立模型 | `Task` 保留 scrapyd 专用，另建 `DockerTask` / `ScriptTask`（同库或同表继承） | 模型清晰但 `execute_task` 分派逻辑需重写 |
| C. 单表继承（STI） | 共用 `task` 表 + `task_type` 区分子类 | SQLAlchemy 原生支持，但列冗余 |

**节点策略（开放问题）**：当前**没有「指定全部 / 随机选一个」的字段**。`selected_nodes` 只存「选中哪些节点」，下发逻辑见 `execute_task.py:53` 对 `nodes` 循环。dopilot 需新增字段（建议 `node_strategy`：`all` / `random` / `specified`），并在执行器里据此挑节点；「推模式指定执行」可参考 scrapydweb「向指定 node 的 scrapyd 下发」的行为语义（`execute_task.py:75-103` 的 `schedule_task(node)`），由 dopilot 在 `apps/` 下全新复刻。

### 6.2 cron / interval / date 触发参数扩展

- 位置：`Task` 表的 `trigger` + `year/month/day/week/day_of_week/hour/minute/second` + `start_date/end_date/timezone/jitter/misfire_grace_time/coalesce/max_instances`（`models.py:94-121`）。
- 这些字段**直接映射 APScheduler `add_job` 的 trigger 参数**（`schedule.py:481` 的 `**task_data`）。新增调度策略时在此扩展并同步 `task_data` 与 `db_process_task`（`schedule.py:416-444`）。

### 6.3 应用级配置项扩展

- 给 `Metadata` 加列并设 `default`，经 `handle_metadata(key, value)`（`common.py:83`）读写。
- 注意 G5：升级 `__version__` 会新插一行，旧配置不迁移。

### 6.4 每节点作业表结构扩展

- 改 `create_jobs_table` 工厂（`models.py:43`），bind=`jobs`。
- 新增列需同时考虑历史表迁移——dopilot 通过 Alembic revision 升级（G1），不沿用 scrapydweb 的删库重建。

### 6.5 国际化 i18n（中文）

- **持久化层基本无关**：DB 层 MySQL 用 `utf8`/`utf8_general_ci`、PostgreSQL 用 `UTF8` 建库（`setup_database.py:110,157`），Text 列可正常存中文。
- 用户可见文案的 i18n 框架应在**视图 / 模板层**引入，而非本子系统。本子系统只需保证编码正确即可。

---

## 7. 给 dopilot 的落地清单（建议）

1. **先解决 G1（迁移）**：dopilot 从**阶段 0** 起就走 **裸 Alembic** 版本化迁移（**不是 Flask-Migrate**——dopilot 是 FastAPI，无 Flask app，`flask db` CLI 无从挂载，故不能用 Flask-Migrate；直接用 Alembic 的 `env.py` + `alembic.ini` 管 migration）。**「删库重建」只是 scrapydweb reference 的现状行为，不作为 dopilot 的迁移策略**；任何 `Task` 扩展都通过 Alembic revision 升级，不删库。
2. **统一序列化**：把 `selected_nodes` 从 `str(list)` 改为 `json.dumps`（修 G6）。
3. **去掉硬编码 `SQLALCHEMY_ECHO=True`**（修 G7），改为读配置。
4. **抽象 `Task` 的对象类型**：加 `task_type` + `node_strategy`，并放宽 scrapyd 专用列的 nullable（6.1）。
5. **明确两套持久化边界**（G2）：若 dopilot 引入新调度后端（如 Docker exec / 子进程），仍可沿用 APScheduler jobstore 这一行为模式（在 dopilot 自有实现中）；新对象类型的执行逻辑参考 scrapydweb `execute_task` 的分派语义、由 dopilot 全新复刻。
6. **APScheduler jobstore 落 PostgreSQL**：dopilot 唯一库即 PostgreSQL，APScheduler 的 `SQLAlchemyJobStore` 直接指向同一 PostgreSQL（`apscheduler_jobs` 表），不再像 scrapydweb 那样另起一个独立 `apscheduler` 库 / SQLite 文件。注意单实例硬约束——server = 单容器 + uvicorn workers=1 + 单 APScheduler 实例，jobstore 落 PG 仅为持久化，**不引入任何分布式锁 / 多副本 fan-out**。
7. **口令安全**（G8）：`Metadata.password` 改加密 / 外置。
