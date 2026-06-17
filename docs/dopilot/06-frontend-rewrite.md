# dopilot —— 前端整体重构方案（Vue 3 + Element Plus）

> 决策来源：用户 2026-06-17 拍板。归属**阶段 0（平台基座）**。
> 配套现状参考：`docs/architecture/04-views-and-frontend.md`（scrapydweb 前端现状）。

## 0. 决策摘要

| 项 | 选型 |
|----|------|
| 框架 | **Vue 3**（Composition API）+ TypeScript |
| 构建 | **Vite** |
| UI 库 | **Element Plus**（内建完善中文 i18n） |
| 路由/状态 | Vue Router + Pinia |
| i18n | **vue-i18n**，默认中文，预留多语言 |
| 请求 | axios（统一封装 `/api/v1`） |
| 实时 | **SSE**（单向日志流；详见 `03-gap-realtime-logs.md`） |
| 架构 | **前后端分离**：Flask 收敛为 `/api/v1/*` JSON API |
| 迁移 | **渐进式 strangler**：搭 SPA 骨架后按页迁移，新旧共存 |
| 脚手架 | 可基于 `vue-vben-admin` / `vue-element-admin` 起步 |

## 1. 目标架构（前后端分离）

```
        ┌──────────────────────── dopilot-server (Docker) ────────────────────────┐
        │                                                                          │
 浏览器 │   ┌─────────────────┐   HTTP/JSON    ┌──────────────────────────────┐    │
 ──────►│   │  Vue 3 SPA      │ ─────────────► │ Flask  /api/v1/*  (JSON API) │    │
        │   │  Element Plus   │ ◄───────────── │  - 认证(单管理员 token)       │    │
        │   │  Pinia/Router   │                │  - servers/jobs/schedule/... │    │
        │   │  vue-i18n(zh)   │   SSE          │  - APScheduler 定时           │    │
        │   └─────────────────┘ ◄──SSE 流──── │  - SSE 实时日志(单向)         │    │
        │     (Vite 构建产物                   │  - SQLAlchemy DB             │    │
        │      由 Flask/nginx 托管)            └──────────────┬───────────────┘    │
        └────────────────────────────────────────────────────┼────────────────────┘
                                                    push/调用 │
                                              ┌───────────────▼────────────────┐
                                              │ dopilot-agent (Docker, 可多实例)│
                                              │  scrapyd(阶段1) / 脚本(阶段2)   │
                                              └─────────────────────────────────┘
```

关键变化：Flask 不再返回 Jinja2 HTML 页面，而是返回 JSON；HTML 由 Vue SPA 负责。`multinode.js`（现状多节点核心逻辑，模板引用 79 处）将被重写为前端组件 + API 调用——**这是重构工作量大头**。

## 2. 渐进式 strangler 里程碑

> 原则：任何里程碑结束时平台都可用；旧 Jinja2 页与新 SPA 在过渡期共存，逐页替换。

| 里程碑 | 内容 | 对应阶段 |
|--------|------|---------|
| **M0 骨架** | Vite+Vue3+EP+TS 工程；登录页 + 主布局 + 菜单 + vue-i18n(中文) + axios 封装 + SSE 客户端(EventSource)；Flask 新增 `/api/v1` 蓝图骨架 + 单管理员 token 认证 + CORS；确定 SPA 托管方式 | 阶段 0 |
| **M1 只读核心页** | `servers`（节点状态）、`jobs`（任务列表）迁移 + 对应 API 化 | 阶段 0/1 |
| **M2 实时日志** | 日志/`stats` 页迁移，落地 SSE 实时日志流（先落地 `LogSource` 抽象） | 阶段 0/1 |
| **M3 操作页** | `schedule`（运行爬虫，含**节点策略 指定/全部/随机 + 推模式立即下发** 的 UI）、`tasks`（定时任务 CRUD） | 阶段 1 |
| **M4 收尾** | `projects`/`deploy`/`settings` 迁移；下线旧 Jinja2 模板、移除 `multinode.js` 等遗留 | 阶段 1 |

## 3. 前端工程结构（建议）

```
frontend/
├── index.html
├── vite.config.ts
├── tsconfig.json
├── package.json
└── src/
    ├── main.ts                 # 挂载 app、注册 EP / i18n / pinia / router
    ├── App.vue
    ├── api/                    # axios 封装 + 各模块 API（servers.ts/jobs.ts/...）
    │   ├── client.ts           # baseURL=/api/v1, 拦截器(注入 token / 统一错误)
    │   └── ...
    ├── router/                 # 路由表（与菜单对应）
    ├── stores/                 # pinia（auth、servers、settings...）
    ├── locales/                # vue-i18n：zh-CN.ts（默认）、预留 en-US.ts
    ├── layouts/                # 主布局（侧边菜单 + 顶栏）
    ├── views/                  # 页面：servers / jobs / schedule / tasks / logs / ...
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
| 运行爬虫 | `schedule.html` / operations | `POST /run`（body 含 project/spider/**节点策略**/**push**/args） |
| 定时任务 | `tasks.html` / system(timer) | `GET/POST/PUT/DELETE /tasks`、`POST /tasks/{id}/pause|resume` |
| 项目/部署 | `projects.html`/`deploy.html` | `GET /projects`、`POST /projects/deploy`(egg) |
| 日志/统计 | `logs_items.html`/`stats.html` | `GET /jobs/{id}/log`（历史）、`GET /jobs/{id}/log/stream`（SSE 实时） |
| 设置 | `settings.html` | `GET/PUT /settings` |
| 认证 | HTTP Basic Auth | `POST /auth/login` → token；后续请求带 `Authorization` |

## 5. 认证改造（单用户唯一管理员）

- 现状是全局 HTTP Basic Auth（`ENABLE_AUTH`/`USERNAME`/`PASSWORD`）。
- SPA 化后改为 **token 登录**：`POST /api/v1/auth/login` 校验单管理员账号 → 返回 token（简单 JWT 或服务端签发的 session token 即可，单用户无需复杂 RBAC）。
- 前端 axios 拦截器统一注入 token；401 跳登录页。
- 详细现状见 `docs/architecture/06-auth-and-utils.md`。

## 6. 实时日志（SSE）

> 以 `docs/dopilot/03-gap-realtime-logs.md` 经代码核实的结论为准：日志是**单向流**（server→浏览器），采用 **SSE** 而非 WebSocket——纯 WSGI 即可运行、与现有 `LogView` 同构、无需额外设施。WebSocket 仅在未来需要双向交互（如在线下发控制指令）时再考虑。

- 现状靠 logparser 解析日志文件 + 页面硬刷新轮询（见 `docs/architecture/05-scrapyd-cluster-io.md` 与 `docs/dopilot/03-gap-realtime-logs.md`）。
- 方案：后端先落地 **`LogSource` 抽象**，再加 SSE 端点 `Response(stream_with_context(gen), mimetype='text/event-stream')`；前端 `composables/useLogStream()` 用 `EventSource` 订阅 `GET /api/v1/jobs/{id}/log/stream`，增量渲染。
- 需兼容三类执行器日志源（scrapyd 日志文件 / 脚本 stdout / 容器 logs）——由 `LogSource` 统一成同一日志流协议。

## 7. i18n（默认中文）

- 前端 `vue-i18n`：`locales/zh-CN.ts` 为默认，预留 `en-US.ts`；Element Plus 用其自带 `zh-cn` locale。
- 文案集中在前端，**不再有 Jinja2 模板 + 内联 JS 双处文案**的问题（这是分离的额外收益）。
- 后端 API 返回数据型内容（不含展示文案），错误码由前端映射文案。
- 与后端 i18n 的协作见 `docs/dopilot/04-gap-i18n.md`。

## 8. 部署（契合 server/agent + Docker）

- **单镜像最简**：多阶段 Docker build——前端 `vite build` 产物 COPY 进 server 镜像，由 Flask（`send_from_directory`）或镜像内 nginx 托管静态资源，API 同源（免 CORS）。
- 开发期：Vite dev server + `proxy` 转发 `/api`（含 SSE 流）到 Flask，前后端分别热更。
- agent 镜像不含前端，只跑执行器（scrapyd/脚本/容器管理）。

## 9. 风险与开放问题

1. **`multinode.js` 重写成本高**：79 处引用、多节点 fan-out 逻辑深，是迁移最大难点。建议在 M1 就把"节点选择器 + 多节点结果聚合"抽成可复用 Vue 组件。
2. **过渡期双栈并存**：strangler 期间 Jinja2 与 SPA 同时在线，需规划路由分流（如新页挂 `/ui/*`，旧页保留原路径），并明确每页"已迁/未迁"状态。
3. **SSE × 部署**：SSE 长连接会占用一个 worker/线程，需确认 WSGI 服务器并发模型（gevent/线程池）；若 server 未来多副本，需考虑粘性会话（当前单 server 可暂不处理）。
4. **待确认**：① SPA 托管走 Flask 内置还是镜像内 nginx？② 是否引入现成后台脚手架（vben/element-admin）还是从空白 Vite 模板起？③ token 用 JWT 还是服务端 session token？

> 上述开放问题待 workflow 现状文档产出、且进入 M0 实作前再与用户敲定。
