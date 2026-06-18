# dopilot —— 前端整体构建方案（Vue 3 + Element Plus）

> 决策来源：用户 2026-06-17 拍板。归属**阶段 0（平台基座）**。
> 配套现状参考：`docs/architecture/04-views-and-frontend.md`（scrapydweb 前端现状）。

> **【scrapydweb 参考边界】** scrapydweb 仅作**功能层/行为参考**与**测试 oracle**；其代码写法、目录结构、模块划分、命名、依赖、配置形态**一律不得作为 dopilot 的设计依据**。dopilot 为 greenfield、按 `apps/`+`packages/` 自有领域 structure-first 设计（权威布局见 `05-dev-setup-and-known-issues.md` §1），**不对 scrapydweb 做改名/git mv**。详见 `00-requirements.md` 决策表。

## 0. 决策摘要

| 项 | 选型 |
|----|------|
| 框架 | **Vue 3**（Composition API）+ TypeScript |
| 构建 | **Vite** |
| UI 库 | **Element Plus**（内建完善中文 i18n） |
| 路由/状态 | Vue Router + Pinia |
| i18n | **vue-i18n**，默认中文，预留多语言 |
| 请求 | axios（统一封装 `/api/v1`） |
| 实时 | **agent 侧无主动连接**；**server 按需 HTTP pull agent tail API**（reconcile loop）；**server → web 使用 SSE**（浏览器单向日志流）；详见 `03-gap-realtime-logs.md` |
| 后端 | **FastAPI + Pydantic + ASGI**，提供 `/api/v1/*` JSON/SSE API |
| 数据库 | **PostgreSQL 唯一数据库**；SQLAlchemy + 裸 Alembic；**PG 只存日志索引 `execution_log_files`，正文落 server 本地 `/server-data/logs`**（不入 PG） |
| 架构 | **前后端分离**：FastAPI server 提供 API，Vue SPA 负责所有页面 |
| 构建 | **SPA greenfield 全新构建**，直接对接 `/api/v1`；可分阶段交付页面，不存在与既有 Jinja 共存的过渡栈 |
| 脚手架 | 可基于 `vue-vben-admin` / `vue-element-admin` 起步 |

## 1. 目标架构（前后端分离）

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
        │      独立 Web 容器运行，反代可选)          │  - 本地 /server-data/logs 正文   │    │
        │                                     └──────────────┬───────────────┘    │
        └────────────────────────────────────────────────────┼────────────────────┘
                              server→agent HTTP pull(tail/status) │
                                              ┌───────────────▼────────────────┐
                                              │ dopilot-agent (Docker, 可多实例)│
                                              │  scrapyd(阶段1) / 脚本(阶段2)   │
                                              └─────────────────────────────────┘
```

关键变化：dopilot 后端为全新 **FastAPI** `/api/v1/*` JSON/SSE API（不投产任何 Jinja2 HTML 页面），HTML 由 Vue SPA 负责。scrapydweb 的多节点 fan-out 行为（参考 `multinode.js`，模板引用 79 处）需在 dopilot 前端以全新 Vue 组件 + `/api/v1` 调用**重新实现**——这是工作量大头（仅作行为参考，不改写既有文件）。

## 2. 分阶段交付里程碑

> 原则：每个里程碑结束时平台均可用；按页面分批交付全新 SPA，后端逐步暴露对应 `/api/v1` 端点。

| 里程碑 | 内容 | 对应阶段 |
|--------|------|---------|
| **M0 骨架** | Vite+Vue3+EP+TS 工程；登录页 + 主布局 + 菜单 + vue-i18n(中文) + axios 封装 + SSE 客户端(EventSource)；FastAPI 新增 `/api/v1` 路由骨架 + 单管理员 opaque token 认证 + CORS；Web 以独立 Vue/Vite 容器运行，反代可选 | 阶段 0 |
| **M1 只读核心页** | `servers`（节点状态）、`jobs`（任务列表）只读页构建 + 对应 `/api/v1` 端点 | 阶段 0/1 |
| **M2 实时日志** | 日志/`stats` 页构建，落地 server pull（reconcile loop）+ server→web SSE + `/server-data/logs` 正文 + PG `execution_log_files` 索引（先落地 `LogSource` 抽象）；**无 WebSocket** | 阶段 0/1 |
| **M3 操作页** | `schedule`（运行爬虫，含**节点策略 指定/全部/随机 + 推模式立即下发** 的 UI）、`tasks`（定时任务 CRUD） | 阶段 1 |
| **M4 收尾** | `projects`/`deploy`/`settings` 页面构建完成，平台功能闭环 | 阶段 1 |

## 3. 前端工程结构（建议）

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
- 单用户唯一管理员，无 RBAC、多租户、用户管理。

配置示例：

```toml
[auth]
admin_username = "admin"
admin_password = "change-me"
token_secret = "change-me"
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

约束：`stream_token` 只允许订阅指定 execution 的日志，TTL 建议 60 秒，**仅校验建连**（建连后不再逐条校验）；配合 `id:<seq>` + `Last-Event-ID` 断点续传；服务端日志与可选反向代理日志避免记录完整 query string；若用户自行接 nginx，SSE 路径需 `proxy_buffering off`。认证为 config-present-or-off（管理员认证开时才签发 `stream_token`，关闭时直连）。

### 5.3 Server → Agent：机器 token（agent 被动响应）

Agent 不使用管理员账号密码，**也不主动回连 server**（无需 `DOPILOT_SERVER_URL`）。Agent 只**被动响应** server 发起的 HTTP pull（tail/status/cleanup/health），用独立 `shared_token` 校验来访请求；后续可升级 mTLS。

```toml
[agent_auth]
shared_token = "change-me-agent-token"
```

Server 调用 agent 的 tail/status/cleanup/health 端点时带机器身份；配置键统一为 `shared_token`，agent 校验：

```http
Authorization: Bearer <shared_token>
```

`shared_token` 只用于校验 server→agent 的 pull 请求，agent 不主动上报、不持有管理员 API 凭据。**第一版完全不用 WebSocket**：日志正文由 server reconcile loop 主动 HTTP pull agent tail API 取回，offset 权威在 server（PG `last_pulled_offset`）。认证为 config-present-or-off（配置存在则启用，缺失则关闭）。

## 6. 实时日志（server pull + SSE）

> 以 `docs/dopilot/03-gap-realtime-logs.md` 为准：日志链路分两段。**server → agent 由 server 主动 HTTP pull**（reconcile loop 调 agent tail/status API），第一版完全不用 WebSocket、agent 不主动推 chunk；**server → web 使用 SSE**，用于浏览器单向查看实时日志。

- 现状靠 logparser 解析日志文件 + 页面硬刷新轮询（见 `docs/architecture/05-scrapyd-cluster-io.md` 与 `docs/dopilot/03-gap-realtime-logs.md`）。
- 方案：后端先落地 **`LogSource` 抽象**；agent 提供 HTTP tail/status/cleanup API 被动响应；server 的 reconcile loop 主动 pull agent tail（active execution 后台 30s 低频 drain、开 Web 日志窗口升 1s、结束 final drain），把正文写入本地文件 `/server-data/logs/YYYY/MM/{execution_id}/{attempt_id}.{stream}.log`，并更新 PG `execution_log_files`（主键 `execution_id, attempt_id, stream`，只存索引与 `last_pulled_offset`，不存正文），同时通过 FastAPI SSE 端点推给前端。offset 权威在 server。
- 结束检测 = server 轮询 agent status；tail 终止 = finished + EOF 稳定 3s / hard timeout 30s。
- 前端 `composables/useLogStream()` 用浏览器原生 `EventSource` 订阅 `GET /api/v1/executions/{id}/logs/stream`，增量渲染；历史日志由 `GET /api/v1/executions/{id}/logs` 按 offset 从 server 本地文件读取。
- stream 支持 `log` / `stdout` / `stderr` / `system`（scrapy 只产 `log`）。
- 需兼容三类执行器日志源（scrapyd 日志文件 / 脚本 stdout / 容器 logs）——由 `LogSource` 统一成同一日志流协议。

## 7. i18n（默认中文）

- 前端 `vue-i18n`：业务译文文件统一为 `i18n/locales/zh.ts`（默认）与 `i18n/locales/en.ts`（预留）；Element Plus 用其自带 `zh-cn` locale。
- 文案集中在前端，**不再有 Jinja2 模板 + 内联 JS 双处文案**的问题（这是分离的额外收益）。
- 后端 API 返回数据型内容（不含展示文案），错误码由前端映射文案。
- 与后端 i18n 的协作见 `docs/dopilot/04-gap-i18n.md`。

## 8. 部署（契合 server/agent + Docker）

- **Web 容器**：第一版不把 SPA copy 进 server 镜像，也不内置 nginx。`apps/web` 按 Vue/Vite 常规方式构建并由独立 Web 容器运行；server 容器只提供 `/api/v1` 与 SSE。Web 容器的生产托管方式与反向代理属用户部署层，本文不规定。因 Web 与 server 默认不同源，server 需开 CORS 放行 Web origin（见 M0）。
- 开发期：Vite dev server + `proxy` 转发 `/api`（含 SSE 流）到 FastAPI，前后端分别热更。
- agent 镜像不含前端，只跑执行器（scrapyd/脚本/容器管理）。

## 9. 风险与开放问题

1. **多节点 fan-out 行为复杂**：参考 scrapydweb `multinode.js` 的 79 处引用与多节点 fan-out 逻辑，全新实现成本高，是工作量最大点。建议在 M1 就把"节点选择器 + 多节点结果聚合"抽成可复用 Vue 组件。
2. **分阶段交付期入口管理**：未完成页面应有占位/禁用入口，避免暴露未实现功能；无需双栈路由分流（全程单一 SPA + `/api/v1`）。
3. **SSE × 部署**：仅 **server → web SSE** 为长连接（无 agent WebSocket）；生产用 ASGI server（uvicorn workers=1）承载，配单 APScheduler。若用户自行加 nginx 等反代，SSE 路径必须关闭 buffering；dopilot 镜像自身不内置 nginx。**v1 单实例硬约束，不支持多副本/多 worker、未来也不做**，不引入 Redis/NATS/PG LISTEN-NOTIFY。
4. **已定部署/认证口径**：Web 独立容器运行 Vue/Vite；反代是用户可选项；Web access token 使用服务端签发的 opaque token。
