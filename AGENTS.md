# 项目说明

dopilot 是自托管、单管理员的调度平台(MIT 开源):在远端 worker 节点上
运行 Scrapy 爬虫与 Python 脚本,实时回流日志并留存运行记录。架构现状见
`docs/architecture/`,已确认决策见 `docs/decisions/`。

本文件面向进入本仓库的任何 AI 编码工具(AGENTS.md 开放标准),只描述
项目事实与通用约束,不为任何工具指派角色。

> **⚠️ 项目级硬边界**:上游 scrapydweb 仅作外部行为参考,其代码绝不被
> 拉取/内置/import/作为结构依据进入本仓库,详见
> `docs/decisions/0001-scrapydweb-behavior-reference-only.md`。

## 技术栈

版本号:前端以 pnpm-lock.yaml 实际解析结果为准,后端约束写在各
`apps/*/pyproject.toml`(无锁文件);表格只在大版本升级时更新。

### 前端(apps/web,栈 A:前后端分离、静态导出)

Next `output: "export"` 产出纯静态文件,由后端(FastAPI)静态托管,
无 Node 生产运行时;数据一律经 axios 调后端 API。shadcn 取 new-york
风格、slate 基色。

| 类别 | 技术 | 版本 |
|---|---|---|
| 框架 | Next.js(App Router,静态导出) | 16.x |
| UI 库 | React / React DOM | 19.x |
| 语言 | TypeScript | 5.x |
| 样式 | Tailwind CSS(@tailwindcss/postcss)+ tw-animate-css | 4.x |
| 组件体系 | shadcn/ui(手写组件入库,非 npm 包) | — |
| 无障碍基座 | radix-ui(umbrella 包) | 1.x |
| 图标 | lucide-react | 1.x |
| 工具类 | clsx、tailwind-merge、class-variance-authority | — |
| 主题 | next-themes(light / dark / system) | 0.4.x |
| 国际化 | i18next + react-i18next | 24.x / 15.x |
| HTTP 客户端 | axios | 1.x |
| 图表 | recharts | 3.x |
| 通知 toast | sonner | 2.x |
| 包管理 | pnpm(经 Corepack:`corepack pnpm …`) | — |

开发与测试工具:

| 类别 | 技术 |
|---|---|
| 单元测试 | Vitest + jsdom + @testing-library(react / jest-dom / user-event) |
| E2E | Playwright(选择器走 `data-tone`/`data-testid`) |
| Lint | ESLint(flat config)+ typescript-eslint + react-hooks 插件 |
| 类型检查 | tsc --noEmit(独立 script,不阻塞构建) |

### 后端(apps/server、apps/agent、packages/protocol)

全面异步:ORM 走 async engine,阻塞库经 asyncio.to_thread 下沉线程池,
不得直接混入事件循环。

| 类别 | 技术 | 版本 |
|---|---|---|
| 语言 | Python | ≥3.12 |
| Web 框架 | FastAPI + uvicorn(仅 server;agent 纯出站无 HTTP 服务) | 0.110+ / 0.27+ |
| 校验与配置 | Pydantic(自有 TOML 加载器,经 `DOPILOT_CONFIG`) | 2.x |
| ORM 与数据库 | SQLAlchemy(asyncio)+ psycopg\[binary\]（精确钉死,升级须刻意）,PostgreSQL | 2.0.x / 3.x |
| 数据库迁移 | Alembic(`apps/server/migrations/`,server 独占) | 1.x |
| 缓存与消息 | redis-py;server↔agent 走 Redis Streams | 5.x+ |
| HTTP 客户端 | httpx(异步) | 0.27+ |
| 任务调度 | APScheduler(AsyncIOScheduler,单实例) | 3.10.x |
| 打包 | hatchling,console-script 入口(`dopilot-server` / `dopilot-agent`) | — |

开发与测试工具:

| 类别 | 技术 |
|---|---|
| 测试 | pytest(asyncio_mode=auto);替身 fakeredis、aiosqlite |
| Lint | ruff(`ruff check apps packages`) |
| 类型检查 | 暂未引入 |

### 部署

- Docker:统一镜像 `rabbir/dopilot`(`deploy/docker/`,Dockerfile +
  三份 compose;⚠️ 镜像命名空间 `rabbir` ≠ git origin `senjianlu`)
- GitHub Actions(`.github/workflows/docker.yml`)

## 目录约定

仓库为 apps/ + packages/ monorepo(晋级态);完整树与承重说明见
`docs/architecture/README.md`。

| 目录 | 放什么 |
|---|---|
| `apps/server/`、`apps/agent/`、`apps/web/` | 三个可部署单元(FastAPI 调度中枢 / 纯出站 worker / Next.js 静态导出 SPA) |
| `packages/protocol/` | server↔agent 共享 Pydantic 协议 |
| `tests/` | 仅跨应用共享 fixtures;测试本体随各应用 |
| `docs/`、`.ai/` | 持久真相 / 过程痕迹(分工见 docs/README.md;`.ai/` 每个任务目录含 `evidence/` 证据与 `assets/` 资源子目录) |
| `deploy/` | Dockerfile 之外的编排(`docker/` compose;`kubernetes/` K8s 参考清单) |
| `configs/` | server/agent TOML 配置样例 |
| `scripts/` | 仓库级辅助脚本(dev-db、smoke、deps-hash) |
| `examples/` | 示例被调度对象(scrapy_clock) |
| `.github/workflows/`、`.agents/skills/` | CI / 项目内建 skill |

原则:

- 应用一律平铺,不建 `src/`;Python 包具名(`dopilot_server` /
  `dopilot_agent` / `dopilot_protocol`),单元测试在各应用 `tests/` 与包
  平级
- `app/` 这个名字只属于 Next 路由目录
- 根 pyproject.toml 只放共用 dev 工具配置(pytest 聚合 testpaths、ruff),
  不是可安装包
- 新顶级目录先记 docs/decisions/ 再开

## 通用硬规则(对任何 AI 工具生效)

- 永不主动 git commit / git push,必须用户明确确认
- `.ai/` 下是开发过程产物(方案/实现记录/评审记录),历史轮次文件只增不改
- `docs/` 下是持久设计真相(架构/决策),任务改变二者时须在收尾前回写,
  与代码同一提交(分工详见 docs/README.md)
- 开发必须走 rawf 工作流(由 Claude Code 驱动,细则见 CLAUDE.md),
  不得绕过其闸门与产物约定;预计触及文件 > 10 的改动,须在方案确认闸之前
  先经 plan 阶段 Codex 评审(plan-review,默认最多 3 轮,用户明确指定
  轮数时以其为准);≤ 10 不强制。细则见 CLAUDE.md
- 代码评审的角色约束、标准与严重度定义见 .ai-workflow/review-standards.md
- 尊重 `docs/decisions/` 的已确认决策,不复议(如单管理员、单实例
  server、PostgreSQL 唯一数据库、scrapydweb 参考边界);要推翻走新增
  决策记录
- 新增/变更行为需要测试:`apps/server/tests/`、`apps/agent/tests/`、
  `packages/protocol/tests/`、`apps/web`(vitest/e2e)

## Git 提交规范

遵循 Conventional Commits,由 `.githooks/commit-msg` 钩子本地强制。
启用(克隆后执行一次):

```bash
git config core.hooksPath .githooks
git config commit.template .gitmessage
```

- header:`<type>(<scope>): <subject>`;scope 可选(小写短词);subject
  祈使句、≤72 字符、不以句号结尾
- type 取 feat | fix | docs | refactor | perf | test | build | ci |
  chore | style | revert
- scope 建议取 server | agent | web | protocol | deploy | ci | configs |
  docs | repo
- 正文(如有)说明动机与影响;不兼容变更用 `BREAKING CHANGE:` footer
  或 type 后加 `!`
- footer 约定:rawf 任务附 `Rawf: <yyyy-mm-dd>/<task-slug>`;引用权威
  文档用 `Refs:`;结对代理保留 `Co-Authored-By:`
- 一次提交一个主题;代码与其决策痕迹(.ai/ 任务目录)同一提交

## Skill 基线

Agent skills 分两类管理:

- **项目内建**:随仓库提交在 `.agents/skills/`,由 `skills-lock.json`
  按内容哈希锁定,对进入本仓库的任何 AI 工具生效。当前:
  `shadcn`(shadcn/ui 组件开发约定)
- **每机自装**:装在本机全局(如 `~/.claude/skills/`),不入库;新
  机器先按清单安装再开工。当前:(无)
