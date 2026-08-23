# 开发环境与测试基线

> 决策依据:[0017 测试基线](../decisions/0017-testing-baseline-own-regression-net.md)。

## 本地开发

前置:Python **3.12**、Node **22+**（Corepack:`corepack pnpm …`）、
Docker（跑 PostgreSQL 与 Redis）。

```bash
# Python 包(protocol 先装;server/agent 依赖它)
python3.12 -m venv .venv && source .venv/bin/activate
pip install -U pip wheel
pip install -e ./packages/protocol
pip install -e "./apps/server[dev]"
pip install -e "./apps/agent[dev]"

# 依赖容器:PostgreSQL + Redis(AOF)
scripts/dev-db.sh up
docker run -d --rm --name dopilot-redis-dev -p 6379:6379 \
  redis:7 redis-server --appendonly yes

# 迁移(server 独占 schema)
(cd apps/server && DOPILOT_CONFIG=../../configs/server.example.toml alembic upgrade head)

# 运行(分终端);agent 纯出站,无 -b/-p
DOPILOT_CONFIG=configs/server.example.toml dopilot-server
DOPILOT_CONFIG=configs/agent.local.toml dopilot-agent
NEXT_PUBLIC_API_BASE=http://localhost:5000/api/v1 corepack pnpm --filter web dev
```

日常开发只容器化 db + redis，server/web/agent 在宿主机跑（editable
install、`next dev` 热更新）;完整 Docker 闭环仅用于集成验收/镜像验证。

## 测试与验证命令

```bash
# 日志洪泛防护的并发用例(行锁 / 部分唯一索引)只在 PostgreSQL 上有意义:
# 先 scripts/dev-db.sh up,再导出下面的变量;缺失时这些用例 FAIL 而非 skip。
export DOPILOT_TEST_DATABASE_URL=postgresql+psycopg://dopilot:dopilot@localhost:5432/dopilot
pytest                              # server / agent / protocol(根 pyproject 聚合 testpaths)
ruff check apps packages            # Python lint
corepack pnpm --filter web test     # web vitest
corepack pnpm --filter web build    # 静态导出构建
cd deploy/docker && docker compose config
scripts/smoke-phase1.sh             # Scrapy 端到端(本地源码构建 compose 栈)
scripts/smoke-phase1-ui.sh          # UI 端到端
```

测试落点:`apps/server/tests/`、`apps/agent/tests/`、
`packages/protocol/tests/`（pytest，异步 asyncio_mode=auto;Redis 测试用
fakeredis / 容器）、`apps/web`（vitest / Playwright e2e）。

测试原则（详见 [0017](../decisions/0017-testing-baseline-own-regression-net.md)）:
后端测 `/api/v1` JSON 契约不测文案;executor 层可 mock;Redis 通信可靠性
域（outbox/幂等/offset gap/heartbeat/lost/reconcile）无上游 oracle，按
[03-execution-and-logs.md](03-execution-and-logs.md) 的语义自构造。上游
scrapydweb 测试仅作外部行为 oracle，需要观察时在仓库之外克隆上游。

## CI

`.github/workflows/docker.yml`:镜像构建与推送（见
[05-deployment.md](05-deployment.md)）。测试/lint 在开发流程与 rawf 评审
证据中执行。

## 开发期工具

- Playwright MCP（仓库根 `.mcp.json`，项目级）:浏览器驱动前端功能点
  验证。
- 项目内建 skill:`.agents/skills/shadcn`（由根 `skills-lock.json` 按内容
  哈希锁定），服务 shadcn/ui 组件开发。
