# 改造分析：多类型执行器抽象（Scrapy / Docker 长连接 / Python 脚本）

> 适用对象：后续承接 dopilot 改造的工程师。
> 阅读约定：本文严格区分「**现状事实**」（已 Read/Grep 核实源码，标注 `文件:行号`）与「**改造建议 / 开放问题**」（设计推演，需团队决策）。
> 行为参考基线：`reference/scrapydweb/`（**只读**，仅作功能 / 行为对照与测试 oracle）；dopilot 代码**全新编写**于 `apps/server/dopilot_server/` 等骨架，本文所有 `文件:行号` 引用均指向 `reference/scrapydweb/` 的行为参考，**不是** dopilot 待改文件。

> **【scrapydweb 参考边界】** scrapydweb 仅作**功能层/行为参考**与**测试 oracle**；其代码写法、目录结构、模块划分、命名、依赖、配置形态**一律不得作为 dopilot 的设计依据**。dopilot 为 greenfield、按 `apps/`+`packages/` 自有领域 structure-first 设计(权威布局见 `05-dev-setup-and-known-issues.md` §1)，**不对 scrapydweb 做改名/git mv**。详见 `00-requirements.md` 决策表。

---

## 0. 一句话结论

scrapydweb 目前**没有任何「执行器（executor）抽象层」**——所有「运行 / 下发」路径都硬编码为对 scrapyd 的 `*.json` HTTP API 调用（行为参考事实）。要支持「Docker 常驻爬虫」与「一次性 Python3 脚本」，dopilot 在 `apps/server/dopilot_server/executors/` 下**全新设计一个 `BaseExecutor` 抽象层**；scrapydweb 的 scrapyd-only 链路仅作为 `ScrapydExecutor` 要复刻的**行为参考**（它做什么 / 语义为何），不是被改造的代码——dopilot 没有「现有链路」可改。

推荐主干：**方案 A（`BaseExecutor` 抽象 + 按 `task_type` 多态分派）**。执行通道按 v1 已锁定 spec **统一经 dopilot-agent**：server 不直连裸 scrapyd、不直连各节点 docker daemon；ScrapydExecutor / DockerExecutor / ScriptExecutor 一律通过 agent HTTP API 下发，由 agent 在本机调本机 scrapyd（子进程拉起）/ docker SDK / subprocess。**dopilot-agent 是阶段 1 即落地的正式架构（非分布式终态选项）**。

---

## 1. 现状事实：为什么当前「只支持 scrapyd」

scrapydweb 围绕 scrapyd 的 HTTP 协议（`schedule.json` / `cancel.json` / `listjobs.json` …）构建。「运行 / 下发 / 状态采集」的每一条路径都直接拼 scrapyd URL，没有 `task_type` 判别、没有 Docker SDK、没有 SSH/agent 机制、没有裸脚本执行能力。下面是核实过的完整证据链。

### 1.1 四条「下发 / 运行」链路全部硬编码 scrapyd

| # | 场景 | 入口（文件:行号） | 硬编码事实 |
|---|------|------------------|-----------|
| 1 | 即时运行 | `scrapydweb/views/operations/schedule.py:395` `ScheduleRunView.handle_action()` | `_action='run'` 分支直接 `self.make_request(self.url, data=self.data, auth=self.AUTH)`，其中 `self.url` 在 `ScheduleView.__init__` 第 64 行硬编码为 `'http://%s/schedule.json' % self.SCRAPYD_SERVER` |
| 2 | 定时执行 | `scrapydweb/views/operations/execute_task.py:75` `TaskExecutor.schedule_task()` → `scrapydweb/views/operations/schedule.py:617` `ScheduleTaskView` | `execute_task` 通过 `get_response_from_view` 进程内 POST 到 `/N/schedule/task/`，命中 `ScheduleTaskView.dispatch_request()`（第 627-642 行），组装 `project/_version/spider/jobid + settings_arguments` 后 `make_request` 到第 622 行的 `'http://%s/schedule.json'` |
| 3 | 单节点 API | `scrapydweb/views/api.py:8` `API_MAP` | `API_MAP = dict(start='schedule', stop='cancel', forcestop='cancel', liststats='logs/stats')` 把语义动作翻成 scrapyd 端点；第 20 行 `self.url = 'http://{}/{}.json'.format(self.SCRAPYD_SERVER, ...)` |
| 4 | HTTP 封装 | `scrapydweb/views/baseview.py:285` `make_request()` | 唯一的 HTTP 封装，假定下游返回 scrapyd 风格 JSON（取 `status/message/jobid`） |

> 注（方案 A 的复用价值）：链路 1 与链路 2 最终都收口到 `make_request(schedule.json)`，这正是「下沉为 `ScrapydExecutor.run_on_node` 后行为不变」的天然切点。

### 1.2 数据模型强绑 scrapyd 语义

`scrapydweb/models.py` `Task` 模型（第 89-128 行）：

```text
project   = db.Column(..., nullable=False)   # models.py:98   scrapyd 专属
version   = db.Column(..., nullable=False)   # models.py:99   scrapyd 专属
spider    = db.Column(..., nullable=False)   # models.py:100  scrapyd 专属
jobid     = db.Column(..., nullable=False)   # models.py:101  scrapyd 专属
settings_arguments = db.Column(db.Text(), nullable=False)  # models.py:102
selected_nodes     = db.Column(db.Text(), nullable=False)  # models.py:103
```

- 这四个 scrapyd 专属列均 `nullable=False`（事实，`models.py:98-101`）。
- **没有 `task_type` 判别列**，无法在分派点区分三类对象。
- **没有节点策略列**（`all` / `random`）。
- Docker / 脚本所需字段（`image/command/env/volumes` 或 `script_path/interpreter/args`）一概不存在。
- `models.py:14` 顶部 TODO 明确：**当前无数据库迁移机制（无 Alembic / Flask-Migrate）**，加列须手动迁移或重建库。

### 1.3 节点配置模型只能描述 scrapyd 节点

`scrapydweb/views/baseview.py:99-104`：`SCRAPYD_SERVERS` 被解析成 4 个**等长并行 list**，按 `node-1` 索引取值：

```text
SCRAPYD_SERVERS              # baseview.py:99   ['ip:port', ...]
SCRAPYD_SERVERS_GROUPS       # baseview.py:101
SCRAPYD_SERVERS_AUTHS        # baseview.py:102  [(user,pwd)|None, ...]
SCRAPYD_SERVERS_PUBLIC_URLS  # baseview.py:103
```

只能表达「`ip:port` + basic auth」。**无法声明节点能力**（scrapyd / docker / script）、docker daemon 端点、agent token 等——新执行器拿不到目标节点的连接信息。

### 1.4 启动期强制 scrapyd 连通性断言

`scrapydweb/utils/check_app_config.py:429`：

```python
assert any(results), "None of your SCRAPYD_SERVERS could be connected. "
```

无任何 scrapyd 可达即**启动失败**。可用 `CHECK_SCRAPYD_SERVERS=False` / CLI `-dc` 跳过，但默认行为对「纯 Docker / 脚本」平台不友好。

### 1.5 状态采集机制 scrapyd 专属

- `scrapydweb/utils/poll.py`：靠正则解析 scrapyd `/jobs` HTML 页面拿任务状态。
- 依赖 logparser 解析 scrapy 日志统计（pages / items）。
- scrapyd 的 jobs 状态机是 `pending → running → finished`（`models.py:55` `status` 注释：`Pending 0, Running 1, Finished 2`）。

**常驻 Docker 进程永远 `running`、永不 `finished`**，与该状态机根本冲突；常驻进程没有 scrapyd jobs 页、没有 scrapy 日志格式，无法复用这套采集。

### 1.6 远程执行通道实为「进程内伪分布式」

定时执行链路里，`get_response_from_view`（`scrapydweb/common.py`）是 **Flask test_client 进程内自调用**，再由 `ScheduleTaskView` 用 `requests` 转发到 scrapyd。**没有任何真正的远程执行 agent**——Docker / 脚本若运行在远程 worker 节点，缺少下发协议（agent HTTP API / SSH / docker daemon over TLS）。

### 1.7 依赖缺失

`scrapydweb/setup.py` `install_requires`（第 35 行起）**无 `docker` / `paramiko` / `kubernetes`**。当前关键钉死版本（改造时须兼容）：

| 依赖 | 钉死版本 | 行号 |
|------|---------|------|
| APScheduler | 3.6.0 | `setup.py:36` |
| Flask | 2.0.0 | `setup.py:39` |
| Flask-SQLAlchemy | 2.4.0 | `setup.py:41` |
| SQLAlchemy | 1.3.24 | `setup.py:53` |
| Werkzeug | 2.0.0 | `setup.py:56` |

---

## 2. 三类被调度对象的差异（改造的核心驱动）

| 维度 | (1) Scrapy 爬虫（现状支持） | (2) Docker 长连接 / 常驻爬虫（待建） | (3) Python3 一次性脚本（待建） |
|------|------|------|------|
| 生命周期 | 一次跑完即退出 | **常驻 / 长连接，进程不退出** | 一次跑完即退出 |
| 部署单元 | egg 包 + spider 名 | Docker 镜像 | 脚本文件（`.py`） |
| 下发协议（v1 统一经 agent） | agent → 本机 scrapyd `schedule.json` | agent → docker SDK `run -d` | agent → `subprocess` |
| 启动参数 | `project/version/spider/settings/args` | `image/command/env/volumes/ports` | `script_path/interpreter/args/env` |
| 状态语义 | pending / running / finished | **running / stopped / unhealthy**（无 finished） | running / exited(退出码) |
| 状态采集（server 轮询 agent `/status`） | agent tail scrapyd `/jobs` + logparser | 容器存活 + 健康检查 + 退出码 | 进程存活 + 退出码 |
| 实时日志（server pull agent tail API，stream） | scrapyd job.log（stream=log） | agent tail 容器日志（stream=log） | 子进程 stdout/stderr 捕获（stream=stdout/stderr）|
| 停止语义（经 agent `/stop`） | `cancel.json`（信号） | `docker stop` | 进程 kill / 信号 |
| 与现有契约 | 完全契合 | **finished 状态机冲突** | scrapyd 无法跑任意脚本 |

关键冲突点：**Docker 常驻进程的「永不 finished」语义**会打乱 scrapyd 风格的 jobs 页 / 告警逻辑（`poll.py`）；而 scrapyd 只接受 egg+spider，**无法运行裸脚本**。这两点决定了不能用 scrapyd 硬扛（见方案 D 反模式）。

---

## 3. 可复用项（现成且经过验证的资产）

| # | 组件 | 文件:行号 | 复用方式 |
|---|------|----------|---------|
| R1 | `TaskExecutor.main()` 编排骨架（行为参考） | `execute_task.py:42-61` | 「遍历 `selected_nodes` → 逐节点执行 → 成功/失败计数 → 写 `TaskResult/TaskJobResult` → 失败节点延迟 3 秒重试一次」是可复刻的执行编排行为骨架。dopilot 自有编排基类把「实际下发」抽象成 `run_on_node(node)` 接口、由各子类实现；scrapydweb 中对应的下发逻辑是 `schedule_task()`（`execute_task.py:75-104`），作为 `ScrapydExecutor` 的行为参考 |
| R2 | 结果记录契约 | `execute_task.py:63,106,125` | `get_task_result_id()` / `db_insert_task_job_result()` / `db_update_task_result()` 与执行类型无关，三类对象通用 |
| R3 | `TaskResult` / `TaskJobResult` 三层结果模型 | `models.py:131-179` | `TaskResult`（汇总 fail/pass）+ `TaskJobResult`（每节点明细 `node/server/status_code/status/result`）与执行类型解耦，**直接复用** |
| R4 | Task 的全部触发字段 | `models.py:105-121` | `year..second / start_date / end_date / timezone / jitter / misfire_grace_time / coalesce / max_instances`（cron/interval/date）三类对象共用，只需新增 `task_type` 列并放宽 NOT NULL |
| R5 | APScheduler 引擎 + 统一回调 | `execute_task.py:150-172`，`utils/scheduler.py` | `execute_task(task_id)` 是 `add_job` 的统一回调，**是按 `task_type` 分派执行器的最佳单点**：第 152 行读出 task 后选 `ScrapydExecutor/DockerExecutor/ScriptExecutor` |
| R6 | 路由注册机制 | `__init__.py:148` `register_view()` | 统一给视图加 `/<int:node>/` 前缀（第 151 行）。新增 docker/script 页面与下发端点按同样模式挂入，复用 node 索引语义与 1-based 约定 |
| R7 | 节点选择基座 | `baseview.py:257-262` `get_selected_nodes()` | 解析勾选节点列表，三类对象的「指定/全部」共用；「随机一个」策略可在执行器入口对返回列表做 `random.choice` 归约 |
| R8 | 统一 HTTP 封装（行为参考） | `baseview.py:285` `make_request()` | 返回 `(status_code, dict)` 的封装契约可复刻。v1 三类对象**都经 dopilot-agent HTTP API** 下发，dopilot 自有 HTTP 客户端按此契约发请求；返回 dict 只要补齐 `status/message/jobid` 即可无缝接入结果记录（行为参考 `db_insert_task_job_result` `execute_task.py:106-122`）|
| R9 | 常驻进程范式（行为参考，**用于 agent 侧**） | `utils/sub_process.py`（`init_poll:85` / `init_logparser:53`） | `Popen` 拉起子进程 + `prctl(PR_SET_PDEATHSIG)`（第 36-38 行）/ `atexit`（第 57/89 行）绑定父进程生命周期。**dopilot-agent** 在本机跑脚本 / 拉起本机 scrapyd 子进程时可复刻此范式管理子进程生命周期（server 侧不直接跑这些子进程）|
| R10 | scrapyd 校验开关 | `check_app_config.py:429`，`CHECK_SCRAPYD_SERVERS` / `-dc` | `assert any(results)` 可被开关跳过（`update_app_config` 已支持）。纯 Docker/脚本部署时复用此开关避免启动失败，**无需改断言** |

> 资产分布示意：

```text
                ┌──────────────────────────────────────────────────┐
   复用骨架     │ APScheduler 引擎 (R5)  +  路由注册 (R6)             │
   （类型无关） │ TaskExecutor.main 编排 (R1) + 结果记录契约 (R2/R3) │
                │ 触发字段 (R4) + 节点选择 (R7) + HTTP 封装 (R8)     │
                └──────────────────────────────────────────────────┘
                          ▲              ▲              ▲
       仅此处需替换 ─────┐ │              │              │
                  ┌──────┴─┴─────┐ ┌──────┴───────┐ ┌────┴─────────┐
   按 task_type   │ ScrapydExec  │ │ DockerExec   │ │ ScriptExec   │
   多态分派       │ (复刻 scrapyd│ │ (待建/新依赖)│ │ (待建/参考R9)│
                  │  下发行为)   │ │              │ │              │
                  └──────────────┘ └──────────────┘ └──────────────┘
```

---

## 4. 缺口清单（gaps）

| # | 缺口 | 根因（文件:行号） | 影响的目标 |
|---|------|------------------|-----------|
| G1 | 无执行器抽象接口（Executor/Runner） | 下发动作硬编码 scrapyd（`schedule.py:64`、`execute_task.py:75`、`api.py:8`），无统一 `run/stop/status` 接口 | A 全部 |
| G2 | Task 缺 `task_type` 列；`project/version/spider/jobid` 为 NOT NULL；无迁移机制 | `models.py:98-101` nullable=False；`models.py:14` TODO 无 Alembic | A 全部 |
| G3 | Docker 编排能力完全缺失 | `setup.py` 无 `docker`；scrapyd「跑完即退」与「常驻」语义不匹配（`models.py:55` 状态机） | A-2 |
| G4 | 裸 Python3 脚本执行能力缺失 | 无「在节点上 `python3 script.py`」通道；scrapyd 只接受 egg+spider | A-3 |
| G5 | 远程节点执行通道缺失 | `get_response_from_view` 为进程内 test_client 自调用（`common.py`），仅转发到 scrapyd；无远程 agent/SSH/daemon | A-2、A-3、B-4(push) |
| G6 | 常驻进程状态采集 / 健康检查缺失 | `poll.py` 解析 scrapyd `/jobs` HTML + logparser；常驻容器无此格式 | A-2、B-1 |
| G7 | 节点配置模型只描述 scrapyd 节点 | `baseview.py:99-104` 四并行 list 按 `node-1` 索引；无能力 / docker 端点 / token | A-2、A-3、B-3(节点策略) |
| G8 | 启动期强制 scrapyd 连通性断言 | `check_app_config.py:429` `assert any(results)` | 纯 Docker/脚本部署 |

---

## 5. 候选方案对比

### 5.1 概览对比表（含工作量）

| 方案 | 核心思路 | 主要优点 | 主要缺点 | 工作量 | 定位 |
|------|---------|---------|---------|-------|------|
| **A**：`BaseExecutor` 抽象 + 三实现类，按 `task_type` 分派 | dopilot 在 `apps/server/dopilot_server/executors/` 下新建执行器包，定义抽象基类 `run_on_node/stop/get_status`（日志走 server 侧 pull，见 03，不在 Executor 上放 push 式 `stream_logs`）；三类执行器一律**经 dopilot-agent HTTP API** 下发；scheduler 回调按 `task_type` 选实现 | 结构清晰、可最大化复刻编排骨架行为（R1-R3 结果记录/重试/节点遍历）；统一入口；加新类型只需加子类 | scheduler 回调 + Task 模型 + 迁移须配套实现；**只解决「如何多态分派」，不解决「在哪执行」**（在哪执行由 v1 锁定：经 agent 本机执行） | 中（抽象层 + ScrapydExecutor 约 1-2 天；Docker/Script 具体实现另算） | **架构主干（不可绕过）** |
| **B（v1 已锁定通道）**：dopilot-agent（每节点跑 HTTP agent，server 只与 agent 通信） | agent 暴露统一 HTTP API：`POST /run`(type=scrapy\|docker\|script)、`/stop`、`GET /status`、**`GET /logs/tail`（按 offset 拉日志增量）**、cleanup；内部对接本机 scrapyd（子进程拉起）/ docker SDK / subprocess。**server 主动 pull、agent 不主动推、第一版完全不使用 WebSocket** | 三类对象节点侧统一收口；server 不直连裸 scrapyd、不直连各节点 docker daemon（docker SDK 调用全归 agent）；docker/脚本本机执行天然解决；实时日志由 **server 按需从 agent tail API 拉取增量**，写 `/server-data/logs` + PG 索引，再经 SSE 推前端（详见 03-gap-realtime-logs） | 需新增 + 部署 + 运维 agent（每节点装）；安全面收敛为 agent `shared_token`（非空才启用，内网防误操作非零信任） | 高（1-2 周起，但 **阶段 1 即落地、非可选项**） | **v1 已锁定执行通道** |
| ~~**C**：主程序直连 docker SDK + 本机 subprocess（无 agent）~~ | ~~主程序用 docker SDK 连各节点 docker daemon~~ | — | **v1 spec 已否决**：server **不得**直连各节点 docker daemon、不得直连裸 scrapyd；docker SDK 调用 / subprocess 一律归 dopilot-agent 本机执行 | — | **已否决（违反 v1 单一 agent 通道约束）** |
| **D**：复用 scrapyd 跑脚本 / 包装常驻进程 | 脚本伪装成最简 spider 经 egg 部署；常驻容器用 supervisor spider 拉起。完全复用现有 deploy/schedule/jobs/log 链路 | 几乎不改主程序，复用全部 scrapyd 生态 | **反模式**：脚本伪装成 spider；常驻进程与 finished 状态机冲突（jobs 页/告警全乱）；egg 打包裸脚本极笨重；无法满足 Docker 常驻语义；本质未解决目标 A | 低（但技术债极高） | **不推荐** |

### 5.2 方案对目标 B（平台功能）的覆盖

| 目标功能 | 方案 A | 方案 B（v1 通道） | ~~方案 C~~ | 方案 D |
|---------|:-----:|:-----:|:-----:|:-----:|
| B-1 实时日志流 | 由 server 侧 pull 链路承载（非 Executor 职责） | **server 从 agent tail API 按 offset 拉增量 + SSE 推前端（无 WS）** | ~~已否决~~ | 仅 scrapy 日志 |
| B-2 定时调度 | 复用 APScheduler | 复用 | ~~已否决~~ | 复用 |
| B-3 节点策略(全部/随机) | 入口归约 R7 | agent 寻址清晰 | ~~已否决~~ | 复用 |
| B-4 push 模式下发 | 取决于通道 | **agent `POST /run` 原生 push** | ~~已否决~~ | 伪分布式 |
| B-5 i18n（中文） | 与执行器解耦，独立任务 | 同左 | ~~已否决~~ | 同左 |

---

## 6. 推荐架构

### 6.1 推荐组合

> **方案 A 为架构主干**（不可绕过的多态分派层），执行通道按 v1 已锁定 spec **统一为方案 B（dopilot-agent）**：
> - server 端三类 Executor 均**经 dopilot-agent HTTP API** 下发（`POST /run` push）；
> - agent 在本机执行：scrapy → 调本机 scrapyd（agent 子进程拉起，scrapyd 仅监听容器内部端口、对外只暴露 agent API）；docker → docker SDK；script → subprocess（参考 R9）；
> - **dopilot-agent 阶段 1 即落地**，不存在「先无 agent 直连、后补 agent」的过渡形态（方案 C 已否决）。

理由：
1. 无论 task_type 为何，都**需要一个 `task_type` 多态分派层**，且能最大化复用 `TaskExecutor.main` 的现成编排资产（R1-R3）。
2. 先按 scrapyd 的 `schedule.json` 调用语义**全新实现 ScrapydExecutor**（以 `reference/scrapydweb` 的 scrapyd 下发行为为对照 oracle，验证其输出契约一致）；注意 dopilot 的 ScrapydExecutor **不直连裸 scrapyd**，而是 `server → agent → 本机 scrapyd`，agent 内部再调 scrapyd `schedule.json`/`addversion.json`。
3. 实时日志（B-1）由 **server 侧 pull 链路** 承载：server 按 offset 从 agent `GET /logs/tail` 拉增量、写 `/server-data/logs` 正文 + PG 索引、经 SSE 推前端，**第一版完全不用 WebSocket**（agent tail scrapyd job.log；脚本阶段用 stdout/stderr 流）。详见 03-gap-realtime-logs。
4. egg 部署 **第一版仅支持上传已构建 egg**：用户上传 → server → 转发 agent → agent 调本机 scrapyd `/addversion.json`，不做本地/源码/Git/CI 构建。
5. **务必先加 `Task.task_type` 列并放宽 `project/version/spider/jobid` 的 nullable**，否则三类对象无法共表。

### 6.2 执行器抽象（方案 A 接口设想）

```text
apps/server/dopilot_server/executors/
├── base.py            # BaseExecutor 抽象基类 + EXECUTOR_REGISTRY（缝① 执行器注册表）
├── scrapyd.py         # ScrapydExecutor（经 agent 调本机 scrapyd schedule.json/addversion.json，行为参考 execute_task.py:75-104）
├── docker.py          # DockerExecutor（经 agent，agent 内部用 docker SDK）
└── script.py          # ScriptExecutor（经 agent，agent 内部用 subprocess）

class BaseExecutor:
    task_type = None
    # 三类执行器一律经 dopilot-agent HTTP API 下发（server 不直连裸 scrapyd / docker daemon）
    def run_on_node(self, agent) -> dict: ...   # POST agent /run；返回 {status, message|jobid, status_code, url}
    def stop(self, agent, job): ...             # POST agent /stop
    def get_status(self, agent, job): ...       # GET agent /status（server 轮询此 API 判结束，不依赖 agent 回调）
    # 注：实时日志不在 Executor 接口上。日志为 server 侧 pull：server 按 offset 调 agent GET /logs/tail
    #     拉增量 → 写 /server-data/logs 正文 + PG 索引 → SSE 推前端。第一版无 WebSocket。详见 03-gap-realtime-logs。

EXECUTOR_REGISTRY = {
    'scrapy': ScrapydExecutor,
    'docker': DockerExecutor,
    'script': ScriptExecutor,
}
```

分派单点：dopilot scheduler 的统一回调（`apps/server/dopilot_server/scheduler/`）读出 task 后，按 `task_type` 选执行器：

```text
task = task_repository.get(task_id)                # dopilot scheduler 回调
executor_cls = EXECUTOR_REGISTRY[task.task_type]   # 缝① 多态分派
executor = executor_cls(...)
executor.run()                                     # 执行编排（遍历节点/记结果/重试），仅 run_on_node 不同
```

> 行为参考：scrapydweb 在 `execute_task.py:152` 读出 task 处是天然的分派单点，其 `TaskExecutor.main()`（`execute_task.py:42-61`）「遍历节点→执行→记结果→重试」是可复刻的编排骨架。dopilot 自有的执行编排基类在循环中调用子类 `run_on_node(node)`；`ScrapydExecutor.run_on_node` 按 scrapyd `schedule_task`（`execute_task.py:75-104`）的下发语义全新实现。

### 6.3 v1 执行/日志架构（方案 B：dopilot-agent，阶段 1 即落地）

> 三类 task_type 共用同一条链路：server → dopilot-agent → 本机执行器。server **不直连裸 scrapyd、不直连各节点 docker daemon**。日志为 **server 主动 pull**（agent tail API），**无 WebSocket、agent 不主动推**。

```text
        ┌─────────────────────── dopilot server (FastAPI, 单容器/uvicorn workers=1/单 APScheduler) ───────────────────────┐
        │  APScheduler ── execute_task(task_id) ── EXECUTOR_REGISTRY[task_type]                                          │
        │        │              │              │                                                                         │
        │  ScrapydExecutor  DockerExecutor  ScriptExecutor   ── 均经 agent HTTP API ──┐                                   │
        │                                                                              │                                  │
        │  日志 pull loop: 每 30s 后台 drain / 打开日志窗口升 1s ── GET agent /logs/tail?offset (≤256KB/次) ──┐           │
        │        └─→ 写 /server-data/logs/YYYY/MM/{execution_id}/{attempt_id}.{stream}.log + PG execution_log_files 索引     │
        │        └─→ SSE 单向推前端 (server→web；无 WS)                                                       │           │
        └──────────────────────────────────────────────────────────────────────────────┼───────────────────┼───────────┘
                                         │ POST /run (push) / POST /stop / GET /status / GET /logs/tail / POST /logs/cleanup
                                         ▼
                                  ┌────────────────────────────────────────────────────────┐
                                  │  dopilot-agent  (每节点一个；对外 6800 = agent API)        │
                                  │  /run /stop /status /logs/tail /logs/cleanup /health      │
                                  │   ├─ scrapy → 本机 scrapyd（agent 子进程拉起，仅听内部端口如 6801）→ tail job.log │
                                  │   ├─ docker → docker SDK                                   │
                                  │   └─ script → subprocess（stdout/stderr）                  │
                                  │  无状态/无 ack/无去重队列；offset 权威在 server PG          │
                                  └────────────────────────────────────────────────────────┘
```

> 结束检测：server 轮询 agent `GET /status`（不依赖 agent 回调），finished/failed/canceled → finalizing → final drain → EOF 稳定（默认 3s）或 hard timeout（30s）→ complete；complete 后 server 调 agent `POST /executions/{attempt_id}/logs/cleanup`（agent 另有 TTL 兜底）。详见 03-gap-realtime-logs。

### 6.4 推荐落地顺序

> 注：执行通道从第一步起就是 dopilot-agent（apps/agent，阶段 1 即落地），不存在「先无 agent、后补 agent」的过渡。

```text
① 抽象接口 (apps/server/dopilot_server/executors/base.py：BaseExecutor + EXECUTOR_REGISTRY)
   + dopilot-agent 骨架 (apps/agent：/run /stop /status /logs/tail /logs/cleanup /health)
        ↓
② ScrapydExecutor (经 agent 调本机 scrapyd schedule.json；agent 子进程拉起 scrapyd；
   egg 仅上传部署：上传→server→agent→本机 scrapyd /addversion.json。以 scrapydweb 行为为对照 oracle)
        ↓
③ Task 模型 (apps/server/dopilot_server/models/) 自带 task_type/node_strategy + 三类对象字段
   + PostgreSQL + SQLAlchemy + 裸 Alembic 迁移 (apps/server/migrations/)
        ↓
④ 日志 pull 链路：server 从 agent GET /logs/tail 拉增量 → 写 /server-data/logs 正文 + PG execution_log_files 索引
   → SSE 推前端（第一版无 WebSocket）。详见 03-gap-realtime-logs
        ↓
⑤ DockerExecutor (经 agent；agent 内部用 docker SDK 起停常驻容器、采集健康/退出码)
        ↓
⑥ ScriptExecutor (经 agent；agent 内部用 subprocess，参考 sub_process.py 子进程生命周期范式 R9)
        ↓
⑦ 节点模型：Node 实体 (apps/server/dopilot_server/nodes/ + models/) 承载 stable agent_id/type/endpoint(agent 地址)/token/能力，
   支持 all/random 策略；第一版 [nodes].agents 仅作初始发现，server 轮询 agent /health 后 upsert nodes 表
        ↓
⑧ docker/script 的 /api/v1 JSON 端点 + apps/web SPA 页面/路由 + i18n 接入
```

---

## 7. dopilot 新建文件 ↔ 行为参考映射

> 左列为 dopilot **全新实现**的文件（`apps/server/dopilot_server/` 等 canon 路径，权威布局见 `05-dev-setup-and-known-issues.md` §1）；右列为「要实现的行为 + `reference/scrapydweb/` 中可对照的行为语义（`文件:行号`，仅作参考，**非**待改文件）」。reference/scrapydweb 只读、不被 import、不进构建上下文。

| dopilot 新建文件 | 要实现的行为 + 行为参考（reference/scrapydweb） |
|------|---------|
| `apps/server/dopilot_server/executors/base.py` | 定义 `BaseExecutor` 抽象基类（`run_on_node/stop/get_status`，三者均经 dopilot-agent HTTP API）与 `EXECUTOR_REGISTRY`（`task_type → Executor`），供 scheduler 回调按 `task_type` 分派（缝①）。**日志不在 Executor 接口上**——为 server 侧 pull（见 03）|
| `apps/server/dopilot_server/executors/scrapyd.py` | `ScrapydExecutor`：经 dopilot-agent 调**本机** scrapyd（server 不直连裸 scrapyd）。`run_on_node` → `POST agent /run`(type=scrapy)，agent 内部调本机 scrapyd `schedule.json`；egg 仅上传部署，经 agent 调本机 scrapyd `addversion.json`。行为参考：`schedule_task`（`execute_task.py:75-104`）+ `ScheduleTaskView`（`schedule.py:617`）的 `schedule.json` 下发语义，作对照 oracle 验证输出契约一致 |
| `apps/server/dopilot_server/executors/docker.py` | `DockerExecutor`：经 dopilot-agent 起/停常驻容器（**docker SDK 调用归 agent，server 不直连各节点 docker daemon**）；容器健康 / 退出码由 agent 采集、server 轮询 agent `/status`；返回 `(status/message/jobid)` 契约以复用结果记录（行为参考：`db_insert_task_job_result` `execute_task.py:106-122`）。日志经 server pull agent tail API（非 `docker logs --follow` 直连）|
| `apps/server/dopilot_server/executors/script.py` | `ScriptExecutor`：经 dopilot-agent 跑 `python3` 脚本（subprocess 在 agent 侧；行为参考：`sub_process.py` 的 `Popen+prctl(PR_SET_PDEATHSIG)+atexit` 子进程生命周期范式 R9），捕获退出码；stdout/stderr 经 server pull agent tail API（stream=stdout/stderr）|
| `apps/server/dopilot_server/scheduler/` | 统一调度回调：读出 task 后按 `task_type` 分派 Executor，执行编排（遍历节点 / 记结果 / 失败延迟 3 秒重试一次）。行为参考：`TaskExecutor.main`（`execute_task.py:42-61`）编排骨架、`execute_task(task_id)`（`execute_task.py:150-172`）作为 APScheduler 统一回调与天然分派单点 |
| `apps/server/dopilot_server/models/` + `apps/server/migrations/` | `Task` 模型自带 `task_type`（scrapy\|docker\|script）/`node_strategy`（all\|random）与三类对象字段（`image/command/env/volumes/script_path/interpreter/args`，或统一 `payload` JSON）；`TaskResult/TaskJobResult` 三层结果语义；**从第一天起用迁移工具**。行为参考（实现时注意）：scrapydweb `models.py:98-101` 四列 NOT NULL 仅适配 scrapyd、无 `task_type/node_strategy`，且 `models.py:14` 无 Alembic 迁移机制 |
| `apps/server/dopilot_server/api/v1/` | 即时运行 / 定时任务的 JSON 端点：按 `task_type` 调对应 Executor 并写入 `task_type` 与新字段。行为参考：scrapydweb `schedule.py:383-395`（即时运行）/ `617-642`（定时下发）把两条路径收口到 `schedule.json` 的语义 |
| `apps/server/dopilot_server/config/` + `nodes/` | 节点连通性校验支持多类型节点：纯 docker/script 部署不因「无 scrapyd」而启动失败。行为参考：scrapydweb `check_app_config.py:429` `assert any(results)` 在启动期强制 scrapyd 连通断言（dopilot 不复刻此强约束）|
| `apps/server/dopilot_server/nodes/` + `models/` | 建立 `Node` 表，实体自带稳定 `agent_id`（agent 启动传入，容器重启不变）/`type`/`endpoint`(agent 地址，非裸 scrapyd)/`token`(agent shared_token)/能力，支持 all/random 节点策略（入口对节点列表做归约）。第一版 `[nodes].agents=["agent:6800"]` 仅作初始发现地址；server 轮询 agent `GET /health` 后 upsert `nodes` 表，调度只选健康 agent（agent 主动 heartbeat 留后续）。行为参考：scrapydweb `baseview.py:99-104` 四并行 list 按 `node-1` 索引、只能表达 `ip:port + basic auth`；`get_selected_nodes` `baseview.py:257-262` 的勾选/全部选择语义 |
| `apps/server/dopilot_server/api/v1/` + `apps/web/src/{pages,router}/` | docker/script 的 JSON 端点与对应 SPA 页面 / 路由（greenfield SPA 分阶段交付，**无 Jinja 视图 / 菜单 URL 注入**）。行为参考：scrapydweb 经 `register_view`/`handle_route`（`__init__.py:147-151`）注册视图、用 node 索引前缀的路由语义 |
| `apps/server/pyproject.toml` | 声明 FastAPI / uvicorn / SQLAlchemy / 裸 Alembic / PostgreSQL driver / APScheduler 等依赖；**docker SDK 归 `apps/agent`（server 不直连 docker daemon），不加 `paramiko`/SSH 通道**。dopilot 自管依赖、自选版本。行为参考（选型时规避的已知坑）：scrapydweb `setup.py:35-56` 钉死的 Flask==2.0.0 / Werkzeug==2.0.0 / SQLAlchemy==1.3.24 / **APScheduler==3.6.0**（后者 `+pkg_resources`/`setuptools` 坑见 `CLAUDE.md`）|
| `configs/server.example.toml` + `apps/server/dopilot_server/config/` | 以 toml 声明节点 / 执行通道 / `node_strategy`（all\|random）/ 执行通道默认值（**`[nodes].agents` agent 地址列表 + agent `shared_token`**；docker daemon 配置属 agent 侧、不在 server config），由 dopilot 配置加载器（`DOPILOT_CONFIG`）读取，**不继承 scrapydweb 硬编码 settings 形态**。认证为 config-present-or-off：agent `shared_token` 非空才启用 agent 认证。行为参考：scrapydweb 在 `default_settings.py` 以硬编码 settings 承载节点配置块 |

---

## 8. 开放问题（需用户决策）

> 下表多数决策点已被 **v1 已锁定 spec** 收口（见 `00-requirements.md` 决策表），此处保留为「已锁定结论 + 仍开放的实现细节」。

| # | 决策点 | v1 已锁定结论 / 仍开放项 | 影响 |
|---|--------|------|------|
| Q1 | **Docker 常驻爬虫的执行通道** | **已锁定 = 方案 B（dopilot-agent）**：server 不直连 docker daemon，docker SDK 调用全归 agent。方案 C（server 直连 daemon over TLS）已否决 | `DockerExecutor` 经 agent `POST /run`；安全面收敛为 agent `shared_token` |
| Q2 | **一次性脚本「在哪执行」** | **已锁定 = 经 dopilot-agent 在节点本机 subprocess**（不走 SSH、不在 server 本机跑）。仍开放：脚本分发方式 / 是否隔离环境（venv / 容器）| 脚本阶段为第三类对象（在 scrapy → script → docker 顺序的中段）|
| Q3 | **常驻进程的「任务状态」语义** | server 轮询 agent `GET /status`（不依赖 agent 回调）判 running/finished/failed/canceled。仍开放：常驻容器健康判定细节（存活 + 健康检查 + 退出码组合）| 不复用 `poll.py` 的 scrapyd-jobs-HTML 采集（G6）；状态采集归 agent |
| Q4 | **是否保留 scrapyd 兼容** | **已锁定 = scrapy 经 agent 调本机 scrapyd 是一等公民链路**（scrapyd 仅监听容器内部端口、对外只暴露 agent API）。不向后兼容 scrapydweb 的 `SCRAPYD_SERVERS` 直连格式 | `ScrapydExecutor` 经 agent，非直连裸 scrapyd |
| Q5 | **数据库迁移策略** | **已锁定**：PostgreSQL 唯一库 + SQLAlchemy + **裸 Alembic**（非 Flask-Migrate）；禁止以「删库重建」作为正式迁移策略 | reference 无 Alembic（`models.py:14` TODO）；dopilot 不继承 |
| Q6 | **节点配置模型重构尺度** | **已锁定第一版 = 独立 `nodes` 表 + 稳定 `agent_id`**；`[nodes].agents` 只作为初始发现地址（指向 agent，非裸 scrapyd），server 轮询 agent `/health` 后 upsert 节点 | **注意**：node 索引/选择若沿用顺序索引会随增删漂移；dopilot 统一使用稳定 `agent_id` |
| Q7 | **实时日志（B-1）与执行器的耦合** | **已锁定 = 解耦**：日志不挂在 Executor 上，而是 server 侧 pull 链路（server 按 offset 调 agent `GET /logs/tail` → 写 `/server-data/logs` + PG 索引 → SSE）。**第一版完全不用 WebSocket**。详见 03-gap-realtime-logs | Executor 接口**不含** `stream_logs`；日志为独立子系统 |

---

## 附：本文引用的源码位置速查

| 主题 | 文件 | 关键行 |
|------|------|-------|
| 即时运行硬编码 schedule.json | `scrapydweb/views/operations/schedule.py` | 64, 383-395 |
| 定时执行 + ScheduleTaskView | `scrapydweb/views/operations/schedule.py` | 617-642 |
| TaskExecutor 骨架 / 分派单点 | `scrapydweb/views/operations/execute_task.py` | 42-61, 75-104, 106-122, 150-172 |
| Task / TaskResult / TaskJobResult 模型 | `scrapydweb/models.py` | 89-128, 131-179；nullable 列 98-101；迁移 TODO 14 |
| API_MAP 语义翻译 | `scrapydweb/views/api.py` | 8, 20 |
| make_request / get_selected_nodes | `scrapydweb/views/baseview.py` | 285, 257-262 |
| 节点 4 并行 list | `scrapydweb/views/baseview.py` | 99-104 |
| scrapyd 连通性断言 | `scrapydweb/utils/check_app_config.py` | 429 |
| 路由注册 | `scrapydweb/__init__.py` | 147-151 |
| 常驻进程范式 | `scrapydweb/utils/sub_process.py` | 36-38, 53, 85 |
| 依赖钉死版本 | `scrapydweb/setup.py` | 35-56 |
