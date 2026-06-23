# dopilot —— 前端整体构建方案（Next.js + shadcn/ui）

> 决策来源：用户 2026-06-17 拍板（阶段 0 选型）。归属**阶段 0（平台基座）**。
> 配套现状参考：`docs/architecture/04-views-and-frontend.md`（scrapydweb 前端现状）。

> **⚠️【阶段 2.1 技术栈迁移，权威更新】** 自**阶段 2.1**起，前端技术栈由 **Vue 3 + Element Plus + Vite** 迁移为 **Next.js（静态导出 `output: export` + `trailingSlash`）+ shadcn/ui（slate 主题、明暗模式）+ Recharts + react-i18next + TypeScript**，仍为**纯静态产物，由 dopilot-server 托管**（无 `next start`/Node 生产运行时/独立 Web 容器），API/SSE 契约不变。下文「决策摘要」表已更新为当前选型；正文中若仍出现 Vue/Element Plus/Vite/vue-i18n/Pinia 等旧词，按当前栈对应理解（组件→shadcn/ui、状态→React hooks、i18n→react-i18next、路由→Next App Router 静态导出、任务详情路由 `/tasks/detail?id=<id>`）。迁移细节见 `docs/phases/phase-2.1/00-brief.md` 与 `docs/phases/phase-2.1/01-claude-implementation-report.md`。

> **【scrapydweb 参考边界】** scrapydweb 仅作**功能层/行为参考**与**测试 oracle**；其代码写法、目录结构、模块划分、命名、依赖、配置形态**一律不得作为 dopilot 的设计依据**。dopilot 为 greenfield、按 `apps/`+`packages/` 自有领域 structure-first 设计（权威布局见 `05-dev-setup-and-known-issues.md` §1），**不对 scrapydweb 做改名/git mv**。详见 `00-requirements.md` 决策表。

## 0. 决策摘要

> 当前选型（阶段 2.1 起）。括注为原阶段 0 选型。

| 项 | 选型 |
|----|------|
| 框架 | **Next.js（App Router，静态导出 `output: export`）+ TypeScript**（原 Vue 3 + Composition API） |
| 构建 | **Next.js 静态导出**（`output: export`、`trailingSlash`，产物 `apps/web/out`）（原 Vite） |
| UI 库 | **shadcn/ui**（Tailwind v4、slate 主题、内置明暗模式；`sidebar-07`/`login-01` 区块） + Recharts 图表（原 Element Plus） |
| 路由/状态 | **Next App Router（静态导出）+ React hooks**（原 Vue Router + Pinia） |
| i18n | **react-i18next**，默认中文，预留多语言（原 vue-i18n） |
| 请求 | axios（统一封装 `/api/v1`，同源；开发期可经 `NEXT_PUBLIC_API_BASE` 指向独立 server） |
| 实时 | **agent 主动经 Redis Streams 消费命令、主动推状态/日志事件、主动 POST heartbeat**；**server 消费 agent→Redis 日志事件后落盘**（不再 HTTP pull agent tail）；**server → web 使用 SSE**（浏览器单向日志流）；详见 `03-gap-realtime-logs.md` 与 `refactor/00-redis-streams-agent-communication.md` |
| 后端 | **FastAPI + Pydantic + ASGI**，提供 `/api/v1/*` JSON/SSE API |
| 数据库 | **PostgreSQL 唯一数据库**；SQLAlchemy + 裸 Alembic；**PG 只存日志索引 `execution_log_files`，正文落 server 本地 `/server-data/logs`**（不入 PG） |
| 架构 | **前后端分离**：FastAPI server 提供 API，Next 静态导出 SPA 负责所有页面（由 server 托管静态资源） |
| 构建 | **SPA greenfield 全新构建**，直接对接 `/api/v1`；可分阶段交付页面，不存在与既有 Jinja 共存的过渡栈 |
| 脚手架 | **shadcn/ui CLI**（`shadcn add` 拉取 `sidebar-07` / `login-01` 区块 + 所需基础组件，组件源码落 `apps/web/components/ui`）（原 vue-vben-admin / vue-element-admin） |

## 1. 目标架构（前后端分离）

> **（历史设计；阶段 2.1 起对应：浏览器侧为 Next.js 静态导出 SPA + shadcn/ui + Recharts + react-i18next，状态用 React hooks，路由为 Next App Router 静态导出，产物 `apps/web/out` 由 server 角色托管。）** 下面 ASCII 图中的 `Vue 3 SPA / Element Plus / Pinia/Router / vue-i18n(zh) / Vite 构建产物` 为阶段 0 旧栈描述；除前端框架词外，后端契约（FastAPI `/api/v1/*`、SSE、PostgreSQL 日志索引、`/server-data/logs` 正文、Redis Streams）不变。

```text
        ┌──────────────────────── dopilot-server (Docker) ────────────────────────┐
        │                                                                          │
 浏览器 │   ┌─────────────────┐   HTTP/JSON    ┌──────────────────────────────┐    │
 ──────►│   │  Vue 3 SPA      │ ─────────────► │ FastAPI /api/v1/*            │    │
        │   │  Element Plus   │ ◄───────────── │  - 单管理员 token 认证       │    │
        │   │  Pinia/Router   │                │  - tasks/nodes/executions    │    │
        │   │  vue-i18n(zh)   │   SSE          │  - APScheduler 定时           │    │
        │   └─────────────────┘ ◄──日志流──── │  - PostgreSQL: 业务+日志索引/  │    │
        │     (Vite 构建产物                   │    offset(SQLAlchemy)         │    │
        │      由 server 角色托管)              │  - 本地 /server-data/logs 正文   │    │
        │                                     └──────────────┬───────────────┘    │
        └────────────────────────────────────────────────────┼────────────────────┘
         server XADD 命令 / 消费 agent→Redis 状态&日志事件 │ (Redis Streams)
                                              ┌───────────────▼────────────────┐
                                              │ dopilot-agent (Docker, 可多实例)│
                                              │  scrapyd(阶段1) / 脚本(阶段2)   │
                                              │  消费命令 / XADD 事件&日志       │
                                              │  主动 POST heartbeat            │
                                              └─────────────────────────────────┘
```

> 通信链路已由"server 主动 HTTP pull agent"翻案为"server↔agent 经 Redis Streams、agent 主动消费命令并推事件/日志、agent 主动 POST heartbeat"，详见 `refactor/00-redis-streams-agent-communication.md`。

关键变化：dopilot 后端为全新 **FastAPI** `/api/v1/*` JSON/SSE API（不投产任何 Jinja2 HTML 页面），HTML 由前端 SPA 负责（**历史设计写作「Vue SPA」；阶段 2.1 起为 Next.js 静态导出 SPA**）。scrapydweb 的多节点 fan-out 行为（参考 `multinode.js`，模板引用 79 处）需在 dopilot 前端以全新组件 + `/api/v1` 调用**重新实现**（**历史设计写作「全新 Vue 组件」；阶段 2.1 起为 shadcn/ui + React 组件**）——这是工作量大头（仅作行为参考，不改写既有文件）。

## 2. 分阶段交付里程碑

> 原则：每个里程碑结束时平台均可用；按页面分批交付全新 SPA，后端逐步暴露对应 `/api/v1` 端点。

| 里程碑 | 内容 | 对应阶段 |
|--------|------|---------|
| **M0 骨架** | Vite+Vue3+EP+TS 工程；登录页 + 主布局 + 菜单 + vue-i18n(中文) + axios 封装 + SSE 客户端(EventSource)；FastAPI 新增 `/api/v1` 路由骨架 + 单管理员 opaque token 认证 + CORS；Web 以独立 Vue/Vite 容器运行，反代可选 _（历史设计；阶段 2.1 起对应：Next.js（静态导出）+ shadcn/ui + TS 工程，登录页 + 主布局 + 菜单 + react-i18next(中文) + axios 封装 + SSE 客户端(EventSource)；开发期 `next dev`，生产为同源静态导出由 server 托管，不再有独立 Web 容器）_ | 阶段 0 |
| **M1 只读核心页** | `servers`（节点状态）、`jobs`（任务列表）只读页构建 + 对应 `/api/v1` 端点 | 阶段 0/1 |
| **M2 实时日志** | 日志/`stats` 页构建，落地 server 端 log consumer（消费 agent→Redis 日志事件）+ server→web SSE + `/server-data/logs` 正文 + PG `execution_log_files` 索引（先落地 `LogSource` 抽象，实现为 `RedisLogSource`）；**无 WebSocket** | 阶段 0/1 |
| **M3 操作页** | `schedule`（运行爬虫，含**节点策略 指定/全部/随机 + 推模式立即下发** 的 UI）、`tasks`（定时任务 CRUD） | 阶段 1 |
| **M4 收尾** | `projects`/`deploy`/`settings` 页面构建完成，平台功能闭环 | 阶段 1 |

## 3. 前端工程结构（建议）

> **（历史设计；为阶段 0 的 Vue/Vite 布局。阶段 2.1 起当前布局改为 Next.js：根目录 `apps/web/` 含 `next.config.mjs`（`output: export` + `trailingSlash`）、`components.json`（shadcn/ui）、`package.json`、`tsconfig.json`、`public/`，构建产物落 `apps/web/out/`；源码为 `app/`（Next App Router 页面，任务详情路由 `/tasks/detail?id=<id>`）、`components/`（shadcn/ui 组件 + 业务组件，`components/ui` 为 shadcn 区块源码）、`lib/`（axios 封装、i18n、SSE/`useLogStream` 等共享库）。权威布局见 05-dev-setup-and-known-issues.md §1。）** 下面的 `vite.config.ts / main.ts / App.vue / stores(pinia) / i18n(vue-i18n) / pages` 为旧栈结构，仅作历史参考。

```text
apps/web/                       # 权威布局见 05-dev-setup-and-known-issues.md §1
├── index.html
├── vite.config.ts
├── tsconfig.json
├── package.json
├── public/
└── src/
    ├── main.ts                 # 挂载 app、注册 EP / i18n / pinia / router
    ├── App.vue
    ├── api/                    # axios 封装 + 各模块 API（servers.ts/jobs.ts/...）
    │   ├── client.ts           # baseURL=/api/v1, 拦截器(注入 token / 统一错误)
    │   └── ...
    ├── router/                 # 路由表（与菜单对应）
    ├── stores/                 # pinia（auth、servers、settings...）
    ├── i18n/                   # vue-i18n：locales/zh.ts（默认）、预留 locales/en.ts
    ├── layouts/                # 主布局（侧边菜单 + 顶栏）
    ├── pages/                  # 页面：servers / jobs / schedule / tasks / logs / ...
    ├── components/             # 复用组件（节点选择器、实时日志面板...）
    └── composables/            # useLogStream()（EventSource）等
```

部署形态见 `docs/architecture` 与第 6 节。

## 4. 后端 API 化映射（现状视图 → 建议 API）

> 以下为建议草案，最终以 `docs/architecture/04-views-and-frontend.md` 的真实路由清单为准（workflow 产出后校订）。

| 功能 | 现状（Jinja2 页面/视图） | 建议 API（`/api/v1`） |
|------|------------------------|----------------------|
| 节点状态 | `servers.html` / overview | `GET /servers`、`GET /servers/{id}/status` |
| 任务列表 | `jobs.html` / dashboard | `GET /jobs?node=&project=&state=` |
| 运行爬虫 / 立即推送 | `schedule.html` / operations | `POST /executions/run`（body 含 task_type、payload、候选 nodes、node_strategy；server 侧受控并发下发） |
| 定时任务 | `tasks.html` / system(timer) | `GET/POST/PUT/DELETE /tasks`、`POST /tasks/{id}/pause|resume` |
| 项目/部署 | `projects.html`/`deploy.html` | `GET /projects`、`POST /projects/deploy`(egg) |
| 日志/统计 | `logs_items.html`/`stats.html` | `GET /executions/{id}/logs/stream`（SSE 实时）、`GET /executions/{id}/logs`（历史，按 offset 从本地文件读） |
| 设置 | `settings.html` | `GET/PUT /settings` |
| 认证 | HTTP Basic Auth | `POST /auth/login` → token；后续请求带 `Authorization` |

## 5. 认证改造（Web 与 Agent 分离）

> 现状是 scrapydweb 全局 HTTP Basic Auth（`ENABLE_AUTH`/`USERNAME`/`PASSWORD`）。dopilot 不继承该实现，改为两套身份：Web 管理员身份与 Agent 机器身份。

### 5.1 Web → Server：单管理员登录

- SPA 登录页调用 `POST /api/v1/auth/login`，提交 `admin_username/admin_password`。
- FastAPI server 校验后返回服务端签发的 **opaque `access_token`**。token 本身不承载业务 claims；server 端按 token 查验有效性/过期时间。
- 前端 axios 拦截器统一注入 `Authorization: Bearer <access_token>`；401 跳登录页。
- 自动化调用可直接使用静态 `admin_api_token`（env `DOPILOT_ADMIN_API_TOKEN`，非空须 >= 16 字符）作为 `Authorization: Bearer <token>`，无需登录换取 opaque token。
- 单用户唯一管理员，无 RBAC、多租户、用户管理。

配置示例：

```toml
[auth]
admin_username = "admin"
admin_password = "change-me"
# 登录 access token / SSE stream token 的内部 HMAC 签名密钥；仅 TOML 配置，无 env 覆盖。
token_secret = "shLv5qNwC3aViZQYr08x3yfaY6yGZACB6ujydXiVaGnb7OdOflc91xVLyXBoeRDL"
# 静态 admin API token；可直接作 Bearer 调用 admin API。仅管理员、仅 server 端，不充当机器 token。
admin_api_token = "change-me-admin-api-token"
access_token_ttl_minutes = 720
```

### 5.2 Server → Web SSE：短期 stream token

浏览器 `EventSource` 不适合携带自定义 `Authorization` header。第一版采用短期日志流 token：

```text
POST /api/v1/executions/{id}/logs/stream-token
Authorization: Bearer <access_token>

-> { "stream_token": "...", "expires_in": 60 }

GET /api/v1/executions/{id}/logs/stream?token=...
```

约束：`stream_token` 只允许订阅指定 execution 的日志，TTL 建议 60 秒，**仅校验建连**（建连后不再逐条校验）；配合 `id:<seq>` + `Last-Event-ID` 断点续传；服务端日志与可选反向代理日志避免记录完整 query string；若用户自行接 nginx，SSE 路径需 `proxy_buffering off`。Web 管理员认证为 **fail-closed**（阶段 2.2）：默认要求凭据，仅当显式 `DOPILOT_AUTH_DISABLED=true` 时才以匿名管理员直连；管理员认证开启时才签发 `stream_token`，被显式关闭时直连。

### 5.3 Agent ↔ Server：机器 token（agent 主动消费/上报）

Agent 不使用管理员账号密码。破坏性重构后 agent 是**主动方**：经 Redis Streams consumer group **主动消费** server 投递的命令（run/stop/cleanup_logs），**主动 XADD** 状态事件与日志事件，并**主动 POST heartbeat** 到 server（需配置 `server_url`）。详见 `refactor/00-redis-streams-agent-communication.md`。

机器鉴权（阶段 2.2.3）用**单一** `agent_token`；阶段 2.2.7 后 agent 为纯出站，令牌认证 agent→server 调用：

- **agent → server（heartbeat API）**：agent 携带 `agent_token` 调 `POST /api/v1/agents/{agent_id}/heartbeat`。
- **agent → server（artifact/wheel fetch）**：agent 携带 `agent_token` 拉取运行所需 artifact。
- **agent ↔ Redis**：Redis 启用 AUTH/ACL，agent/server 各自以 Redis 凭据连接消息总线。

```toml
[agent]
server_url = "http://server:5000"
heartbeat_interval_seconds = 10
agent_token = "change-me-agent-token"   # 与 server [agents].agent_token 同值

[redis]
url = "redis://redis:6379/0"
```

`agent_token` 是唯一机器令牌，必须与 server `[agents].agent_token` **同值**；agent 仍**不直连 PostgreSQL**（经 Redis 与 server 通信）。`admin_api_token`（`DOPILOT_ADMIN_API_TOKEN`）**仅管理员、仅 server 端**，绝不下发给 agent、也不充当机器令牌；旧的拆分令牌（`DOPILOT_AGENT_SHARED_TOKEN` / `DOPILOT_SERVER_SHARED_TOKEN`）已删除、无效果。**第一版完全不用 WebSocket**：日志正文由 server 端 log consumer 消费 agent→Redis 日志事件后写入，offset 权威仍在 server（PG `last_pulled_offset`）。机器认证在配置层仍是 config-present-or-off（`agent_token` 非空才启用，非空须 >=16 字符），但阶段 2.2.4 的 server 运行时/CLI 会在未配置时生成并持久化唯一机器令牌（`<server.data_dir>/secrets/agent-token`），因此 server-only 部署最终会以生成令牌开启机器认证；Web 管理员认证则是 fail-closed（默认要求凭据，仅 `DOPILOT_AUTH_DISABLED=true` 时匿名）。Token 认证不是传输加密，跨主机加密仍需 TLS/VPN/私有网络。

## 6. 实时日志（agent → Redis 推送 + server 消费落盘 + SSE）

> 以 `docs/dopilot/03-gap-realtime-logs.md` 与 `refactor/00-redis-streams-agent-communication.md` 为准：日志链路分两段。**agent → server 由 agent 主动 XADD 日志事件到 Redis log stream（`dopilot:server:logs`），server 端 log consumer 消费后落盘**（不再 HTTP pull agent tail，不再轮询 agent status 做结束检测）；第一版完全不用 WebSocket；**server → web 使用 SSE**，用于浏览器单向查看实时日志。

- 现状靠 logparser 解析日志文件 + 页面硬刷新轮询（见 `docs/architecture/05-scrapyd-cluster-io.md` 与 `docs/dopilot/03-gap-realtime-logs.md`）。
- 方案：后端先落地 **`LogSource` 抽象**（缝保留，实现由 `AgentTailLogSource` 换为 `RedisLogSource`）；agent 端 log publisher tail 本地日志、按字节 offset 主动 XADD（base64 字节，带 `offset`/`size_bytes`/`eof`）到 Redis；server 端 log consumer 串行消费同一 attempt 的日志事件，把正文写入本地文件 `/server-data/logs/YYYY/MM/{execution_id}/{attempt_id}.{stream}.log`，并更新 PG `execution_log_files`（主键 `execution_id, attempt_id, stream`，只存索引与 `last_pulled_offset`，不存正文），同时通过 FastAPI SSE 端点推给前端。offset 权威在 server；日志 RPO≠0（server 长停或 Redis 裁剪致 partial），完整性由新增 `log_integrity` 列与业务状态分离表达。
- 结束检测 = server 消费 agent 主动推的 terminal 状态事件（`dopilot:server:agent-events`）后进入 bounded drain 窗口；drain timeout / `eof` 信号到达后转 `complete`/`partial`（不再轮询 agent status）。
- 前端 `useLogStream()`（**历史设计写作 `composables/useLogStream()`；阶段 2.1 起为 `lib/` 下的 React hook**）用浏览器原生 `EventSource` 订阅 `GET /api/v1/executions/{id}/logs/stream`，增量渲染；历史日志由 `GET /api/v1/executions/{id}/logs` 按 offset 从 server 本地文件读取。
- stream 支持 `log` / `stdout` / `stderr` / `system`（scrapy 只产 `log`）。
- 需兼容三类执行器日志源（scrapyd 日志文件 / 脚本 stdout / 容器 logs）——由 `LogSource` 统一成同一日志流协议。

## 7. i18n（默认中文）

- 前端 i18n（**历史设计写作 `vue-i18n`；阶段 2.1 起为 `react-i18next`**）：业务译文文件统一为 `zh`（默认）与 `en`（预留，旧栈写作 `i18n/locales/zh.ts` / `en.ts`，当前置于 `lib/` 下）；旧栈下 Element Plus 用其自带 `zh-cn` locale，阶段 2.1 起改用 shadcn/ui（无内置 locale 包，文案统一走 react-i18next）。
- 文案集中在前端，**不再有 Jinja2 模板 + 内联 JS 双处文案**的问题（这是分离的额外收益）。
- 后端 API 返回数据型内容（不含展示文案），错误码由前端映射文案。
- 与后端 i18n 的协作见 `docs/dopilot/04-gap-i18n.md`。

## 8. 部署（契合 server/agent + Docker）

- **Web UI 托管**：第一版本地测试镜像会把 `apps/web` 构建产物（**历史设计为 Vite 产物；阶段 2.1 起为 Next.js 静态导出产物 `apps/web/out/`**）copy 进统一应用镜像；server 角色直接托管 SPA（**同源静态导出，无 `next start`/Node 生产运行时/独立 Web 容器**），同时保留 `/api/v1` 与 SSE。开发期热更见下。
- 开发期（**历史设计：Vite dev server + `proxy` 转发 `/api`；阶段 2.1 起：`next dev` + 环境变量 `NEXT_PUBLIC_API_BASE` 指向独立运行的 FastAPI server，前后端分别热更**），含 SSE 流；生产为同源静态导出，不经 Vite/Next 代理。
- agent 角色只跑执行器（scrapyd/脚本/容器管理），不托管前端。

## 9. 风险与开放问题

1. **多节点 fan-out 行为复杂**：参考 scrapydweb `multinode.js` 的 79 处引用与多节点 fan-out 逻辑，全新实现成本高，是工作量最大点。建议在 M1 就把"节点选择器 + 多节点结果聚合"抽成可复用组件（**历史设计写作「Vue 组件」；阶段 2.1 起为 shadcn/ui + React 组件，置于 `components/`**）。
2. **分阶段交付期入口管理**：未完成页面应有占位/禁用入口，避免暴露未实现功能；无需双栈路由分流（全程单一 SPA + `/api/v1`）。
3. **SSE × 部署**：仅 **server → web SSE** 为长连接（无 agent WebSocket）；生产用 ASGI server（uvicorn workers=1）承载，配单 APScheduler。若用户自行加 nginx 等反代，SSE 路径必须关闭 buffering；dopilot 镜像自身不内置 nginx。**v1 单实例硬约束，不支持多副本/多 worker、未来也不做**。收窄口径：**不引入 Redis 做多副本 HA / fan-out / 分布式锁，server→web SSE fan-out 仍在单进程内存完成**；但**显式允许 Redis 作单实例 server↔agent 通信总线**（命令/事件/日志 Redis Streams，见 `refactor/00-redis-streams-agent-communication.md`），docker compose 新增单 Redis 服务并启用 AUTH/AOF。
4. **已定部署/认证口径**：~~Web 独立容器运行 Vue/Vite~~（**历史设计；阶段 2.1 起：生产为同源 Next.js 静态导出由 dopilot-server 托管，无独立 Web 容器；开发期 `next dev` + `NEXT_PUBLIC_API_BASE`**）；反代是用户可选项；Web access token 使用服务端签发的 opaque token。
