# dopilot —— 综合改造路线图（总纲）

> 本文串联**现状**（`docs/architecture/`）+ **差距分析**（`docs/dopilot/0x-gap-*`）+ **用户决策**（`00-requirements.md`），给出分阶段 backlog 与依赖顺序。
> 细节不在此复述，请点进对应文档。

> **【scrapydweb 参考边界】** scrapydweb 仅作**功能层/行为参考**与**测试 oracle**；其代码写法、目录结构、模块划分、命名、依赖、配置形态**一律不得作为 dopilot 的设计依据**。dopilot 为 greenfield、按 `apps/`+`packages/` 自有领域 structure-first 设计（权威布局见 `05-dev-setup-and-known-issues.md` §1），**不对 scrapydweb 做改名/git mv**。详见 `00-requirements.md` 决策表。

> **类型图例（canon 下的语义）**：本表的 Epic 类型一律以 dopilot 视角标注 —— 🆕 dopilot 全新实现（绝大多数 Epic 属此类，行为可对齐 scrapydweb 参考）；♻️ 复用 dopilot 自身已建能力（非 scrapydweb）；❓ 待定义的开放问题。不存在"复用/扩展 scrapydweb 现网代码"这一类。

## 0. 总览

分期沿用 `00-requirements.md`：**阶段0 基座 → 阶段1 Scrapy 跑稳 → 阶段2 Python 脚本 → 阶段3 Docker 长连接**。核心原则：**一类做稳再上下一类**。

```
抽象先行(贯穿)   ┌─ BaseExecutor 执行器抽象 ─┬─ LogSource 日志源抽象 ─┬─ node_strategy 节点策略 ─┐
                │   (01-gap §6 方案A)        │  (03-gap §4 server pull) │  (02-gap §3 方案A)        │
阶段0 基座 ─────┼────────────────────────────┴────────────────────────┴──────────────────────────┤
阶段1 Scrapy ───┤  dopilot-agent(内管本机 scrapyd) + ScrapydExecutor(全新实现) + server pull 日志 + 定时 + 节点策略 + 推模式 + 前端 M1~M3 │
阶段2 脚本 ─────┤  ScriptExecutor(复用阶段1 agent) + 脚本 stdout/stderr 日志源                      │
阶段3 长连接 ───┤  DockerExecutor(Docker/K3s SDK) + 容器生命周期 + 容器日志源                      │
                └─────────────────────────────────────────────────────────────────────────────────┘
```

> **节点形态（v1 已锁定）**：阶段1 的「节点」= **dopilot-agent**（agent 对外 `agent:6800` 暴露 HTTP API：tail / status / cleanup / addversion 转发；内部子进程拉起本机 scrapyd，scrapyd 仅监听容器内部端口如 6801、对外不可见），**不是裸 scrapyd**。执行链路：`server → dopilot-agent → 本机 scrapyd → scrapy process`，agent tail scrapyd 的 `job.log`。dopilot-agent 阶段1 即落地，承载「本机 scrapyd 包装 + server pull 日志」两职责。
>
> **日志主线（v1 已锁定）**：第一版**完全不使用 WebSocket、agent 不主动推**。server 主动 **pull**：后台 reconcile loop 每 30s 低频 drain active execution；打开 Web 日志窗口该 execution 升到 1s；关窗降回低频；结束做 final drain；正文落 server 本地文件 `/server-data/logs`，索引/offset/状态落 **PostgreSQL**；再经 **SSE** 单向推给 Vue。详见决策 #11 与 `03-gap-realtime-logs.md`。

## 1. 贯穿全程的三条抽象主线（务必"先抽象"）

> 这三条是避免"三类执行器各改一遍"的关键，应在阶段0/1 就立好接口。

| 抽象 | 作用 | 来源 | 推荐方案 |
|------|------|------|---------|
| **`BaseExecutor`** | 按 `task_type` 多态分派下发/运行；scrapyd / 脚本 / docker 各实现一个 | `01-gap-executors.md` §6 | 方案 A（抽象 + 多态）；通道**自阶段1 即走 dopilot-agent**（agent 内管本机 scrapyd，server↔agent 走 HTTP，无消息队列/回调），不再分「集中式过渡 + 终态分布式」两步 |
| **`LogSource`** | 统一三类日志来源（scrapyd job.log / 脚本 stdout·stderr / 容器 logs）为同一流 | `03-gap-realtime-logs.md` §4 | **server 主动 pull agent tail API + server→web SSE**（第一版不用 WebSocket、agent 不主动推）；正文落 server `/server-data/logs`，索引/offset/状态落 PostgreSQL |
| **`node_strategy`** | 节点选择三态：指定 / 全部 / 随机；触发时动态归约 | `02-gap-scheduling-nodes-push.md` §3 | 方案 A（Task 加 `node_strategy`，默认 `all`，random→`random.choice`） |

## 2. 阶段 0：平台基座

| Epic | 类型 | 说明 | 文档 |
|------|------|------|------|
| 搭建 dopilot 骨架(apps/packages) | 🆕 | 新建 `apps/server`、`apps/agent`、`apps/web`、`packages/protocol` 骨架（structure-first，权威布局见 `05` §1），不对 scrapydweb 改名/git mv | `../phases/phase-0/00-brief.md`、`09-package-rename.md` |
| 单管理员 token 认证 | 🟡 | HTTP Basic → token 登录（单用户，无需 RBAC） | `06-frontend-rewrite.md` §5、`architecture/06-auth-and-utils.md` |
| 前端骨架 M0 | 🆕 | Vite+Vue3+EP+TS + 登录/布局/菜单 + axios + SSE 客户端；后端 FastAPI `/api/v1` 骨架 | `06-frontend-rewrite.md` §2 |
| i18n 框架 | 🆕 | SPA 用 vue-i18n，默认中文；后端 `/api/v1` 仅返回结构化 message code，由前端做文案映射 | `04-gap-i18n.md` §7、`06-frontend-rewrite.md` §7 |
| server/agent Docker 化 | 🆕 | 统一应用镜像 + PostgreSQL 服务/连接配置；server/agent/migrate 通过启动命令选择角色；reference 的 `vars.py` 启动清目录只作行为坑说明 | `08-docker-deployment.md` |
| 镜像构建发布 + CI | 🆕 | `deploy/docker/Dockerfile` + `.dockerignore`（排除 `reference/`）+ GitHub Actions 推送 `rabbir/dopilot:latest`（决策 7、monorepo 决策 8） | `08-docker-deployment.md` §7 |
| 测试基线 | 🆕 | dopilot 自有测试套件(`apps/server/tests`、`apps/agent/tests`、`apps/web`)；以 scrapydweb/tests 的行为预期作对照(oracle)校准移植正确性 | `07-testing-baseline.md` |
| 实时日志框架(第一步) | 🆕 | server pull（agent tail API）+ server→web SSE + LogSource 主干，先打通 scrapyd；正文落 server `/server-data/logs`，索引/offset/状态落 PostgreSQL（无 WebSocket、agent 不主动推） | `03-gap-realtime-logs.md` §4 |

## 3. 阶段 1：Scrapy 跑稳（节点 = dopilot-agent，内管本机 scrapyd）

> **节点形态澄清**：阶段1 唯一节点形态是 **dopilot-agent**（对外 `agent:6800` 暴露 HTTP API、内管本机 scrapyd），**不是裸 scrapyd**。现成 scrapyd 镜像仅本地 spike，非正式架构。

| Epic | 类型 | 说明 | 文档 |
|------|------|------|------|
| dopilot-agent（内管本机 scrapyd） | 🆕 | **阶段1 即落地**：agent 子进程拉起本机 scrapyd（glibc 基础镜像，init:true/tini，scrapyd 仅监听容器内部端口如 6801，对外 6800=agent API）；暴露 tail API（`GET /logs/tail?execution_id&attempt_id&stream&offset` → `{start_offset,end_offset,content,eof,finished}`）+ status API + cleanup API（`POST /executions/{attempt_id}/logs/cleanup`）+ `/addversion.json` 转发；agent 无状态（offset 权威在 server），重启从 `/agent-data/state/executions/{attempt_id}.json` 恢复 `execution_id↔scrapyd job_id↔log_path` 映射 | `08-docker-deployment.md`、`01-gap-executors.md` §6.3 |
| agent 注册 + 健康检查 | 🆕 | 第一版 `[nodes].agents=["agent:6800"]` 作为初始发现地址（指向 agent API，非裸 scrapyd）；agent 启动携带稳定 `agent_id`，server 轮询 `GET agent /health` 后 upsert `nodes` 表；调度只选健康 agent。agent 主动 heartbeat 留后续 | `02-gap-scheduling-nodes-push.md` §3 |
| server pull 日志链路 | 🆕 | active execution 后台 reconcile loop 每 30s 低频 drain（`background_drain_interval_seconds=30`），打开 Web 日志窗口升到 1s（`realtime_drain_interval_seconds=1`），关窗降回，结束 final drain；单次最多 256KB（`max_tail_bytes_per_pull=262144`）；结束检测靠 server 轮询 agent status API（不依赖 agent 回调），finished/failed/canceled→finalizing→final drain→EOF 稳定(默认 3s)或 hard timeout(30s)→complete，complete 后调 agent cleanup API；正文落 server `/server-data/logs/YYYY/MM/{execution_id}/{attempt_id}.{stream}.log`，索引落 PG 表 `execution_log_files`（PG 不存正文）；server→web 单向 SSE（多窗口看同一 execution 复用一个 pull loop + SSE fan-out） | `03-gap-realtime-logs.md` §4 |
| egg 上传下发 | 🆕 | 第一版仅支持上传已构建 egg：用户上传→server→转发 agent→agent 调本机 scrapyd `/addversion.json`；不做本地/源码/Git/CI 构建 | `01-gap-executors.md` §6.4 |
| `ScrapydExecutor` | 🆕 | 在 `apps/server/dopilot_server/executors/scrapyd.py` 全新实现 scrapyd 下发执行器（经 dopilot-agent，不直连裸 scrapyd），行为对齐 scrapydweb 参考的 scrapyd 集群 I/O 语义；server 生成 `execution_id`/`attempt_id` 下发 agent | `01-gap-executors.md` §6.4 |
| 定时任务 | 🆕 | 在 `apps/server/dopilot_server/scheduler` 新建调度，沿用 APScheduler + Task 持久化的机制语义（功能参考），按 dopilot 模型重写；实现时注意 APScheduler 版本/pkg_resources(setuptools>=81) 坑与单实例无分布式锁 | `02-gap` §2.5、`architecture/03-scheduler-engine.md` |
| 节点策略(指定/全部/随机) | 🆕 | dopilot 新立的抽象主线，落在 `apps/server/dopilot_server/nodes`：`node_strategy` 默认 `all`，触发时动态归约 | `02-gap` §3 |
| 推模式(立即下发) | 🆕 | 经 `BaseExecutor` 抽象 + `api/v1` 独立推送端点，下发到指定节点立即执行 | `02-gap` §4 |
| 前端分阶段交付 M1~M3 | 🆕 | SPA greenfield 分阶段交付：servers/jobs(M1) → 实时日志/stats(M2) → schedule/tasks(M3，含节点策略+推模式 UI) | `06-frontend-rewrite.md` §2 |

## 4. 阶段 2：Python 脚本（复用阶段1 已落地的 dopilot-agent）

> dopilot-agent 已在**阶段1 落地**（内管本机 scrapyd + server pull 日志），阶段2 不再新建 agent，仅在既有 agent 上加脚本执行能力。

| Epic | 类型 | 说明 | 文档 |
|------|------|------|------|
| `ScriptExecutor` | 🆕 | 一次性 Python3 脚本执行器，复用阶段1 dopilot-agent（agent 拉起脚本子进程） | `01-gap-executors.md` §6 |
| 脚本日志源 | 🆕 | LogSource 接脚本 `stream=stdout/stderr`（schema/tail API 第一版已支持 log/stdout/stderr/system 四类，脚本阶段启用 stdout/stderr）；仍走 server pull + SSE 主线 | `03-gap-realtime-logs.md` §2 |
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
dopilot-agent(阶段1,内管本机 scrapyd) ──► agent 注册+/health ──► server→agent→本机 scrapyd→scrapy
BaseExecutor 抽象 ──► ScrapydExecutor(阶段1,经 agent) ──► ScriptExecutor(阶段2,复用 agent) ──► DockerExecutor(阶段3)
LogSource 抽象 ──► server pull(agent tail API) ──► server→web SSE ──► 正文落 /server-data/logs + 索引/offset/状态落 PostgreSQL
   stream: scrapyd job.log(log) ──► 脚本 stdout/stderr ──► 容器 logs    (第一版不使用 WebSocket、agent 不主动推)
node_strategy ──► (阶段1 起对所有 Executor 生效)
```

## 7. 跨文档关键决策状态

> 完整清单见各 gap 文档末节。以下为影响架构的关键项：

| # | 问题 | 来源 | 现状 |
|---|---------|------|------|
| 1 | worker agent 与 server 的通信协议 | `01-gap` §8 | 已定：server 主动 HTTP pull（agent 暴露 tail/status/cleanup API，offset 权威在 server PG），不用回调/消息队列；agent 通过初始发现地址 + 稳定 `agent_id` 入库，server 轮询 `/health` |
| 2 | Docker 长连接的"定时"语义（启新容器 vs 发指令） | `02-gap` §2.3 | 待定（阶段3 前定） |
| 3 | JS 文案 i18n 策略 | `04-gap` §4 | 已定：Vue SPA 用 vue-i18n，后端返回 message_key/code |
| 4 | Web 部署 | `06-frontend` §9 | 已定：不内置 nginx；反代用户可选；Web 以独立 Vue/Vite 容器运行 |
| 5 | token 形式 | `06-frontend` §9 | 已定：服务端签发 opaque token，无 refresh token |
| 6 | 容器持久化卷边界（哪些目录随卷、哪些可清） | `08-docker` | 已定：PostgreSQL 数据卷 + `/server-data/logs` + `/agent-data` 持久化；构建缓存/临时目录可清 |

## 8. 文档矩阵（按阶段查阅）

| 阶段 | 必读现状 | 必读改造 |
|------|---------|---------|
| 阶段0 | `architecture/00,01,06` | `phases/phase-0/00-brief`, `dopilot/05,06,07,08,09` |
| 阶段1 | `architecture/02,03,04,05` | `dopilot/01,02,03,06` |
| 阶段2 | `architecture/01,02` | `dopilot/01,08` |
| 阶段3 | `architecture/05` | `dopilot/01,02,03` |
