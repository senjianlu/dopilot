# dopilot —— 开发环境搭建与已知问题

> **【scrapydweb 参考边界】** scrapydweb 仅作**功能层/行为参考**与**测试 oracle**;其代码写法、目录结构、模块划分、命名、依赖、配置形态**一律不得作为 dopilot 的设计依据**。dopilot 为 greenfield、按 `apps/`+`packages/` 自有领域 structure-first 设计(权威布局见 `05-dev-setup-and-known-issues.md` §1),**不对 scrapydweb 做改名/git mv**。详见 `00-requirements.md` 决策表。
>
> 本文为「开发环境搭建」入口文,最容易把 scrapydweb 的装机/配置/目录当成 dopilot 自身做法。请牢记:`reference/scrapydweb` 只读、不被 import、不参与 dopilot 构建、不改名;下文凡涉及 scrapydweb 安装/配置/目录之处,均为**参考观察用途**,不等于 dopilot 自身设计。

> 记录本地导入、依赖安装、以及当前已发现的兼容性问题与修复方案。

> **⚠️【阶段 2.1 前端技术栈已迁移】** 自**阶段 2.1**起，前端由 **Vue 3 + Element Plus + Vite + vue-i18n + Pinia** 迁移为 **Next.js（静态导出 `output: export` + `trailingSlash`）+ shadcn/ui（slate 主题、明暗模式）+ Recharts + react-i18next + TypeScript**：开发用 `next dev`（经 `NEXT_PUBLIC_API_BASE` 指向 server），生产为同源静态产物由 dopilot-server 托管（无 `next start`/Node 生产运行时/独立 Web 容器）；前端测试用 vitest + Testing Library，lint 为 `eslint .`（flat config）。组件源码在 `apps/web/components`、页面在 `apps/web/app`、共享库在 `apps/web/lib`。下文涉及前端框架/目录/开发服务器/构建的旧 Vue/Vite 指引一律以阶段 2.1 为准；权威说明见 `docs/dopilot/06-frontend-rewrite.md` 顶部对照表与 `docs/phases/phase-2.1/01-claude-implementation-report.md`。

## 1. 仓库与远程

本仓库为 **monorepo**（`00-requirements.md` 决策 8）：server 与 agent 同仓开发，`reference/` 仅作基线参考、不参与构建。

> **【通信模型新口径，superseded-by】** server↔agent 通信已由"server 主动 HTTP run/status/tail pull"翻案为"server→Redis Streams 投命令、agent 主动消费/推状态/推日志 + 主动 POST heartbeat"(破坏性、无双轨)。下文布局已据此补入 `apps/server/dopilot_server/redis/`、`apps/agent/dopilot_agent/redis/` 子包与 `packages/protocol/dopilot_protocol/streams.py`;权威口径见 `docs/refactor/00-redis-streams-agent-communication.md`。

dopilot 自身代码按 **structure-first** 的 `apps/`+`packages/` monorepo 全新编写(各包均为 greenfield,以 scrapydweb 为行为参考逐域移植,**不对 scrapydweb 改名/git mv**)。权威布局:

```text
dopilot/                                  # 仓库根 = Docker 构建上下文(origin: senjianlu/dopilot;镜像命名空间 rabbir)
├── apps/
│   ├── server/                           # FastAPI 调度中心:API、PostgreSQL、APScheduler、认证、节点管理、日志聚合
│   │   ├── dopilot_server/
│   │   │   ├── api/v1/                    # FastAPI /api/v1/* JSON + SSE 端点(server↔agent 走 Redis Streams;server→web 仍 SSE、无 WebSocket)
│   │   │   ├── redis/                     # server↔agent Redis Streams 基础设施:client/streams/commands/consumers(command outbox/dispatcher、event/log consumer、heartbeat)
│   │   │   ├── auth/  scheduler/  nodes/  logs/  models/  repositories/  services/  config/  db/
│   │   │   ├── executors/                 # 缝① BaseExecutor + EXECUTOR_REGISTRY
│   │   │   │   ├── base.py  scrapyd.py  script.py  docker.py
│   │   │   └── app.py
│   │   ├── migrations/  tests/  pyproject.toml
│   ├── agent/                            # worker 执行节点:经 Redis Streams 主动消费命令、主动推状态/日志、主动 POST heartbeat,实际跑 Scrapy/Python/Docker
│   │   ├── dopilot_agent/
│   │   │   ├── api/                       # /health 仅容器本地 healthcheck(不再作 server 节点发现/健康来源)
│   │   │   ├── redis/                     # server↔agent Redis Streams 基础设施:client/commands/events/logs(command consumer、event/log publisher、event outbox)
│   │   │   ├── runners/                   # base.py scrapyd.py script.py docker.py
│   │   │   ├── logs/  workspace/  heartbeat/  config/  main.py
│   │   ├── tests/  pyproject.toml
│   └── web/                              # Next.js + shadcn/ui + Recharts + react-i18next + TS（阶段 2.1 起;静态导出 output:export,直连 /api/v1）
│       ├── app/  components/  lib/  public/   # app=页面路由, components=shadcn/UI 组件, lib=共享库(api 客户端/i18n 等)
│       ├── package.json  next.config.mjs  components.json  eslint.config.mjs
│       ├── out/                          # next build 静态导出产物(同源由 dopilot-server 托管)
│       # 历史:阶段 2.1 前为 Vue3 + Element Plus + Vite(src/{api,pages,components,layouts,stores,router,i18n}/、vite.config.ts、index.html、env.d.ts),已移除
├── packages/
│   ├── protocol/                         # server↔agent 共享协议 schema(含 dopilot_protocol/streams.py:AgentCommand/AgentEvent/AgentLogEvent/AgentHeartbeat*;前端也消费可并列 protocol/typescript/)
│   └── client/                           # 可选:server→agent 客户端 SDK
├── deploy/{docker/{Dockerfile.base,Dockerfile,docker-compose.yml},k8s/}
├── configs/{server.example.toml,agent.example.toml}   # dopilot 自有 toml 配置(经 DOPILOT_CONFIG 加载,不继承 scrapydweb 硬编码 settings)
├── scripts/  docs/
├── reference/scrapydweb/                 # 只读行为参考,绝不进构建上下文/不被 import/不改名
├── README.md  pyproject.toml  pnpm-workspace.yaml  .dockerignore
```

> `09-package-rename.md` 不是「把 scrapydweb 改名」的指南,而是 scrapydweb 行为参考 + 逐域移植时的注意事项;dopilot 的 server/agent 包均为全新编写、以 scrapydweb 为行为参考,不做 git mv。

> 镜像发布命名空间为 Docker Hub **`rabbir`**（与 git `origin` 的 `senjianlu` 互不等同），详见 `08-docker-deployment.md` §7。

Git 远程：

| 远程 | 地址 | 用途 |
|------|------|------|
| `origin` | https://github.com/senjianlu/dopilot | dopilot 自己的仓库 |
| `upstream` | https://github.com/my8100/scrapydweb.git | 跟踪上游、diff/cherry-pick 修复（不合并历史） |

导入快照：scrapydweb `1.6.0`，上游 commit `1341cf9`。

## 2. 环境信息

- Python：3.12.1（`setup.py` 分类器声明支持 3.6–3.13）
- 依赖版本**全部 pin 死**（Flask 2.0.0、Werkzeug 2.0.0、SQLAlchemy 1.3.24、APScheduler 3.6.0、Jinja2 3.0.0、MarkupSafe 2.0.0 等）

## 3. 搭建步骤

dopilot 自身的开发搭建与「跑通 scrapydweb 基线做参考观察」是**两件不同的事**:dopilot 不依赖、不 import、不安装 `reference/scrapydweb`。

### 3.a dopilot 自身开发搭建(按 apps/packages 布局)

```bash
# 后端:server / agent 各自带 pyproject.toml,独立可编辑安装
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip wheel
pip install -e apps/server          # FastAPI 调度中心包 dopilot_server(等价可用 uv pip install -e apps/server)
pip install -e apps/agent           # worker 执行节点包 dopilot_agent

# 前端:web 为 Next.js + shadcn/ui app(pnpm workspace,见仓库根 pnpm-workspace.yaml)
pnpm install                        # 在仓库根安装,或 pnpm --filter web install
pnpm --filter web dev               # next dev,经 NEXT_PUBLIC_API_BASE 指向 server;生产用 pnpm --filter web build 产出 out/ 静态导出
```

> 上述包/路径随阶段 0 起逐步落地;在对应包未创建前,这是目标搭建形态而非现状。

### 3.b 本地开发容器策略

日常开发默认需要 PostgreSQL 与 Redis 两个容器（Redis 是 server↔agent 通信总线，agent 经 Redis Streams 消费命令、推状态/日志，server 消费后落库/落盘）；`server` / `web` / `agent` 都在宿主机运行，便于 Python editable install、`next dev` 热更新和调试。完整 Docker 闭环（`db + redis + server + web + agent`）只用于集成验收、镜像验证或模拟部署。

> Redis 仅作消息总线/瞬时传输,不是 dopilot 持久化数据库:业务真相仍在 PostgreSQL,日志正文仍落 `/server-data/logs`。引入 Redis 也不表示支持多副本——单实例约束不变（server 单容器、uvicorn `workers=1`、单 APScheduler）。

最小开发依赖：

```yaml
services:
  db:
    image: postgres:16
    environment:
      POSTGRES_DB: dopilot
      POSTGRES_USER: dopilot
      POSTGRES_PASSWORD: dopilot
    ports:
      - "5432:5432"
    volumes:
      - dopilot-db:/var/lib/postgresql/data

  redis:
    image: redis:7
    # server↔agent 通信总线;开发期也建议启用 AUTH + AOF,贴近生产
    command: ["redis-server", "--appendonly", "yes", "--requirepass", "dopilot"]
    ports:
      - "6379:6379"
    volumes:
      - dopilot-redis:/data

volumes:
  dopilot-db:
  dopilot-redis:
```

宿主机运行时，server 的日志正文路径仍按角色命名为 `/server-data/logs`；本地可通过配置把它映射到仓库外或 `.local/server-data/logs`，但不要把日志正文写入 PostgreSQL。

### 3.c 可选:跑通 scrapydweb 基线以做行为参考观察

仅用于**观察 scrapydweb 的参考行为**(功能层对照 + 测试 oracle),**不是 dopilot 自身的安装**,也不进入 dopilot 的运行/构建路径:

```bash
python3 -m venv .venv-ref
source .venv-ref/bin/activate
pip install -U pip wheel
pip install -e reference/scrapydweb   # editable 安装 scrapydweb 本体,仅供参考观察
# 关键修复（见下文「已知问题」）：
pip install "setuptools<81"
```

scrapydweb 的依赖均能在 Python 3.12 上正常编译安装（含旧版 SQLAlchemy 1.3.24、MarkupSafe 2.0.0、tzlocal 1.5.1 的 C 扩展 wheel 构建）——此为运行基线观察时的兼容性实测结论,**非 dopilot 自身依赖选型的直接依据**。

## 4. 已知问题

### 4.1 ⚠️ APScheduler 3.6.0 依赖 `pkg_resources`，新版 setuptools 已移除

**现象**：`import scrapydweb` / 运行 `scrapydweb` CLI 报错：

```
File ".../apscheduler/__init__.py", line 1, in <module>
    from pkg_resources import get_distribution, DistributionNotFound
ModuleNotFoundError: No module named 'pkg_resources'
```

**根因**：APScheduler 3.6.0 在 `apscheduler/__init__.py` 顶部 `from pkg_resources import ...`；而 `setuptools >= 81` 已彻底移除内置的 `pkg_resources` 模块。`pip install -e .` 会顺带把 setuptools 升级到 82，于是缺失 `pkg_resources`。

**修复方案（按推荐度排序）**：

| 方案 | 操作 | 优点 | 缺点 |
|------|------|------|------|
| A（推荐，最小改动） | `pip install "setuptools<81"` | 立即恢复 `pkg_resources`，零代码改动 | 锁住 setuptools 旧版 |
| B（长期） | 升级 APScheduler 到 3.10.x（3.x 末版，已改用 importlib 不再依赖 pkg_resources） | 去掉历史包袱 | 需回归验证 scrapydweb 调度逻辑对新版 APScheduler 的兼容性 |
| C | 在环境内单独提供 `pkg_resources`（保留旧 setuptools 或 vendoring） | —— | 不如 A 干净 |

> ⚠️ 当前状态：方案 A 的命令在本次会话中**被用户取消，尚未执行**。因此当前 `.venv` 里依赖已装好，但 `import scrapydweb` 仍会因本问题失败。需要跑通时执行方案 A 即可。

reference 环境若需要长期复跑，可在 reference 专用约束中 pin `setuptools<81`；dopilot 自身依赖不继承该 pin，直接选 `APScheduler>=3.10,<4` 并写入 `apps/server/pyproject.toml`。

## 5. 首次运行（待补）

dopilot 自身的首次运行基于其**自有 toml 配置**(不继承 scrapydweb 的硬编码 settings 形态):

```bash
# server:复制示例配置 → 由 dopilot 自有 toml 加载器读取(经 DOPILOT_CONFIG 指定路径)
cp configs/server.example.toml configs/server.toml   # 配置节点、PostgreSQL、Redis、认证、调度等
DOPILOT_CONFIG=configs/server.toml dopilot-server     # 起 Web + scheduler hub

# agent:同理
cp configs/agent.example.toml configs/agent.toml      # 配置 server 地址、Redis、workspace、心跳等
DOPILOT_CONFIG=configs/agent.toml dopilot-agent       # 起 worker 执行节点
```

> 完整命令名/参数随 apps/server、apps/agent 落地后补全;在此之前为目标运行形态。

通信走 Redis Streams,server 与 agent 都需配 `[redis]` 段(口径见 `docs/refactor/00-redis-streams-agent-communication.md`「配置建议」)。最小示例:

```toml
# configs/server.toml(节选)
[redis]
url = "redis://:dopilot@localhost:6379/0"   # server 消费 agent-events / logs、投 command;开发期对齐 compose 的 AUTH 口令
stream_maxlen_commands = 100000
stream_maxlen_events = 100000
stream_maxlen_logs = 1000000
log_retention_seconds = 86400
consumer_name = "server-1"
require_aof = true

[agents]
heartbeat_timeout_seconds = 30                # healthy = now - nodes.last_seen_at <= 该值
stalled_attempt_seconds = 300
lost_after_stalled_seconds = 900

[logs]
log_drain_timeout_seconds = 30
```

```toml
# configs/agent.toml(节选)
[redis]
url = "redis://:dopilot@localhost:6379/0"   # agent 主动消费命令、XADD 状态/日志
command_block_ms = 5000
pending_idle_ms = 30000
event_outbox_dir = "/agent-data/outbox"

[agent]
agent_id = "agent-01"
server_url = "http://localhost:5000"          # 主动 POST /api/v1/agents/{agent_id}/heartbeat 用
heartbeat_interval_seconds = 10
server_shared_token = "change-me-agent-server-token"   # agent→server token,不复用 server→agent 旧 token
```

**移植/对照注意(功能参考,非 dopilot 设计)**:scrapydweb 首次运行会在工作目录生成默认 `scrapydweb_settings_v11.py`(文件名硬编码于 `vars.py:29` `SCRAPYDWEB_SETTINGS_PY`),且仅从 `os.getcwd()` 查找,在其中配置 `SCRAPYD_SERVERS` 等。dopilot **不沿用**这种「硬编码文件名 + 仅 cwd 查找」的加载方式——仅参考其配置键的**语义**,改用上述 toml + `DOPILOT_CONFIG` 显式路径加载。

相关：scrapydweb 配置加载顺序(行为参考)见 `docs/architecture/01-bootstrap-and-config.md`。

## 6. 开发期工具链：MCP 与 Skills

记录 Claude Code 在 dopilot 开发中用到的 MCP server 与 skills，以及它们各自服务的目标。原则：**能用内置 skill / Bash 解决的就不引入多余 MCP**，当前只新增一个浏览器驱动 MCP。

### 6.1 两个开发目标 → 工具映射

| 目标 | 需要的能力 | 用什么 |
|------|-----------|--------|
| ① 开发中自己开页面、测前端功能点 | 浏览器导航 / 点击 / 填表 / 截图 / 读控制台·网络 | **Playwright MCP**(唯一需新增的 MCP)+ 内置 `run` / `verify` skill |
| ② 构建镜像、本地起 server+agent 双端、跑爬虫验收 | Docker 构建与编排 | **Bash + Docker CLI**(不需要 MCP)+ 内置 `verify` skill |

### 6.2 MCP server

| 名称 | 配置位置 | 作用 | 备注 |
|------|---------|------|------|
| `playwright` | 仓库根 `.mcp.json`(项目级、已签入 git) | 驱动浏览器测试 Next.js + shadcn/ui 前端功能点 | 靠 `npx -y @playwright/mcp@latest` 拉起,需先装 Node |

> 选型：相比 chrome-devtools MCP,Playwright MCP 更通用、可自带下载 Chromium,适合常规页面功能点测试。后续若需深挖 SSE 实时日志的 EventStream/网络面板,可再叠加 chrome-devtools MCP。
> Docker 侧刻意**不引入 Docker MCP**——目标 ② 全程用 Bash 调 Docker CLI 即可,且 `08-docker-deployment.md` 已规划好 `Dockerfile` / compose。

### 6.3 Skills(均为内置,零新增)

| skill | 用途 |
|-------|------|
| `run` | 拉起 dopilot 前端/后端 app |
| `verify` | 跑起来观察行为做验收(功能点测试 + 双端爬虫端到端) |
| `code-review` / `security-review` | 改动的质量与安全把关 |

### 6.4 前置系统依赖(已就绪,实测于 2026-06-18)

| 依赖 | 实测版本 | 状态 | 备注 |
|------|---------|------|------|
| Node / npx | v22.22.3 / npx 10.9.8 | ✅ | Playwright MCP 经 npx 拉起 |
| Docker | 29.5.3 | ✅ | daemon 免 sudo 可达(已在 docker 组) |
| Docker Compose | v5.1.4 | ✅ | 目标 ② 编排用 |
| `@playwright/mcp` | v0.0.76 | ✅ | npx 缓存已预热 |
| Playwright Chromium | revision **1228**(Chrome 149) | ✅ | 与 MCP 捆绑的 playwright-core 所需 revision **精确匹配**;已实测无头启动 + 截图成功,系统库齐全 |

> Playwright MCP 配置在仓库根 `.mcp.json`,需在 Claude Code **下次会话 / 重连 MCP** 时才被拉起,可用 `/mcp` 查看状态。

**重新置备时的参考命令**(换机/重装环境时用):

```bash
# Node(经 npx 拉起 Playwright MCP)
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash - && sudo apt-get install -y nodejs
# Playwright 浏览器:务必与 @playwright/mcp 捆绑的 playwright-core revision 对齐
npx playwright install chromium               # 仅缺系统库时再加: sudo npx playwright install-deps chromium
# Docker
curl -fsSL https://get.docker.com | sudo sh && sudo usermod -aG docker $USER   # 重登生效
```

> ⚠️ Chromium revision 必须和 `@playwright/mcp` 内置的 playwright-core 一致(本次均为 1228)。若 MCP 报 "browser not found",多半是 MCP 版本变动带来的 revision 漂移——重跑一次 `npx playwright install chromium` 即可。
