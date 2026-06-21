<p align="center">
  <img src="apps/web/public/logo.svg" alt="dopilot logo" width="120" />
</p>

<h1 align="center">dopilot</h1>

<p align="center">
  一个面向单管理员的私有调度平台，用于在多个 worker 节点上运行 Scrapy 爬虫与
  Python 脚本。
</p>

<p align="center">
  <a href="README.md">English</a> · <b>简体中文</b>
</p>

---

## dopilot 是什么

dopilot 是一个自托管平台：在远端 worker 节点上调度并运行任务，实时回传日志，并为
每一次运行保留可追溯的记录。它以 `apps/` + `packages/` monorepo 全新构建。

它刻意只支持**单管理员**——没有多用户体系，也没有 RBAC。上游的 **scrapydweb**
项目（位于 `reference/scrapydweb/`）仅作只读行为参考保留，**不被 import、不参与
构建**。

### 当前可运行的任务类型

| 任务类型 | 状态 | 运行方式 |
| --- | --- | --- |
| **Scrapy 爬虫** | ✅ 已支持 | 上传已构建的 `.egg`，agent 在本机内置 scrapyd 上运行 spider。 |
| **Python 脚本** | ✅ 已支持 | 上传 `.whl`，agent 把 wheel 注入 `PYTHONPATH` 后执行 shell 命令。 |
| **Docker 长连接爬虫** | 🚧 规划中 | 属于后续阶段，**尚未实现**。 |

## 工作原理

dopilot 有两种 Docker 角色，均来自同一个统一镜像（`rabbir/dopilot:latest`），
运行角色由容器启动命令选择：

- **server** —— FastAPI 中枢。提供 `/api/v1/*` JSON/SSE API 并托管内置 Web UI，
  负责调度（APScheduler），在 **PostgreSQL** 中持久化业务数据与日志索引，并把日志
  正文写入 `/server-data/logs` 下的文件。
- **agent** —— worker。主动消费命令、运行任务，并把状态事件与日志增量回推。

server 与 agent 之间通过 **Redis Streams** 加 agent 心跳通信。Redis 只是瞬时消息
总线——不是数据库，也绝不是业务真相来源。agent 不直连 PostgreSQL。

```
 server ──XADD 命令──►  Redis Streams  ──消费──►  agent ──run──► scrapyd / python
   ▲                                                  │
   └────── 状态事件 · 日志增量 · 心跳 ──────────────────┘
```

核心领域模型（任务创建时冻结快照）：

```
构建产物 → 执行模板 → 定时调度 → 任务 → 执行实例
BuildArtifact → ExecutionTemplate → Schedule → Task → Execution
```

一个**任务（Task）**对应一次触发，按节点策略（`selected` / `all` / `random`，并
按节点能力与健康度过滤）fan-out 为每个选中节点上的一个**执行实例（Execution）**。

### Python 脚本执行模型

Python 脚本以 `.whl` 构建产物形式接入。在 agent 上，每个 wheel 按 `sha256` 仅安装
一次：

```bash
pip install --no-deps --target <agent-cache>/python_wheel/<sha256>/site <wheel>
```

随后以该目录注入 `PYTHONPATH` 运行 shell 命令：

```bash
PYTHONPATH=<site-dir>:$PYTHONPATH /bin/sh -c "<command>"
```

**不使用 virtualenv**，不做依赖解析（`--no-deps`），也没有 console-script 入口。
请运行可导入的模块，例如 `python -m main`。脚本所需的、wheel 之外的依赖必须已存在于
agent 环境中。

## 快速部署（Docker Compose）

compose 栈基于两个本地 base 镜像构建（`rabbir/dopilot-py-base:local`、
`rabbir/dopilot-web-base:local`）。`make compose-up` 会先构建这两个 base 镜像，再拉起
整套栈（PostgreSQL + Redis + 一次性 migrate + agent + server）：

```bash
make compose-up
```

随后 server 可在 **http://localhost:5000** 访问（Web UI 与 API）。server 仅支持
单副本运行（进程内调度器 + 进程内 SSE 表）。

> compose 配置设置了 `[auth]`，因此 Web 认证在那里是**开启**的。默认的 `change-me`
> 凭据不可用于生产——对外暴露前请先修改。

## 本地开发

前置要求：Python **3.12**、带 Corepack 的 Node **22+**（`corepack pnpm …`），以及
Docker（用于 PostgreSQL 与 Redis）。

```bash
# 1. Python 包（protocol 优先；server/agent 依赖它）
make install
source .venv/bin/activate

# 2. 后端依赖服务。
# Postgres 可使用仓库内 compose 服务；host 进程访问 Redis 需要暴露 host 端口。
scripts/dev-db.sh up
docker run -d --rm --name dopilot-redis-dev -p 6379:6379 \
  redis:7 redis-server --appendonly yes

# 3. 应用迁移（schema 由 server 持有）
make migrate

# 4. 运行服务（分别开终端）。
# agent 需先复制 configs/agent.example.toml 为本地配置，并设置：
#   [agent].server_url = "http://localhost:5000"
#   [agent].advertise_endpoint = "localhost:6800"
#   [redis].url = "redis://localhost:6379/0"
make server
DOPILOT_CONFIG=configs/agent.local.toml dopilot-agent

# 5. 开发模式启动 Web UI（Next.js）
NEXT_PUBLIC_API_BASE=http://localhost:5000/api/v1 corepack pnpm --filter web dev
```

本地 Redis 可用 `docker stop dopilot-redis-dev` 停止。

`DOPILOT_CONFIG` 指向 `configs/` 下的 TOML 配置；`DOPILOT_DATABASE_URL` 与
`DOPILOT_REDIS_URL` 可覆盖数据库与 Redis 地址。Web 认证与 agent 认证均为
**config-present-or-off**：仅在对应凭据齐全时启用。

Web 应用是 **Next.js 静态导出**产物（shadcn/ui + react-i18next），由
`dopilot-server` 在同一容器内托管——没有独立的 Web 容器，也没有 Node 生产运行时。

## 测试与 lint

```bash
make test                          # pytest（server/agent/protocol）+ web vitest
corepack pnpm --filter web build   # 静态导出构建
ruff check apps packages           # lint
cd deploy/docker && docker compose config
```

## 文档

目标、决策与分阶段路线图见 [`docs/`](docs/README.md)：

- [`docs/dopilot/00-requirements.md`](docs/dopilot/00-requirements.md) ——
  北极星：产品目标、已确认决策、分阶段路线图。
- [`docs/dopilot/10-roadmap.md`](docs/dopilot/10-roadmap.md) —— 综合构建/移植
  路线图。
- [`CLAUDE.md`](CLAUDE.md) —— 架构、硬约束与当前状态。

## 许可

许可详情见本仓库。
