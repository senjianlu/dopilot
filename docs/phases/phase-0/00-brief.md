# 00 · 阶段 0 实现任务书（交给 Claude 编码）

> **【scrapydweb 参考边界】** scrapydweb 仅作**功能层/行为参考**与**测试 oracle**；其代码写法、目录结构、模块划分、命名、依赖、配置形态**一律不得作为 dopilot 的设计依据**。dopilot 为 greenfield、按 `apps/`+`packages/` 自有领域 structure-first 设计（权威布局见 `05-dev-setup-and-known-issues.md` §1），**不对 scrapydweb 做改名/git mv**。
>
> 本文是阶段 0 的工程执行任务书。开发与初测交由 Claude 完成；Codex 拿到代码后负责 review、复跑关键测试、指出问题并给出修复建议。阶段 0 只建立可运行、可测试、可扩展的基座，不实现 Scrapy 真实执行闭环。

---

## 0. 阶段 0 目标

阶段 0 交付一个最小可运行的 dopilot monorepo 骨架：

- `apps/server`：FastAPI API server，可加载配置、连接 PostgreSQL、运行 Alembic、提供健康检查和认证骨架。
- `apps/agent`：agent HTTP 服务骨架，可加载配置、暴露 `/health`，返回稳定 `agent_id` 与能力声明。
- `apps/web`：Vue 3 + Element Plus + Vite + TypeScript SPA 骨架，含登录页、主布局、中文 i18n、API client。
- `packages/protocol`：server↔agent 共享协议 schema，至少覆盖 health、错误响应、基础 execution/log 标识类型。
- `deploy/docker`：server/agent Dockerfile 与后端执行闭环 compose（server + agent + PostgreSQL）。
- `configs`：server/agent 示例 toml。
- `scripts` 或 Makefile：统一开发、测试、迁移、启动命令。
- 测试基线：server/agent pytest，web vitest/build，protocol schema 测试。

阶段 0 的验收标准是：新 checkout 后能安装依赖、启动 PostgreSQL、运行迁移、启动 server/agent/web，并通过基础测试。

---

## 1. 明确不做

阶段 0 不实现以下内容：

- 不上传 egg，不调用 scrapyd `/addversion.json` 或 `/schedule.json`。
- 不启动本机 scrapyd 子进程。
- 不实现 `ScrapydExecutor` 的真实下发，只允许有接口/占位和明确的 `501 Not Implemented`。
- 不实现 APScheduler 定时执行，只允许建立 scheduler 包和配置骨架。
- 不实现实时日志 pull loop、SSE 正式流、`execution_log_files` 的完整状态机；可以保留模型/路由占位。
- 不实现 Python 脚本执行器、Docker 长连接执行器。
- 不引入 WebSocket、Redis、NATS、Celery、多 server 副本、多用户/RBAC。
- 不 import `reference/scrapydweb`，不把 `reference/` 放进 Docker build context。

---

## 2. 目标目录

Claude 应按以下结构创建文件。若因工具链需要微调，必须保持领域边界不变。

```text
dopilot/
├── apps/
│   ├── server/
│   │   ├── dopilot_server/
│   │   │   ├── api/v1/
│   │   │   │   ├── auth.py
│   │   │   │   ├── health.py
│   │   │   │   ├── nodes.py
│   │   │   │   └── router.py
│   │   │   ├── auth/
│   │   │   ├── config/
│   │   │   ├── db/
│   │   │   ├── models/
│   │   │   ├── nodes/
│   │   │   ├── logs/
│   │   │   ├── executors/
│   │   │   ├── scheduler/
│   │   │   └── app.py
│   │   ├── migrations/
│   │   ├── tests/
│   │   └── pyproject.toml
│   ├── agent/
│   │   ├── dopilot_agent/
│   │   │   ├── api/
│   │   │   ├── config/
│   │   │   ├── logs/
│   │   │   ├── runners/
│   │   │   └── main.py
│   │   ├── tests/
│   │   └── pyproject.toml
│   └── web/
│       ├── src/{api,components,layouts,pages,router,stores,i18n}/
│       ├── package.json
│       └── vite.config.ts
├── packages/
│   └── protocol/
│       ├── dopilot_protocol/
│       ├── tests/
│       └── pyproject.toml
├── configs/
│   ├── server.example.toml
│   └── agent.example.toml
├── deploy/docker/
│   ├── Dockerfile.server
│   ├── Dockerfile.agent
│   └── docker-compose.yml
├── scripts/
├── .dockerignore
├── pyproject.toml
└── pnpm-workspace.yaml
```

---

## 3. Server 要求

### 3.1 技术栈

- Python 3.12。
- FastAPI + Pydantic。
- Uvicorn，生产约束 `workers=1`。
- SQLAlchemy 2.x。
- Alembic 裸迁移，不使用 Flask-Migrate。
- PostgreSQL driver 使用 `psycopg` 或 `asyncpg`，选一种并保持全项目一致。
- APScheduler 依赖若在阶段 0 引入，必须使用 `APScheduler>=3.10,<4`，不能使用 3.6.0。

### 3.2 配置

配置从 `DOPILOT_CONFIG` 指向的 toml 读取。环境变量可覆盖数据库 URL。

`configs/server.example.toml` 至少包含：

```toml
[server]
host = "0.0.0.0"
port = 5000
public_url = "http://localhost:5000"

[database]
url = "postgresql+psycopg://dopilot:dopilot@localhost:5432/dopilot"

[auth]
admin_username = "admin"
admin_password = "change-me"
token_secret = "change-me"
access_token_ttl_minutes = 720
stream_token_ttl_seconds = 60

[agent_auth]
shared_token = "change-me-agent-token"

[nodes]
agents = ["localhost:6800"]

[scheduler]
enabled = true
timezone = "Asia/Shanghai"

[logs]
root_dir = "/server-data/logs"
background_drain_interval_seconds = 30
realtime_drain_interval_seconds = 1
max_tail_bytes_per_pull = 262144
eof_stable_seconds = 3
final_drain_hard_timeout_seconds = 30
retention_days = 30

[i18n]
locale = "zh"
timezone = "Asia/Shanghai"
```

### 3.3 API

阶段 0 必须提供：

| Endpoint | 行为 |
|---|---|
| `GET /api/v1/health` | 返回 server 状态、版本、数据库连通性 |
| `POST /api/v1/auth/login` | config-present-or-off；启用时校验单管理员并返回 opaque access token |
| `GET /api/v1/auth/me` | 返回当前管理员状态；认证关闭时返回 anonymous admin/off 状态 |
| `GET /api/v1/nodes` | 返回配置里的初始 agent 地址以及已知 health 状态；可为空 |
| `POST /api/v1/nodes/refresh` | 主动轮询 `[nodes].agents` 的 `/health`，成功则 upsert `nodes` 表 |
| `POST /api/v1/executions/run` | 阶段 0 返回 `501`，响应体说明阶段 1 实现 |
| `GET /api/v1/executions/{id}/logs/stream` | 阶段 0 返回 `501` 或可连接的空 SSE 占位，二选一但需测试覆盖 |

错误响应统一结构：

```json
{
  "code": "error.code",
  "message_key": "errors.someKey",
  "detail": {}
}
```

### 3.4 数据库与模型

阶段 0 至少建立这些模型与迁移：

- `nodes`
  - `id` UUID 或 bigint 主键。
  - `agent_id` 唯一，可为空直到 health 返回。
  - `endpoint` 唯一，指向 agent API 地址。
  - `status`: `unknown` / `healthy` / `unhealthy`。
  - `capabilities` JSONB。
  - `last_seen_at`。
  - `created_at` / `updated_at`。
- `auth_tokens`
  - opaque token 的 hash、过期时间、撤销标记。
- 可选占位：`executions`、`execution_attempts`、`execution_log_files`。若建表，字段必须与 `03-gap-realtime-logs.md` 兼容；若不建，必须在 README/注释中说明阶段 1/3 补齐。

禁止用 `Base.metadata.create_all()` 代替 Alembic 正式迁移。测试中可以使用临时数据库或事务 fixture。

---

## 4. Agent 要求

### 4.1 技术栈

- Python 3.12。
- HTTP 服务可以用 FastAPI，也可以用轻量 ASGI 框架；但 agent 不应依赖 server 的 DB/Alembic。
- agent 阶段 0 不启动 scrapyd，不执行任务。

### 4.2 配置

`configs/agent.example.toml` 至少包含：

```toml
[agent]
agent_id = "scrapy-agent-1"
host = "0.0.0.0"
port = 6800
workdir = "/agent-data"

[auth]
shared_token = "change-me-agent-token"

[capabilities]
scrapy = true
script = false
docker = false
```

`AGENT_ID` 和 `AGENT_WORKDIR` 可覆盖 toml。

### 4.3 API

阶段 0 必须提供：

| Endpoint | 行为 |
|---|---|
| `GET /health` | 返回 `agent_id`、版本、能力、workdir、状态 |
| `GET /logs/tail` | 返回 `501` 或空占位响应；必须保留查询参数 schema |
| `GET /status` | 返回 `501` |
| `POST /executions/{attempt_id}/logs/cleanup` | 返回 `501` |

若 `shared_token` 非空，server→agent 请求必须带：

```http
Authorization: Bearer <shared_token>
```

---

## 5. Protocol 要求

`packages/protocol` 提供 server 和 agent 共用的 Pydantic schema，至少包括：

- `HealthResponse`
- `CapabilitySet`
- `ErrorResponse`
- `TailRequest`
- `TailResponse`
- `ExecutionRunRequest`
- `ExecutionRunResponse`

协议包不能依赖 server 或 agent 包。依赖方向只能是 server/agent 依赖 protocol。

---

## 6. Web 要求

### 6.1 技术栈

- Vue 3 + TypeScript + Vite。
- Element Plus。
- Vue Router。
- Pinia。
- vue-i18n。
- axios。

### 6.2 页面

阶段 0 至少包含：

- 登录页。
- 主布局：侧边菜单 + 顶栏。
- 节点页：调用 `GET /api/v1/nodes`，展示 endpoint、agent_id、status、last_seen_at。
- 健康页或首页：展示 server health。
- 未实现页面占位，不暴露可误操作的 Scrapy 执行按钮。

### 6.3 i18n

译文文件统一：

```text
apps/web/src/i18n/locales/zh.ts
apps/web/src/i18n/locales/en.ts
```

默认 locale 为 `zh`。Element Plus 使用 `zh-cn` locale。

### 6.4 API client

- API base path 为 `/api/v1`。
- token 存储位置由 Claude 选择，但必须避免散落在组件内；统一由 store/client 管理。
- 401 统一跳登录页。

---

## 7. Docker 与开发命令

### 7.1 Docker

必须新增：

- `deploy/docker/Dockerfile.server`
- `deploy/docker/Dockerfile.agent`
- `deploy/docker/docker-compose.yml`
- `.dockerignore`

`.dockerignore` 必须排除：

```text
reference/
.venv/
.venv-ref/
.git/
node_modules/
apps/web/dist/
**/__pycache__/
**/.pytest_cache/
**/tests/.tmp/
```

compose 第一版是后端执行闭环：server + agent + PostgreSQL。Web 可由 Vite dev server 单独运行。

### 7.2 推荐命令

Claude 应在仓库 README 或阶段 0 文档补充实际命令。目标形态：

```bash
# Python
python3 -m venv .venv
source .venv/bin/activate
pip install -e packages/protocol
pip install -e apps/server
pip install -e apps/agent

# Web
pnpm install
pnpm --filter web dev

# DB / backend
cd deploy/docker && docker compose up -d db
DOPILOT_CONFIG=configs/server.example.toml dopilot-server
DOPILOT_CONFIG=configs/agent.example.toml dopilot-agent
```

命令名可由 pyproject console_scripts 定义，但必须文档化。

---

## 8. 测试要求

Claude 完成阶段 0 后必须运行并记录结果：

```bash
# server
pytest apps/server/tests

# agent
pytest apps/agent/tests

# protocol
pytest packages/protocol/tests

# web
pnpm --filter web test
pnpm --filter web build

# compose smoke
cd deploy/docker && docker compose config
```

如果某条命令因环境缺依赖无法运行，Claude 必须说明原因、失败输出摘要、以及后续如何补齐。不能把未运行的测试写成通过。

### 8.1 最低测试覆盖

- server config loader：加载 toml、环境覆盖、缺失配置错误。
- server auth：认证关闭、认证开启成功、认证失败、token 过期/无效。
- server health：数据库可达/不可达分支。
- nodes refresh：mock agent `/health` 后 upsert `nodes`。
- agent config：`AGENT_ID` 覆盖 toml。
- agent health：含 `agent_id` 和 capabilities。
- protocol schema：请求/响应序列化。
- web：至少一个组件/页面测试，验证 i18n 和 API client 基础行为。

---

## 9. Claude 交付格式

Claude 编码完成后，交付给 Codex review 时必须提供：

1. 变更摘要：按 server / agent / web / protocol / deploy 分组。
2. 运行过的命令及结果。
3. 未运行或失败的命令及原因。
4. 新增配置文件说明。
5. 数据库迁移说明。
6. 已知问题和下一阶段 TODO。

Claude 不需要写长篇自评；事实、命令和 diff 足够。

---

## 10. Codex review / 验收清单

Codex 拿到阶段 0 代码后按以下顺序 review：

1. **边界检查**：确认没有 import `reference/scrapydweb`，没有把 `reference/` 放进 Docker 上下文。
2. **架构检查**：确认 server/agent/protocol/web 依赖方向正确，protocol 不反向依赖 app。
3. **配置检查**：确认 `DOPILOT_CONFIG`、`shared_token`、`AGENT_ID`、PostgreSQL URL 口径一致。
4. **迁移检查**：确认 Alembic migration 可从空库跑通，无 `create_all` 替代正式迁移。
5. **API 检查**：确认 `/api/v1/health`、auth、nodes、agent `/health` 契约符合本文。
6. **测试复跑**：优先复跑 Claude 声称通过的命令；失败时记录失败输出和最小复现。
7. **安全检查**：确认 opaque token 不明文落库，默认 `change-me` 配置不会被误认为生产安全。
8. **Docker 检查**：确认 `.dockerignore` 排除 reference，Dockerfile 不 copy 前端到 server，compose 不声明多 server 副本。
9. **Web 检查**：确认未实现功能不可误点，i18n 文件名和 API base path 正确。

Codex review 输出采用代码审查格式：先列发现，按严重程度排序；没有问题则明确写“未发现阻塞问题”，并列出仍未覆盖的测试风险。

---

## 11. 进入阶段 1 的门槛

阶段 0 只有满足以下条件才算完成：

- server/agent/web/protocol 四个包均可安装或构建。
- PostgreSQL 空库可运行迁移。
- server 和 agent 可同时启动。
- server 能刷新 agent health 并写入/读取 `nodes`。
- Web 能登录或在认证关闭时进入主布局，并显示 health/nodes 基础数据。
- Docker compose 后端闭环配置有效。
- 基础测试通过，或失败项有明确环境原因且不影响代码可 review。

满足后，阶段 1 才开始实现 dopilot-agent 内管 scrapyd、egg 上传、ScrapydExecutor 和真实执行状态。
