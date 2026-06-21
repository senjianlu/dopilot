# dopilot —— 需求与目标（北极星文档）

> 本文记录 dopilot 的产品目标与改造需求，是后续所有架构/改造文档的依据。
> 内容来自用户口述，已标注我方理解与**已确认决策**。如与用户最新意见冲突，以用户为准。

> **【scrapydweb 参考边界】** scrapydweb 仅作**功能层/行为参考**与**测试 oracle**；其代码写法、目录结构、模块划分、命名、依赖、配置形态**一律不得作为 dopilot 的设计依据**。dopilot 为 greenfield、按 `apps/`+`packages/` 自有领域 structure-first 设计（权威布局见 `05-dev-setup-and-known-issues.md` §1），**不对 scrapydweb 做改名/git mv**。详见 §4 决策表。

## 1. 背景

dopilot 是在开源项目 [scrapydweb](https://github.com/my8100/scrapydweb)（Flask 实现的 Scrapyd 集群管理 / 调度 Web 平台）基础上改造而来的**私有调度平台**。

- scrapydweb 本体作为**只读功能层/测试参照**置于 `reference/scrapydweb/`（保留上游完整目录结构）；它**不参与构建、不被 import、不作目录结构依据**。dopilot 按自身领域 structure-first 全新设计，采用 **apps/packages monorepo 布局**（`apps/server/dopilot_server`、`apps/agent/dopilot_agent`、`apps/web`、`packages/protocol`、`packages/client`、`deploy/`、`configs/`、`scripts/`、`docs/`），并保留 dopilot git 历史（origin: `senjianlu/dopilot`）。权威布局见 `docs/dopilot/05-dev-setup-and-known-issues.md` §1。
- 上游以 `upstream` 远程保留（`my8100/scrapydweb`），便于后续 diff / cherry-pick 修复，但不合并其历史。
- 导入快照版本：scrapydweb `1.6.0`，上游 commit `1341cf9`（该 hash 来自上游仓库；本仓库为压缩后的单个 `Initial commit`，需 `git fetch upstream` 后才能 `git show 1341cf9` 核对）。

## 2. 需要支持的「被调度对象」（三类）

| # | 类型 | 说明 | scrapydweb 现状 |
|---|------|------|----------------|
| 1 | **Scrapy 框架爬虫** | 经由 scrapyd 部署(egg)与调度 | ✅ 原生支持 |
| 2 | **Docker 容器内长连接爬虫** | 运行在 Docker 容器中的**长连接 / 常驻进程**（不是跑完即退） | ❌ 不支持，需新增执行器 |
| 3 | **简单 Python3 脚本** | 一次性的普通 Python 脚本任务 | ❌ 不支持，需新增执行器 |

> 核心架构挑战：scrapydweb 完全围绕 scrapyd 协议（egg 部署 + schedule API）。类型 2、3 需要引入**执行器（Executor / Runner）抽象层**，详见 `docs/dopilot/01-gap-executors.md`。

### 2.1 阶段 1.8 后的核心领域模型

阶段 1.8 将原先偏 Scrapy 的「爬虫 / 任务模板 / execution-attempt」
口径清理为跨执行类型的统一模型，为阶段 2 Python 脚本和阶段 3 Docker
执行器铺路：

```text
构建产物 BuildArtifact
  -> 执行模板 ExecutionTemplate
    -> 定时调度 Schedule
      -> 任务 Task
        -> 执行实例 Execution
```

- **构建产物（BuildArtifact）** 是“可执行产物”，不是构建过程。阶段
  1.8 仅支持 `artifact_type=scrapy` + `.egg`；阶段 2 预留
  `python_wheel` + `.whl`；阶段 3 预留 `docker_image`。
- **执行模板（ExecutionTemplate）** 必须绑定一个构建产物，保存默认执行
  参数、节点策略与节点选择。Scrapy 的执行命令在 Web 中只读展示，用户只
  配置参数。
- **定时调度（Schedule）** 必须引用一个执行模板，可覆盖执行参数、
  节点策略和节点选择，但不能覆盖构建产物。
- **任务（Task）** 是一次触发产生的父级运行记录。直接运行构建产物、
  运行执行模板、定时 trigger-now 或 timer firing 都会创建任务。
- **执行实例（Execution）** 是任务按节点 fan-out 后产生的单节点原子执行
  单元。每个执行实例通过任务快照可追溯到构建产物；执行模板和定时调度
  只是可选来源关系。
- 任务创建时冻结 resolved snapshot，优先级固定为：

```text
schedule override > execution template default > build artifact default
```

节点选择除健康、未下线、未删除外，还必须按构建产物类型过滤能力：

```text
scrapy -> scrapy
python_wheel -> python_wheel
docker_image -> docker_runtime
```

Redis / agent / 日志路径的兼容 seam 仍保留旧字段名：
`execution_id` 表示父级 Task id，`attempt_id` 表示原子 Execution id；
这些名字只允许存在于 wire/disk/agent 边界。

## 3. 需要支持的「平台功能」（五项）

| # | 功能 | 要点 | scrapydweb 现状（待 workflow 核实） |
|---|------|------|--------------------------------|
| 1 | **实时日志** | 实时日志流，而非刷新页面看日志文件 | 现为 logparser 解析日志文件 + 轮询/iframe，非实时流 |
| 2 | **定时任务设置** | cron / interval 定时调度 | ✅ 已有基于 APScheduler 的 timer task，可复用扩展 |
| 3 | **节点选择策略** | 可指定 worker 节点；可选「指定节点**全部**执行」或「**动态随机**选一个健康节点执行」；全部执行时并发下发 | 支持多节点选择执行；dopilot 新增动态随机与并发 fan-out |
| 4 | **推模式指定执行** | push 模式：主动下发任务到指定节点执行 | 待核实现状语义 |
| 5 | **多语言 i18n** | 预留国际化框架，**当前只需中文** | 模板存在中英文案，需引入正式 i18n 框架 |

## 4. 已确认的关键决策（用户拍板，2026-06-17）

| # | 问题 | 决策 |
|---|------|------|
| 1 | Docker 长连接爬虫管理边界 | 通过 **Docker / K3s API SDK** 启停容器。**优先级最低**：等 Scrapy 与 Python 脚本两类都支持并稳定后才开发。 |
| 2 | 「推模式」语义 | **下发到指定 worker 立即执行**（平台主动 push，与定时/拉相对）。 |
| 3 | worker 节点形态 | **第一版仅一类节点：`dopilot-agent`**（内置/管理本机 scrapyd，以完整 Docker 容器部署，以稳定 `agent_id` 为主标识——见决策 #11/#13；裸 scrapyd 仅本地 spike，非节点形态）。待 Scrapy 稳定后再加入「类型 3 Python 脚本」的 worker 节点。 |
| 4 | 用户 / 权限体系 | **单用户、唯一管理员**。无需多用户/角色，保留并简化为单管理员认证即可。 |
| 5 | dopilot 自身部署形态 | 分 **server**（调度中心 + Web）与 **agent**（worker 节点）两种部署角色，**均使用 Docker 部署**。 |
| 6 | 前后端技术栈（整体重构） | **后端采用 FastAPI + Pydantic + ASGI**，由 `apps/server` 提供 `/api/v1/*` JSON API；前端采用 **Next.js（静态导出 `output: export`，`trailingSlash`）+ shadcn/ui + Recharts + TypeScript**（自 **阶段 2.1** 起，替换原 Vue 3 + Element Plus + Vite 选型，详见 `docs/phases/phase-2.1/00-brief.md`），位于 `apps/web`，是 **greenfield SPA**，全新构建直接对接 `/api/v1`，构建产物为**纯静态 HTML/CSS/JS，由 dopilot-server 托管，不引入 Node 生产运行时**（无 `next start`）。dopilot **不继承任何 scrapydweb Jinja 模板**，故不存在与既有 Jinja 页面共存/strangler 迁移；可分阶段交付页面。技术栈骨架归属**阶段 0**，Next.js/shadcn 迁移归属**阶段 2.1**。详见 `docs/dopilot/06-frontend-rewrite.md`。 |
| 7 | 镜像构建与发布 | dopilot 镜像统一构建并推送到 **Docker Hub `rabbir/dopilot`**：server、agent、migrate 使用同一个 `rabbir/dopilot:latest` 镜像，通过启动命令选择角色。⚠️ git `origin` 为 `senjianlu/dopilot`，镜像命名空间为 `rabbir`（Docker Hub 账号），**两者独立**，文档/CI 中不要混用。详见 `docs/dopilot/08-docker-deployment.md` §7。 |
| 8 | 代码仓库结构 | **monorepo，apps/packages 布局**：server = `apps/server/dopilot_server`，agent = `apps/agent/dopilot_agent`，web = `apps/web`；server↔agent 共享协议在 `packages/protocol`（可选客户端 SDK 在 `packages/client`），部署物在 `deploy/`，配置样例在 `configs/`。三者**同仓开发，不拆分多仓**。`reference/scrapydweb/` 仅作只读功能/测试参照，不参与构建。权威布局详见 `docs/dopilot/05-dev-setup-and-known-issues.md` §1。 |
| 9 | scrapydweb 参考边界（原则锁定） | scrapydweb 仅作 **(1) 功能层/行为参考** 与 **(2) 测试 oracle**；其**代码写法、目录结构、模块划分、命名、依赖、配置形态一律不得作为 dopilot 的设计依据**。dopilot 为 **greenfield**、按 `apps/`+`packages/` 自有领域 **structure-first** 全新编写：`reference/scrapydweb/` **只读、不进构建上下文、不被 import、不做改名/git mv**。凡文档中出现的 scrapydweb `file:line` 引用，**仅为行为参考**（约定见各文档「Docs convention」），绝非 dopilot 的改动目标。 |
| 10 | 数据库选型 | **只使用 PostgreSQL 作为 dopilot 唯一数据库**。server 是唯一持有数据库连接、事务与迁移的角色；agent 和 web 不直连数据库。ORM 使用 SQLAlchemy，迁移使用**裸 Alembic**（不用 Flask-Migrate，FastAPI 无 Flask app）；APScheduler jobstore 也落 PostgreSQL。**PostgreSQL 存业务数据 + 日志索引/offset/状态**（执行器差异化配置和原始运行元数据可用 `JSONB`；日志索引见 `execution_log_files` 表，主键 `(execution_id, attempt_id, stream)`，含 `storage_path`/`last_pulled_offset`/`final_offset`/`status`/`log_integrity` 等）；**日志正文不入 PostgreSQL，存 server 本地文件 `/server-data/logs`**。删库重建不作为 dopilot 正式迁移策略（仅 scrapydweb reference 行为）。**补注（Redis 边界，重构后）**：Redis 是 server↔agent 单实例通信的**消息总线/瞬时传输层**，**不是 dopilot 数据库、不持久化业务真相**；业务状态权威仍是 PostgreSQL，日志正文最终存储仍是 `/server-data/logs`。agent 经 Redis 与 server 通信，**仍不直连 PostgreSQL**。详见 `docs/refactor/00-redis-streams-agent-communication.md`。 |
| 11 | 实时日志链路 | **重构后（拉→推，破坏性、无双轨；详见 `docs/refactor/00-redis-streams-agent-communication.md`）**：日志由 **agent 经 Redis log stream（`dopilot:server:logs`）主动推送增量**（base64 字节，带 offset/size_bytes/eof），**server 消费后落盘**，不再由 server 主动 pull agent tail API。四个不变量保持不变：①第一版不使用 WebSocket；②server→web 走 SSE；③日志正文写入 `/server-data/logs`；④PostgreSQL 只存日志索引/offset/状态。`LogSource` 抽象保留，实现由 `AgentTailLogSource` 换为 `RedisLogSource`。日志 RPO≠0（接受 server 长停或 Redis 裁剪致片段缺失 `partial`）：业务状态与日志完整性分离，日志完整性新增 `log_integrity` 列（`complete`/`partial`/`missing`/`expired`），缺片以可见 gap marker 暴露、不阻塞执行状态收敛。 |
| 12 | 认证 / 通信边界 | **Web 管理员认证与 Agent 机器认证分离，均 config-present-or-off**（配置齐全才启用，缺失则对应认证关闭）。**Web→Server**：单管理员登录 + Bearer **opaque access token**（无 refresh token）；SSE 用短期 `stream_token`（TTL 60s、仅校验建连），避免长期 token 放 URL。**Server↔Agent（重构后，破坏性、无双轨；详见 `docs/refactor/00-redis-streams-agent-communication.md`）**：通信主路径改为 **Redis Streams**——server→agent 命令（run/stop/cleanup_logs）经 `dopilot:agent:{agent_id}:commands` 投递，**agent 经 consumer group 主动消费命令、主动 XADD 推送状态事件（`dopilot:server:agent-events`）与日志（`dopilot:server:logs`）**，删除 server→agent HTTP run/status/tail 主路径。健康检查改为 **agent 主动 POST `/api/v1/agents/{agent_id}/heartbeat`**（不再由 server 轮询 agent `/health`）。鉴权拆分：agent→server 用 `server_shared_token`（**不复用 server→agent 旧 token**），Redis 启用 AUTH/ACL。agent 仍**不直连 PostgreSQL**。agent 启动携带容器重启不变的稳定 `agent_id`，server 将节点落入 `nodes` 表，健康来源由 heartbeat 写入的 `nodes.last_seen_at` 判定。第一版不做 mTLS / token 轮换 / RBAC / 多用户。 |
| 13 | 节点持久化 | 第一版即建立 `nodes` 表。agent 启动配置/环境变量传入稳定 `agent_id`（容器重启不变），server 以该 ID 作为节点主标识；`[nodes].agents` 只作为初始发现地址列表，不作为业务关系的长期主键。 |
| 14 | Web 部署 | 不内置 nginx；反向代理是用户可选部署层。前端为 **Next.js 静态导出**产物（自阶段 2.1），**由 dopilot-server 直接托管静态资源**（`DOPILOT_WEB_DIST=/app/web`，每路由一个 HTML + `_next/` 资源 + `404.html`），不引入独立 Web 容器/Node 生产运行时；server 同时提供 FastAPI API/SSE。 |
| 15 | 阶段 1.8 领域模型清理 | 使用 **BuildArtifact / ExecutionTemplate / Schedule / Task / Execution** 作为产品与 API 口径；构建产物成为真实 DB 实体；执行模板必须绑定构建产物；public API/Web 硬切到 Task/Execution；`task_type` 仅作为现有 agent wire 字段保留在边界。 |
| 16 | Python 脚本打包与运行预期 | 阶段 2 使用 `.whl` 作为 Python 脚本构建产物格式。agent 侧按 sha256 用 `pip install --no-deps --target <cache>/python_wheel/<sha256>/site` 安装 wheel（**不创建 venv、不做依赖解析、不写 console-script 入口**），运行时把该 site 目录注入 `PYTHONPATH` 并以 `/bin/sh -c "<command>"`（进程组）启动脚本，强制 `PYTHONUNBUFFERED=1`，stdout/stderr 合并推送 Redis log stream，以子进程退出码收敛执行状态。wheel 之外的依赖需操作者预先装入 agent 环境。详见 `docs/phases/phase-2b/00-brief.md`。 |

## 5. 分期路线（由决策推导）

> 核心原则：**一类一类做，做稳一类再上下一类**。

| 阶段 | 目标 | 被调度对象 | 节点形态 | 说明 |
|------|------|-----------|---------|------|
| 阶段 0 | 平台基座 | —— | —— | 搭建 dopilot 自有骨架（apps/packages 布局、`apps/server` 的 FastAPI `/api/v1` 与配置加载器、PostgreSQL + Alembic 基线、`packages/protocol` 协议）、单管理员认证、i18n(中文)、server/agent 的 Docker 化部署骨架、实时日志框架 |
| 阶段 1 | Scrapy 优先跑稳 | 类型 1（Scrapy） | dopilot-agent 内置/管理本机 scrapyd | 以 scrapydweb 的 scrapyd 集群 I/O 行为为功能参考，但第一版架构按 **server → dopilot-agent → 本机 scrapyd → scrapy process** 实现（scrapyd 监听容器内部端口仅本机可见，对外暴露的是 agent API）；agent 负责调本机 scrapyd、tail `job.log` 并提供 HTTP tail / status / cleanup API；**日志由 server 主动 pull（agent 不主动推、第一版不用 WebSocket）**。egg **仅支持上传已构建产物**：用户上传 → server → 转发 agent → agent 调本机 scrapyd `/addversion.json`，不做本地/源码/Git/CI 构建。agent 启动携带稳定 `agent_id`，server 写入/更新 `nodes` 表并轮询 agent `/health`，调度只选健康 agent；agent 主动 heartbeat 留后续。dopilot-agent 阶段 1 即落地。**（注：阶段 1 的 server↔agent 通信为 HTTP pull——既定事实；通信层翻案为 Redis Streams 作为下方独立的「阶段 1.5」承载，决策口径见决策 #11/#12，不回改本行已交付内容。）** |
| 阶段 1.5 | 通信层重构（→ Redis Streams） | 类型 1（不新增调度对象） | 同阶段 1（dopilot-agent） | **破坏性重构、无双轨**：把阶段 1 的 server 主动 HTTP（run/status/tail pull + 轮询 `/health`）整体翻案为 **Redis Streams**——server 经 `dopilot:agent:{agent_id}:commands` 下发命令（事务性 command_outbox + dispatcher），**agent 经 consumer group 主动消费、主动 XADD 状态事件（`dopilot:server:agent-events`）与日志（`dopilot:server:logs`，base64 字节增量），server 消费后落盘**；健康改为 **agent 主动 POST `/api/v1/agents/{agent_id}/heartbeat`**，server 据 `nodes.last_seen_at` 判健康（不再轮询 agent `/health`，`/health` 降级为容器本地 healthcheck）；鉴权拆 `server_shared_token` + Redis AUTH/ACL；删除 server→agent HTTP run/status/tail 主路径与 `AgentTailLogSource` 主路径。保留四不变量（不用 WebSocket / SSE / 正文落盘 / PG 只存索引）与单实例约束。立即启动（不等阶段 2/3）。任务书见 `docs/phases/phase-1.5/00-brief.md`，唯一设计真相见 `docs/refactor/00-redis-streams-agent-communication.md`。 |
| 阶段 1.8 | 领域模型清理 | 类型 1（Scrapy，构建产物化） | 同阶段 1.5（dopilot-agent） | 将 Scrapy artifact 泛化为 BuildArtifact，将任务模板改为 ExecutionTemplate，public API/Web 硬切到 Task/Execution，定时调度支持覆盖参数/节点策略/节点，直接运行构建产物会创建 ad-hoc snapshot 任务。阶段 1.8 不新增 Python/Docker 执行器。 |
| 阶段 2 | 接入脚本 | 类型 3（Python 脚本） | 复用 dopilot-agent，新增 python_wheel 能力 | Python 脚本以 `.whl` 构建产物接入；agent 下载 wheel、按 sha256 用 `pip install --no-deps --target` 安装到缓存 site 目录（无 venv、无依赖解析），把该目录注入 `PYTHONPATH` 后以 `/bin/sh -c` + 独立进程组启动，stdout/stderr 合并经 Redis log stream 实时推送，退出码映射执行状态。 |
| 阶段 3 | 接入长连接 | 类型 2（Docker 长连接爬虫） | Docker / K3s API SDK | 容器生命周期管理，最后开发 |

### server / agent 部署形态（重构后）

> 通信重构（破坏性、无双轨）后，server↔agent 主路径走 Redis Streams；详见 `docs/refactor/00-redis-streams-agent-communication.md`。

```
┌─────────────────────────────┐                    ┌──────────────────────────┐
│  dopilot-server (Docker)    │                    │  dopilot-agent (Docker)  │
│  - FastAPI API + 调度中心   │   ┌────────────┐   │  - 本机 scrapyd (阶段1)  │
│  - APScheduler 定时         │ ─►│   Redis    │◄─ │  - 脚本 worker (阶段2)   │
│  - command outbox/dispatcher│   │  Streams   │   │  - 容器管理 (阶段3)      │
│  - event/log consumer       │◄─ │ (消息总线) │ ─►│  - 命令 consumer 消费    │
│  - PG(业务+日志索引/offset) │   └────────────┘   │  - 状态/日志 XADD 推送   │
│  - 日志正文落本地文件        │                    │  - 容器本地 /health      │
│  - 单管理员认证 + SSE→web   │◄── heartbeat ───── │  - 主动 POST heartbeat   │
└─────────────────────────────┘                    └──────────────────────────┘
   server XADD 命令 ─► dopilot:agent:{agent_id}:commands ─► agent 消费(run/stop/cleanup_logs)
   agent XADD 事件 ─► dopilot:server:agent-events ─► server 消费(attempt.*)
   agent XADD 日志 ─► dopilot:server:logs ─► server 消费落盘 /server-data/logs
   agent ─► POST /api/v1/agents/{id}/heartbeat ─► server(更新 nodes.last_seen_at)
```

> **镜像与仓库**：上图两个角色都在**同一 monorepo**（决策 8）内开发；构建产物统一推送到 Docker Hub `rabbir/dopilot:latest`，server/agent 由启动命令区分（决策 7）。第一版架构目标就是自有 `dopilot-agent` 包装/管理本机 scrapyd；直接使用现成 Scrapyd 镜像只允许作为本地 spike 或连通性验证，不作为第一版正式架构。
>
> **Redis 消息总线（重构后）**：docker compose 新增 `redis` 服务并启用 AUTH/AOF。配置口径新增——server 端 `[redis]`（`url`/`stream_maxlen_*`/`log_retention_seconds`/`consumer_name`/`require_aof`）、`[agents]`（`heartbeat_timeout_seconds`/`stalled_attempt_seconds`/`lost_after_stalled_seconds`）、`[logs].log_drain_timeout_seconds`；agent 端 `[redis]`（`url`/`command_block_ms`/`pending_idle_ms`/`event_outbox_dir`）、`[agent].server_url`/`heartbeat_interval_seconds`/`server_shared_token`。Redis 仅作**单实例 server↔agent 通信总线**，不引入 Redis 做多副本 HA/fan-out/分布式锁；server→web SSE fan-out 仍在单进程内存完成。单实例约束不变（server 单容器、uvicorn `workers=1`、单 APScheduler）。详见 `docs/refactor/00-redis-streams-agent-communication.md`。

## 6. 文档导航

- 现状架构：`docs/architecture/`（总览、启动配置、数据模型、调度引擎、视图前端、scrapyd 通信、认证工具）
- 改造分析：`docs/dopilot/`（执行器、定时+节点+推模式、实时日志、i18n、本需求文档、开发环境）
