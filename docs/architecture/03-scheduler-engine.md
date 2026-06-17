# 03 · 调度与定时引擎（核心）

> 本文面向参与 dopilot 改造的工程师，详尽剖析 scrapydweb 的「定时任务（Timer Tasks）」子系统：它基于 APScheduler 的 `BackgroundScheduler` 在 Flask 进程内调度作业，是 dopilot 改造的**核心复用对象**。
>
> 文中区分两类内容：
> - **【现状】** 当前代码事实，均标注真实文件路径与 `file:line`；
> - **【改造】 / 【开放问题】** 针对 dopilot 目标（Docker 常驻爬虫、一次性脚本、随机节点、推模式、实时日志、i18n）的建议与待决策点。

---

## 1. 一句话定位

每个「定时任务（Task）」以触发器（当前硬编码为 cron）周期性回调模块级函数 `execute_task(task_id)`；该回调通过 Flask `test_client` 做**进程内 HTTP 调用**命中各节点的 `/N/schedule/task/` 路由，再由该路由向对应 scrapyd 的 `/schedule.json` 下发爬虫。任务的业务元数据存于自有 SQLAlchemy 模型（`Task`/`TaskResult`/`TaskJobResult`），而 APScheduler 的作业状态（trigger、next_run_time）独立存于 APScheduler 自己的 `SQLAlchemyJobStore`。

这套现成框架已经具备「定时 + 多节点下发 + 任务结果记录」，dopilot 只需在其上**扩展被调度对象类型与下发协议**。

---

## 2. 关键文件总览

| 文件 | 角色 |
| --- | --- |
| `scrapydweb/utils/scheduler.py` | 全局 `BackgroundScheduler` 单例的定义、jobstore/executor 配置、事件监听、`import` 时 `start(paused=True)`、`atexit` 优雅停机 |
| `scrapydweb/views/operations/schedule.py` | 定时任务创建/编辑核心：表单渲染、`__task_data` 打包、落库 + `scheduler.add_job()`、内部端点 `ScheduleTaskView` |
| `scrapydweb/views/operations/execute_task.py` | APScheduler 作业回调 `execute_task()` 及 `TaskExecutor` 类（实际遍历节点下发、记录结果、失败重试） |
| `scrapydweb/views/overview/tasks.py` | Timer Tasks 管理页 `TasksView` 与 XHR 操作端点 `TasksXhrView`（enable/disable/pause/resume/remove/fire/delete） |
| `scrapydweb/models.py` | `Task` / `TaskResult` / `TaskJobResult` 数据模型 |
| `scrapydweb/utils/check_app_config.py` | 启动期接入 scheduler：按持久化状态 `resume()`，并用 `memory` jobstore 注册两个维护作业 |
| `scrapydweb/vars.py` | 常量与路径：`APSCHEDULER_DATABASE_URI`、`SCHEDULE_PATH`、`TIMER_TASKS_HISTORY_LOG`、`SCHEDULER_STATE_DICT` 等 |
| `scrapydweb/utils/setup_database.py` | 计算 `APSCHEDULER_DATABASE_URI` 与各业务库 URI（SQLite/MySQL/PostgreSQL） |
| `scrapydweb/__init__.py` | `create_app()`/`handle_db()`/`handle_route()`：注册路由、`db.app = app`（APScheduler 后台线程访问 DB 的关键集成点） |
| `scrapydweb/views/baseview.py` | `BaseView` 把全局 scheduler 暴露为 `self.scheduler`、读取相关配置、`get_selected_nodes()`、`get_response_from_view()` |
| `scrapydweb/templates/scrapydweb/schedule.html` | 定时任务表单 UI（Vue + Element-UI）；`trigger` 硬编码为 `'cron'` |
| `scrapydweb/common.py` | `get_response_from_view()`（`app.test_client()` 进程内 HTTP）、`handle_metadata()` |
| `scrapydweb/run.py` | 入口；`use_reloader=False`（必须） |

---

## 3. 整体架构图

```
                          ┌──────────────────────────────────────────────────────────────┐
                          │                  Flask 单进程（dopilot/scrapydweb）              │
                          │                                                                │
  浏览器  ───POST表单──►   │   ScheduleCheckView ──► ScheduleRunView                         │
 (Run Spider /            │   /schedule/check       /schedule/run                          │
  Schedule 页)            │        │                     │ db_insert_update_task()         │
                          │   prepare_data()         ┌───┴── add_update_task()             │
                          │   (pickle 参数)          │       scheduler.add_job(...)        │
                          │        │                 ▼                                     │
                          │        ▼            ┌──────────────────────────────┐          │
                          │   SCHEDULE_PATH     │  业务库 (Flask-SQLAlchemy)     │          │
                          │   *.pickle          │  Task / TaskResult /          │          │
                          │   + 内存 slot       │  TaskJobResult                │          │
                          │                     │  (timer_tasks.db)             │          │
                          │                     └──────────────────────────────┘          │
                          │                                ▲   关联键: str(Task.id)        │
                          │   ┌────────────────────────────┼──────────────────────────┐   │
                          │   │  BackgroundScheduler 单例 (后台线程 + ThreadPool=20)     │   │
                          │   │  jobstores:                                            │   │
                          │   │    default = SQLAlchemyJobStore(apscheduler.db) ◄──────┘   │
                          │   │    memory  = MemoryJobStore (维护作业)                  │   │
                          │   │                                                        │   │
                          │   │  到点 ──► 线程池调用 execute_task(task_id)              │   │
                          │   └───────────────────┬────────────────────────────────────┘   │
                          │                       ▼                                        │
                          │   TaskExecutor.main() ── 遍历 selected_nodes                    │
                          │       │ get_response_from_view() (test_client 进程内 HTTP)      │
                          │       ▼                                                        │
                          │   /N/schedule/task/  (ScheduleTaskView)                        │
                          │       │ make_request()                                         │
                          └───────┼────────────────────────────────────────────────────────┘
                                  ▼
                  http://<node-N scrapyd>/schedule.json   ──►  scrapyd 启动爬虫
```

**关键观察【现状】**：所谓「下发到节点」其实是 scrapydweb **本机**通过 `test_client` 代理转发到各 scrapyd，并非真正分布式 worker 推送。详见 §11 局限与 §12 改造点。

---

## 4. 全局 Scheduler 单例

文件 `scrapydweb/utils/scheduler.py`。

| 项 | 值 | 位置 |
| --- | --- | --- |
| jobstores.default | `SQLAlchemyJobStore(url=APSCHEDULER_DATABASE_URI)` 持久化 | `scheduler.py:32` |
| jobstores.memory | `MemoryJobStore()` 临时（维护作业） | `scheduler.py:33` |
| executors.default | `ThreadPoolExecutor(20)`（`ProcessPoolExecutor` 已留注释） | `scheduler.py:36-37` |
| job_defaults | `coalesce=True, max_instances=1` | `scheduler.py:39-42` |
| 调度器类型 | `BackgroundScheduler(...)`（未指定 timezone，用本地时区） | `scheduler.py:45` |
| 事件监听 | `my_listener` 监听 `EVENT_JOB_MAX_INSTANCES \| EVENT_JOB_REMOVED` | `scheduler.py:68-87` |
| 日志 | APScheduler 日志写入 `TIMER_TASKS_HISTORY_LOG`，`level=WARNING` | `scheduler.py:16-23` |
| import 时启动 | `scheduler.start(paused=True)` | `scheduler.py:90` |
| 优雅停机 | `atexit.register(lambda: shutdown_scheduler())` | `scheduler.py:93-111` |

要点说明：

- **`import` 即 `start(paused=True)`**：模块被导入时调度器即启动但处于暂停态，真正 `resume()` 推迟到 `check_app_config` 末尾（见 §9）。
- **事件监听按 jobstore 分级**：`my_listener` 据 `event.jobstore != 'default'` 决定日志级别——`memory`（维护作业）写 INFO，`default`（用户任务）写 WARNING（`scheduler.py:72-75`）。
- **`shutdown_scheduler()`** 调 `scheduler.shutdown()`，**等待**当前运行中的作业结束后再退出（`scheduler.py:99`）。

---

## 5. 数据模型与「双存储」结构

### 5.1 三张业务表（`scrapydweb/models.py`）

| 表 | 关键字段 | 说明 |
| --- | --- | --- |
| `Task` (`models.py:89-128`) | `id`、`name`、`trigger`、`project/version/spider/jobid`、`settings_arguments`(JSON Text)、`selected_nodes`(JSON Text)、cron 全字段 `year/month/day/week/day_of_week/hour/minute/second`、`start_date/end_date`、`timezone/jitter/misfire_grace_time/coalesce/max_instances` | 一个定时任务的完整定义 |
| `TaskResult` (`models.py:131-144`) | `task_id`(FK)、`execute_time`、`fail_count`、`pass_count` | 每次定时触发的**汇总**结果 |
| `TaskJobResult` (`models.py:147-179`) | `task_result_id`(FK)、`run_time`、`node`、`server`、`status_code`、`status`、`result` | 每节点**单次下发**结果 |

关系：`Task 1─N TaskResult 1─N TaskJobResult`，均 `cascade='all, delete-orphan'`（删 Task 级联删结果）。

字段细节【现状】：

- `Task.trigger` 注释写「cron, interval, date」（`models.py:94`），**但所有 cron 字段 `year..second` 均为 `nullable=False`**（`models.py:105-112`），实际只支持 cron。
- `coalesce` 以**字符串** `'True'/'False'` 存储（`models.py:120`），避免 bool 被存成 1/0；写入逻辑见 `schedule.py:443`。
- `misfire_grace_time` 为 `nullable=True`，`0` 被转成 `None`（表示正无穷宽限），见 §6 清洗规则。
- `selected_nodes` 用 `str(list)`（如 `"[1, 3]"`）存储（`schedule.py:424`），读取时 `json.loads`（`execute_task.py:168`）——注意写入用 Python `str()` 而非 `json.dumps`，因列表内是 int 故 JSON 可解析。

### 5.2 APScheduler 独立 jobstore

APScheduler 的作业（**trigger 表达式、next_run_time、序列化的函数引用**）存于完全独立的 `SQLAlchemyJobStore`，库地址为 `APSCHEDULER_DATABASE_URI`（`scheduler.py:32`）。

```
SQLite 模式（setup_database.py:55-61）：
  apscheduler.db   ← APScheduler jobstore (trigger / next_run_time)   [独立]
  timer_tasks.db   ← Task / TaskResult / TaskJobResult                [业务库, SQLALCHEMY_DATABASE_URI]
  metadata.db      ← Metadata (bind: 'metadata')
  jobs.db          ← Job 表 (bind: 'jobs')

MySQL/PostgreSQL 模式（setup_database.py:46-52）：自动建 4 个库
  scrapydweb_apscheduler / scrapydweb_timertasks / scrapydweb_metadata / scrapydweb_jobs
```

> **【gotcha】关联键 = `str(Task.id)`**：`Task.id`（int）被字符串化后复用为 apscheduler_job 的 `id`（`schedule.py:458`）。两套存储**靠这个字符串 id 对账**，没有外键约束，删除/编辑任务必须同时维护两边（详见 §11.1）。

---

## 6. 支持的 Trigger 类型

### 6.1 现状：硬编码 cron

| 硬编码点 | 位置 |
| --- | --- |
| 后端组包 `trigger='cron'` | `schedule.py:300`（`update_data_for_timer_task()`，且 line 299 把 `request.form.get('trigger')` 注释掉了） |
| 视图默认 `self.kwargs['trigger']='cron'` | `schedule.py:189` |
| 模板渲染 `trigger: '{{ trigger }}'` | `schedule.html:547` |
| 落库 `self.task.trigger = self.task_data['trigger']` | `schedule.py:427` |

cron 字段（均来自表单，缺省值见括号）：`year(*)`、`month(*)`、`day(*)`、`week(*)`、`day_of_week(*，多选)`、`hour(*)`、`minute(0)`、`second(0)`、`start_date(None)`、`end_date(None)`、`timezone(None→默认调度器时区)`（`schedule.py:305-320`）。

整数字段清洗规则（`get_int_from_form()`，`schedule.py:283-289`）：

| 字段 | 默认 | 下限 | 特殊处理 |
| --- | --- | --- | --- |
| `jitter` | 0 | 0 | — |
| `misfire_grace_time` | 600 | 0 | `0` → `None`（正无穷宽限，`schedule.py:324`） |
| `max_instances` | 1 | 1 | 强制 ≥1 |
| `coalesce` | 'True' | — | bool→存储为 `'True'/'False'` 字符串 |

### 6.2 APScheduler 原生已支持 interval / date

依赖已随包安装，触发器模块存在：

```
.venv/.../apscheduler/triggers/
  cron/        interval.py        date.py        combining.py
```

即 `interval`（weeks/days/hours/minutes/seconds）、`date`（run_date）、`combining`（and/or 组合）均可用，**只是 UI/后端/模型未暴露**。扩展方法见 §12。

---

## 7. APScheduler 与 Flask / DB 的集成方式

这是整个子系统最微妙的部分，dopilot 改造时必须完整保留这套机制。

| 集成点 | 机制 | 位置 |
| --- | --- | --- |
| 后台线程访问 DB | `db.app = app`，使后台线程能 `with db.app.app_context()` 拿到应用上下文 | `__init__.py:123` |
| 回调函数可被反序列化 | `execute_task` 是**模块级函数**（非闭包/方法），jobstore 才能 pickle 其引用 | `execute_task.py:150` |
| 视图引用调度器 | `BaseView.__init__` 设 `self.scheduler = scheduler` | `baseview.py:20,117` |
| 进程内 HTTP 调用 | `get_response_from_view()` 用 `app.test_client()` 发请求 | `common.py:48-52`、`baseview.py:253-255` |
| DB 会话清理 | `@app.teardown_request` 出错回滚、请求结束 `db.session.remove()` | `__init__.py:128-132` |

**线程上下文【gotcha】**：`execute_task` 与 `TaskExecutor` 的**每个** DB 操作都单独包在 `with db.app.app_context()` 中（`execute_task.py:65,107,126,151`）。原因是 SQLite 限制「对象只能在创建它的线程使用」，代码用「每次新建 app_context」规避。改库或改并发模型时**必须保留**这一点。

---

## 8. 端到端流程（时序）

### 8.1 创建 / 编辑流程

```
浏览器表单 (Run Spider / Schedule 页)
   │ ① POST /N/schedule/check
   ▼
ScheduleCheckView.dispatch_request()                       schedule.py:224
   ├─ prepare_data()        把爬虫参数(project/version/spider/jobid/setting…)
   │                        pickle 到 SCHEDULE_PATH/<filename>.pickle 并存内存 slot   schedule.py:236-281
   └─ update_data_for_timer_task()  把定时字段打包进 data['__task_data']            schedule.py:291-328
        (若 request.form 无 'trigger' 则直接 return，即普通 Run Spider 非定时)
   │ 返回 {filename, cmd}
   ▼
浏览器 ② POST /N/schedule/run  (form: filename, checked_amount, 勾选节点…)
   ▼
ScheduleRunView.dispatch_request()                         schedule.py:356
   ├─ handle_form()   从内存 slot 或 pickle 还原 data；解析 selected_nodes          schedule.py:362-381
   └─ handle_action()                                                              schedule.py:383-395
        task_data = data.pop('__task_data')   # 若有 → 定时任务分支
        _action = task_data.pop('action')     # add | add_fire | add_pause
        task_id = task_data.pop('task_id')    # 0=新建; >0=编辑
        to_update_task = replace_existing and task_id
        │
        ├─ db_insert_update_task()                                                 schedule.py:399-414
        │     新建: Task() → db_process_task() → add → commit → 拿到 task_id
        │     编辑: Task.query.get(id) → db_process_task() → (延后 commit)
        │
        └─ add_update_task()                                                       schedule.py:447-533
              task_data['id'] = str(task_id)
              scheduler.add_job(func=execute_task, kwargs={'task_id': id},
                                replace_existing=True, **task_data)  ← 写入 default jobstore
              action='add_fire'  → next_run_time = datetime.now()  (立即触发)
              action='add_pause' → next_run_time = None            (加为暂停态)
              编辑成功 → db.session.commit()；失败 → db.session.rollback()
   │ 成功 redirect 到 /N/tasks/?flash=...
   ▼
Timer Tasks 列表页
```

要点【现状】：

- `add_fire` 在**新建**时直接给 `task_data['next_run_time']=now`；在**编辑**时为避免「任务在 commit 前就触发」，先 `add_job` 再 `job_instance.modify(next_run_time=now)`（`schedule.py:464-469, 503-505`）。
- `add_job` 抛错（如非法 cron 表达式 `Unrecognized expression "10/*"`）时，编辑分支会 `db.session.rollback()`（`schedule.py:484-491`），保证业务库与 jobstore 不出现单边写入。

### 8.2 触发流程（定时到点）

```
BackgroundScheduler 后台线程到点
   │ 线程池调用 (jobstore 反序列化函数引用)
   ▼
execute_task(task_id)                                       execute_task.py:150
   with db.app.app_context():
     task = Task.query.get(task_id)
     if not task:  apscheduler_job.remove()   # 自删孤儿 job（对账）  execute_task.py:154-156
     else:
        metadata = handle_metadata()
        TaskExecutor(task_id, task.name, url_scrapydweb,
                     url_schedule_task='/1/schedule/task/',  ← 来自 metadata 默认值
                     url_delete_task_result, auth,
                     selected_nodes=json.loads(task.selected_nodes))
        task_executor.main()
   ▼
TaskExecutor.main()                                         execute_task.py:42-61
   get_task_result_id()      # 先插一条 TaskResult 拿到 id
   for nodes in [selected_nodes, nodes_to_retry]:           # 两轮：首发 + 重试
       for node in nodes:
           schedule_task(node)                              execute_task.py:75-104
              url = re.sub('/1/' → '/N/', url_schedule_task) # 节点号改写
              js = get_response_from_view(url, ...)          # test_client 进程内 POST
              失败 → 加入 nodes_to_retry, 延迟 3 秒重试一次   execute_task.py:38,49-51,91-94
           db_insert_task_job_result(js)   # 写 TaskJobResult（每节点）
   db_update_task_result()    # 回填 fail_count / pass_count
   ▼
/N/schedule/task/  → ScheduleTaskView.dispatch_request()    schedule.py:627-642
   task = Task.query.get(task_id)
   data = {project, _version, spider, jobid} + settings_arguments
   make_request('http://<node-N scrapyd>/schedule.json', data)   ← 最终落点
   ▼
scrapyd 启动爬虫
```

要点【现状】：

- **节点号 1 硬编码**：`url_schedule_task` 默认 `'/1/schedule/task/'`（`models.py:29`、`execute_task.py:165`），`TaskExecutor.schedule_task` 用正则把 `/1/` 替换成 `/N/`（`execute_task.py:82`，`REPLACE_URL_NODE_PATTERN = ^/(\d+)/`）。
- **失败重试**：每个节点首发失败入 `nodes_to_retry`，整体延迟 `sleep_seconds_before_retry=3` 秒后**统一重试一次**（`execute_task.py:38,44-52`），仍失败记为 `status='exception'`。
- **jobid 生成**：`TaskExecutor.__init__` 生成 `jobid='task_<task_id>_<时间戳>'`（`execute_task.py:31`）；但 `ScheduleTaskView` 实际用的是 `request.form['jobid']`（读取于 `schedule.py:624`，并在 `schedule.py:638` 写入 `self.data['jobid']`），由 `TaskExecutor.data` 通过 POST 传入。

### 8.3 管理流程（列表页状态推导）

`TasksView.process_tasks()`（`tasks.py:122-189`）对列表中每个 Task 调 `scheduler.get_job(str(task.id))` 推导 UI 状态：

| 条件 | 状态 | 可用动作 | next_run_time |
| --- | --- | --- | --- |
| 有 job 且 `next_run_time` 非空 | **Running** | pause / fire | 展示具体时间（若 scheduler 整体 PAUSED 则提示「Click DISABLED button first」） |
| 有 job 但 `next_run_time` 为空 | **Paused** | resume | N/A |
| 无对应 job | **Finished** | delete | N/A |

进入列表页时还会先调 `remove_apscheduler_job_without_task()`（`tasks.py:81,112-120`）做对账（见 §11.1）。

---

## 9. 启动与状态恢复

```
① import scrapydweb.utils.scheduler
     → scheduler.start(paused=True)                         scheduler.py:90
② create_app() → handle_db()
     → db.app = app   (后台线程 DB 入口)                    __init__.py:123
     → db.create_all()                                      __init__.py:125
③ check_app_config() 末尾「Apscheduler 段」                 check_app_config.py:286-332
     ├─ if metadata.scheduler_state != STATE_PAUSED:
     │       scheduler.resume()                             check_app_config.py:288-289
     ├─ add_job('jobs_snapshot', trigger='interval',
     │          seconds=JOBS_SNAPSHOT_INTERVAL,
     │          jobstore='memory', replace_existing=True)   check_app_config.py:306-309
     └─ add_job('delete_task_result', trigger='interval',
                seconds=CHECK_TASK_RESULT_INTERVAL,
                jobstore='memory', replace_existing=True)   check_app_config.py:329-332
```

要点【现状】：

- **持久化 cron 任务自动恢复**：用户定时任务在 `default`（SQLAlchemy）jobstore，进程重启后由 jobstore 自动加载，无需重新注册。
- **维护作业不持久化**：`jobs_snapshot` 与 `delete_task_result` 用 `jobstore='memory'`（`check_app_config.py:309,332`），每次启动靠 `replace_existing=True` 重新 `add_job`。它们与用户任务分属不同 store，`my_listener` 据此区分日志级别。
- **全局开关持久化**：`scheduler_state` 存在 `Metadata` 表（`models.py:33`），`enable_disable_scheduler()` 改它（`tasks.py:318`），重启时 `check_app_config` 读它决定是否 `resume()`。
- 这两个维护作业还展示了 `add_job` 的**另一种用法**：直接传 `func`（`create_jobs_snapshot` / `delete_task_result`）而非走 UI 表单——dopilot 新增内置周期作业可参考此法。

---

## 10. 暂停 / 恢复 / 触发 / 删除 逻辑

所有动作经 `TasksXhrView.generate_response()` 分发（`tasks.py:292-309`）：

| 动作 | 作用对象 | 实现 | 位置 |
| --- | --- | --- | --- |
| `enable` / `disable` | **整个 scheduler** | `scheduler.resume()` / `scheduler.pause()` + 持久化 `scheduler_state` | `tasks.py:311-319` |
| `pause` | 单个 job | `apscheduler_job.pause()` | `tasks.py:366-378` |
| `resume` | 单个 job | `apscheduler_job.resume()` | `tasks.py:366-378` |
| `remove`（Stop 按钮） | 单个 job | `apscheduler_job.remove()`（Task 保留） | `tasks.py:375-376` |
| `fire`（立即触发） | 单个 job | `apscheduler_job.modify(next_run_time=datetime.now())` | `tasks.py:353-364` |
| `delete`（带 task_id） | Task + job | 删 `apscheduler_job` + `db.session.delete(task)` | `tasks.py:333-351` |
| `delete`（带 task_result_id） | TaskResult | `db.session.delete(task_result)` | `tasks.py:321-331` |
| `delete`（无 id） | 批量清理 | `delete_outdated_task_results()` | `tasks.py:433-466` |

**两层状态【gotcha】**（`tasks.py:79-80,169-170`）：

```
scheduler 全局开关 (pause/resume)  ──►  冻结/恢复所有任务的触发，但保留各 job 的 next_run_time
        └─ 当 scheduler 处于 PAUSED 时，Running 任务显示 "Click DISABLED button first. "
单任务 pause/resume                 ──►  改 job 本身的 next_run_time
```

`fire` 的前置校验：job 不存在或 `next_run_time` 为空（已暂停）时拒绝（`tasks.py:354-361`）。

---

## 11. 进程内 Scheduler 的局限（dopilot 必读）

### 11.1 双存储手工对账

- 业务库（`Task/TaskResult/TaskJobResult`）与 APScheduler jobstore **完全独立**，靠 `str(Task.id)` 关联，无外键。
- 两处补偿逻辑修补不一致：
  - `TasksView.remove_apscheduler_job_without_task()`（`tasks.py:112-120`）：取 default jobstore 全部 job id 与 Task 表 id **求差集**，移除孤儿 job。
  - `execute_task()`（`execute_task.py:154-156`）：触发时若 Task 已删则**自删**对应 job。
- **改造提醒**：删除/编辑任务务必同时维护两边；新增任务类型若复用此模型，需保证 id 关联策略一致。

### 11.2 多进程 / reloader 重复触发

- `BackgroundScheduler` 跑在 Flask **同进程**的后台线程，因此：
  - **必须** `use_reloader=False`（`run.py:120`），否则 reloader 起两个进程导致作业重复执行 / 抢库。
  - **gunicorn 多 worker / 多进程部署会让每个 worker 各起一个 scheduler，造成重复触发**。【开放问题】生产部署需特别处理（见 §12）。

### 11.3 进程内 HTTP 而非真实网络

- `execute_task` → `get_response_from_view()`（`test_client`）→ `/N/schedule/task/` → 该路由再请求 scrapyd。
- 即「下发到节点」实为 scrapydweb **本机代理转发**到各 scrapyd，**不是**真正的分布式 worker 推送。dopilot 要真正 push 到远程 worker/容器，需替换这层进程内调用（见 §12「推模式」「新任务类型」）。

### 11.4 metadata URL 的 TODO 技术债

- `url_schedule_task` / `url_delete_task_result` / `url_jobs` 只有 `Metadata` 模型里的**默认值**（如 `/1/schedule/task/`，`models.py:29`），代码从未用 `handle_metadata(key, value)` 写入更新（`schedule.py:453-456` 是注释掉的 TODO）。
- `execute_task` 靠正则把 `/1/` 改写成目标 `/N/`（`execute_task.py:82`）。节点号 1 的硬编码是**已知技术债**，扩展路由时小心。

### 11.5 pickle 缓存非持久

- `SCHEDULE_PATH` 目录下的 pickle 在 `vars.py` 启动时被**清空**（`vars.py:59-66`，重启删除 `schedule/` 下文件，仅保留 `ScrapydWeb_demo.log`），内存 slot 也非持久。
- 若在 `ScheduleCheck` 与 `ScheduleRun` 两步之间重启进程，pickle 可能丢失导致 run 失败。

---

## 12. dopilot 改造扩展点（核心）

> 下表「目标」对应任务书 A/B 项。优先级为建议值。

| # | 目标 | 主要落点【现状】 | 改造建议 |
| --- | --- | --- | --- |
| 1 | 支持 interval / date 触发器 | `schedule.py:300`（`trigger='cron'`）、`schedule.py:189`、`schedule.html:547`、`models.py:105-112`（cron 字段 NOT NULL） | 改 `trigger=request.form.get('trigger')`；按类型组装 task_data（cron 用 `year..second`，interval 用 `weeks/days/hours/minutes/seconds`，date 用 `run_date`）；`add_job(**task_data)` 即可。需放宽 `Task` cron 字段为 nullable 并新增 interval/date 列 + 表单 |
| 2 | 节点策略「随机选一个执行」 | `execute_task.py:44,168`（遍历全部 selected_nodes） | `Task` 增 `node_strategy`（all\|random）列；`random` 时在 `execute_task()` 读 Task 后 `random.choice(selected_nodes)` 裁剪为单节点再传入 `TaskExecutor` |
| 3 | 新增类型：Docker 常驻爬虫 / 一次性脚本 | `execute_task.py:75-104`（只会 POST scrapyd schedule.json）、`models.py`（缺类型列）、`schedule.py:617-642`（scrapyd 专用） | `Task` 增 `task_type`（scrapy\|docker\|script）列；**抽象 Executor 接口**（`ScrapydExecutor` / `DockerExecutor` / `ScriptExecutor`），`execute_task` 按 `task_type` 选实现。docker 走容器编排 API（`docker run/exec` 或自建 agent），script 走脚本执行端点 |
| 4 | 推模式（push）主动下发 | `execute_task.py:82,88`（`/1/→/N/` + test_client）、`tasks.py:353-364`（fire） | 「指定节点 + fire 立即触发」即雏形。可复用 `TaskExecutor` 做不依赖定时器的「立即推送」端点；**把进程内 test_client 调用替换为对远程 worker agent 的真实网络下发** |
| 5 | 实时日志流 | `schedule.py:48-50` / `tasks.py:22-24`（仅 `send_file` 静态日志）、`scheduler.py:19`（写文件）、`views/files/log.py`（解析 scrapyd 日志） | 现状是文件下载式，非实时。新增 SSE / WebSocket 端点流式推送 `TaskExecutor`/scrapyd/容器日志；`TaskExecutor` 各阶段改为流式 `emit` 而非仅写文件 |
| 6 | i18n（当前界面/flash 英文硬编码） | `schedule.html` / `tasks.html` 模板、各视图 `flash()` / `js['tip']` / `msg` 英文串（如 `tasks.py:80,319,363`） | 引入 Flask-Babel，模板与视图字符串包 `gettext`，提供 zh 翻译。**无现成 i18n 框架，属新增**。任务书当前只需中文，建议预留 locale 切换 |
| 7 | jobstore 持久化后端切换 | `scheduler.py:31-34`、`setup_database.py`（计算 URI） | 改 `DATABASE_URL` 即可让 jobstore 走 MySQL/PG；如需 Redis 可把 default jobstore 换 `apscheduler.jobstores.redis`（随包提供）；executor 可换 `ProcessPoolExecutor`（`scheduler.py:7,37` 已留注释） |
| 8 | 任务结果保留策略 | `check_app_config.py:311-332`、`tasks.py:433-466`、配置 `CHECK_TASK_RESULT_INTERVAL` / `KEEP_TASK_RESULT_LIMIT` / `KEEP_TASK_RESULT_WITHIN_DAYS` | 调配置或改 `delete_outdated_task_results` 过滤条件；`JOBS_SNAPSHOT_INTERVAL` 控快照频率 |

### 12.1 多进程部署的开放问题【开放问题】

§11.2 指出多 worker 会重复触发。dopilot 可选方案（需决策）：

1. **单独的调度进程**：把 scheduler 从 Web 进程剥离为独立守护进程（Web 进程只读写 DB / 下发指令），从根上消除多副本。
2. **分布式锁 / 选主**：多 worker 中仅一个持锁运行 scheduler（如基于 Redis/DB 选主）。
3. **维持单进程**：Web 用单 worker，下发改为对远程 agent 的真实网络调用（与 #3/#4 改造一致）——这是与「真正分布式」目标最契合的方向。

### 12.2 推荐的核心抽象（与 #3/#4 配合）

```
execute_task(task_id)
   └─ 读 Task → 按 task.task_type 选 Executor
        ┌──────────────┬───────────────────┬────────────────────┐
   ScrapydExecutor   DockerExecutor      ScriptExecutor        (现状仅第一个，
   POST schedule.json  docker run/exec /   远程脚本执行端点       内联在 TaskExecutor)
   (现 TaskExecutor)   编排 API / agent
        └──────────────┴───────────────────┴────────────────────┘
                按 node_strategy(all|random) 决定下发节点集合
                结果统一写 TaskResult / TaskJobResult
```

将「下发」从 `TaskExecutor.schedule_task`（`execute_task.py:75-104`）抽象为可插拔 Executor，是支撑 Docker 常驻爬虫与一次性脚本最干净的切入点。Docker 常驻进程与「一次跑完即退」的语义差异（如健康检查、是否记 finish、重复触发时已在运行的处理）也应在各 Executor 内部约定。

---

## 13. 配置项速查

| 配置项 | 默认 | 含义 | 读取处 |
| --- | --- | --- | --- |
| `JOBS_SNAPSHOT_INTERVAL` | 300 | jobs 快照抓取周期（秒） | `baseview.py:118`、`check_app_config.py:292-309` |
| `CHECK_TASK_RESULT_INTERVAL` | 300 | 清理旧 TaskResult 的周期（秒） | `baseview.py:119`、`check_app_config.py:311-332` |
| `KEEP_TASK_RESULT_LIMIT` | 1000 | 保留 TaskResult 条数上限 | `baseview.py:120`、`tasks.py:437-449` |
| `KEEP_TASK_RESULT_WITHIN_DAYS` | 31 | TaskResult 保留天数 | `baseview.py:121`、`tasks.py:451-466` |
| `DATABASE_URL` | `''`→SQLite | 决定 jobstore 与业务库后端 | `setup_database.py`、`vars.py:72-74` |

`SCHEDULER_STATE_DICT`（`vars.py:116-120`）：`STATE_STOPPED=0`、`STATE_RUNNING=1`、`STATE_PAUSED=2`。

---

## 14. 改造时务必保留的不变量（checklist）

- [ ] `execute_task` 保持**模块级函数**，否则 jobstore 无法 pickle。
- [ ] DB 操作保持 `with db.app.app_context()` 包裹（线程安全 + SQLite 线程限制）。
- [ ] `use_reloader=False`；多进程部署前先决策 §12.1。
- [ ] 删除/编辑任务时**同时**维护业务库与 apscheduler jobstore（关联键 `str(Task.id)`）。
- [ ] `coalesce` 存字符串、`misfire_grace_time=0→None`、`max_instances≥1` 等清洗规则（`schedule.py:283-328,443`）与模型保持一致。
- [ ] 新增触发器/任务类型时，同步改三处：**后端组包逻辑、`Task` 模型、表单模板**。
