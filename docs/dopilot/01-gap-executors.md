# 改造分析：多类型执行器抽象（Scrapy / Docker 长连接 / Python 脚本）

> 适用对象：后续承接 dopilot 改造的工程师。
> 阅读约定：本文严格区分「**现状事实**」（已 Read/Grep 核实源码，标注 `文件:行号`）与「**改造建议 / 开放问题**」（设计推演，需团队决策）。
> 代码基线：当前仓库 `master`（基于 scrapydweb 改造）。

---

## 0. 一句话结论

scrapydweb 目前**没有任何「执行器（executor）抽象层」**——所有「运行 / 下发」路径都硬编码为对 scrapyd 的 `*.json` HTTP API 调用。要支持「Docker 常驻爬虫」与「一次性 Python3 脚本」，**必须从零设计一个 Executor 抽象层**，并旁路 / 扩展所有现有的 scrapyd-only 链路。

推荐主干：**方案 A（`BaseExecutor` 抽象 + 按 `task_type` 多态分派）**，执行通道按节点形态选配（集中式先用方案 C，分布式终态走方案 B）。

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
| 下发协议 | scrapyd `schedule.json` | `docker run -d` / SDK / agent | `subprocess` / SSH / agent |
| 启动参数 | `project/version/spider/settings/args` | `image/command/env/volumes/ports` | `script_path/interpreter/args/env` |
| 状态语义 | pending / running / finished | **running / stopped / unhealthy**（无 finished） | running / exited(退出码) |
| 状态采集 | scrapyd `/jobs` HTML + logparser | 容器存活 + 健康检查 + 退出码 | 进程存活 + 退出码 |
| 实时日志 | scrapy 日志文件 | `docker logs --follow`（天然支持） | 子进程 stdout/stderr 捕获 |
| 停止语义 | `cancel.json`（信号） | `docker stop` | 进程 kill / 信号 |
| 与现有契约 | 完全契合 | **finished 状态机冲突** | scrapyd 无法跑任意脚本 |

关键冲突点：**Docker 常驻进程的「永不 finished」语义**会打乱 scrapyd 风格的 jobs 页 / 告警逻辑（`poll.py`）；而 scrapyd 只接受 egg+spider，**无法运行裸脚本**。这两点决定了不能用 scrapyd 硬扛（见方案 D 反模式）。

---

## 3. 可复用项（现成且经过验证的资产）

| # | 组件 | 文件:行号 | 复用方式 |
|---|------|----------|---------|
| R1 | `TaskExecutor.main()` 编排骨架 | `execute_task.py:42-61` | 「遍历 `selected_nodes` → 逐节点执行 → 成功/失败计数 → 写 `TaskResult/TaskJobResult` → 失败节点延迟 3 秒重试一次」是天然的执行器骨架。新执行器应**只替换 `schedule_task()` 这一个「实际下发」方法**，建议抽象成 `run_on_node(node)` 接口 |
| R2 | 结果记录契约 | `execute_task.py:63,106,125` | `get_task_result_id()` / `db_insert_task_job_result()` / `db_update_task_result()` 与执行类型无关，三类对象通用 |
| R3 | `TaskResult` / `TaskJobResult` 三层结果模型 | `models.py:131-179` | `TaskResult`（汇总 fail/pass）+ `TaskJobResult`（每节点明细 `node/server/status_code/status/result`）与执行类型解耦，**直接复用** |
| R4 | Task 的全部触发字段 | `models.py:105-121` | `year..second / start_date / end_date / timezone / jitter / misfire_grace_time / coalesce / max_instances`（cron/interval/date）三类对象共用，只需新增 `task_type` 列并放宽 NOT NULL |
| R5 | APScheduler 引擎 + 统一回调 | `execute_task.py:150-172`，`utils/scheduler.py` | `execute_task(task_id)` 是 `add_job` 的统一回调，**是按 `task_type` 分派执行器的最佳单点**：第 152 行读出 task 后选 `ScrapydExecutor/DockerExecutor/ScriptExecutor` |
| R6 | 路由注册机制 | `__init__.py:148` `register_view()` | 统一给视图加 `/<int:node>/` 前缀（第 151 行）。新增 docker/script 页面与下发端点按同样模式挂入，复用 node 索引语义与 1-based 约定 |
| R7 | 节点选择基座 | `baseview.py:257-262` `get_selected_nodes()` | 解析勾选节点列表，三类对象的「指定/全部」共用；「随机一个」策略可在执行器入口对返回列表做 `random.choice` 归约 |
| R8 | 统一 HTTP 封装 | `baseview.py:285` `make_request()` | 返回 `(status_code, dict)` 契约稳定。若 Docker/脚本走「节点 HTTP agent」方案，可直接复用它发请求；返回 dict 只要补齐 `status/message/jobid` 即可无缝接入 `db_insert_task_job_result`（`execute_task.py:106-122`） |
| R9 | 常驻进程范式 | `utils/sub_process.py`（`init_poll:85` / `init_logparser:53`） | `Popen` 拉起子进程 + `prctl(PR_SET_PDEATHSIG)`（第 36-38 行）/ `atexit`（第 57/89 行）绑定父进程生命周期。「本机直接跑脚本 / 起容器客户端进程」可复用此范式管理子进程生命周期 |
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
   多态分派       │ (迁移现状)   │ │ (待建/新依赖)│ │ (待建/复用R9)│
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
| **A**：`BaseExecutor` 抽象 + 三实现类，按 `task_type` 分派 | 新建 `executors/` 包，定义抽象基类 `run_on_node/stop/get_status/stream_logs`；现有 scrapyd 逻辑下沉为 `ScrapydExecutor`；`execute_task` 按 `task_type` 选实现 | 侵入最小、最贴现有架构；直接复用 `main` 的结果记录/重试/节点遍历；统一入口；加新类型只需加子类 | 需重构 `execute_task.py`；需改 Task 模型 + 迁移；**只解决「如何多态分派」，不解决「在哪执行」** | 中（抽象层 + ScrapydExecutor 迁移约 1-2 天；Docker/Script 具体实现另算） | **架构主干（不可绕过）** |
| **B**：节点侧自研 worker agent（每节点跑 HTTP agent） | agent 暴露统一 REST：`POST /run`(type=scrapy\|docker\|script)、`/stop`、`GET /status`、`GET /logs/stream`(SSE)；内部对接 scrapyd/docker SDK/subprocess | 真正分布式 push（替代伪分布式）；三类对象节点侧统一收口；主程序极简；实时日志由 agent SSE/WS 推流；docker/脚本本机执行天然解决 | 需新增 + 部署 + 运维 agent（每节点装）；版本兼容 / 安全（token/TLS）面；与现有 scrapyd 并存期双轨 | 高（1-2 周起） | **分布式终态** |
| **C**：主程序直连 docker SDK + 本机 subprocess（无 agent） | 主程序用 docker SDK 连各节点 docker daemon(over TLS) 起停常驻容器；脚本用 subprocess（复用 `sub_process.py`）或 SSH(paramiko) 跑远程 python3 | 无需开发 agent，落地快；docker SDK 成熟，`run/logs --follow/stop/健康检查` 开箱即用；适合节点少、运维集中 | 暴露 docker daemon over TLS 有安全风险；脚本走 SSH 需各节点免密 + python 环境 + 分发；docker logs 长连与 Flask 同步 WSGI 耦合；与「随机/全部节点」叠加时连接管理复杂 | 中-高（docker SDK 约 2-3 天；SSH 通道 + 依赖 + 安全另算） | **过渡 / 集中式小规模** |
| **D**：复用 scrapyd 跑脚本 / 包装常驻进程 | 脚本伪装成最简 spider 经 egg 部署；常驻容器用 supervisor spider 拉起。完全复用现有 deploy/schedule/jobs/log 链路 | 几乎不改主程序，复用全部 scrapyd 生态 | **反模式**：脚本伪装成 spider；常驻进程与 finished 状态机冲突（jobs 页/告警全乱）；egg 打包裸脚本极笨重；无法满足 Docker 常驻语义；本质未解决目标 A | 低（但技术债极高） | **不推荐** |

### 5.2 方案对目标 B（平台功能）的覆盖

| 目标功能 | 方案 A | 方案 B | 方案 C | 方案 D |
|---------|:-----:|:-----:|:-----:|:-----:|
| B-1 实时日志流 | 需配 `stream_logs` 实现 | 原生 SSE/WS 最佳 | docker logs 可，脚本需自建 | 仅 scrapy 日志 |
| B-2 定时调度 | 复用 APScheduler | 复用 | 复用 | 复用 |
| B-3 节点策略(全部/随机) | 入口归约 R7 | agent 寻址清晰 | 连接管理复杂 | 复用 |
| B-4 push 模式下发 | 取决于通道 | **原生 push** | 主程序直推 | 伪分布式 |
| B-5 i18n（中文） | 与执行器解耦，独立任务 | 同左 | 同左 | 同左 |

---

## 6. 推荐架构

### 6.1 推荐组合

> **方案 A 为架构主干**（不可绕过的多态分派层），执行通道按节点形态选配：
> - 集中式 / 小规模：先用 **方案 C** 快速跑通（docker SDK + subprocess）；
> - 分布式 / 多节点终态：叠加 **方案 B** 的 worker agent（同时解决 push + SSE 日志 + 常驻健康采集）。

理由：
1. 无论通道是 agent 还是 docker SDK，都**需要一个 `task_type` 多态分派层**，且能最大化复用 `TaskExecutor.main` 的现成资产（R1-R3）。
2. 先做 **方案 A + ScrapydExecutor 迁移**（行为不变、零风险回归），再分别填充 Docker/Script。
3. docker `logs --follow` 天然满足实时日志（B-1）；脚本初期用本机 subprocess（复用 R9），后续统一收敛到 agent。
4. **务必先加 `Task.task_type` 列并放宽 `project/version/spider/jobid` 的 nullable**，否则三类对象无法共表。

### 6.2 执行器抽象（方案 A 接口设想）

```text
scrapydweb/executors/
├── __init__.py        # BaseExecutor 抽象基类 + EXECUTOR_REGISTRY
├── scrapyd.py         # ScrapydExecutor（迁移自 execute_task.py，行为不变）
├── docker.py          # DockerExecutor（docker SDK / agent）
└── script.py          # ScriptExecutor（subprocess / agent / SSH）

class BaseExecutor:
    task_type = None
    def run_on_node(self, node) -> dict: ...   # 返回 {status, message|jobid, status_code, url}
    def stop(self, node, job): ...
    def get_status(self, node, job): ...
    def stream_logs(self, node, job): ...       # 预留：SSE/WS 实时日志

EXECUTOR_REGISTRY = {
    'scrapy': ScrapydExecutor,
    'docker': DockerExecutor,
    'script': ScriptExecutor,
}
```

分派单点（在 `execute_task.py:152` 读出 task 后）：

```text
task = Task.query.get(task_id)            # execute_task.py:152（现状）
executor_cls = EXECUTOR_REGISTRY[task.task_type]   # 新增
executor = executor_cls(...)
executor.main()                            # 复用 main() 骨架，仅 run_on_node 不同
```

> 关键：`TaskExecutor.main()`（`execute_task.py:42-61`）的循环里把 `self.schedule_task(node)` 改为 `self.run_on_node(node)`，`run_on_node` 由子类实现。`ScrapydExecutor.run_on_node` 就是把现 `schedule_task`（`execute_task.py:75-104`）原样搬过来。

### 6.3 终态分布式架构（方案 B worker agent 设想）

```text
        ┌─────────────────────── dopilot 主程序 (Flask) ───────────────────────┐
        │  APScheduler ── execute_task(task_id) ── EXECUTOR_REGISTRY[task_type] │
        │        │                                          │                   │
        │   ScrapydExecutor                    Docker/ScriptExecutor            │
        │        │ (兼容期)                            │ make_request(R8)        │
        └────────┼────────────────────────────────────┼─────────────────────────┘
                 │ schedule.json                       │ POST /run  (push)
                 ▼                                      ▼  GET /logs/stream (SSE)
          ┌─────────────┐                       ┌──────────────────────┐
          │  scrapyd     │                      │  dopilot worker agent │  ← 每节点一个
          │  (node-N)    │                      │  /run /stop /status   │
          └─────────────┘                       │  /logs/stream(SSE)    │
                                                │   ├─ scrapy → scrapyd │
                                                │   ├─ docker → SDK     │
                                                │   └─ script → subproc │
                                                └──────────────────────┘
```

### 6.4 推荐落地顺序

```text
① 抽象接口 (executors/__init__.py)
        ↓
② ScrapydExecutor 迁移 (保证现网零回归) ← 行为不变，可立即合入
        ↓
③ Task 模型加 task_type/node_strategy + 放宽 nullable + 迁移
        ↓
④ DockerExecutor (方案 C：docker SDK，先跑通常驻容器 + logs --follow)
        ↓
⑤ ScriptExecutor (方案 C：subprocess，复用 sub_process.py 范式)
        ↓
⑥ 节点配置模型：4 并行 list → list[dict] / Node DB 表（承载 type/endpoint/token）
        ↓
⑦ 视图与表单扩展 (DockerScheduleView / ScriptRunView) + i18n 接入
        ↓
⑧ (终态) 收敛到 worker agent (方案 B)：push + SSE 日志 + 常驻健康采集
```

---

## 7. 需改动文件（touch points）

> 标注 `（新建）` 为新增文件；其余为现有文件改动。

| 文件 | 改动要点 |
|------|---------|
| `scrapydweb/executors/__init__.py`（新建） | 定义 `BaseExecutor` 抽象基类（`run_on_node/stop/get_status/stream_logs`）与 `EXECUTOR_REGISTRY`（`task_type → Executor`），供 `execute_task` 分派 |
| `scrapydweb/executors/scrapyd.py`（新建） | 把 `TaskExecutor.schedule_task`（`execute_task.py:75-104`）与 `ScheduleTaskView`（`schedule.py:617`）的 `schedule.json` 逻辑下沉为 `ScrapydExecutor.run_on_node`，**行为保持不变** |
| `scrapydweb/executors/docker.py`（新建） | `DockerExecutor`：docker SDK 起/停常驻容器、`docker logs --follow` 流式日志、容器健康 / 退出码采集；返回 `(status/message/jobid)` 契约以复用 `db_insert_task_job_result` |
| `scrapydweb/executors/script.py`（新建） | `ScriptExecutor`：subprocess（复用 `sub_process.py` 范式 R9）或经 agent/SSH 跑 `python3` 脚本，捕获退出码与 stdout |
| `scrapydweb/views/operations/execute_task.py` | 重构 `TaskExecutor`：`main()`(第 42-61 行) 内 `schedule_task → run_on_node` 委托给按 `task.task_type` 选出的 Executor；`execute_task(task_id)`(第 150-172 行) 第 152 行读 task 后按 `task_type` 实例化。**保留** `main/get_task_result_id/db_insert_task_job_result/db_update_task_result` 骨架 |
| `scrapydweb/models.py` | `Task` 加 `task_type`（scrapy\|docker\|script，默认 scrapy）与 `node_strategy`（all\|random）列；**放宽** `project/version/spider/jobid`（第 98-101 行）的 nullable；新增 docker/script 专属字段（`image/command/env/volumes/script_path/interpreter/args`，或统一存 `payload` JSON）；`TaskJobResult` 复用。**需配套迁移（当前无 Alembic）** |
| `scrapydweb/views/operations/schedule.py` | `ScheduleRunView.handle_action()`(第 383-395 行) 即时运行分支按 `task_type` 走对应 Executor，不再硬编码 `make_request(schedule.json)`；`db_process_task()`(第 416 行) / `db_insert_update_task()`(第 399 行) / `add_update_task()`(第 447 行) 写入 `task_type` 与新字段；`ScheduleTaskView`(第 617-642 行) 改为 scrapyd-only 或泛化 |
| `scrapydweb/utils/check_app_config.py` | `check_scrapyd_servers` / `check_scrapyd_connectivity`(至第 429 行) 扩展支持非 scrapyd 节点；放宽 `assert any(results)`（第 429 行，无 scrapyd 节点时跳过）；扩展节点配置解析携带 `type/能力/凭证` |
| `scrapydweb/views/baseview.py` | 节点配置从 4 并行 list（第 99-104 行 `node-1` 索引）重构为 `list[dict]` 或 DB 表以承载 `type/docker_endpoint/agent_token`；`get_selected_nodes`(第 257-262 行) 之上加节点策略归约（`random.choice` 实现「随机一个」） |
| `scrapydweb/__init__.py` | `handle_route()` / `register_view()`(第 147-148 行起) 注册 Docker/脚本新页面与下发端点（如 `DockerScheduleView/ScriptRunView`），并在 `update_g` 挂菜单 URL |
| `scrapydweb/setup.py` | `install_requires`(第 35 行起) 新增 docker SDK；若用 SSH 通道加 `paramiko`。**注意兼容钉死的 Flask==2.0.0 / Werkzeug==2.0.0 / SQLAlchemy==1.3.24 / APScheduler==3.6.0** |
| `scrapydweb/default_settings.py` | 新增 Docker/脚本节点配置块（如 `DOCKER_NODES/SCRIPT_NODES` 或统一 `WORKER_NODES`）、`DEFAULT_NODE_STRATEGY`（all\|random）、执行通道默认值（agent 地址/token、docker daemon TLS 等） |

---

## 8. 开放问题（需用户决策）

> 以下为**设计决策点**，直接影响实现复杂度与安全模型，须在动工前与团队确认。

| # | 决策点 | 选项 | 影响 |
|---|--------|------|------|
| Q1 | **Docker 常驻爬虫的执行通道** | (B) 节点 worker agent / (C) 主程序直连 docker daemon over TLS / docker SDK | 决定 `DockerExecutor` 实现复杂度与安全模型。**dopilot 的节点数量级是多少？**（影响 agent 是否值得开发） |
| Q2 | **一次性脚本「在哪执行」** | 主程序所在机 subprocess / 分发到远程 worker | 脚本如何分发（git 拉取 / 上传 zip / 预装节点）？是否需隔离环境（venv / 容器）？ |
| Q3 | **常驻进程的「任务状态」语义** | 仅 running/stopped/unhealthy / 加心跳健康检查端点 / 只看容器存活 + 退出码 | 直接影响是否要替换 `poll.py` 的 scrapyd-jobs-HTML 采集机制（G6） |
| Q4 | **是否保留 scrapyd 兼容** | 长期一等公民 / 仅过渡兼容层 | 决定 `ScrapydExecutor` 定位，也影响节点配置模型是否需向后兼容现有 `SCRAPYD_SERVERS` 格式 |
| Q5 | **数据库迁移策略** | 引入 Flask-Migrate 正式迁移 / 接受「删库重建」（私有平台早期可接受） | 当前无 Alembic（`models.py:14` TODO）；给 Task 加列时的落地方式 |
| Q6 | **节点配置模型重构尺度** | 4 并行 list → `list[dict]`（改动集中在 `baseview.__init__` + `check_scrapyd_servers`） / 独立 Node DB 表（改动大但支持运行时增删节点） | **注意**：现有 node 是按排序后顺序的 1-based 索引，已存 `Task.selected_nodes`（`models.py:103`）会随节点增删**漂移** |
| Q7 | **实时日志流（B-1）与执行器的耦合** | 本轮一并设计 / 先做执行落地，日志流作为独立子任务 | 两者共用 `Executor.stream_logs` 接口，**建议接口先预留**（`docker logs --follow` / agent SSE） |

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
