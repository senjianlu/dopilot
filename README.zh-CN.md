<p align="center">
  <img src="apps/web/public/logo.svg" alt="dopilot logo" width="120" />
</p>

<h1 align="center">dopilot</h1>

<p align="center">
  一个面向单管理员的自托管调度平台，用于在多个 worker 节点上运行 Scrapy 爬虫与
  Python 脚本。
</p>

<p align="center">
  <a href="README.md">English</a> · <b>简体中文</b>
</p>

<p align="center">
  <img src="screenshot.png" alt="dopilot 控制台截图" width="960" />
</p>

---

## dopilot 是什么

dopilot 是一个自托管平台：在远端 worker 节点上调度并运行任务，实时回传日志，并为
每一次运行保留可追溯的记录。它以 `apps/` + `packages/` monorepo 全新构建。

它刻意只支持**单管理员**——没有多用户体系，也没有 RBAC。项目以 [MIT 许可证](LICENSE)
开源。dopilot 在**行为层面**参考了上游的
[**scrapydweb**](https://github.com/my8100/scrapydweb) 项目（仅作外部行为参考查阅）；
上游 scrapydweb 代码**绝不被拉取、内置、import 或参与构建**。

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

默认 compose 栈直接拉取 CI 构建的 `rabbir/dopilot` 镜像，**无需本地构建**，一键拉起
整套栈（PostgreSQL + Redis + 一次性 migrate + 三个 Scrapy agent + server）：

```bash
cd deploy/docker
cat > .env <<'EOF'
DOPILOT_ADMIN_PASSWORD=replace-with-admin-login-password
DOPILOT_ADMIN_API_TOKEN=replace-with-long-random-token
DOPILOT_AGENT_TOKEN=replace-with-long-random-agent-token
REDIS_PASSWORD=replace-with-redis-password
EOF
docker compose pull
docker compose up -d
```

随后 server 可在 **http://localhost:5000** 访问（Web UI 与 API）。server 仅支持
单副本运行（进程内调度器 + 进程内 SSE 表）。可用 `DOPILOT_IMAGE` 覆盖镜像（默认
`rabbir/dopilot:latest`）。

API 客户端最简单的方式是用静态 admin API token：直接把 `DOPILOT_ADMIN_API_TOKEN`
作为 Bearer token 调用，无需登录：

```bash
curl -H "Authorization: Bearer $DOPILOT_ADMIN_API_TOKEN" \
  http://localhost:5000/api/v1/auth/me
```

或者先用单管理员账号登录，拿返回的 opaque access token（由内部 `token_secret`
签名）调用接口：

```bash
ACCESS_TOKEN=$(
  curl -s http://localhost:5000/api/v1/auth/login \
    -H 'Content-Type: application/json' \
    -d '{"username":"admin","password":"'"$DOPILOT_ADMIN_PASSWORD"'"}' \
    | python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])'
)

curl -H "Authorization: Bearer $ACCESS_TOKEN" \
  http://localhost:5000/api/v1/auth/me
```

`DOPILOT_ADMIN_API_TOKEN` 是外部提供的静态 admin API token（非空时须 >= 16 字符），
**仅管理员、仅 server 端**：从不下发给 agent，也不作为机器 token 的来源。
`DOPILOT_AGENT_TOKEN` 是 agent 机器 token（非空时须 >= 16 字符）：agent 在出站调用
server（heartbeat + artifact/wheel 拉取）时携带，因此 server 与每个 agent 必须设置
**相同的值**；留空则关闭机器认证。agent 不暴露任何入站 HTTP API。登录/stream 的
签名密钥（`token_secret`）是另一个仅 TOML 配置、已烤进镜像的值。

Token 认证不是传输加密。跨主机要加密时，请把 server、agent、Redis 放在私有网络/VPN
内，或在反向代理处终止 TLS。

### 拆分部署（server-only / agent-only）

若 server 与 agent 分主机运行，用拆分 compose 文件而非一体栈：

```bash
cd deploy/docker
# server-only 栈（db + redis + migrate + server，无 agent）。可省略 DOPILOT_AGENT_TOKEN
# —— server 首次启动会在数据卷生成并持久化机器令牌（/server-data/secrets/agent-token）。
docker compose -f docker-compose.server.yml up -d

# 读取（生成或配置的）机器令牌，发给 agent：
docker compose -f docker-compose.server.yml exec server dopilot-server agent-token print          # DOPILOT_AGENT_TOKEN=<token> + 提示
docker compose -f docker-compose.server.yml exec server dopilot-server agent-token print --quiet  # 仅打印裸令牌

# 在每个 agent 主机：用该令牌（必填、无开发回退）+ server 的 HTTP 基址 + server 的 Redis 接入。
# DOPILOT_SERVER_URL 是 agent 端环境变量——agent 用于 heartbeat 与 artifact/wheel 拉取的
# server HTTP 基址；此处必填，因为烤进的 http://server:5000 只在一体栈 compose 网络内可解析
# （例：http://<server-ip-or-dns>:5000、
#   http://dopilot-server.dopilot.svc.cluster.local:5000、https://dopilot.example.com）。
# token 鉴权不等于传输加密，跨主机 HTTP 仍需私网 / VPN / TLS / 反代。
# agent 绝不接收 DOPILOT_ADMIN_API_TOKEN。
DOPILOT_AGENT_TOKEN=<token-from-server> DOPILOT_SERVER_URL=http://<server-host>:5000 \
  REDIS_PASSWORD=<server-redis-pass> REDIS_HOST=<server-host> \
  docker compose -f docker-compose.agent.yml up -d
```

一体栈 `docker-compose.yml` 仍用显式共享 `DOPILOT_AGENT_TOKEN`（server 与 agent 同时启动，
生成的令牌无法传给 agent）。Token 认证仍不是传输加密——见上文说明。

如需用本地源码构建镜像（而非拉取），叠加 build 覆盖文件（smoke 脚本即用此方式）：

```bash
cd deploy/docker
docker compose -f docker-compose.yml -f docker-compose.build.yml up -d --build
```

> compose 配置保持 Web 认证**开启**，Redis 密码认证也默认开启。默认的 `change-me`
> fallback 仅适合开发；对外暴露前请先设置上面的 `.env`。Docker 镜像已内置
> server/agent 默认 TOML，compose 栈不需要配置 `DOPILOT_CONFIG`。

## 本地开发

前置要求：Python **3.12**、带 Corepack 的 Node **22+**（`corepack pnpm …`），以及
Docker（用于 PostgreSQL 与 Redis）。

```bash
# 1. Python 包（protocol 优先；server/agent 依赖它）
python3.12 -m venv .venv
source .venv/bin/activate
pip install -U pip wheel
pip install -e ./packages/protocol
pip install -e "./apps/server[dev]"
pip install -e "./apps/agent[dev]"

# 2. 后端依赖服务。
# Postgres 可使用仓库内 compose 服务；host 进程访问 Redis 需要暴露 host 端口。
scripts/dev-db.sh up
docker run -d --rm --name dopilot-redis-dev -p 6379:6379 \
  redis:7 redis-server --appendonly yes

# 3. 应用迁移（schema 由 server 持有）
(cd apps/server && DOPILOT_CONFIG=../../configs/server.example.toml alembic upgrade head)

# 4. 运行服务（分别开终端）。
# agent 需先复制 configs/agent.example.toml 为本地配置，并设置：
#   [agent].server_url = "http://localhost:5000"
#   [redis].url = "redis://localhost:6379/0"
# agent 为纯出站：不开任何入站端口（无 -b/-p 参数）。
DOPILOT_CONFIG=configs/server.example.toml dopilot-server
DOPILOT_CONFIG=configs/agent.local.toml dopilot-agent

# 5. 开发模式启动 Web UI（Next.js）
NEXT_PUBLIC_API_BASE=http://localhost:5000/api/v1 corepack pnpm --filter web dev
```

本地 Redis 可用 `docker stop dopilot-redis-dev` 停止。

`DOPILOT_CONFIG` 用于让本地开发进程读取 `configs/` 下的 TOML 配置；
`DOPILOT_DATABASE_URL` 与 `DOPILOT_REDIS_URL` 可覆盖数据库与 Redis 地址。Web
管理员认证是 **fail-closed**：除非显式设置 `DOPILOT_AUTH_DISABLED=true`，否则
`admin_username`、`admin_password`、`token_secret` 必须全部配置。server-agent 机器
认证使用唯一的 `DOPILOT_AGENT_TOKEN`（agent 在出站调用——heartbeat + 拉取 artifact/wheel
——时携带，server 与每个 agent 设相同值）；留空则关闭机器认证。agent 不暴露任何入站
HTTP API。admin API token 绝不充当机器 token。

Web 应用是 **Next.js 静态导出**产物（shadcn/ui + react-i18next），由
`dopilot-server` 在同一容器内托管——没有独立的 Web 容器，也没有 Node 生产运行时。

## 测试与 lint

```bash
pytest                             # pytest（server/agent/protocol）
corepack pnpm --filter web test    # web vitest
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

## 贡献

设置与验证命令见 [`CONTRIBUTING.md`](CONTRIBUTING.md)；漏洞上报与运维加固（对外暴露前
请替换默认 `change-me` 凭据）见 [`SECURITY.md`](SECURITY.md)。

## 许可

dopilot 以 [MIT 许可证](LICENSE) 发布（SPDX-License-Identifier: `MIT`）。
