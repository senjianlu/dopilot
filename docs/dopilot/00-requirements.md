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
| 6 | 前后端技术栈（整体重构） | **后端采用 FastAPI + Pydantic + ASGI**，由 `apps/server` 提供 `/api/v1/*` JSON API；前端采用 **Vue 3 + Element Plus + Vite + TypeScript**，位于 `apps/web`，是 **greenfield SPA**，全新构建直接对接 `/api/v1`。dopilot **不继承任何 scrapydweb Jinja 模板**，故不存在与既有 Jinja 页面共存/strangler 迁移；可分阶段交付页面。归属**阶段 0**。详见 `docs/dopilot/06-frontend-rewrite.md`。 |
| 7 | 镜像构建与发布 | dopilot 镜像统一构建并推送到 **Docker Hub `rabbir/dopilot`**：server、agent、migrate 使用同一个 `rabbir/dopilot:latest` 镜像，通过启动命令选择角色。⚠️ git `origin` 为 `senjianlu/dopilot`，镜像命名空间为 `rabbir`（Docker Hub 账号），**两者独立**，文档/CI 中不要混用。详见 `docs/dopilot/08-docker-deployment.md` §7。 |
| 8 | 代码仓库结构 | **monorepo，apps/packages 布局**：server = `apps/server/dopilot_server`，agent = `apps/agent/dopilot_agent`，web = `apps/web`；server↔agent 共享协议在 `packages/protocol`（可选客户端 SDK 在 `packages/client`），部署物在 `deploy/`，配置样例在 `configs/`。三者**同仓开发，不拆分多仓**。`reference/scrapydweb/` 仅作只读功能/测试参照，不参与构建。权威布局详见 `docs/dopilot/05-dev-setup-and-known-issues.md` §1。 |
| 9 | scrapydweb 参考边界（原则锁定） | scrapydweb 仅作 **(1) 功能层/行为参考** 与 **(2) 测试 oracle**；其**代码写法、目录结构、模块划分、命名、依赖、配置形态一律不得作为 dopilot 的设计依据**。dopilot 为 **greenfield**、按 `apps/`+`packages/` 自有领域 **structure-first** 全新编写：`reference/scrapydweb/` **只读、不进构建上下文、不被 import、不做改名/git mv**。凡文档中出现的 scrapydweb `file:line` 引用，**仅为行为参考**（约定见各文档「Docs convention」），绝非 dopilot 的改动目标。 |
| 10 | 数据库选型 | **只使用 PostgreSQL 作为 dopilot 唯一数据库**。server 是唯一持有数据库连接、事务与迁移的角色；agent 和 web 不直连数据库。ORM 使用 SQLAlchemy，迁移使用**裸 Alembic**（不用 Flask-Migrate，FastAPI 无 Flask app）；APScheduler jobstore 也落 PostgreSQL。**PostgreSQL 存业务数据 + 日志索引/offset/状态**（执行器差异化配置和原始运行元数据可用 `JSONB`；日志索引见 `execution_log_files` 表，主键 `(execution_id, attempt_id, stream)`，含 `storage_path`/`last_pulled_offset`/`final_offset`/`status` 等）；**日志正文不入 PostgreSQL，存 server 本地文件 `/server-data/logs`**。删库重建不作为 dopilot 正式迁移策略（仅 scrapydweb reference 行为）。 |
| 11 | 实时日志链路 | server 按需从 agent tail API 拉取日志增量；打开 Web 日志窗口时高频拉取，后台低频 drain active execution，任务结束后 final drain。server 将日志正文写入 `/server-data/logs`，将日志索引/offset/状态写入 PostgreSQL，并通过 SSE 推给 Vue。第一版不使用 WebSocket。 |
| 12 | 认证边界 | **Web 管理员认证与 Agent 机器认证分离，均 config-present-or-off**（配置齐全才启用，缺失则对应认证关闭）。**Web→Server**：单管理员登录 + Bearer **opaque access token**（无 refresh token）；SSE 用短期 `stream_token`（TTL 60s、仅校验建连），避免长期 token 放 URL。**Server→Agent**：server 持共享 `shared_token` 调用 agent 的 HTTP API（派发任务、pull 日志 tail、轮询 status、cleanup、health），由 agent 校验 server 身份。**v1 agent 不主动回连 server**（无 agent→server 注册/心跳/日志上报）；agent 启动时携带容器重启不变的稳定 `agent_id`，server 将节点落入 `nodes` 表并主动 pull + health 轮询。第一版不做 mTLS / token 轮换 / RBAC / 多用户。 |
| 13 | 节点持久化 | 第一版即建立 `nodes` 表。agent 启动配置/环境变量传入稳定 `agent_id`（容器重启不变），server 以该 ID 作为节点主标识；`[nodes].agents` 只作为初始发现地址列表，不作为业务关系的长期主键。 |
| 14 | Web 部署 | 不内置 nginx；反向代理是用户可选部署层。第一版 Web 容器按 Vue/Vite 常规方式运行前端应用，server 只提供 FastAPI API/SSE。 |

## 5. 分期路线（由决策推导）

> 核心原则：**一类一类做，做稳一类再上下一类**。

| 阶段 | 目标 | 被调度对象 | 节点形态 | 说明 |
|------|------|-----------|---------|------|
| 阶段 0 | 平台基座 | —— | —— | 搭建 dopilot 自有骨架（apps/packages 布局、`apps/server` 的 FastAPI `/api/v1` 与配置加载器、PostgreSQL + Alembic 基线、`packages/protocol` 协议）、单管理员认证、i18n(中文)、server/agent 的 Docker 化部署骨架、实时日志框架 |
| 阶段 1 | Scrapy 优先跑稳 | 类型 1（Scrapy） | dopilot-agent 内置/管理本机 scrapyd | 以 scrapydweb 的 scrapyd 集群 I/O 行为为功能参考，但第一版架构按 **server → dopilot-agent → 本机 scrapyd → scrapy process** 实现（scrapyd 监听容器内部端口仅本机可见，对外暴露的是 agent API）；agent 负责调本机 scrapyd、tail `job.log` 并提供 HTTP tail / status / cleanup API；**日志由 server 主动 pull（agent 不主动推、第一版不用 WebSocket）**。egg **仅支持上传已构建产物**：用户上传 → server → 转发 agent → agent 调本机 scrapyd `/addversion.json`，不做本地/源码/Git/CI 构建。agent 启动携带稳定 `agent_id`，server 写入/更新 `nodes` 表并轮询 agent `/health`，调度只选健康 agent；agent 主动 heartbeat 留后续。dopilot-agent 阶段 1 即落地。 |
| 阶段 2 | 接入脚本 | 类型 3（Python 脚本） | 新增脚本 worker agent（Docker 容器） | 引入执行器抽象，agent 角色落地 |
| 阶段 3 | 接入长连接 | 类型 2（Docker 长连接爬虫） | Docker / K3s API SDK | 容器生命周期管理，最后开发 |

### server / agent 部署形态（初步）

```
┌─────────────────────────────┐         ┌──────────────────────────┐
│  dopilot-server (Docker)    │  push   │  dopilot-agent (Docker)  │
│  - FastAPI API + 调度中心   │ ──────► │  - 本机 scrapyd (阶段1)  │
│  - APScheduler 定时         │         │  - 脚本 worker (阶段2)   │
│  - PG(业务+日志索引/offset) │ ─pull─► │  - 容器管理 (阶段3)      │
│  - 日志正文落本地文件        │ ◄─tail─ │  - tail/status/cleanup   │
│  - 单管理员认证 + SSE→web   │         │    HTTP API              │
└─────────────────────────────┘         └──────────────────────────┘
                          (server 主动 pull 日志；agent 不主动推)
```

> **镜像与仓库**：上图两个角色都在**同一 monorepo**（决策 8）内开发；构建产物统一推送到 Docker Hub `rabbir/dopilot:latest`，server/agent 由启动命令区分（决策 7）。第一版架构目标就是自有 `dopilot-agent` 包装/管理本机 scrapyd；直接使用现成 Scrapyd 镜像只允许作为本地 spike 或连通性验证，不作为第一版正式架构。

## 6. 文档导航

- 现状架构：`docs/architecture/`（总览、启动配置、数据模型、调度引擎、视图前端、scrapyd 通信、认证工具）
- 改造分析：`docs/dopilot/`（执行器、定时+节点+推模式、实时日志、i18n、本需求文档、开发环境）
