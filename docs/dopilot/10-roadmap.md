# dopilot —— 综合改造路线图（总纲）

> 本文串联**现状**（`docs/architecture/`）+ **差距分析**（`docs/dopilot/0x-gap-*`）+ **用户决策**（`00-requirements.md`），给出分阶段 backlog 与依赖顺序。
> 细节不在此复述，请点进对应文档。

> **【scrapydweb 参考边界】** scrapydweb 仅作**功能层/行为参考**与**测试 oracle**；其代码写法、目录结构、模块划分、命名、依赖、配置形态**一律不得作为 dopilot 的设计依据**。dopilot 为 greenfield、按 `apps/`+`packages/` 自有领域 structure-first 设计（权威布局见 `05-dev-setup-and-known-issues.md` §1），**不对 scrapydweb 做改名/git mv**。详见 `00-requirements.md` 决策表。

> **类型图例（canon 下的语义）**：本表的 Epic 类型一律以 dopilot 视角标注 —— 🆕 dopilot 全新实现（绝大多数 Epic 属此类，行为可对齐 scrapydweb 参考）；♻️ 复用 dopilot 自身已建能力（非 scrapydweb）；❓ 待定义的开放问题。不存在"复用/扩展 scrapydweb 现网代码"这一类。

## 0. 总览

分期沿用 `00-requirements.md`：**阶段0 基座 → 阶段1 Scrapy 跑稳 → 阶段1.5 通信层重构（Redis Streams） → 阶段1.8 领域模型清理 → 阶段2 Python 脚本 → 阶段3 Docker 长连接**。核心原则：**一类做稳再上下一类**。

> **【通信层重构 = 阶段1.5】** 阶段0/1 以 **server 主动 HTTP pull** 交付（既定事实，见各 phase brief）。server↔agent 通信破坏性翻案为 **Redis Streams + agent 主动 heartbeat** 作为独立的**阶段1.5**承载，**不回改 phase-0/1 历史记录**。任务书见 [`phases/phase-1.5/00-brief.md`](../phases/phase-1.5/00-brief.md)，唯一设计真相见 [`refactor/00-redis-streams-agent-communication.md`](../refactor/00-redis-streams-agent-communication.md)。下文阶段0/1 的 Epic 与节点/日志主线维持 HTTP pull 既定形态；通信迁移集中见 §3.5。

```
抽象先行(贯穿)   ┌─ BaseExecutor 执行器抽象 ─┬─ LogSource 日志源抽象 ─┬─ node_strategy 节点策略 ─┐
                │   (01-gap §6 方案A)        │  (03-gap §4 Redis 推送)  │  (02-gap §3 方案A)        │
阶段0 基座 ─────┼────────────────────────────┴────────────────────────┴──────────────────────────┤
阶段1 Scrapy ───┤  dopilot-agent(内管本机 scrapyd) + ScrapydExecutor(全新实现) + server pull 日志 + 定时 + 节点策略 + 推模式 + 前端 M1~M3 │
阶段1.5 重构 ──┤  server↔agent 通信 HTTP pull → Redis Streams(命令/事件/日志) + agent 主动 heartbeat（破坏性、无双轨；见 §3.5 / phase-1.5）│
阶段1.8 清理 ──┤  BuildArtifact + ExecutionTemplate + Schedule overrides + Task/Execution public clean-cut，为 python_wheel/docker_image 预留类型与能力过滤 │
阶段2 脚本 ─────┤  PythonWheelExecutor(复用阶段1 agent) + .whl/pip --no-deps --target/PYTHONPATH/subprocess + stdout/stderr 日志源        │
阶段3 长连接 ───┤  DockerExecutor(Docker/K3s SDK) + 容器生命周期 + 容器日志源                      │
                └─────────────────────────────────────────────────────────────────────────────────┘
```

> **节点形态（阶段1 已交付；v1 最终主路径见阶段1.5）**：阶段1 的「节点」= **dopilot-agent**（内部子进程拉起本机 scrapyd，scrapyd 仅监听容器内部端口如 6801、对外不可见），**不是裸 scrapyd**。执行链路 `server → dopilot-agent → 本机 scrapyd → scrapy process`，agent tail scrapyd 的 `job.log`。dopilot-agent 阶段1 即落地。**阶段1 交付的 server↔agent 通信为 HTTP**（agent 对外 `agent:6800` 暴露 tail/status/cleanup/addversion API、server pull 日志）——既定事实；**阶段1.5 起 v1 最终主路径翻案为 Redis Streams + agent 主动 heartbeat**（阶段1.5 时仅剩 egg 部署转发与容器本地 healthcheck 走 HTTP；**阶段2.2.7 进一步删除 agent 全部入站 HTTP——egg 改由 agent 执行 Redis `run` 命令时从 server 拉取、`/health` 端点删除、`6800` 移除，agent 成为纯出站守护进程**），见 §3.5、`refactor/00-redis-streams-agent-communication.md`。
>
> **日志主线（阶段1 已交付；v1 最终主路径见阶段1.5）**：第一版**完全不使用 WebSocket**。**阶段1 交付**为 server 主动 **pull**（后台 reconcile loop 每 30s 低频 drain、开窗升到 1s、结束 final drain）——既定事实。**阶段1.5 起 v1 最终主路径翻案为 agent 经 Redis log stream 主动推增量、server 消费后落盘**。两者均：正文落 server 本地文件 `/server-data/logs`，索引/offset/状态落 **PostgreSQL**，再经 **SSE** 单向推给 Vue。详见决策 #11、`03-gap-realtime-logs.md`、§3.5。

## 1. 贯穿全程的三条抽象主线（务必"先抽象"）

> 这三条是避免"三类执行器各改一遍"的关键，应在阶段0/1 就立好接口。

| 抽象 | 作用 | 来源 | 推荐方案 |
|------|------|------|---------|
| **`BaseExecutor`** | 按 resolved `artifact_type` 多态分派下发/运行；scrapy / python_wheel / docker_image 各实现一个 | `01-gap-executors.md` §6、`phases/phase-1.8/00-brief.md` | 方案 A（抽象 + 多态）；通道**自阶段1 即走 dopilot-agent**（agent 内管本机 scrapyd），不再分「集中式过渡 + 终态分布式」两步。server↔agent 传输：**阶段1 交付 HTTP；阶段1.5 起 v1 最终为 Redis Streams**（`run_on_node`→XADD command、`get_status`→消费 `agent-events`），见下方注与 §3.5。阶段1.8 后，`task_type` 仅作为现有 agent wire 字段保留在边界，核心域使用 `artifact_type`。 |
| **`LogSource`** | 统一三类日志来源（scrapyd job.log / 脚本 stdout·stderr / 容器 logs）为同一流 | `03-gap-realtime-logs.md` §4 | **阶段1 交付 server 主动 pull agent tail API；阶段1.5 起 v1 最终为 agent 经 Redis log stream 推 + server 消费落盘（`RedisLogSource`）**；均 server→web SSE、第一版不用 WebSocket；正文落 server `/server-data/logs`，索引/offset/状态落 PostgreSQL |
| **`node_strategy`** | 节点选择三态：指定 / 全部 / 随机；触发时动态归约 | `02-gap-scheduling-nodes-push.md` §3 | 方案 A（Task 加 `node_strategy`，默认 `all`，random→`random.choice`） |

> **阶段1.5 起（通信层重构）**：上表 `BaseExecutor` 的 server↔agent 通道与 `LogSource` 的取数链路由 HTTP 翻案为 **Redis Streams**——`run_on_node` 由 POST `/run` 改为 XADD command、`get_status` 由轮询改为消费 `dopilot:server:agent-events`；`AgentTailLogSource` 换为 `RedisLogSource`（缝保留、仅换实现）；`node_strategy` 三态语义不变，叠加 heartbeat 健康过滤（来源 `nodes.last_seen_at`）。详见 §3.5、`refactor/00-redis-streams-agent-communication.md`。

## 2. 阶段 0：平台基座

| Epic | 类型 | 说明 | 文档 |
|------|------|------|------|
| 搭建 dopilot 骨架(apps/packages) | 🆕 | 新建 `apps/server`、`apps/agent`、`apps/web`、`packages/protocol` 骨架（structure-first，权威布局见 `05` §1），不对 scrapydweb 改名/git mv | `../phases/phase-0/00-brief.md`、`09-package-rename.md` |
| 单管理员 token 认证 | 🟡 | HTTP Basic → token 登录（单用户，无需 RBAC） | `06-frontend-rewrite.md` §5、`architecture/06-auth-and-utils.md` |
| 前端骨架 M0 | 🆕 | 阶段 0 起 SPA + 登录/布局/菜单 + axios + SSE 客户端；后端 FastAPI `/api/v1` 骨架。**阶段 2.1 起技术栈为 Next.js（静态导出）+ shadcn/ui + Recharts + TS**（替换原 Vite+Vue3+EP） | `06-frontend-rewrite.md` §2、`../phases/phase-2.1/00-brief.md` |
| i18n 框架 | 🆕 | SPA 默认中文（阶段 2.1 起用 **react-i18next**，原 vue-i18n）；后端 `/api/v1` 仅返回结构化 message code，由前端做文案映射 | `04-gap-i18n.md` §7、`06-frontend-rewrite.md` §7 |
| server/agent Docker 化 | 🆕 | 统一应用镜像 + PostgreSQL 服务/连接配置；server/agent/migrate 通过启动命令选择角色；reference 的 `vars.py` 启动清目录只作行为坑说明 | `08-docker-deployment.md` |
| 镜像构建发布 + CI | 🆕 | `deploy/docker/Dockerfile` + `.dockerignore`（排除 `reference/`，防御性保留）+ GitHub Actions 推送 `rabbir/dopilot:latest`（决策 7、monorepo 决策 8） | `08-docker-deployment.md` §7 |
| 测试基线 | 🆕 | dopilot 自有测试套件(`apps/server/tests`、`apps/agent/tests`、`apps/web`)；以 scrapydweb/tests 的行为预期作对照(oracle)校准移植正确性 | `07-testing-baseline.md` |
| 实时日志框架(第一步) | 🆕 | **阶段1 交付** server pull（agent tail API）+ server→web SSE + LogSource 主干，先打通 scrapyd；正文落 server `/server-data/logs`，索引/offset/状态落 PostgreSQL（无 WebSocket）。**阶段1.5 起 v1 最终为 agent 经 Redis log stream 推 + server 消费（`RedisLogSource`）**，见 §3.5 | `03-gap-realtime-logs.md` §4 |

## 3. 阶段 1：Scrapy 跑稳（节点 = dopilot-agent，内管本机 scrapyd）

> **节点形态澄清**：阶段1 唯一节点形态是 **dopilot-agent**（对外 `agent:6800` 暴露 HTTP API、内管本机 scrapyd），**不是裸 scrapyd**。现成 scrapyd 镜像仅本地 spike，非正式架构。

| Epic | 类型 | 说明 | 文档 |
|------|------|------|------|
| dopilot-agent（内管本机 scrapyd） | 🆕 | **阶段1 即落地**：agent 子进程拉起本机 scrapyd（glibc 基础镜像，init:true/tini，scrapyd 仅监听容器内部端口如 6801，对外 6800=agent API）；暴露 tail API（`GET /logs/tail?execution_id&attempt_id&stream&offset` → `{start_offset,end_offset,content,eof,finished}`）+ status API + cleanup API（`POST /executions/{attempt_id}/logs/cleanup`）+ `/addversion.json` 转发；agent 无状态（offset 权威在 server），重启从 `/agent-data/state/executions/{attempt_id}.json` 恢复 `execution_id↔scrapyd job_id↔log_path` 映射 | `08-docker-deployment.md`、`01-gap-executors.md` §6.3 |
| agent 注册 + 健康检查 | 🆕 | 第一版 `[nodes].agents=["agent:6800"]` 作为初始发现地址（指向 agent API，非裸 scrapyd）；agent 启动携带稳定 `agent_id`，server 轮询 `GET agent /health` 后 upsert `nodes` 表；调度只选健康 agent。agent 主动 heartbeat 留后续 | `02-gap-scheduling-nodes-push.md` §3 |
| server pull 日志链路（阶段1 交付；v1 最终见阶段1.5） | 🆕 | **阶段1 交付的 HTTP pull 链路（既定事实，阶段1.5 替换为 Redis log consumer）**：active execution 后台 reconcile loop 每 30s 低频 drain（`background_drain_interval_seconds=30`），打开 Web 日志窗口升到 1s（`realtime_drain_interval_seconds=1`），关窗降回，结束 final drain；单次最多 256KB（`max_tail_bytes_per_pull=262144`）；结束检测靠 server 轮询 agent status API，finished/failed/canceled→finalizing→final drain→EOF 稳定(默认 3s)或 hard timeout(30s)→complete，complete 后调 agent cleanup API；正文落 server `/server-data/logs/YYYY/MM/{execution_id}/{attempt_id}.{stream}.log`，索引落 PG 表 `execution_log_files`（PG 不存正文）；server→web 单向 SSE。**阶段1.5 起改为 server 消费 `dopilot:server:logs` 落盘 + 事件驱动结束检测**，见 §3.5 | `03-gap-realtime-logs.md` §4 |
| egg 上传下发 | 🆕 | 第一版仅支持上传已构建 egg：用户上传→server→转发 agent→agent 调本机 scrapyd `/addversion.json`；不做本地/源码/Git/CI 构建 | `01-gap-executors.md` §6.4 |
| `ScrapydExecutor` | 🆕 | 在 `apps/server/dopilot_server/executors/scrapyd.py` 全新实现 scrapyd 下发执行器（经 dopilot-agent，不直连裸 scrapyd），行为对齐 scrapydweb 参考的 scrapyd 集群 I/O 语义；server 生成 `execution_id`/`attempt_id` 下发 agent | `01-gap-executors.md` §6.4 |
| 定时任务 | 🆕 | 在 `apps/server/dopilot_server/scheduler` 新建调度，沿用 APScheduler + Task 持久化的机制语义（功能参考），按 dopilot 模型重写；实现时注意 APScheduler 版本/pkg_resources(setuptools>=81) 坑与单实例无分布式锁 | `02-gap` §2.5、`architecture/03-scheduler-engine.md` |
| 节点策略(指定/全部/随机) | 🆕 | dopilot 新立的抽象主线，落在 `apps/server/dopilot_server/nodes`：`node_strategy` 默认 `all`，触发时动态归约 | `02-gap` §3 |
| 推模式(立即下发) | 🆕 | 经 `BaseExecutor` 抽象 + `api/v1` 独立推送端点，下发到指定节点立即执行 | `02-gap` §4 |
| 前端分阶段交付 M1~M3 | 🆕 | SPA greenfield 分阶段交付：servers/jobs(M1) → 实时日志/stats(M2) → schedule/tasks(M3，含节点策略+推模式 UI) | `06-frontend-rewrite.md` §2 |

## 3.8 阶段 1.8：领域模型清理（Build Artifact / Execution Template）

> 阶段 1.8 是接入 Python `.whl` 脚本前的概念与 API clean-cut。任务书见
> [`phases/phase-1.8/00-brief.md`](../phases/phase-1.8/00-brief.md)。

| Epic | 类型 | 说明 | 文档 |
|------|------|------|------|
| BuildArtifact 实体 | 🆕 | Scrapy egg 从“爬虫 artifact”泛化为真实 DB 实体 `build_artifacts`；阶段 1.8 仅 `artifact_type=scrapy` + `package_format=egg` 可运行，预留 `python_wheel` 和 `docker_image`。 | `phases/phase-1.8/00-brief.md` |
| ExecutionTemplate | 🆕 | `TaskTemplate` 改为 `ExecutionTemplate`，必须绑定一个 BuildArtifact；Scrapy 命令只读展示，用户配置 spider/settings/args 与节点策略。 | `phases/phase-1.8/00-brief.md` |
| public Task/Execution clean-cut | 🆕 | public API/Web 中父级运行统一叫 Task，单节点原子单元叫 Execution；Redis/disk/agent seam 仍保留 `execution_id=task_id`、`attempt_id=execution_id`。 | `phases/phase-1.8/00-brief.md` |
| Schedule overrides | 🆕 | Schedule 必须引用 ExecutionTemplate，可覆盖执行参数、节点策略、节点，不可覆盖构建产物；resolved snapshot 优先级为 schedule override > template default > artifact default。 | `phases/phase-1.8/00-brief.md` |
| 能力过滤 | 🆕 | 调度目标过滤增加 artifact type → capability 映射：`scrapy -> scrapy`、`python_wheel -> python_wheel`、`docker_image -> docker_runtime`。 | `phases/phase-1.8/00-brief.md` |

## 3.5 阶段 1.5：通信层重构（server↔agent → Redis Streams）

> **破坏性重构、无双轨**：把阶段 1 已交付的 server 主动 HTTP（run/status/tail pull + 轮询 `/health`）整体翻案为 **Redis Streams + agent 主动 heartbeat**。立即启动（不等阶段 2/3）。任务书见 [`phases/phase-1.5/00-brief.md`](../phases/phase-1.5/00-brief.md)，**唯一设计真相**见 [`refactor/00-redis-streams-agent-communication.md`](../refactor/00-redis-streams-agent-communication.md)。阶段 1 的 HTTP pull 为既定事实，本阶段替换之、不回改 phase-1 记录。

| Epic | 类型 | 说明 | 文档 |
|------|------|------|------|
| Redis 通信基座 | 🆕 | redis 服务(AUTH/AOF) + 连接管理 + `packages/protocol/.../streams.py` + `apps/{server,agent}/.../redis/` 子包 + 三条 stream（commands / agent-events / logs）+ consumer group 约定 | `refactor/00` |
| command_outbox + producer + dispatcher | 🆕 | execution/attempt/outbox 同事务落库 + dispatcher XADD（at-least-once、`command_id` 对账、`attempt_id` 幂等）；手动 run try_dispatch(503/202 `dispatch_unknown`)、定时 queued+give_up(`dispatch_timeout`)、取消 CAS+`stop(intent=cancel)` | `refactor/00` |
| agent command consumer + 状态文件 CAS | 🆕 | consumer group 消费 commands、接现有 `ScrapyRunner`；`attempt_id` 执行幂等 + 两阶段状态文件 CAS（`reserved`→`started`）；启动先处理 pending entries | `refactor/00` |
| agent event/log publisher + event outbox | 🆕 | status publisher XADD agent-events（event outbox at-least-once）；log publisher tail 本机日志 XADD logs（base64 字节，offset/size_bytes/eof） | `refactor/00` |
| server event/log consumer + reconcile loop | 🆕 | event consumer 更新 attempt（去重、terminal 不回退）；log consumer 按 offset 串行落盘（gap→`partial` 黏性 + marker）；reconcile loop（heartbeat_timeout/event_stall→`lost` 软 terminal、`stalled` 告警） | `refactor/00`、`03-gap` §4 |
| heartbeat API + node selection 改 heartbeat | 🆕 | agent 主动 POST `/api/v1/agents/{agent_id}/heartbeat`；server upsert `nodes.last_seen_at`，`healthy=now-last_seen_at<=heartbeat_timeout_seconds`；agent `/health` 降为容器本地 healthcheck；阶段 2.2.3 收敛为单一 `agent_token` 机器认证 | `02-gap` §3、`refactor/00` |
| 数据模型迁移（Alembic 0003+） | 🆕 | `command_outbox` 表、`execution_log_files.log_integrity`+gap 字段、`execution_attempts.reconciled_from`/`lost_reason`、event dedupe/audit 表、`nodes.last_seen_at` 语义翻转 | `refactor/00` §代码改动范围 |
| 删除旧 HTTP 主路径 + 测试 | 🆕 | 删/隔离 server→agent run/status/tail 与 `AgentTailLogSource` 主路径（标 legacy）；新增 ack/pending/幂等/offset gap/heartbeat/取消/lost reason 测试矩阵 | `refactor/00` §测试要求、`07-testing-baseline.md` |

> **顺序约束**：log publisher/consumer 必须先于 executor 切 command stream 上线（否则经 Redis 执行的 attempt 无日志承载）。完整 15 步顺序见 `phases/phase-1.5/00-brief.md` §4。

## 4. 阶段 2：Python 脚本（复用阶段1 已落地的 dopilot-agent）

> dopilot-agent 已在**阶段1 落地**（内管本机 scrapyd + server pull 日志；
> 通信层于**阶段1.5**迁至 Redis Streams，见 §3.5），阶段 1.8 已把
> BuildArtifact / ExecutionTemplate / Task / Execution 模型清理为跨类型口径。
> 阶段2 不再新建 agent，仅在既有 agent 上加 `python_wheel` 能力。

| Epic | 类型 | 说明 | 文档 |
|------|------|------|------|
| `PythonWheelExecutor` / Script runner | 🆕 | Python 脚本以 `.whl` 构建产物接入。agent 下载 wheel、校验 sha256，按 sha256 用 `pip install --no-deps --target <cache>/python_wheel/<sha256>/site` 安装一次（无 venv、无依赖解析、无 console-script），把该 site 目录注入 `PYTHONPATH` 后以 `/bin/sh -c "<command>"` 启动（如 `python -m main`）。详见 `phases/phase-2b/00-brief.md`。 | `01-gap-executors.md` §6 |
| 脚本状态 | 🆕 | agent 以子进程生命周期为权威：准备环境→启动成功发 running→退出码 0 为 succeeded/finished，非 0 为 failed，取消时 SIGTERM→grace→SIGKILL 后 canceled。第一版不要求脚本 SDK/心跳协议。 | `phases/phase-1.8/00-brief.md` |
| 脚本日志源 | 🆕 | LogSource 接脚本 `stream=stdout/stderr`；agent 强制 `PYTHONUNBUFFERED=1` / `python -u`，异步读取 stdout/stderr 并经 Redis log stream 推送，server 消费落盘 + SSE。 | `03-gap-realtime-logs.md` §2 |
| 定时/节点/推模式 | ♻️ | 复用 dopilot 阶段1 已建能力（dopilot 自有，非 scrapydweb） | `02-gap` |

## 5. 阶段 3：Docker 长连接爬虫（最后）

| Epic | 类型 | 说明 | 文档 |
|------|------|------|------|
| `DockerExecutor` | 🆕 | Docker / K3s API SDK 启停容器 | `01-gap-executors.md` §6 |
| 容器生命周期 | 🆕 | 常驻语义，**注意与 scrapyd finished 状态机冲突** | `01-gap` §1.6、§2 |
| 容器日志源 | 🆕 | LogSource 接容器 logs | `03-gap-realtime-logs.md` §2 |
| "定时"语义定义 | ❓ | 定时启新容器 vs 对常驻容器发指令——先定义再实现 | `02-gap` §2.3 开放问题 |

## 6. 关键依赖顺序

```
测试基线(07) ──► dopilot 自有测试，随每个域同步落地
dopilot 骨架搭建(apps/packages) ─┐
token认证 ──────────────────────┼─► 前端骨架 M0 ──► 前端分阶段交付 M1~M3
Docker化(08, server+agent) ──────┘
dopilot-agent(阶段1,内管本机 scrapyd) ──► [阶段1]agent 注册+轮询/health ──► server→agent→本机 scrapyd→scrapy   (健康→heartbeat 见阶段1.5)
BuildArtifact/ExecutionTemplate(阶段1.8) ──► scrapy egg ──► python_wheel(.whl) ──► docker_image
BaseExecutor 抽象 ──► ScrapydExecutor(阶段1,经 agent) ──► PythonWheelExecutor(阶段2,复用 agent) ──► DockerExecutor(阶段3)
LogSource 抽象 ──► [阶段1]server pull(agent tail API) / [阶段1.5]agent XADD log stream + server consumer ──► server→web SSE ──► 正文落 /server-data/logs + 索引/offset/状态落 PostgreSQL
   stream: scrapyd job.log(log) ──► 脚本 stdout/stderr ──► 容器 logs    (第一版不使用 WebSocket;阶段1=server pull,阶段1.5 起=agent 主动推)
node_strategy ──► (阶段1 起对所有 Executor 生效;健康过滤来源阶段1.5 改 last_seen_at)

阶段1.5 通信重构(破坏性) ──► Redis 基座(streams.py + redis 子包 + redis 服务 AUTH/AOF)
   ──► command_outbox/dispatcher + agent command consumer ──► event/log publisher+consumer(log 先于 executor 切换)
   ──► heartbeat API/worker + node selection(last_seen_at) ──► 删旧 server→agent HTTP run/status/tail 主路径
   (HTTP pull → Redis Streams + agent 主动 heartbeat;见 §3.5、phase-1.5/00-brief)
```

## 7. 跨文档关键决策状态

> 完整清单见各 gap 文档末节。以下为影响架构的关键项：

| # | 问题 | 来源 | 现状 |
|---|---------|------|------|
| 1 | worker agent 与 server 的通信协议 | `01-gap` §8、`refactor/00` | **阶段1 交付**：server 主动 HTTP pull（agent 暴露 tail/status/cleanup API，offset 权威在 server PG），server 轮询 `/health`。**阶段1.5 破坏性翻案为 Redis Streams**：server XADD command（事务性 outbox + dispatcher，at-least-once，`attempt_id` 幂等）+ agent consumer group 主动消费 + 主动 XADD 状态/日志 + 主动 POST heartbeat（`last_seen_at` 判健康），删 HTTP run/status/tail 主路径。详见 `refactor/00-redis-streams-agent-communication.md`、`phases/phase-1.5/00-brief.md` |
| 2 | Docker 长连接的"定时"语义（启新容器 vs 发指令） | `02-gap` §2.3 | 待定（阶段3 前定） |
| 3 | JS 文案 i18n 策略 | `04-gap` §4 | 已定：SPA 用 react-i18next（阶段 2.1 起，原 vue-i18n），后端返回 message_key/code |
| 4 | Web 部署 | `06-frontend` §9 | 已定：不内置 nginx；反代用户可选；前端为 Next.js 静态导出产物，由 dopilot-server 托管（无独立 Web 容器/Node 生产运行时） |
| 5 | token 形式 | `06-frontend` §9 | 已定：服务端签发 opaque token，无 refresh token |
| 6 | 容器持久化卷边界（哪些目录随卷、哪些可清） | `08-docker` | 已定：PostgreSQL 数据卷 + `/server-data/logs` + `/agent-data` 持久化；构建缓存/临时目录可清 |

## 8. 文档矩阵（按阶段查阅）

| 阶段 | 必读现状 | 必读改造 |
|------|---------|---------|
| 阶段0 | `architecture/00,01,06` | `phases/phase-0/00-brief`, `dopilot/05,06,07,08,09` |
| 阶段1 | `architecture/02,03,04,05` | `dopilot/01,02,03,06` |
| 阶段1.5 | —— | `phases/phase-1.5/00-brief`, **`refactor/00-redis-streams-agent-communication.md`**, `dopilot/01,02,03,08`（已按新模型）, `07`（Redis 测试矩阵） |
| 阶段2 | `architecture/01,02` | `dopilot/01,08` |
| 阶段3 | `architecture/05` | `dopilot/01,02,03` |
