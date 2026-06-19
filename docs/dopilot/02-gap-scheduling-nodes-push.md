# 改造分析：定时任务 + 节点调度策略 + 推模式

> 面向后续改造工程师。本文聚焦 dopilot 改造目标中的 **B-2（定时任务）**、**B-3（节点选择策略）**、**B-4（推模式）** 三块，并牵连 **A-1/A-2/A-3（三类被调度对象）** 在调度与下发层面的影响。
>
> 阅读约定：
> - **【现状事实】** = 已通过 Read/Grep 在代码中核实，标注 `file:line`。
> - **【改造建议】 / 【开放问题】** = 设计推断，未实现，需决策。
> - 本文所有 scrapydweb 路径均指 `reference/scrapydweb/` 下的只读基线，行号以核实当日为准，后续会漂移，请以符号名（函数/类名）为准。

> **【scrapydweb 参考边界】** scrapydweb 仅作**功能层/行为参考**与**测试 oracle**；其代码写法、目录结构、模块划分、命名、依赖、配置形态**一律不得作为 dopilot 的设计依据**。dopilot 为 greenfield、按 `apps/`+`packages/` 自有领域 structure-first 设计（权威布局见 `05-dev-setup-and-known-issues.md` §1），**不对 scrapydweb 做改名/git mv**。本文所有 scrapydweb `file:line` 均为**行为参考引用**而非 dopilot 的待改文件；前端为 SPA greenfield（`apps/web`，直连 `/api/v1`），**无 Jinja 新旧共存式 strangler**；dopilot 自带 `migrations/`（**裸 Alembic**，SQLAlchemy + Alembic，非 Flask-Migrate——FastAPI 无 Flask app），模型演进走迁移，**不继承** scrapydweb「无 Alembic、手工 ALTER、删库重建」的形态；**PostgreSQL 为唯一库**（替换 scrapydweb 多 SQLite），APScheduler jobstore 也落 PG。详见 `00-requirements.md` 决策表。

---

## 0. 一页速览（TL;DR）

| 主题 | 现状一句话 | 核心缺口 | 推荐落地 |
|---|---|---|---|
| B-2 定时引擎 | APScheduler 单例已可用，但 trigger 硬编码 `cron` | interval/date 未通；回调写死 scrapyd | **方案A**（解硬编码 + 加 interval/date 字段），再叠 **方案B**（task_type + Executor 抽象） |
| B-3 节点策略 | 只有「指定单节点」「勾选多节点全部」 | 无「随机选一个」；策略不持久化；节点序号会漂移 | **方案A**（Task 加 `node_strategy`，触发时动态归约），并提前消化稳定节点 ID |
| B-4 推模式 | scrapydweb 对 scrapyd 是真 HTTP 推；平台内部是「进程内自调用」fan-out | 无远程 worker agent 通道；无独立「一键推送」端点 | **方案D**（Executor 抽象 + 独立即时推送端点 + agent 协议）。**dopilot v1：所有下发（含 scrapy/scrapyd）一律经 dopilot-agent，server 不直连裸 scrapyd** |

> 关键事实校正（与需求输入相比）：`Task` 模型 **已有 `trigger` 列**（`models.py:94`，注释 `# cron, interval, date`）与 **`timezone` 列**（`models.py:117`，nullable）。即「加 trigger 列」无需做，列已在，只是被代码层硬编码忽略；timezone 列也已在，缺的是把它接进 scheduler。

---

## 1. 现状全景图

```
                         ┌──────────────────────────────────────────────┐
                         │  Flask App (scrapydweb 进程)                  │
                         │                                              │
  用户表单 ───────────►  │  schedule.py: ScheduleCheckView /            │
  (schedule.html)        │              ScheduleRunView                 │
                         │     │ update_data_for_timer_task()           │
                         │     │ db_process_task()  ──► reference SQLite(Task) │
                         │     │ add_update_task()  ──► scheduler.add_job│
                         │     ▼                                        │
                         │  utils/scheduler.py                          │
                         │   BackgroundScheduler 单例 (start paused)    │
                         │   ├ SQLAlchemyJobStore (持久化, 跨重启恢复) │
                         │   ├ MemoryJobStore (2 个内置 interval 维护作业)│
                         │   └ ThreadPoolExecutor(20)                   │
                         │            │ 到点回调                        │
                         │            ▼                                 │
                         │  execute_task.py: execute_task(task_id)      │
                         │   TaskExecutor.main()                        │
                         │    for node in selected_nodes:  (串行)       │
                         │       schedule_task(node)                    │
                         │         get_response_from_view(...)  ◄─ 进程内│
                         │            │  test_client 自调用 /N/schedule/task/
                         │            ▼                                 │
                         │  ScheduleTaskView ──► make_request()         │
                         └────────────┼─────────────────────────────────┘
                                      │ 真·HTTP POST
                                      ▼
                         http://<server>/schedule.json   (scrapyd 节点)
```

要点（均为【现状事实】）：
- **「推」只对 scrapyd 成立**：`make_request` 真 HTTP POST 到各 scrapyd（`baseview.py:285`）。
- **平台内部多节点编排是「进程内自调用」**：`get_response_from_view` 走 Flask `test_client`（`common.py:48-80`），并非对远程 worker 的网络推送。
- **状态采集是「拉」**：`poll.py` 子进程定期 GET 各 scrapyd `/jobs`。

> **以上是 scrapydweb 基线现状（server 进程直连各 scrapyd）。dopilot v1 链路不同**：server 不直连裸 scrapyd，而是 server → dopilot-agent → 本机 scrapyd（详见 §4.3）。**【superseded-by `docs/refactor/00-redis-streams-agent-communication.md`】** 通信重构后，scrapydweb 这套「server 主动连接、server 拉」语义在 dopilot 侧两处发生反转，不再代表 dopilot v1 当前口径：① 日志链路由「server 按 offset 从 agent tail API pull」反转为「agent 经 Redis log stream 主动 XADD 日志增量、server 消费后落盘」（仍无 WebSocket、仍 server→web SSE；详见 §8.3）；② 节点健康由「server 轮询 agent `/health`」反转为「agent 主动 POST `/heartbeat`，server 以 `now - nodes.last_seen_at <= heartbeat_timeout_seconds` 判健康」，`/health` 降级为容器本地 healthcheck。下文以下各节凡述及 server 主动 HTTP run/status/tail、server 轮询 `/health`、agent 不主动推/不回连者，均以该 refactor 文档为准。

---

## 2. B-2 定时任务引擎

### 2.1 可复用项（已核实）

| 复用组件 | 文件:行 | 说明 |
|---|---|---|
| BackgroundScheduler 单例 + SQLAlchemyJobStore + ThreadPoolExecutor(20) | `scrapydweb/utils/scheduler.py:32,36,45,90` | 引擎本身与 trigger 类型无关；APScheduler 原生支持 cron/interval/date。dopilot 调度器沿用 APScheduler 这套引擎语义（自有 `scheduler/` 模块封装），新 trigger 只需向 `add_job` 传不同参数。**dopilot v1 硬约束：server = 单容器 + uvicorn workers=1 + 单 APScheduler 实例，jobstore 落 PostgreSQL（不再 SQLite）；不支持多副本/多 worker、未来也不做。不引入 Redis/NATS/PG LISTEN-NOTIFY 做多副本 HA / 跨实例分布式锁 / 跨进程 fan-out；server→web SSE fan-out 仍在单进程内存完成**（in-process BackgroundScheduler 无分布式锁，多副本会重复触发）。**【superseded-by `docs/refactor/00-redis-streams-agent-communication.md`】注意**：通信重构后 dopilot **显式引入 Redis 作单实例 server↔agent 通信总线**（command/event/log 三条 Stream）——这与上文一致，约束收窄为「不引入 Redis 做多实例 HA/fan-out/分布式锁」，而非「完全不用 Redis」；单容器 + workers=1 + 单 APScheduler 不变。 |
| `trigger='interval'` 的现成完整样例 | `scrapydweb/utils/check_app_config.py:306-309, 329-332` | `jobs_snapshot` / `delete_task_result` 两个内置维护作业已是 `trigger='interval', seconds=..., misfire_grace_time=60, coalesce=True, max_instances=1, jobstore='memory'` 的工作样例，可直接照搬到用户 interval 任务的组包逻辑。 |
| paused 启动 + 全局 resume/pause | `scheduler.py:90`（`start(paused=True)`）+ `check_app_config.py:288`（按 `scheduler_state` 决定 resume） | 「整体启停定时系统」机制现成。 |
| 持久化三件套 Task / TaskResult / TaskJobResult | `scrapydweb/models.py:89,131,147` | 任务定义、执行汇总、按节点明细的三层数据线语义完整，dopilot `models/` 按此领域分层设计自有实体（含 trigger/interval/date/node_strategy/task_type 字段）。 |
| 任务管理全套操作 | `scrapydweb/views/overview/tasks.py`（`TasksXhrView` / `TasksView.process_tasks`） | enable/disable、pause/resume/remove、fire、delete、清理、孤儿对账齐全；状态推导依赖 `apscheduler_job.next_run_time`（`tasks.py:166-188`），**不依赖 trigger 类型**，对 interval/date 通用。 |
| 创建/编辑总装配点 | `schedule.py`：`db_process_task()`（416）+ `add_update_task()`（447） | `action=add/add_fire/add_pause`、`replace_existing`、立即触发/暂停、先 modify 后 commit 的事务逻辑可复用。`add_update_task` 的 `**task_data` 组包对 interval/date 同样适用，基本不动。 |
| 回调 + 多节点遍历/重试/入库框架 | `execute_task.py`：`execute_task(task_id)`（150）+ `TaskExecutor.main/schedule_task`（42/75） | 回调签名、`selected_nodes` 遍历、失败 `nodes_to_retry` 重试一次（44-54）、`(status_code, dict)` 入库契约可复用。 |

### 2.2 缺口（已核实）

| 缺口 | 根因（file:line） | 影响需求 |
|---|---|---|
| interval / date 触发不支持 | `schedule.py:189` `self.kwargs['trigger']='cron'` 写死；`schedule.py:300` `trigger='cron'` 写死（注意 299 行已有被注释的 `trigger=request.form.get('trigger') or 'cron'` 雏形）；`schedule.py:292` 表单虽提交 `trigger` 但仅做非空校验后被忽略 | B-2（cron+interval）、A-3（一次性脚本） |
| 模型有 trigger 列但无 interval/date 列 | `models.py:94` 已有 `trigger`；但只有 cron 列 `year..second`（105-112，全 `nullable=False`），**无** `weeks/days/hours/minutes/seconds`（interval）与 `run_date`（date） | B-2 |
| dump/编辑回填读取 cron 专属属性 | `tasks.py:414` `self.apscheduler_job.trigger.fields`（CronTrigger 特有）；`schedule.py:query_task()`（93）回填只读 cron 列 | 引入 interval/date 后 dump 与编辑回填会报错或丢字段 |
| scheduler 未显式设置时区 | `scheduler.py:44` timezone 参数被注释，`scheduler.py:45` 使用系统默认（容器内常为 UTC） | cron/date 时间偏移；注意 `models.py:117` 已有 per-task `timezone` 列但未接入 |
| 回调写死 scrapyd，无 task_type 判别 | `execute_task.py:165` 默认 `/1/schedule/task/`，最终落到 scrapyd `schedule.json`；Task 无 `task_type` 列 | A-2（Docker 常驻）、A-3（脚本）无法定时触发 |
| date（一次性）触发未接入 | 无 date trigger 入口 | A-3 天然契合 date trigger（执行后 job 自动移除 → `process_tasks` 显示 Finished） |

### 2.3 非 scrapyd 执行器扩展（A-2 / A-3）

现状 `TaskExecutor.schedule_task(node)`（`execute_task.py:75`）固定走 `/N/schedule/task/ → scrapyd schedule.json`，且 Task 的 `project/version/spider/jobid`（`models.py:98-101`）为 scrapy 专有且 `NOT NULL`，与 Docker/脚本任务语义冲突。

**【改造建议】** 抽象 Executor 接口，按 `task_type` 分派，**统一保持 `(status_code, dict)` 返回契约**，使外层重试/入库/告警零改动：

```
                       execute_task(task_id)
                              │
                    task.task_type ?
        ┌─────────────┬───────────────┬──────────────┐
        ▼             ▼               ▼
  ScrapydExecutor  DockerExecutor  ScriptExecutor
  (经 agent →      (经 agent:       (经 agent:
   本机 scrapyd     启容器/         跑 py3
   addversion/     exec/重启)      脚本)
   schedule)
        └─────────────┴───────────────┴──────────────┘
              都返回 (status_code, dict) → 统一入库 TaskResult/TaskJobResult
```

> **dopilot v1 链路（已锁定）：** 三类 Executor 一律 server → dopilot-agent，**没有 server 直连裸 scrapyd 的路径**。重构后（阶段 1.5，见 `docs/refactor/00-redis-streams-agent-communication.md`）server↔agent 主路径走 **Redis Streams**：scrapy 类执行链是 server 写 `command_outbox` → dispatcher `XADD run` → `dopilot:agent:{agent_id}:commands` → agent consumer 消费 → agent 子进程拉起的本机 scrapyd（监听容器内部端口如 6801、仅本机可见）调 `schedule.json` → scrapy process，agent tail 其 `job.log` 后经 `dopilot:server:logs` 推回 server。**egg 上传部署是例外，仍走 HTTP**：server → agent HTTP `/addversion.json` 转发 → 本机 scrapyd `/addversion.json`（refactor/00 命令类型仅 run/stop/cleanup_logs，不含 deploy_egg）。现成 scrapyd 镜像仅本地 spike，非正式架构。

> Docker「定时」语义需先定义（见开放问题）：是「定时启动新容器实例」，还是「定时对常驻容器发指令（exec/重启/健康检查）」？这决定 DockerExecutor 接口形态。

### 2.4 候选方案对比

| 方案 | 做法 | 优点 | 缺点 | 工作量 |
|---|---|---|---|---|
| **A 原生三 trigger** | dopilot 调度器从零原生支持 cron/interval/date trigger（行为参考：APScheduler 三类 trigger 语义、`check_app_config.py:306-332` interval 样例参数）；Task 模型设计含 interval 字段（`weeks/days/hours/minutes/seconds`）+ `run_date`，cron 字段可空；服务层按提交的 trigger 类型组装作业参数；`apps/web` 调度页提供 trigger 类型选择；编辑回填按类型读取 | 改动集中、风险低、完全复用调度引擎/落库/管理/结果链路语义；trigger 类型对调度引擎透明；无额外依赖 | 三类 trigger 字段集合需在模型与表单内统一管理；仍只覆盖 scrapyd 类执行（Docker/脚本待第二步）| 中 |
| **B = A + task_type + Executor 抽象** | A 之上加 `task_type(scrapy\|docker\|script)`，放宽 `project/version/spider/jobid` nullable；`schedule_task` 重构为 Executor 分派 | 一次打通 B-2 与 A-2/A-3；调度/执行解耦；与 B-3/B-4 共用入口 | 改动面大；Docker/脚本 agent 协议是另一大块；模型大改 + 无迁移 | 大 |
| **C 直接套用 Flask-APScheduler 框架** | 用 Flask-APScheduler 等成品框架接管调度，而非按 dopilot 数据模型自建调度服务 | 长期 API 更清晰、内置 REST | 框架内置数据模型/作业表达与 dopilot 自有 Task/TaskResult/TaskJobResult 领域模型贴合度低，enable/disable/fire/对账/结果等管理语义要绕开框架约定重做；可控性差 | 很大（不推荐） |

### 2.5 推荐（B-2）

**分两步，先 A 后 B。**

1. **第一步（方案A，落地 B-2）**：dopilot scheduler 模块原生支持 cron/interval/date 与 per-task timezone（行为参考：`models.py:117` 的 timezone 列语义、`scheduler.py:44-45` 因未显式设置 timezone 导致偏移的陷阱），前端调度页提供 trigger 类型选择、编辑回填按类型读取。APScheduler 引擎本身与 trigger 类型无关、原生支持三类 trigger，风险最低，最快满足 cron+interval，并顺带支持 date 一次性（服务 A-3）。同步：调度器显式设置时区，并加全局 `TIMEZONE` 默认（`Asia/Shanghai`）。
2. **第二步（方案B）**：加 `task_type` + Executor 抽象，把 Docker 常驻/脚本接入同一定时框架。

> dopilot 自带 `migrations/`（**裸 Alembic**，不是 Flask-Migrate——FastAPI 无 Flask app；SQLAlchemy + Alembic），所有模型变更走迁移；APScheduler jobstore 也落 **PostgreSQL（唯一库）**。（scrapydweb 基线无迁移框架、模型内有手工 ALTER 的 TODO 注释、删库重建，仅作行为参考，非 dopilot 约束。）

---

## 3. B-3 节点选择策略（指定 / 全部 / 随机）

### 3.1 现状机制（已核实）

**单节点选择**：所有 URL 第一段 `/<int:node>/`，`BaseView.__init__`（`baseview.py:189-197`）取 `view_args['node']`（1-based），断言 `0 < node <= SCRAPYD_SERVERS_AMOUNT`，用 `node-1` 去四个并行列表取值：

```
node (1-based)  ──► node-1 索引 ──┬─► SCRAPYD_SERVERS[node-1]          (host:port)
                                  ├─► SCRAPYD_SERVERS_GROUPS[node-1]
                                  ├─► SCRAPYD_SERVERS_AUTHS[node-1]
                                  └─► SCRAPYD_SERVERS_PUBLIC_URLS[node-1]
   四列表等长，由 check_scrapyd_servers() 派生 (check_app_config.py:361-392)
```

**多节点选择**：`BaseView.get_selected_nodes()`（`baseview.py:257-262`）遍历表单 key `'1'..'N'`，值为 `'on'` 即选中，返回节点编号列表。前端在 `include_multinodes_checkboxes.html` 与 `schedule.html` 提供「Check current node only / Sync from Servers / CheckAll-UncheckAll」+ 隐藏字段 `checked_amount`。

**「全部」支持**：CheckAll 勾全部。定时任务 `TaskExecutor.main()`（`execute_task.py:42-54`）对 `selected_nodes` **串行逐节点** `schedule_task()`；即时运行 `ScheduleRunView.handle_form`（`schedule.py:362-373`）只对 `first_selected_node` 同步下发一次，其余节点由前端 `schedule.xhr` 逐个 AJAX 补发（**浏览器端 fan-out**）。

**随机：没有**。全代码无 `random.choice` / `node_strategy`；`Task`（`models.py:89-128`）只有 `selected_nodes`（Text，存 `str(list)`，`models.py:103`），**无策略列**。

### 3.2 缺口（已核实）

| 缺口 | 根因 |
|---|---|
| 无「随机选一个」 | 仅「指定单节点」与「勾选全部」两种；无随机/负载逻辑；Task 无策略列；`execute_task`/`ScheduleRunView` 无分支 |
| 策略不持久化 | `db_process_task`（`schedule.py:416`）把 `selected_nodes` 存为 `str(list)`，但「用哪种策略」无列记录；定时触发只会照搬整张列表全跑 |
| 随机语义二义 | 「静态随机」（建任务时定死一个）vs「动态随机」（每次触发时选）。后者价值高（均摊/容灾），但需在**触发时刻**而非建任务时刻选，与「建任务即固化 selected_nodes」模型冲突 |
| 节点序号会漂移 | `check_app_config.py:388` `servers=sorted(set(servers), key=key_func)`；node 1-based 对应排序后顺序，**增删节点会整体漂移**，已存任务 `selected_nodes` 可能指向错节点，随机选中的 node 也无法稳定映射物理节点 |
| 随机缺健康过滤 | 无集中节点健康数据；`daemonstatus` 仅页面按需查询，无法在调度时过滤「只在存活节点里随机」 |

### 3.3 设计：策略三态

| 策略值 | 候选集 | 实际下发 | 落点 |
|---|---|---|---|
| `specified` | 表单勾选的若干节点 | 这些节点全部 | 等价现有「勾选多节点」 |
| `all` | 全部节点 | 全部（默认，兼容旧数据） | 等价 CheckAll |
| `random` | 表单勾选的候选集（或全部） | **触发时** `random.choice(candidates)` 取一个 | 在 `execute_task` 触发时刻归约 |

```
建任务：selected_nodes = 完整候选集 (不缩减)  +  node_strategy = random
                                  │
                                  ▼ 每次到点触发
execute_task(): candidates = json.loads(task.selected_nodes)   (execute_task.py:168)
                if node_strategy == 'random':
                    candidates = [random.choice(candidates)]   ← 动态随机（推荐）
                TaskExecutor(selected_nodes=candidates).main()
```

### 3.4 候选方案对比

| 方案 | 做法 | 优点 | 缺点 | 工作量 |
|---|---|---|---|---|
| **A 加 node_strategy + 触发时动态归约**（推荐核心） | Task 加 `node_strategy`（默认 `all`）；表单/组件加策略单选；`selected_nodes` 存完整候选集；`execute_task` 解析后按策略归约（random→`random.choice`）；即时运行同步加分支 | 复用全部 fan-out/重试/入库；动态随机天然实现（容灾/均摊）；改动集中、向后兼容 | 需手工迁库；node 序号漂移仍在 | 中 |
| **B 仅请求层加随机，不持久化** | 不动模型，random 时在请求处理把 `selected_nodes` 缩成一个再存 | 零迁移、最快 | 只是「静态随机」（每次跑同一节点），无均摊/容灾；策略不可见不可编辑 | 低 |
| **C 节点模型重构为 list[dict] + 稳定 ID** | 四并行列表 → 一个 `list[dict]`（`{id,host,port,auth,group,type,public_url}`）或独立表；节点用稳定 id（如 host:port）；`selected_nodes` 存稳定 id；`BaseView.__init__` 取值随之改 | 根治序号漂移；为三类对象 + 推模式 + 随机提供统一底座；策略/类型一等公民 | 改动面大（BaseView/所有按 node 索引取值处/数据迁移）；回归成本大 | 高 |

### 3.5 推荐（B-3）

**采用方案A 为主线**，给 Task 加 `node_strategy`（`specified/all/random`，默认 `all`），在 `execute_task` 触发时刻按策略归约（random → `random.choice`，实现**动态随机**——方案B 的静态随机不可取）。

**dopilot nodes 模型从设计起即以独立 `nodes` 表 + 稳定 `agent_id` 为一等公民，`selected_nodes` 存稳定 ID**，从根上杜绝序号漂移。agent 启动时传入容器重启也不会变化的 `agent_id`，server 以该 ID upsert `nodes` 表；`[nodes].agents` 只作为初始发现地址列表。行为陷阱参考：scrapydweb `check_app_config.py:388` 的 `sorted(set())` 使增删节点后序号整体漂移、已存任务选错节点——设计 dopilot 节点标识时要避开此坑。

> **【superseded-by `docs/refactor/00-redis-streams-agent-communication.md`】健康判定来源已翻转。** 通信重构后，node_strategy 的三态语义（`specified/all/random`、random 动态归约）**不变**，叠加 heartbeat 健康过滤：健康来源由「server 轮询 agent `/health`」翻转为「agent 主动 POST `/api/v1/agents/{agent_id}/heartbeat` 写入 `nodes.last_seen_at`」，server 判定 `healthy = now - nodes.last_seen_at <= heartbeat_timeout_seconds`。`node_strategy` 在触发时仍只在健康候选集内归约，只是「健康」的判据从轮询响应换成 last_seen_at 新鲜度。

---

## 4. B-4 推模式（主动下发到指定节点执行）

### 4.1 现状（已核实）

| 维度 | 现状 | file:line |
|---|---|---|
| 对 scrapyd 是否真推 | 是，HTTP POST `schedule.json` | `baseview.py:285` `make_request` |
| 平台内部 fan-out | 进程内 `test_client` 自调用，非远程推送 | `common.py:48-80` `get_response_from_view` |
| 推送链 | APScheduler 线程 → `execute_task` → `TaskExecutor` 遍历 → `get_response_from_view` POST `/N/schedule/task/` → `ScheduleTaskView` → `make_request` → scrapyd | `execute_task.py:88` + `schedule.py`(ScheduleTaskView) |
| 失败处理 | 入 `nodes_to_retry`，延迟重试一次 | `execute_task.py:44-54,91-94` |
| 即时触发（push 雏形） | `TasksXhrView.fire_task()` `modify(next_run_time=datetime.now())` | `tasks.py:353-362` |

### 4.2 缺口（已核实）

| 缺口 | 根因 |
|---|---|
| 无真正远程 worker 通道 | 「推」对 scrapyd 是平台本机 HTTP 转发；对 Docker 常驻/脚本无任何下发协议；`execute_task.py:88` 硬编码 `/N/schedule/task/` → scrapyd |
| 无独立「手动即时推送」入口 | 唯一即时多节点推送是 `fire_task`（依附已存 apscheduler_job）和 `ScheduleRunView` 即时 run（走前端 fan-out）。没有「选好节点+策略一键 push、服务端受控并发执行」的统一端点 |

### 4.3 设计：方案D（Executor 抽象 + 独立推送端点）

```
  ┌─ 定时路径 ────────┐        ┌─ 推模式路径（新增）──────────────┐
  │ APScheduler 线程  │        │ 用户点「立即推送」按钮            │
  │   execute_task()  │        │   POST /api/v1/executions/run     │
  └─────────┬─────────┘        │   body: {task_type, nodes,       │
            │                  │          node_strategy, payload} │
            │                  └──────────────┬──────────────────┘
            └──────────┬──────────────────────┘
                       ▼
              统一调度入口：按 node_strategy 归约节点 + 按 task_type 分派 Executor
                       │
        ┌──────────────┼───────────────────────┐
        ▼              ▼                        ▼
  ScrapydExecutor   DockerExecutor          ScriptExecutor
        └──────────────┴───────────────────────┘
                       │  全部经 dopilot-agent（packages/protocol 网络协议）
                       ▼
              dopilot-agent（agent API，对外 6800）
        ┌──────────────┼───────────────────────┐
        ▼              ▼                        ▼
  本机 scrapyd      docker 容器              py3 脚本
  (内部 6801,        (启/exec/重启)          (子进程)
   addversion/
   schedule)
        └──────────────┴───────────────────────┘
              都返回 (status_code, dict) → 复用 TaskResult/TaskJobResult 入库 + 重试
```

要点：
- **dopilot v1 三类下发一律经 dopilot-agent，server 不直连裸 scrapyd。** 重构后 server↔agent 主路径走 **Redis Streams**（阶段 1.5，见 `docs/refactor/00-redis-streams-agent-communication.md`）：对 **scrapy** 类，server 写 `command_outbox` → dispatcher `XADD run` → agent consumer 消费 → agent 调本机 scrapyd（内部端口如 6801）`schedule.json` → scrapy process。**egg 上传部署是例外，仍走 HTTP**：用户上传 → server → 转发 agent → agent 调本机 scrapyd `/addversion.json`（不经 Redis command stream）。`baseview.py:285` `make_request` 仅作 scrapydweb「对 scrapyd 真 HTTP POST」的**行为参考**，不是 dopilot 链路。
- 对 **Docker/脚本**，server→agent 同样走 **Redis command stream**：server `XADD run` command → `dopilot:agent:{agent_id}:commands` → agent consumer 消费，由 `apps/server/.../executors/{docker,script}.py` 写命令、`apps/agent` runners 实际执行。三类 Executor 的 `apps/server/.../executors/{scrapyd,docker,script}.py` 都是「向 agent **写 command stream**」（egg 部署除外，仍走 HTTP `/addversion.json`），差异在 agent 侧 runner。`packages/protocol` 的 stream schema 见 `streams.py`。
- dopilot **不存在**进程内 `test_client` 自调用层可复用（scrapydweb 平台内部 fan-out 是进程内自调用而非远程推送，见 `common.py:48-80`，仅作行为对照）。
- **agent 注册（v1）**：`[nodes].agents=["agent:6800"]` 作为 server 初始发现地址（指向 agent API，非裸 scrapyd）；agent 启动时携带稳定 `agent_id`，server 以该 ID upsert `nodes` 表，调度只选健康 agent。**【superseded-by `docs/refactor/00-redis-streams-agent-communication.md`】**：通信重构后 agent 健康发现/判定改为 **agent 主动 POST `/api/v1/agents/{agent_id}/heartbeat` 写 `nodes.last_seen_at`** 为 v1 主路径（不再「server 轮询 `GET agent /health` 读取」、不再「heartbeat 留后续」），server 判 `healthy = now - last_seen_at <= heartbeat_timeout_seconds`；agent `/health` 降级为容器本地 healthcheck，不再作 server 节点发现/健康来源。`execution_id`/`attempt_id` 由 server 生成。
- 新增「立即推送」端点：`POST /api/v1/executions/run`，可**临时指定节点+策略**，服务端受控并发执行；与 B-3 共用同一「选节点+策略+下发」入口（行为参考 `fire_task` 的即时触发思路）。**【superseded-by 同上】**：下发动作由「server → agent HTTP `POST /run`」改为「server 事务内写 `command_outbox` → dispatcher `XADD` 到 `dopilot:agent:{agent_id}:commands` 的 `run` command → agent 经 consumer group 消费」；server 不再主动 HTTP 连 agent 下发任务（手动 run 请求内 `try_dispatch`/`dispatch_unknown(202)`/`503`、定时触发 queued+outbox give_up 等可靠性细节见 refactor 文档）。

### 4.4 候选方案对比（推模式相关）

| 方案 | 做法 | 优点 | 缺点 | 工作量 |
|---|---|---|---|---|
| **D Executor 抽象 + 独立推送端点 + RemoteExecutor** | `schedule_task` 按 task_type 分派；新增不依赖定时器的「立即推送」端点；Docker/脚本走远程 agent | 一并解决 B-4 与 A 三类对象；保留重试/入库；为分布式 push 打基础 | 需定义并实现 agent 协议（平台外工作量）；与 B-3 策略、B-2 task_type 耦合（同改更顺） | 高（含 agent 协议设计） |
| 复用 fire_task（轻量过渡） | 把 `fire_task` 扩成可临时指定节点的「推模式手动下发」入口 | 不必新造调度，最快出可见效果 | 仍依附已存 apscheduler_job，无法承载非定时一次性 push；不解决远程通道 | 低（仅过渡） |

### 4.5 推荐（B-4）

**采用方案D，与 A-2/A-3 三类对象一起做（第二步）**：dopilot 在 `apps/server/dopilot_server/executors/` 建立 `BaseExecutor` + `Scrapyd/Script/Docker` 实现（`base.py`/`scrapyd.py`/`script.py`/`docker.py`），按 `task_type` 分派；新增 `POST /api/v1/executions/run` 立即推送端点（JSON）做服务端受控并发 push；**三类下发一律经 dopilot-agent（`apps/agent` runners + `packages/protocol`）执行——scrapy 类经 agent 调本机 scrapyd（addversion/schedule），Docker/脚本经 agent runner，server 不直连裸 scrapyd**。重试与 TaskResult/TaskJobResult 入库语义全程复用。

> dopilot-agent 在阶段1 即落地（非阶段2）；阶段1 先做 scrapy/scrapyd，但其下发也已经过 agent。Docker/脚本 runner 在后续阶段补，但走的是同一条 server→agent 通道。

> 行为参考（作为 `BaseExecutor` 与重试/入库设计的对照）：scrapydweb `fire_task` 用 `modify(next_run_time=now)` 实现即时触发；失败入 `nodes_to_retry` 延迟重试一次；统一 `(status_code, dict)` 入库契约。

---

## 5. 整体推荐与实施顺序

```
第一步（低风险，可独立交付）
 ├─ B-2: 原生支持 cron + interval + date trigger
 │       · apps/server/.../scheduler/ + services/ 按提交 trigger 类型组装作业参数
 │       · apps/server/.../models/ 设计 Task 含 interval 字段(weeks/days/hours/minutes/seconds)+run_date，cron 字段可空
 │       · apps/web/src/pages 调度页提供 trigger 类型选择 + 字段切换
 │       · 编辑回填(repositories/services + /api/v1)按 trigger 类型读取
 ├─ B-3: Task 加 node_strategy(默认 all)；scheduler 触发回调按策略归约(random→random.choice)
 │       · nodes 模型自设计起以独立 nodes 表 + 稳定 agent_id 为一等公民，selected_nodes 存稳定 ID
 └─ 时区: 调度器显式 timezone；configs/server.example.toml + config/ 加 TIMEZONE(默认 Asia/Shanghai)；接入 per-task timezone

第二步（大块，含 agent 协议工作；agent 本身阶段1 即落地，scrapy 下发已经过 agent）
 ├─ B/A: Task 加 task_type(scrapy|docker|script)，scrapy 专有字段可空
 ├─ Executor 抽象: apps/server/.../executors/{base,scrapyd,script,docker}.py，保持 (status_code,dict) 契约
 └─ B-4: 新增 /api/v1 立即推送端点；三类(含 scrapy/scrapyd)一律经 apps/agent runners + packages/protocol 执行，server 不直连裸 scrapyd

贯穿
 └─ dopilot 自带 migrations/(裸 Alembic，非 Flask-Migrate)，每步模型变更走迁移；PostgreSQL 唯一库，APScheduler jobstore 落 PG
```

---

## 6. dopilot 目标模块清单（汇总）

> 下表左列是 dopilot 自有骨架中**全新实现**该行为的落点；右列「scrapydweb 行为参考」仅以 `file:line` 标注**行为对照/移植注意**，不是 dopilot 的待改文件。权威目录布局见 `05-dev-setup-and-known-issues.md` §1。

```text
dopilot/                                  # 仓库根 = Docker 构建上下文(origin: senjianlu/dopilot;镜像命名空间 rabbir)
├── apps/
│   ├── server/                           # 调度中心:API、DB、APScheduler、认证、节点管理、日志聚合
│   │   ├── dopilot_server/
│   │   │   ├── api/v1/                    # FastAPI /api/v1/* JSON + SSE(server→web 单向);v1 不用 WebSocket;server↔agent 走 Redis Streams(command/event/log),仅 agent→server heartbeat 走 HTTP(POST /agents/{id}/heartbeat)【superseded-by docs/refactor/00-redis-streams-agent-communication.md;原"走 HTTP agent tail/status/cleanup API"已废】
│   │   │   ├── auth/  scheduler/  nodes/  logs/  models/  repositories/  services/  config/
│   │   │   ├── redis/                      # Redis Streams 基础设施(client/streams/commands/consumers):command producer/dispatcher、event consumer、log consumer
│   │   │   ├── executors/                 # 缝① BaseExecutor + EXECUTOR_REGISTRY(run_on_node 由 POST /run 改为 XADD command;get_status 由轮询改为消费 agent-events)
│   │   │   │   ├── base.py  scrapyd.py  script.py  docker.py
│   │   │   └── app.py
│   │   ├── migrations/  tests/  pyproject.toml
│   ├── agent/                            # worker 执行节点:主动经 Redis 消费命令、主动推状态/日志、主动 POST heartbeat;本机拉起 scrapyd(子进程)/跑 Python/Docker
│   │   ├── dopilot_agent/
│   │   │   ├── api/                       # agent /health 降级为容器本地 healthcheck(不再作 server 节点发现/健康来源);/addversion /schedule 转本机 scrapyd 仍在【superseded-by refactor;原"logs tail/status/cleanup HTTP API"作 server 来源已废,改 Redis Streams】
│   │   │   ├── redis/                      # agent Redis 子包(client/commands/events/logs):consumer group 消费 command、XADD agent-events、XADD logs、event/log outbox
│   │   │   ├── runners/                   # base.py scrapyd.py script.py docker.py
│   │   │   ├── logs/  workspace/  config/  main.py   # logs: tail 本机 scrapyd job.log,agent 主动 XADD 增量到 dopilot:server:logs(无 WS、server 消费后落盘);state/executions/{attempt_id}.json 两阶段 CAS(reserved/started)持久化 execution_id↔scrapyd job_id↔log_path 映射(重启恢复/幂等)
│   │   ├── tests/  pyproject.toml
│   └── web/                              # Vue3 + Element Plus + Vite + TS SPA(greenfield,直连 /api/v1)
│       ├── src/{api,pages,components,layouts,stores,router,i18n}/  public/
│       ├── package.json  vite.config.ts
├── packages/
│   ├── protocol/                         # server↔agent 共享协议 schema(protocol/python/;前端也消费可并列 protocol/typescript/)
│   └── client/                           # 可选:server→agent 客户端 SDK
├── deploy/{docker/{Dockerfile,docker-compose.yml},k8s/}
├── configs/{server.example.toml,agent.example.toml}   # dopilot 自有 toml 配置(经 DOPILOT_CONFIG 加载,不继承 scrapydweb 硬编码 settings)
├── scripts/  docs/
├── reference/scrapydweb/                 # 只读行为参考,绝不进构建上下文/不被 import/不改名
├── README.md  pyproject.toml  pnpm-workspace.yaml  .dockerignore
```

| dopilot 目标模块 | 主题 | 全新实现要点 / scrapydweb 行为参考 |
|---|---|---|
| `apps/server/dopilot_server/scheduler/` + `services/` | B-2/B-3 | 按提交的 trigger 类型组装 cron/interval/date 作业参数并写入 `node_strategy`；trigger 不被硬编码；创建/编辑总装配落库后向调度器登记作业；即时运行按策略决定下发集合。行为参考：`schedule.py:291` 表单组包、`schedule.py:189/300` 的 `trigger='cron'` 硬编码陷阱、`schedule.py:416` 落库事务、`schedule.py:362-373` 即时下发、`add_update_task`(447) `**task_data` 组包语义 |
| `apps/server/dopilot_server/models/` + `migrations/` | B-2/B-3/A | 用 dopilot ORM + 迁移设计 Task/TaskResult/TaskJobResult：含 `trigger`、`timezone`、interval 字段(`weeks/days/hours/minutes/seconds`)、`run_date`、`node_strategy`(默认 `all`)、`task_type`；cron 与 scrapy 专有字段(`project/version/spider/jobid`)在非 scrapy 场景可空；`selected_nodes` 存稳定节点标识。模型演进全部走迁移。行为参考：`models.py:94`(trigger)、`models.py:117`(timezone)、`models.py:105-112`(cron 列)、`models.py:98-101`(scrapy 专有列)、`models.py:103`(selected_nodes) |
| `apps/web/src/pages` 调度表单页 + 节点选择组件 | B-2/B-3 | greenfield SPA(Element Plus)：trigger 类型选择(cron\|interval\|date)与对应字段块、interval/date 输入、`node_strategy` 控件；经 `src/api` 调 `/api/v1` 提交，编辑回填读 `/api/v1`。行为参考(需覆盖的功能点对照)：scrapydweb `schedule.html`/`include_multinodes_checkboxes.html` 的字段集合 checkCurrent/checkAll/`checked_amount` 等 |
| `apps/server/dopilot_server/services/` + `api/v1/` (任务管理/状态) | B-2/B-3/B-4 | 任务列表/dump 按 trigger 类型读取(Cron/Interval/Date 各自字段)，状态推导依赖 `next_run_time` 对三类 trigger 通用；展示 `node_strategy`；即时推送入口。行为参考：`tasks.py:380-414`(dump)、`tasks.py:166-188`(状态推导通用)、`tasks.py:353-362`(`fire_task` 即时触发思路) |
| `apps/server/dopilot_server/executors/{base,scrapyd,script,docker}.py` | B-2/B-3/B-4/A | 调度回调解析 `selected_nodes` 后按 `node_strategy` 归约(random→`random.choice`)，按 `task_type` 经 `EXECUTOR_REGISTRY` 分派 `BaseExecutor` 实现，统一 `(status_code, dict)` 契约。**【superseded-by `docs/refactor/00-redis-streams-agent-communication.md`】缝① 保留、下发/取状态实现翻转**：`run_on_node` 由「server `POST /run` agent」改为「事务内写 `command_outbox` → `XADD` run command」；`get_status` 由「轮询 agent status」改为「消费 `agent-events` 的 `attempt.*` 事件」；不再「server↔agent 走 HTTP、无消息队列/回调」。行为参考：`execute_task.py:150/168`(回调与节点解析)、`execute_task.py:75-104`(下发)、`execute_task.py:44-54`(`nodes_to_retry` 重试一次) |
| `apps/server/dopilot_server/nodes/` | B-3 | 建立 `nodes` 表，节点以稳定 `agent_id` 为一等公民；选择/下发按稳定 ID 解析，不存在按 1-based 序号索引并行列表的取值方式。行为参考(要规避的坑)：`baseview.py:189-197`(node-1 索引四并行列表)、`baseview.py:257-262`(`get_selected_nodes`)、`check_app_config.py:388`(`sorted(set())` 序号漂移) |
| `apps/server/dopilot_server/config/` + `configs/server.example.toml` | B-2/B-3 | dopilot 自有 toml 配置(经 `DOPILOT_CONFIG` 加载)：`TIMEZONE`(默认 `Asia/Shanghai`)、`DEFAULT_NODE_STRATEGY`(默认 `all`)、调度器显式时区，不继承 scrapydweb 硬编码 settings。**【superseded-by refactor】通信重构新增配置段**：server `[redis]`(url/stream_maxlen_*/log_retention_seconds/consumer_name/require_aof)、`[agents]`(heartbeat_timeout_seconds/stalled_attempt_seconds/lost_after_stalled_seconds)、`[logs].log_drain_timeout_seconds`；agent `[redis]`(url/command_block_ms/pending_idle_ms/event_outbox_dir)、`[agent].server_url`/`heartbeat_interval_seconds`/`server_shared_token`；docker compose 新增 redis 服务并启用 AUTH/AOF。行为参考：`scheduler.py:44-45`(timezone 未设导致 cron/date 偏移)、`check_app_config.py:306-332`(interval 样例参数)、`default_settings.py`(配置项命名对照) |
| `apps/server/dopilot_server/executors/` + `apps/server/.../redis/` + `apps/agent/.../redis/` + `apps/agent` runners + `packages/protocol/.../streams.py` | B-4 | **三类下发(含 scrapy/scrapyd)由 server executors 经 Redis `command` stream `XADD` run command、agent consumer group 消费后由 runners 执行;server 不直连裸 scrapyd、不再主动 HTTP `POST /run`**——scrapy 类经 agent 调本机 scrapyd(内部端口如 6801)addversion/schedule,对外 6800=agent API。dopilot 无进程内 `test_client` 自调用层。agent v1 通过 `[nodes].agents` 初始发现 + 稳定 `agent_id` 入 `nodes` 表 + **agent 主动 heartbeat 写 `last_seen_at`** 选健康 agent。protocol 新增 `streams.py`(`AgentCommand/AgentEvent/AgentLogEvent/AgentHeartbeatRequest/Response`),既有 `AgentRunRequest/AgentStatusResponse/TailRequest/TailResponse` 标 legacy。**【superseded-by `docs/refactor/00-redis-streams-agent-communication.md`;原"走 HTTP 网络协议下发 + server 轮询 /health"已废】** 行为参考：`baseview.py:285`(scrapydweb 对 scrapyd 是真 HTTP POST、dopilot 多一跳 agent)、`common.py:48-80`(scrapydweb 平台内部 fan-out 是进程内自调用、非远程推送) |

---

## 7. 已锁定调度与节点决策

### 定时引擎
1. interval 第一版只暴露简单周期值（weeks/days/hours/minutes/seconds），不暴露 `start_date/end_date/jitter`；ORM 可以预留字段，UI 与 API v1 不提供入口。
2. dopilot 自带 migrations，模型演进走迁移；第一版不导入 scrapydweb 存量定时任务数据。
3. cron 时区默认 `Asia/Shanghai`，并保留「每任务 timezone + 全局默认」两层模型。
4. Docker 常驻爬虫的「定时」语义推迟到阶段 3 前定义；不阻塞阶段 1/2。
5. 一次性 Python 脚本使用 date trigger；任务定义保留，允许后续手动重跑。
6. 三类被调度对象共用一个 `Task` 实体，带 `task_type` 与类型相关 `payload JSONB`/可空字段；结果查询统一。

### 节点策略与推模式
7. 「随机选一个」采用**动态随机**：每次触发从候选健康节点中随机选择。
8. 节点选择默认过滤健康状态；暂不引入复杂负载权重。**【superseded-by `docs/refactor/00-redis-streams-agent-communication.md`】**：第一版健康条件由「server 轮询 agent `/health`」改为「agent 主动 POST `/api/v1/agents/{agent_id}/heartbeat`，server 判 `healthy = now - nodes.last_seen_at <= heartbeat_timeout_seconds`」；`/health` 降级为容器本地 healthcheck。
9. 稳定节点标识采用独立 `nodes` 表主键/唯一 `agent_id`；agent 启动传入容器重启不变的 `agent_id`。
10. B-4 推模式对 Docker/脚本的 agent 侧 runner：脚本用 agent subprocess；Docker/K3s SDK 归 agent 侧，阶段 3 实作。**【superseded-by `docs/refactor/00-redis-streams-agent-communication.md`】server→agent 通道锁定从 HTTP 改为 Redis Streams**：命令下发走 `command` stream（server `XADD` / agent consumer group 消费）、状态/日志走 `agent-events` / `logs` stream（agent `XADD` / server 消费）；仅 agent→server heartbeat 走 HTTP（`POST /api/v1/agents/{agent_id}/heartbeat`）。
11. B-4「推模式」与 B-3「随机」共用同一 `POST /api/v1/executions/run` 即时推送端点：请求中传 `task_type`、候选节点、`node_strategy`，server 归约后下发。
12. 多节点「全部执行」采用 server 侧受控并发下发；并发上限做成配置项，避免大集群时压垮 agent 或 PostgreSQL。

---

## 8. PostgreSQL 写入并发与事务边界（替换 SQLite 的取舍）

> 本节是**已锁定 spec 的落地约束**，不是开放问题。dopilot 用 **PostgreSQL 唯一库**（SQLAlchemy + 裸 Alembic）替换 scrapydweb 的多 SQLite，并发与事务边界随之改变；下面给出 dopilot 自有实现的边界约定。scrapydweb 的 SQLite 行为仅作对照。

### 8.1 替换 SQLite 的并发取舍

| 维度 | scrapydweb 现状（SQLite，行为参考） | dopilot（PostgreSQL，已锁定） |
|---|---|---|
| 并发写 | SQLite 单写锁，APScheduler `ThreadPoolExecutor(20)` 回调 + poll 子进程 + Web 请求竞争同库，靠重试/串行化兜底；多 DB 文件分散竞争 | PG 行级锁 + MVCC，天然支持调度回调线程并发写不同任务的 `TaskResult/TaskJobResult` 行 |
| 实例数 | 进程内单 scheduler | **单容器 + uvicorn workers=1 + 单 APScheduler 实例**（硬约束）；写并发仅来自同进程内的回调线程池与请求 handler，不存在跨副本写竞争 |
| 连接 | 文件句柄 | SQLAlchemy 连接池（FastAPI sync 路径用线程池 + 同步 Session，或 async engine）；APScheduler jobstore 用独立连接 |
| 迁移 | 无 Alembic，手工 ALTER / 删库重建 | 裸 Alembic 迁移；删库重建不作为正式策略 |

### 8.2 事务边界约定（dopilot 自有）

- **每个被调度对象的一次执行 = 一段独立事务**：调度回调对 `selected_nodes` 归约后，逐节点（或受控并发）下发；**每个 `(execution, node)` 的 `(status_code, dict)` 结果独立提交**，单节点失败/重试不回滚其他节点已落库的结果（沿用 scrapydweb `(status_code, dict)` 入库契约的语义，但事务粒度按节点切分，避免长事务持锁）。
- **回调线程池写并发**：不同任务/不同节点的结果行天然无冲突，靠 PG 行级锁即可；不要在回调里开「跨多行长事务」，以免与 Web 请求互锁。
- **APScheduler jobstore 与业务表分事务**：jobstore 落 PG，但其 `add_job/modify/remove` 由 APScheduler 自管事务，**不要把业务 `Task` 写入与 jobstore 写入塞进同一事务**——先业务落库 commit，再向调度器登记/修改作业（沿用 `schedule.py:416`「先 modify 后 commit」思路的对照，但拆成两段以隔离 jobstore）。
- **单实例约束兜底**：因 server 单实例单 APScheduler，不存在分布式触发竞争，无需在业务层做分布式锁/幂等去重；这条约束是 PG 事务边界可以保持简单的前提（一旦未来要多副本就会失效——而 spec 已锁定**不做多副本**）。

### 8.3 与日志 pull 模型的事务交叉（涉及）

> **【superseded-by `docs/refactor/00-redis-streams-agent-communication.md`】本小节描述的「server 主动 pull / 轮询 status / cleanup API」链路已被通信重构反转。** 当前 v1 口径：日志由 **agent 经 `dopilot:server:logs` stream 主动 XADD 增量、server log consumer 消费后落盘**（取代 server pull agent tail）；执行状态由 **server event consumer 消费 `dopilot:server:agent-events` 的 `attempt.accepted/running/finished/failed/canceled/lost` 事件**驱动（取代 server 轮询 agent status API）；日志清理由 **server 向 `command` stream 投递 `cleanup_logs` command**（取代 server 调 agent cleanup HTTP API）。下列事务边界结论（正文不入 PG、offset 权威在 server、索引单行 UPDATE、与执行结果事务不相交）**仍成立**，只是触发方向从「server 拉」变为「agent 推 + server 消费」。详见 refactor 文档。

日志链路的权威状态在 server（PG），正文不入库，因此与上面的执行结果事务**分表、分写路径**，互不阻塞：

- **正文不入 PG**：日志正文写 server 本地文件 `/server-data/logs/YYYY/MM/{execution_id}/{attempt_id}.{stream}.log`（`stream=log` 时即 `{attempt_id}.log`）；PG 仅存索引表 `execution_log_files`（主键 `(execution_id, attempt_id, stream)`，列含 `storage_path/size_bytes/last_pulled_offset/final_offset/status/started_at/finished_at/retained_until/created_at/updated_at`）。这避免了把高频增量日志写进事务库造成的写放大与锁竞争。
- **offset 权威在 server**：`last_pulled_offset` 在 PG，记录 server 已处理到的 agent 逻辑字节 offset（消费进度权威），重构后仍是最终落盘进度权威。**【superseded-by refactor】**：原「agent 无状态、无 ack 队列，server 按 offset 主动拉」改为「agent 维护本地 log outbox 按 offset 严格递增 `XADD` 到 `logs` stream，server 消费」；每次消费一段后**先落盘正文、再单行 UPDATE `last_pulled_offset`**（幂等：`offset < last_pulled_offset` 丢弃，`offset > last_pulled_offset` 标 `partial` 黏性 + 插 gap marker），是独立短事务，不与执行结果事务耦合。
- **消费与单实例**（重构后取代「pull 频率」）：server log consumer 消费 `dopilot:server:logs` 的 agent 推送增量并落盘，drain/落盘节奏与 final drain（含 bounded drain 窗口）见 refactor 文档；server→web SSE fan-out 仍在同一 server 单进程内存完成，与单 APScheduler 实例共存。**约束收窄**：「不引入外部 fan-out 中间件」收窄为「不引入 Redis 做多实例 HA / 跨进程 fan-out / 分布式锁」，但**显式引入 Redis 作单实例 server↔agent 传输总线**；SSE 仍单进程内存 fan-out，不经 Redis。
- **状态机与索引写**（重构后）：server **消费 `agent-events` 的 `attempt.*` 事件**（不再轮询 agent status API、不依赖 agent HTTP 回调）；`finished/failed/canceled → finalizing → final drain → EOF 稳定（默认 3s）或 hard timeout（30s）→ complete`，每次状态跃迁是对 `execution_log_files.status`（`active/finalizing/complete/missing/expired`）的单行 UPDATE，另由独立 `log_integrity` 列（`complete/partial/missing/expired`）表达日志完整性（业务状态与日志完整性分离，日志 RPO≠0）。`complete` 后 server **向 `command` stream 投递 `cleanup_logs` command**（不再调 agent cleanup HTTP API），agent 在 server final drain 完成前不得删 `job.log`，并有 TTL 兜底（completed 3 天 / orphan 7 天）。
- **备份边界**：因正文在卷、索引在 PG，备份必须**同时覆盖 PostgreSQL + `/server-data/logs` 卷**，否则索引与正文不一致。

> 详尽日志链路 spec 见 `03`/realtime-logs 文档与决策 #11；通信重构口径以 `docs/refactor/00-redis-streams-agent-communication.md` 为准。本节只点明它与调度/推模式的事务边界**不相交**（不同表、不同写路径），以及它同样落在「server 单实例、agent 经 Redis 推 + server 消费、无 WebSocket、SSE 单进程内存 fan-out」的统一模型下（不再是「HTTP pull」）。
