# scrapydweb 架构总览

> 本文是 dopilot 的**行为参考起点文档**，面向后续在 dopilot 全新复刻这些行为语义的工程师。内容基于对 scrapydweb 1.6.0 参考代码的逐文件核实。
>
> 阅读约定：
> - **现状事实**：当前代码确实如此（已标注 `file:line`，可自行复核）。
> - **行为参考 / 开放问题**：dopilot 全新复刻其行为语义时的方向性意见，尚未落地，可讨论推翻。
> - 所有 `file:line` 路径均**相对上游 scrapydweb 1.6.0 / commit `1341cf9`**（如 `scrapydweb/run.py` 即上游 `scrapydweb/run.py`；本仓库不保留本地快照）。

> **【scrapydweb 参考边界】** 整个 `docs/architecture/` 树是 **scrapydweb 现状的功能层 / 行为参考**与**测试 oracle**；其代码写法、目录结构、模块划分、命名、依赖、配置形态**一律不得作为 dopilot 的设计依据**。本树中任何指向 scrapydweb 源文件的「改造建议」（如「在 `scrapydweb/...` 下新建 / 改 `models.py` / 改 `default_settings.py`」），都应理解为「dopilot 在 `apps/server/dopilot_server/...`（或 `apps/agent`）下**全新实现**该行为」，而**不是**去改 scrapydweb 文件、也不照搬其结构；保留的 `file:line` 仅作行为参考引用。dopilot 为 greenfield、按 `apps/`+`packages/` 自有领域 structure-first 设计（权威布局见 [`docs/dopilot/05-dev-setup-and-known-issues.md`](../dopilot/05-dev-setup-and-known-issues.md) §1），**不对 scrapydweb 做改名 / git mv**。详见 [`docs/dopilot/00-requirements.md`](../dopilot/00-requirements.md) 决策表。

---

## 1. scrapydweb 是什么 · 技术栈

**scrapydweb 是一个 [scrapyd](https://scrapyd.readthedocs.io/) 集群的 Web 管理面板。** 它本身不执行爬虫，而是作为一个集中式控制台，通过 HTTP 与多台 scrapyd 节点通信：部署项目（egg）、下发/停止爬虫、查看作业（jobs）、解析日志统计、设置定时任务、并在异常时发邮件 / Slack / Telegram 告警。一句话：**scrapydweb = scrapyd 集群的「调度 + 监控 + 可视化」前台**。

dopilot 的目标是在这套现成框架上扩展出三类被调度对象（Scrapy 爬虫 / Docker 常驻进程 / 一次性 Python3 脚本），并补齐实时日志流、灵活定时、节点选择策略、推模式下发与中文 i18n。详见 [`docs/dopilot/00-requirements.md`](../dopilot/00-requirements.md)。

| 层 | 技术 | 说明（现状事实） |
| --- | --- | --- |
| Web 框架 | **Flask 2.0.0**（钉死） | app factory 模式 `create_app()`；绝大多数页面是 `MethodView` 子类，仅 3 个真 Blueprint。`setup.py` |
| ORM / 持久化 | **Flask-SQLAlchemy 2.4.0 + SQLAlchemy 1.3.24** | 单一 `db` 实例 + 多 `bind`（4 个逻辑库）。默认 SQLite，可切 MySQL/PostgreSQL。`scrapydweb/models.py` |
| 定时调度 | **APScheduler 3.6.0** `BackgroundScheduler` | `SQLAlchemyJobStore` 持久化 + `MemoryJobStore` + `ThreadPoolExecutor(20)`。`scrapydweb/utils/scheduler.py` |
| 被调度后端 | **scrapyd**（外部服务） | 每节点暴露固定 JSON API（schedule/cancel/listprojects…）。scrapydweb 只是 HTTP 客户端。 |
| 日志统计 | **logparser**（外部 daemon） | 在每台 scrapyd 主机上运行，把 `.log` 解析成 `.json`；scrapydweb 拉取或读本地文件。`scrapydweb/utils/sub_process.py` 拉起 `python -m logparser.run` |
| HTTP 服务器 | **werkzeug 内置开发服务器** | `app.run(..., use_reloader=False)`，**非生产级**（见第 6 节）。`scrapydweb/run.py:119` |
| 前端 | Jinja2 SSR + 原生 JS/jQuery + Vue2/Element-UI 混用 | 多页应用（MPA），静态资源按版本目录 `static/v160/`。无 i18n。 |
| 其他依赖 | Flask-Compress、requests（全局连接池 1000） | — |

> **行为参考**：`setup.py` 把所有依赖版本严格钉死（Flask==2.0.0、Werkzeug==2.0.0、SQLAlchemy==1.3.24、APScheduler==3.6.0…）。引入 Flask-Babel / Docker SDK 等新依赖时务必验证与这些旧版本的兼容性，尤其 Flask 2.0 / Werkzeug 2.0 与较新扩展易冲突。

---

## 2. 架构图（ASCII）

```
                          ┌──────────────────────────────────────────────────────┐
                          │                      浏览器（用户）                      │
                          │   MPA: base.html + 各页面(Vue2/原生JS) + 多节点 fan-out  │
                          └───────────────┬──────────────────────────────────────┘
                                          │ HTTP(S)  (HTTP Basic Auth, 单账号)
                                          │ ※多节点"批量执行"靠浏览器 JS 逐节点发 XHR
                                          ▼
   ┌─────────────────────────────────────────────────────────────────────────────────────┐
   │                        Flask 进程  (werkzeug 开发服务器, 多线程)                          │
   │                                                                                       │
   │  run.py:main()                                                                         │
   │   └─ @before_request require_login()  ← 唯一全局认证关卡 (run.py:51)                     │
   │                                                                                       │
   │  路由层 (handle_route, __init__.py)                                                     │
   │   ├─ MethodView 子类 (绝大多数)  URL 前缀 /<int:node>/...                                │
   │   │    overview / dashboard / operations / files / utilities / system / index / api    │
   │   └─ 3 个真 Blueprint: tasks / schedule / parse (仅 history/source 子路由)               │
   │                                  │                                                     │
   │        BaseView.__init__: node→SCRAPYD_SERVER/AUTH/GROUP/PUBLIC_URL                    │
   │                                  │                                                     │
   │        BaseView.make_request() ──┼──── HTTP ───►  ┌─────────────┐ ┌─────────────┐      │
   │        (统一 scrapyd 调用封装)     │                │  scrapyd #1  │ │  scrapyd #N  │ ...  │
   │                                  │                │  /schedule.json│ │  /jobs       │      │
   │                                  │                │  + logparser   │ │  + logparser │      │
   │                                  │                └─────────────┘ └─────────────┘      │
   │                                  │                                                     │
   │  ┌───────────────────────────┐   │   ┌──────────────────────────────────────────┐    │
   │  │ APScheduler 后台线程         │   │   │ 多库持久化 (Flask-SQLAlchemy, 4 bind)        │    │
   │  │ scheduler.start(paused=True)│  └──►│  • apscheduler  (jobstore, 独立)            │    │
   │  │ (scheduler.py import 时启动) │      │  • timertasks   (Task/TaskResult/...)       │    │
   │  │  到点→ execute_task(task_id) │─────►│  • metadata     (单行: pid/state/账号...)    │    │
   │  │  → TaskExecutor 逐节点下发    │      │  • jobs         (每 scrapyd 节点一张表)       │    │
   │  └───────────────────────────┘      └──────────────────────────────────────────┘    │
   └───────┬──────────────────────────────────────────────────────────┬──────────────────┘
           │ Popen (prctl: 父死子亡)                                    │ Popen
           ▼                                                            ▼
   ┌─────────────────────┐                                  ┌─────────────────────────┐
   │ poll 子进程 (poll.py) │                                  │ logparser 子进程          │
   │ 每 POLL_*s 抓 /jobs   │── 反向 POST /<node>/log/stats ─► │ python -m logparser.run   │
   │ HTML→正则→触发告警     │   (回调本应用, 触发 monitor_alert) │ (各 scrapyd 主机本地解析)   │
   └─────────────────────┘                                  └─────────────────────────┘
```

**关键非直觉点（现状事实）：**
- 服务端**没有**多节点并发聚合。读写操作每请求只打一个 node；"对所有节点执行并汇总"是浏览器 JS 逐节点 XHR 完成的（`templates/scrapydweb/multinode_results.html` 的 `fireXHR`）。**唯一**在服务端做多节点串行下发的是定时任务执行器 `TaskExecutor`（`views/operations/execute_task.py`）。
- APScheduler 在 `utils/scheduler.py:90` **import 时**就 `scheduler.start(paused=True)`，不是在 `main()` 里显式启动。
- 三个后台执行体的生命周期都绑定主进程 pid：APScheduler 线程、poll 子进程、logparser 子进程。
- 图中 `Popen(prctl: 父死子亡)` 的 prctl 机制**仅 Linux 生效**（`sub_process.py:115` 判 `platform.system()=='Linux'`）；非 Linux 退化为普通 Popen，清理可能不彻底。dopilot 决策 server/agent 均 Docker(Linux) 部署，此点不受影响。

---

## 3. 请求与数据生命周期

### 3.1 一次普通页面请求（如 Jobs 看板）

```
浏览器 GET /1/jobs/
  → run.py @before_request require_login()           # 可选 HTTP Basic Auth
  → handle_route 注册的 URL 规则匹配 → JobsView(MethodView)
  → BaseView.__init__: self.node=1, assert 0<node<=AMOUNT,
                       取 SCRAPYD_SERVERS[0]/AUTHS[0]/..., update_g() 注入菜单
  → dispatch_request(): make_request('http://<host:port>/jobs.json', auth=...)
       ↳ 全局 requests.Session(连接池1000), 统一注入 url/auth/status_code/when
  → render_template('scrapydweb/jobs.html', ...)      # context_processor 注入 static_*/版本号
  → 返回 HTML（部分端点如 ?listjobs / log?opt=report 直接返回 JSON）
```

### 3.2 配置加载生命周期（4 层 + 1 导入期旁路）

| 阶段 | 来源 | 优先级 | 位置（现状事实） |
| --- | --- | --- | --- |
| 旁路 | 导入期直接 `import_module('scrapydweb_settings_v11')` 只取 `DATA_PATH`/`DATABASE_URL` | 早于 app.config | `scrapydweb/vars.py` |
| 1 | `from_mapping(SECRET_KEY='dev')` + `from_object('scrapydweb.default_settings')` | 最低 | `__init__.py:create_app` |
| 2 | `from_pyfile('config.py', silent=True)`（instance 目录，一般不用） | ↓ | `__init__.py:create_app` |
| 3 | cwd 的 `scrapydweb_settings_v11.py`（用户自定义） | ↓ | `run.py:load_custom_settings` |
| 4 | CLI 参数 `-b/-p/-ss/-da/-dc/-dlp/-sw/-dm/-d/-v` | **最高** | `run.py:update_app_config` |

加载后 `check_app_config()`（`utils/check_app_config.py`）做断言校验、解析 `SCRAPYD_SERVERS` 成 4 个并行列表、按节点建 jobs 表、`scheduler.resume()`、注册内置定时 job、`init_subprocess()` 起子进程。**校验失败 → `sys.exit`。**

> **开放问题**：`DATA_PATH`/`DATABASE_URL` 有**两条独立读取路径**（导入期 vars.py 直读自定义文件 + app.config 链）。改这两个键必须同时照顾两处，否则数据目录/库位置与预期不一致。

### 3.3 定时任务生命周期（dopilot 需复刻其行为语义的核心面）

```
创建: Schedule 表单 → ScheduleCheckView(/schedule/check, pickle 暂存)
      → ScheduleRunView(/schedule/run)
          ├─ db_process_task()  → 写 Task 行 (timertasks 库)
          └─ add_update_task()  → scheduler.add_job(execute_task, id=str(task_id),
                                    kwargs={'task_id':id}, **task_data)
                                  ↳ 序列化进 APScheduler 自己的 jobstore (apscheduler 库)
                                    [两套存储! 仅靠 job.id == str(Task.id) 软关联, 无外键]

触发: BackgroundScheduler 线程到点 → execute_task(task_id)
      → with db.app.app_context(): 查 Task (不存在则自删 apscheduler_job)
      → TaskExecutor.main(): 遍历 task.selected_nodes
          → get_response_from_view('/<N>/schedule/task/')  # Flask test_client 进程内自调用
              → ScheduleTaskView → make_request 到该节点 scrapyd /schedule.json
          → 失败节点入 nodes_to_retry, 延迟 3s 重试一次
      → 写 TaskResult(汇总) + 每节点一行 TaskJobResult(明细)

管理: TasksView 对每 Task 调 scheduler.get_job() 推导 Running/Paused/Finished
      TasksXhrView: enable/disable(整 scheduler) · pause/resume/remove(单 job)
                    · fire(modify next_run_time=now) · delete(删 Task + job)
```

> **现状事实（重要技术债）**：`trigger` 在 `schedule.py` 里被**硬编码为 `'cron'`**（`update_data_for_timer_task`、`update_kwargs`），`Task` 表只有 cron 字段（`year..second`，且 NOT NULL）。要支持 interval/date 必须同时改①后端组包逻辑 ②`Task` 模型 ③表单模板三处。

### 3.4 数据落点速查

| 数据 | bind | 表 | SQLite 文件 |
| --- | --- | --- | --- |
| APScheduler 序列化作业 | `apscheduler`（独立 JobStore，**非 ORM**） | `apscheduler_jobs` | `apscheduler.db` |
| 定时任务定义 + 执行结果 | 默认（`SQLALCHEMY_DATABASE_URI`） | `task` / `task_result` / `task_job_result` | `timer_tasks.db` |
| 应用级元数据/状态（单行） | `metadata` | `metadata`（pid、scheduler_state、账号、url_*…） | `metadata.db` |
| 每节点作业快照 | `jobs` | 运行时按节点动态建表 | `jobs.db` |

> **现状事实**：**无任何数据库迁移机制**（`models.py` 顶部明确 `TODO: Database Migrations`，无 Alembic）。建表全靠 `db.create_all()`（`CREATE TABLE IF NOT EXISTS`），改列不会 ALTER 旧表。详见 [`02-models.md`](02-models.md)。

---

## 4. 子系统清单

> 下表是 8 个子系统的索引。每个子系统在本目录有独立文档（见第 5 节导航）。

| # | 子系统 | 职责 | 关键文件 / 目录（现状事实） |
| --- | --- | --- | --- |
| 1 | **应用启动与 CLI**（bootstrap） | 进程入口、app factory、配置分层、CLI 解析、注册钩子、起服务与子进程/调度器 | `scrapydweb/run.py`、`scrapydweb/__init__.py`、`scrapydweb/vars.py`、`setup.py`、`utils/check_app_config.py` |
| 2 | **配置与设置**（config） | 4 层配置加载/覆盖、断言校验、派生节点列表、被 BaseView 读到实例属性 | `scrapydweb/default_settings.py`、`run.py`、`utils/check_app_config.py`、`views/baseview.py`、`views/system/settings.py` |
| 3 | **数据模型与持久化**（models） | 4 库多 bind ORM、Metadata/Task/TaskResult/动态 Job、APScheduler JobStore | `scrapydweb/models.py`、`utils/setup_database.py`、`__init__.py:handle_db` |
| 4 | **调度与定时引擎**（scheduler） | APScheduler 单例、cron 定时、多节点下发、任务结果记录 | `utils/scheduler.py`、`views/operations/schedule.py`、`views/operations/execute_task.py`、`views/overview/tasks.py` |
| 5 | **Web 视图与路由**（views） | Flask Web 层：MethodView/Blueprint 注册、`/<int:node>/` 路由、页面与 JSON 端点 | `scrapydweb/views/`（overview/dashboard/operations/files/utilities/system）、`__init__.py:handle_route` |
| 6 | **scrapyd 集群集成**（cluster） | 与多 scrapyd 节点的 HTTP 通信、节点寻址、fan-out、日志统计拉取 | `views/baseview.py`、`views/api.py`、`views/overview/multinode.py`、`utils/poll.py`、`views/files/log.py` |
| 7 | **前端模板与静态资源**（frontend） | Jinja2 SSR MPA、布局/导航/菜单、Vue2+Element-UI、静态资源版本目录 | `scrapydweb/templates/`、`scrapydweb/static/v160/`、`__init__.py:handle_template_context` |
| 8 | **认证、安全与跨切面工具**（auth） | 全局 Basic Auth、后台子进程、邮件/IM 告警、共享 helper | `run.py:require_login`、`scrapydweb/common.py`、`utils/sub_process.py`、`utils/send_email.py`、`views/files/log.py` |

### dopilot 需复刻的行为面一览

> **【已被通信重构取代 · superseded-by】** 本表「实时日志流」与「推模式下发」两行的 dopilot 实现口径，以 [`../refactor/00-redis-streams-agent-communication.md`](../refactor/00-redis-streams-agent-communication.md) 为准：server→agent 改为 server `XADD` 命令到 Redis Streams、agent 主动消费；实时日志改为 agent 主动 `XADD` 日志增量到 Redis log stream、server 消费后落盘 + SSE 推 Web，不再由 server 主动 pull agent tail。其余行不受影响。

| 需求 | 现状（事实） | 对应行为所在的 scrapydweb 参考文件（dopilot 在 apps/ 全新复刻） |
| --- | --- | --- |
| 三类被调度对象 | 全部硬编码假定下游是 scrapyd `*.json` | `views/api.py`、`baseview.make_request`、`execute_task.py`（抽象 Executor 接口：Scrapyd/Docker/Script） |
| 实时日志流 | **非真流式**：整段抓取 + 前端定时 reload | dopilot v1（决策#11）：日志回流走 **Redis log stream**——agent 主动 `XADD` 增量到 `dopilot:server:logs`，server 消费后正文落 `/server-data/logs`、索引/offset/状态落 PG，再经 **server→web SSE** 推 Vue（不引入 WebSocket）；`LogSource` 抽象保留，实现由 `AgentTailLogSource` 换 `RedisLogSource`。详见 [`../refactor/00-redis-streams-agent-communication.md`](../refactor/00-redis-streams-agent-communication.md) |
| 定时 cron/interval | APScheduler 原生支持，但 UI/后端**硬编码 cron** | `schedule.py`（`update_data_for_timer_task`/`update_kwargs`）+ `Task` 模型 + 表单 |
| 节点选择策略 | 已有"指定节点全部执行"；**无"随机一个"** | `baseview.get_selected_nodes`、`execute_task.TaskExecutor.main`、`Task` 加 `node_strategy` 字段 |
| 推模式下发 | 已有雏形（定时器进程内自调用），但**是本机代理转发**非真分布式 | dopilot：server 在同一 PG 事务写 execution/attempt/`command_outbox`，再由 dispatcher `XADD` `run` 命令到 `dopilot:agent:{agent_id}:commands`，agent 主动消费启动（即 `BaseExecutor.run_on_node` 由 POST /run 改为 XADD command）；**不再走 server→agent 直连 HTTP 下发**。详见 [`../refactor/00-redis-streams-agent-communication.md`](../refactor/00-redis-streams-agent-communication.md) |
| i18n（中文） | **完全缺失**：无 Flask-Babel，文案硬编码英文（模板 + JS） | dopilot i18n 走**前端 vue-i18n**(`apps/web`,见 `../dopilot/04-gap-i18n.md`),**不接 Flask-Babel/后端 gettext** |
| 真实用户体系 | 单账号全有/全无，无 session/角色，账号明文存 Metadata | `run.py:require_login` + `common.authenticate`，需同步内部互调凭证 |

---

## 5. 本目录其它文档导航

> 以下为 `docs/architecture/` 的子系统深入文档（本文是入口）。

| 文档 | 内容 |
| --- | --- |
| **`00-overview.md`**（本文） | 架构总览、技术栈、架构图、生命周期、子系统清单 |
| [`01-bootstrap-and-cli.md`](01-bootstrap-and-cli.md) | 启动序列、app factory、CLI 参数、配置覆盖编排 |
| [`02-config.md`](02-config.md) | 配置 4 层加载、断言校验、节点列表解析、消费链 |
| [`02-models.md`](02-models.md) | 多库多 bind、ORM 模型、两套持久化、迁移缺失 |
| [`03-scheduler.md`](03-scheduler.md) | APScheduler、定时任务全生命周期、cron 硬编码 |
| [`04-views-and-routes.md`](04-views-and-routes.md) | MethodView/Blueprint 路由、节点维度、页面 vs JSON |
| [`05-cluster.md`](05-cluster.md) | scrapyd HTTP 集成、节点寻址、fan-out、poll/logparser |
| [`06-frontend.md`](06-frontend.md) | 模板/静态资源、导航菜单、Vue 注入、品牌/i18n 切入 |
| [`07-auth-and-crosscutting.md`](07-auth-and-crosscutting.md) | Basic Auth、后台子进程、告警链路、跨切面工具 |

> 文件名为占位约定，具体编号以实际落盘为准；尚未撰写的章节视为 **TODO**。

### 相关产品/改造文档（`docs/dopilot/`）

| 文档 | 内容 |
| --- | --- |
| [`docs/dopilot/00-requirements.md`](../dopilot/00-requirements.md) | 需求与目标（北极星文档） |
| [`docs/dopilot/05-dev-setup-and-known-issues.md`](../dopilot/05-dev-setup-and-known-issues.md) | 开发环境搭建与已知兼容性问题 |
| [`docs/dopilot/06-frontend-rewrite.md`](../dopilot/06-frontend-rewrite.md) | 前端整体重构方案（阶段 2.1 起为 Next.js 静态导出 + shadcn/ui） |

---

## 6. 全局注意事项（dopilot 复刻行为前必读的 gotchas）

> 这些是 dopilot 复刻其行为语义时容易"踩坑"的 scrapydweb 现状事实，集中前置。

1. **生产服务器**：`app.run()`（`run.py:119`）用的是 werkzeug 开发服务器，`use_reloader=False` 写死。dopilot 生产化使用 FastAPI/uvicorn 且固定 `workers=1`；**BackgroundScheduler 在多 worker 下会被重复启动**，所以 dopilot 明确不支持多 worker/多副本。
2. **调度器 import 时启动**：`utils/scheduler.py:90` 模块级 `scheduler.start(paused=True)`。只要 import 了 scheduler（baseview/execute_task/check_app_config 都 import）调度器就已运行，`check_app_config` 仅 resume。别误以为能在 `main()` 控制其生命周期。
3. **强制 scrapyd 连通性断言**：`check_app_config.py:429` `assert any(results)`，所有 `SCRAPYD_SERVERS` 都连不上 → `sys.exit`。dopilot 支持非 scrapyd 对象时，无 scrapyd 环境会直接启动失败，需 `-dc/--disable_check_scrapyd` 或在复刻该行为时去掉这一硬断言。
4. **首次运行强制退出**：`load_custom_settings` 找不到 cwd 下 `scrapydweb_settings_v11.py` 会拷模板并 `sys.exit`，首次跑不会真起服务。
5. **import 期重副作用**：`vars.py` 在 import 阶段就 mkdir、`setup_database()`、清理 PARSE/DEPLOY/SCHEDULE 目录、建历史日志。二次封装/单测 import 即触发文件系统与 DB 操作，难以纯函数化。
6. **节点编号会漂移**：`check_scrapyd_servers` 对 `SCRAPYD_SERVERS` 做 `sorted(set(...))` 重排，`node` 是 1-based 索引（排序后顺序），增删节点会导致编号漂移，已存任务的 `selected_nodes` 可能指向错节点。
7. **两套配置文件机制**：`from_pyfile('config.py')`（instance）与 cwd 的 `scrapydweb_settings_v11.py`（用户真正用的）并存，易混淆。
8. **Jinja 变量定界符被改**：`__init__.py:100-101` 改成 `'{{ '` / `' }}'`（**带空格**），新增模板必须遵循，否则变量不渲染。
9. **`SECRET_KEY='dev'` 硬编码**：`create_app` 里写死，生产/私有部署必须覆盖为安全随机值。
10. **APScheduler timezone 被注释掉**：`scheduler.py:45`（用系统默认时区）。dopilot 加 cron 调度前最好显式设定时区，避免容器内 UTC 踩坑。
11. **账号明文 + 凭证泄露点**：Metadata 表明文存 username/password；`start_poll` 把账号密码作为命令行参数明文传给 poll 子进程（`ps` 可见）。
12. **外网埋点**：jobs/servers 等页面内嵌对 `my8100.pythonanywhere.com/check_update` 的请求与 GitHub buttons，私有化 dopilot 应移除，否则内网环境有失败请求与隐私外泄。
