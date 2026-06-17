# 改造分析：定时任务 + 节点调度策略 + 推模式

> 面向后续改造工程师。本文聚焦 dopilot 改造目标中的 **B-2（定时任务）**、**B-3（节点选择策略）**、**B-4（推模式）** 三块，并牵连 **A-1/A-2/A-3（三类被调度对象）** 在调度与下发层面的影响。
>
> 阅读约定：
> - **【现状事实】** = 已通过 Read/Grep 在代码中核实，标注 `file:line`。
> - **【改造建议】 / 【开放问题】** = 设计推断，未实现，需决策。
> - 本文所有路径均为仓库内真实路径；行号以核实当日为准，后续重构会漂移，请以符号名（函数/类名）为准。

---

## 0. 一页速览（TL;DR）

| 主题 | 现状一句话 | 核心缺口 | 推荐落地 |
|---|---|---|---|
| B-2 定时引擎 | APScheduler 单例已可用，但 trigger 硬编码 `cron` | interval/date 未通；回调写死 scrapyd | **方案A**（解硬编码 + 加 interval/date 字段），再叠 **方案B**（task_type + Executor 抽象） |
| B-3 节点策略 | 只有「指定单节点」「勾选多节点全部」 | 无「随机选一个」；策略不持久化；节点序号会漂移 | **方案A**（Task 加 `node_strategy`，触发时动态归约），并提前消化稳定节点 ID |
| B-4 推模式 | 对 scrapyd 是真 HTTP 推；平台内部是「进程内自调用」fan-out | 无远程 worker agent 通道；无独立「一键推送」端点 | **方案D**（Executor 抽象 + 独立即时推送端点 + agent 协议） |

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
                         │     │ db_process_task()  ──► SQLite (Task)   │
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

---

## 2. B-2 定时任务引擎

### 2.1 可复用项（已核实）

| 复用组件 | 文件:行 | 说明 |
|---|---|---|
| BackgroundScheduler 单例 + SQLAlchemyJobStore + ThreadPoolExecutor(20) | `scrapydweb/utils/scheduler.py:32,36,45,90` | 引擎本身与 trigger 类型无关；APScheduler 原生支持 cron/interval/date。dopilot 直接复用同一 scheduler 实例，新 trigger 只需传不同参数到 `add_job`。 |
| `trigger='interval'` 的现成完整样例 | `scrapydweb/utils/check_app_config.py:306-309, 329-332` | `jobs_snapshot` / `delete_task_result` 两个内置维护作业已是 `trigger='interval', seconds=..., misfire_grace_time=60, coalesce=True, max_instances=1, jobstore='memory'` 的工作样例，可直接照搬到用户 interval 任务的组包逻辑。 |
| paused 启动 + 全局 resume/pause | `scheduler.py:90`（`start(paused=True)`）+ `check_app_config.py:288`（按 `scheduler_state` 决定 resume） | 「整体启停定时系统」机制现成。 |
| 持久化三件套 Task / TaskResult / TaskJobResult | `scrapydweb/models.py:89,131,147` | 任务定义、执行汇总、按节点明细的数据线完整；扩展只需加列。 |
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
  (复用现逻辑)     (对接 worker     (对接 worker
  POST schedule    agent: 启容器/  agent: 跑 py3
  .json            exec/重启)      脚本)
        └─────────────┴───────────────┴──────────────┘
              都返回 (status_code, dict) → 统一入库 TaskResult/TaskJobResult
```

> Docker「定时」语义需先定义（见开放问题）：是「定时启动新容器实例」，还是「定时对常驻容器发指令（exec/重启/健康检查）」？这决定 DockerExecutor 接口形态。

### 2.4 候选方案对比

| 方案 | 做法 | 优点 | 缺点 | 工作量 |
|---|---|---|---|---|
| **A 最小扩展** | 解除 trigger 硬编码；加 interval 列（`weeks/days/hours/minutes/seconds`）+ `run_date`；放宽 cron 列 nullable；`update_data_for_timer_task` 改读 `request.form.get('trigger')` 按类型组 `task_data`；模板加 trigger 选择器 + v-show 切换；`dump_task_data` 按类型读取 | 改动集中、风险低、完全复用引擎/落库/管理/结果；向后兼容；无新依赖 | 无迁移机制需手工迁库；schedule.py/模板 cron 假设多、分支后复杂；仍只解决 scrapyd 类 | 中 |
| **B = A + task_type + Executor 抽象** | A 之上加 `task_type(scrapy\|docker\|script)`，放宽 `project/version/spider/jobid` nullable；`schedule_task` 重构为 Executor 分派 | 一次打通 B-2 与 A-2/A-3；调度/执行解耦；与 B-3/B-4 共用入口 | 改动面大；Docker/脚本 agent 协议是另一大块；模型大改 + 无迁移 | 大 |
| **C 引入 Flask-APScheduler / 重写** | 替换手搓 scheduler+Task 双存储 | 长期 API 更清晰、内置 REST | 推翻已联调的 enable/disable/fire/对账/结果逻辑；旧依赖兼容需重验；回归风险高 | 很大（不推荐） |

### 2.5 推荐（B-2）

**分两步，先 A 后 B。**

1. **第一步（方案A，落地 B-2）**：解硬编码 + 加 interval/date 列 + 前端 trigger 选择器 + dump/回填按类型读取。纯复用现有 APScheduler 引擎，风险最低，最快满足 cron+interval，并顺带支持 date 一次性（服务 A-3）。同步：**把 per-task `timezone`（`models.py:117` 已存在）接进 scheduler**，并加全局 `TIMEZONE` 默认（`Asia/Shanghai`）。
2. **第二步（方案B）**：加 `task_type` + Executor 抽象，把 Docker 常驻/脚本接入同一定时框架。

> 因 `models.py` 无 Alembic（见模型内 TODO 注释），两步都需配套 **手工 ALTER 或删库重建脚本**。

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

**强烈建议在第一步就摘取方案C 最值钱的部分：把 `selected_nodes` 从「排序序号」迁到「稳定标识（host:port）」**。理由：与方案A 改动点重叠，提前做成本低；否则增删节点后 `sorted(set())` 漂移会让随机/已存任务选错节点。**避免做全量方案C**（风险/成本最高）。

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
| 无独立「手动即时推送」入口 | 唯一即时多节点推送是 `fire_task`（依附已存 apscheduler_job）和 `ScheduleRunView` 即时 run（走前端 fan-out）。没有「选好节点+策略一键 push、服务端串行执行」的统一端点 |

### 4.3 设计：方案D（Executor 抽象 + 独立推送端点）

```
  ┌─ 定时路径 ────────┐        ┌─ 推模式路径（新增）──────────────┐
  │ APScheduler 线程  │        │ 用户点「立即推送」按钮            │
  │   execute_task()  │        │   POST /push  (新 XHR 端点)      │
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
  (现有 HTTP 推送)   ┌─ 远程 worker agent 协议（需自研）─┐
                    │  HTTP API / docker SDK / SSH ?     │
                    └────────────────────────────────────┘
        └──────────────┴───────────────────────┘
              都返回 (status_code, dict) → 复用 TaskResult/TaskJobResult 入库 + 重试
```

要点：
- 对 **scrapyd** 维持现有 HTTP 推送（`make_request`），零改动。
- 对 **Docker/脚本** 引入远程 worker agent 协议，**替换** `test_client` 自调用（`common.py` 那层做真正远程推时应被网络调用取代）。
- 新增「立即推送」端点：仿 `fire_task` 思路但可**临时指定节点+策略**，服务端串行执行；与 B-3 共用同一「选节点+策略+下发」入口。

### 4.4 候选方案对比（推模式相关）

| 方案 | 做法 | 优点 | 缺点 | 工作量 |
|---|---|---|---|---|
| **D Executor 抽象 + 独立推送端点 + RemoteExecutor** | `schedule_task` 按 task_type 分派；新增不依赖定时器的「立即推送」端点；Docker/脚本走远程 agent | 一并解决 B-4 与 A 三类对象；保留重试/入库；为分布式 push 打基础 | 需定义并实现 agent 协议（平台外工作量）；与 B-3 策略、B-2 task_type 耦合（同改更顺） | 高（含 agent 协议设计） |
| 复用 fire_task（轻量过渡） | 把 `fire_task` 扩成可临时指定节点的「推模式手动下发」入口 | 不必新造调度，最快出可见效果 | 仍依附已存 apscheduler_job，无法承载非定时一次性 push；不解决远程通道 | 低（仅过渡） |

### 4.5 推荐（B-4）

**采用方案D，与 A-2/A-3 三类对象一起做（第二步）**：在 `execute_task.py` 抽象 Executor 接口（Scrapyd/Docker/Script），按 `task_type` 分派；新增「立即推送」端点做服务端串行 push；scrapyd 维持现有推送，Docker/脚本引入远程 agent 协议。重试与 TaskResult/TaskJobResult 入库全程复用。过渡期可先用「扩展 fire_task」拿到可见效果。

---

## 5. 整体推荐与实施顺序

```
第一步（低风险，可独立交付）
 ├─ B-2: 解除 trigger 硬编码 → 支持 cron + interval + date
 │       · schedule.py 读 request.form.get('trigger')，按类型组 task_data
 │       · models.py 加 interval 列(weeks/days/hours/minutes/seconds)+run_date，放宽 cron 列 nullable
 │       · schedule.html 加 trigger 选择器 + v-show 切换
 │       · tasks.py dump_task_data 按 trigger 类型读取
 ├─ B-3: Task 加 node_strategy(默认 all)；execute_task 触发时按策略归约(random→random.choice)
 │       · 同步：selected_nodes 从「序号」迁到「稳定标识 host:port」(摘取方案C 要点)
 └─ 时区: scheduler 显式 timezone；default_settings 加 TIMEZONE(默认 Asia/Shanghai)；接入 per-task timezone 列

第二步（大块，含平台外 agent 工作）
 ├─ B/A: Task 加 task_type(scrapy|docker|script)，放宽 scrapy 专有列 nullable
 ├─ Executor 抽象: ScrapydExecutor / DockerExecutor / ScriptExecutor，保持 (status_code,dict) 契约
 └─ B-4: 新增「立即推送」端点；Docker/脚本远程 worker agent 协议

贯穿
 └─ 无 Alembic：每步配套手工 ALTER 或删库重建脚本（models.py 注释 TODO）
```

---

## 6. 改动文件清单（汇总）

| 文件 | 主题 | 改动要点 |
|---|---|---|
| `scrapydweb/views/operations/schedule.py` | B-2/B-3 | `update_data_for_timer_task()`(291)：trigger 改读表单并按 cron/interval/date 组 `task_data`，写入 `node_strategy`；`update_kwargs`(189) 去掉 `trigger='cron'` 硬编码改按任务回填；`db_process_task()`(416) 按 trigger 写对应列 + 落库 `node_strategy`；`query_task()`(93) 编辑回填按 trigger 类型读列；`handle_form()`(362-373) 即时运行按策略决定下发集合/`first_selected_node`；`add_update_task()`(447) 基本不动 |
| `scrapydweb/models.py` | B-2/B-3/A | **已有** `trigger`(94)、`timezone`(117)；新增 interval 列 `weeks/days/hours/minutes/seconds`(Integer,nullable) 与 `run_date`(String(19))；放宽 `year..second`(105-112) 为 nullable；新增 `node_strategy`(String,默认 `all`)；（第二步）加 `task_type` 并放宽 `project/version/spider/jobid`(98-101) nullable；建议 `selected_nodes` 语义迁为稳定标识。**无迁移框架，须手工 ALTER** |
| `scrapydweb/templates/scrapydweb/schedule.html` | B-2/B-3 | 加 trigger 类型选择器(el-radio/el-select: cron\|interval\|date) + v-show 切换 cron/interval/date 字段块；加 interval(seconds/minutes/hours/days/weeks) 与 date(run_date picker) 输入；加 `node_strategy` 控件；Vue `data`/`form` 增对应字段，`submit` 的 formData 增新字段；编辑回填显示已存策略 |
| `scrapydweb/views/overview/tasks.py` | B-2/B-3/B-4 | `dump_task_data()`(380-414) 按 trigger 类型读取（CronTrigger→`trigger.fields`，IntervalTrigger→`trigger.interval`，DateTrigger→`run_date`），避免对 interval/date 报错；`process_tasks`(122) 展示 `node_strategy`（状态推导依赖 `next_run_time`(166-188) 已通用）；`fire_task()`(353-362) 可扩为「推模式手动下发」入口 |
| `scrapydweb/views/operations/execute_task.py` | B-2/B-3/B-4/A | `execute_task()`(150) 在 `json.loads(task.selected_nodes)`(168) 后按 `task.node_strategy` 归约（random→`random.choice`）；`schedule_task()`(75-104) 按 `task_type` 抽象 Executor 分派（scrapyd/docker/script），保持 `(status_code,dict)` |
| `scrapydweb/views/baseview.py` | B-3 | `get_selected_nodes()`(257-262) 加可选策略参数或在调用方归约；若采纳稳定节点 ID，`__init__`(189-197) 按 `node-1` 索引取 SERVER/AUTH 的方式需配套调整 |
| `scrapydweb/templates/scrapydweb/include_multinodes_checkboxes.html` | B-3/B-4 | 加策略单选(指定/全部/随机)与现有 checkCurrent/checkAll/`checked_amount` 并存，提交 `node_strategy`；可挂 push 按钮 |
| `scrapydweb/utils/scheduler.py` | B-2 | `BackgroundScheduler`(45) 显式传 `timezone`（取自 config，默认 `Asia/Shanghai`），解决时区未设(44-45 注释)导致 cron/date 偏移 |
| `scrapydweb/utils/check_app_config.py` | B-2/B-3 | `jobs_snapshot`/`delete_task_result`(306-332) 是 interval 现成样例可照搬；`check_scrapyd_servers()`(361-392) 的 `sorted(set())`(388) 是序号漂移根因，改稳定 ID 或新增节点类型(docker/script) 在此扩展；新增 TIMEZONE/node_strategy 的 `check_assert` 校验 |
| `scrapydweb/default_settings.py` | B-2/B-3 | 新增 `TIMEZONE`(默认 `'Asia/Shanghai'`)、`DEFAULT_NODE_STRATEGY`(默认 `'all'`)（及第二步 task_type 相关），作为表单默认与旧任务回退 |
| `scrapydweb/common.py` | B-4 | `get_response_from_view`(48-80) 进程内自调用：两段式推送可继续复用；做**真正远程 push** 时此层应替换为对远程 agent 的网络调用 |

---

## 7. 开放问题（需产品/架构决策）

### 定时引擎
1. interval 任务是否支持 `start_date/end_date/jitter`（APScheduler IntervalTrigger 支持），还是只暴露简单周期值？影响表单与字段范围。
2. 无 Alembic 下，加列是接受**删库重建**，还是提供一次性手工 ALTER/迁移脚本以保留存量定时任务？
3. cron 时区默认 `Asia/Shanghai` 是否合适？是否做成「每任务 timezone（`models.py:117` 已有列）+ 全局默认」两层？
4. Docker 常驻爬虫的「定时」语义：定时**启动新容器实例**，还是定时**对常驻容器发指令**（exec/重启/健康检查）？决定 DockerExecutor 接口形态与是否需要 date/once 语义。
5. 一次性 Python 脚本用 date trigger（执行后 job 自动移除、显示 Finished）是否符合预期，还是需保留任务定义以便手动重跑？
6. 三类执行器共用同一 Task 表（加 task_type + 可空列）还是各建独立模型？前者改动小但列语义混杂，后者更清晰但管理/结果查询要泛化。

### 节点策略与推模式
7. 「随机选一个」要**静态随机**（建任务时定死）还是**动态随机**（每次触发从候选随机）？后者价值更高但与「建任务即固化 selected_nodes」模型冲突，决定改动落点（`execute_task` vs `ScheduleRunView`）。
8. 随机/负载选择是否需按节点健康状态（daemonstatus 存活、当前 running 数）过滤？若需要，要新增集中的节点健康采集，现状无。
9. 节点标识是否从「排序序号」迁到稳定标识（host:port）？不迁则 `sorted(set())`(`check_app_config.py:388`) 漂移会让随机选中节点在增删后错位，且已存任务 `selected_nodes` 失效。
10. B-4 推模式对 Docker 常驻/脚本的下发协议是什么（自研 agent HTTP API / SSH / docker SDK）？决定 `schedule_task` 是否还能复用 `test_client` 自调用，还是必须替换为真实远程网络调用。
11. B-4「推模式」与 B-3「随机」是否在同一「即时推送」端点统一（选节点+策略+一键下发），还是分别做（定时任务带策略 + 手动 fire）？影响是否新建独立端点还是扩展 `fire_task`。
12. 多节点「全部执行」的并发模型：现状串行逐节点（`execute_task.py:44`）；是否需并发下发以缩短大集群延迟？涉及 `ThreadPoolExecutor(20)` 与 SQLite 线程限制的取舍。
