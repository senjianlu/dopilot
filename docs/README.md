# dopilot 文档

本目录沉淀 dopilot（私有调度平台）的**设计与实现方案**,以及 scrapydweb 的**现状行为参考**。所有文档为简体中文，关键断言均对照源码标注 `file:line`，并经多轮代码校验。

> **【scrapydweb 参考边界】** dopilot 为 **greenfield**(全新编写,按 `apps/`+`packages/` 自有领域 structure-first 设计;权威布局见 [`dopilot/05-dev-setup-and-known-issues.md`](dopilot/05-dev-setup-and-known-issues.md) §1)。scrapydweb（[原项目](https://github.com/my8100/scrapydweb)）仅作**功能层/行为参考**与**测试 oracle**;其代码写法、目录结构、模块划分、命名、依赖、配置形态**一律不得作为 dopilot 设计依据**,也**不做改名/git mv**。详见 [`dopilot/00-requirements.md`](dopilot/00-requirements.md) 决策表。

> 📁 **scrapydweb 本体(只读行为参考)位于 `reference/scrapydweb/`**。本套文档中的 `scrapydweb/…`、`setup.py`、`tests/` 等路径均相对该目录（完整路径 = `reference/scrapydweb/<路径>`）;它不参与 dopilot 构建、不被 import、不改名。

## 推荐阅读顺序

1. **先看目标**：[`dopilot/00-requirements.md`](dopilot/00-requirements.md) —— 需求、已确认决策、四阶段路线、server/agent 部署。
2. **再看总纲**：[`dopilot/10-roadmap.md`](dopilot/10-roadmap.md) —— 综合 greenfield 构建/移植路线图，串联 scrapydweb 行为参考+gap+决策。
3. **开始实现**：阶段 0 直接看 [`phases/phase-0/00-brief.md`](phases/phase-0/00-brief.md) —— 给 Claude 编码用的任务书与 Codex review/验收清单。
4. **按需深入**：scrapydweb 行为参考看 `architecture/`，dopilot 设计/实现看 `dopilot/0x-gap-*`。
5. **重构提案**：[`refactor/00-redis-streams-agent-communication.md`](refactor/00-redis-streams-agent-communication.md) —— server/agent 通信改为 Redis Streams 的破坏性重构概念文档。

## 一、scrapydweb 现状行为参考（`architecture/`）

> scrapydweb 的工作原理,作为 dopilot 的**功能层/行为参考**(非待改文件、非结构模板);dopilot 在 `apps/` 下全新复刻所需行为。

| 文档 | 内容 |
|------|------|
| [`00-overview.md`](architecture/00-overview.md) | 架构总览、技术栈、请求/数据生命周期、ASCII 全景图 |
| [`01-bootstrap-and-config.md`](architecture/01-bootstrap-and-config.md) | 启动序列、CLI、app factory、配置加载与覆盖 |
| [`02-data-model.md`](architecture/02-data-model.md) | ORM 模型、4 个 bind、DB 位置、定时/job 表结构 |
| [`03-scheduler-engine.md`](architecture/03-scheduler-engine.md) | **调度核心**：timer 任务端到端、APScheduler 集成 |
| [`04-views-and-frontend.md`](architecture/04-views-and-frontend.md) | blueprint/路由目录、视图基类、模板继承、前端现状 |
| [`05-scrapyd-cluster-io.md`](architecture/05-scrapyd-cluster-io.md) | 多节点通信、scrapyd API 封装、logparser |
| [`06-auth-and-utils.md`](architecture/06-auth-and-utils.md) | HTTP Basic Auth、三个后台子进程、邮件告警 |

## 二、dopilot 设计与实现方案（`dopilot/`）

| 文档 | 内容 |
|------|------|
| [`00-requirements.md`](dopilot/00-requirements.md) | **北极星**：需求、决策表、四阶段路线、部署图 |
| [`01-gap-executors.md`](dopilot/01-gap-executors.md) | 多类型执行器抽象（Scrapy/脚本/Docker）—— 方案 A |
| [`02-gap-scheduling-nodes-push.md`](dopilot/02-gap-scheduling-nodes-push.md) | 定时 + 节点策略(指定/全部/随机) + 推模式 |
| [`03-gap-realtime-logs.md`](dopilot/03-gap-realtime-logs.md) | 实时日志 —— agent 经 Redis log stream 主动推增量、server 消费落盘（`RedisLogSource`，详见 [`refactor/00`](refactor/00-redis-streams-agent-communication.md)）+ server→web SSE，正文落 /server-data/logs、索引/offset/状态落 PostgreSQL；第一版无 WebSocket |
| [`04-gap-i18n.md`](dopilot/04-gap-i18n.md) | 国际化（默认中文）—— 前端 react-i18next（阶段 2.1 起，原 vue-i18n；greenfield，不用 Flask-Babel） |
| [`05-dev-setup-and-known-issues.md`](dopilot/05-dev-setup-and-known-issues.md) | 环境搭建 + `pkg_resources` 等已知坑 |
| [`06-frontend-rewrite.md`](dopilot/06-frontend-rewrite.md) | 前端整体构建（greenfield SPA，分阶段交付；阶段 2.1 起 Next.js 静态导出 + shadcn/ui，替换原 Vue/Element Plus 选型） |
| [`07-testing-baseline.md`](dopilot/07-testing-baseline.md) | 测试基线（scrapydweb 测试=reference 行为 oracle；dopilot 自有测试在 apps/*/tests） |
| [`08-docker-deployment.md`](dopilot/08-docker-deployment.md) | server/agent Docker 化 + 数据持久化 |
| [`09-package-rename.md`](dopilot/09-package-rename.md) | scrapydweb 行为/契约移植注意事项（非改名；保留耦合点分析供移植参考） |
| [`10-roadmap.md`](dopilot/10-roadmap.md) | **综合 greenfield 构建/移植路线图（总纲）** |

## 三、阶段开发执行文档（`phases/`）

阶段开发文档与主线设计文档分开管理。每个阶段单独建目录，并按执行顺序用 `00-`、`01-`、`02-` 前缀排序。阶段结束后，只把长期有效的架构事实同步回 `dopilot/` 主线文档。

| 文档 | 内容 |
|------|------|
| [`phase-0/00-brief.md`](phases/phase-0/00-brief.md) | 阶段 0 实现任务书 |
| [`phase-0/01-review.md`](phases/phase-0/01-review.md) | 阶段 0 review 与返工清单 |
| [`phase-0/02-review-response.md`](phases/phase-0/02-review-response.md) | 阶段 0 返工响应 |
| [`phase-0/03-acceptance.md`](phases/phase-0/03-acceptance.md) | 阶段 0 验收记录 |
| [`phase-1/00-brief.md`](phases/phase-1/00-brief.md) | 阶段 1 实现任务书 |
| [`phase-1.5/00-brief.md`](phases/phase-1.5/00-brief.md) | 阶段 1.5 重构任务书 —— server↔agent 通信 HTTP pull → Redis Streams（设计真相见 [`refactor/00`](refactor/00-redis-streams-agent-communication.md)） |

## 四、重构概念文档（`refactor/`）

该目录记录尚未合并进主线设计的重构概念、破坏性调整方案和审阅材料。此类文档用于方案评审与改修点整理，不直接覆盖 `dopilot/` 下的当前权威设计。

| 文档 | 内容 |
|------|------|
| [`00-redis-streams-agent-communication.md`](refactor/00-redis-streams-agent-communication.md) | server/agent 任务调度、状态事件、日志回流改为 Redis Streams；健康检查改为 agent 主动 heartbeat 到 server API；不保留 HTTP 调度/状态/日志兜底链路 |

## 决策速查

- **三类被调度对象**：Scrapy(scrapyd) → Python 脚本 → Docker 长连接（按此优先级分期）
- **部署**：server（调度中心+Web）/ agent（worker 节点），均 Docker
- **推模式**：主动下发到指定 worker 立即执行
- **认证**：单用户唯一管理员
- **后端**：FastAPI + Pydantic + ASGI（`apps/server`），提供 `/api/v1/*` JSON/SSE API
- **前端**：Next.js 静态导出（`output: export`）+ shadcn/ui + Recharts + TS（`apps/web`，自阶段 2.1 起替换原 Vue 3 + Element Plus 选型），前后端分离，**greenfield SPA** 直连 `/api/v1`、分阶段交付页面（无 Jinja 共存/strangler）；静态产物由 dopilot-server 托管，无独立 Web 容器/Node 生产运行时
- **数据库**：PostgreSQL 唯一数据库，SQLAlchemy + 裸 Alembic（FastAPI 无 Flask，不用 Flask-Migrate）；PG 存业务数据 + 日志索引/offset/状态（表 `execution_log_files`），**日志正文不进 PG，落 server 本地卷 `/server-data/logs`**
- **实时日志**：~~server 按需从 agent tail API（HTTP `GET /logs/tail`）拉取日志增量~~ **现以 [`refactor/00-redis-streams-agent-communication.md`](refactor/00-redis-streams-agent-communication.md) 新模型为准**：改为 **agent 主动经 Redis 日志 stream（`dopilot:server:logs`，base64 字节 + offset/size_bytes/eof）推送增量、server 消费后落盘**；保留四个不变量 —— 第一版不用 WebSocket、server→web SSE、正文落 `/server-data/logs`、PostgreSQL 只存索引/offset/状态。`LogSource` 抽象保留，实现由 `AgentTailLogSource`（server pull）换为 `RedisLogSource`（agent push + server consume）。日志 RPO≠0：server 长停或 Redis 裁剪致 `partial`（新增 `log_integrity` 列），与业务状态分离、不阻塞执行收敛
- **镜像发布**：构建推送到 Docker Hub `rabbir/dopilot:latest`；server / agent / migrate 使用同一镜像，通过启动命令选择角色；镜像命名空间 `rabbir` ≠ git origin `senjianlu`
- **仓库结构**：monorepo（`apps/{server,agent,web}` + `packages/{protocol,client}`，权威布局见 `dopilot/05-dev-setup-and-known-issues.md` §1）—— 全新编写，`reference/scrapydweb/` 仅行为参考、不参与构建/不被 import/不改名
