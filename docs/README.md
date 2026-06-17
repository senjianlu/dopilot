# dopilot 改造文档

本目录沉淀 dopilot（基于 [scrapydweb](https://github.com/my8100/scrapydweb) 改造的私有调度平台）的**现状架构**与**改造方案**。所有文档为简体中文，关键断言均对照源码标注 `file:line`，并经多轮代码校验。

> 📁 **现状代码（scrapydweb 本体）位于 `reference/scrapydweb/`**。本套文档中的 `scrapydweb/…`、`setup.py`、`tests/` 等路径均相对该目录（完整路径 = `reference/scrapydweb/<路径>`）。

## 推荐阅读顺序

1. **先看目标**：[`dopilot/00-requirements.md`](dopilot/00-requirements.md) —— 需求、已确认决策、四阶段路线、server/agent 部署。
2. **再看总纲**：[`dopilot/10-roadmap.md`](dopilot/10-roadmap.md) —— 综合改造路线图，串联现状+gap+决策。
3. **按需深入**：现状看 `architecture/`，改造看 `dopilot/0x-gap-*`。

## 一、现状架构（`architecture/`）

> scrapydweb 的工作原理，作为改造基线。

| 文档 | 内容 |
|------|------|
| [`00-overview.md`](architecture/00-overview.md) | 架构总览、技术栈、请求/数据生命周期、ASCII 全景图 |
| [`01-bootstrap-and-config.md`](architecture/01-bootstrap-and-config.md) | 启动序列、CLI、app factory、配置加载与覆盖 |
| [`02-data-model.md`](architecture/02-data-model.md) | ORM 模型、4 个 bind、DB 位置、定时/job 表结构 |
| [`03-scheduler-engine.md`](architecture/03-scheduler-engine.md) | **调度核心**：timer 任务端到端、APScheduler 集成 |
| [`04-views-and-frontend.md`](architecture/04-views-and-frontend.md) | blueprint/路由目录、视图基类、模板继承、前端现状 |
| [`05-scrapyd-cluster-io.md`](architecture/05-scrapyd-cluster-io.md) | 多节点通信、scrapyd API 封装、logparser |
| [`06-auth-and-utils.md`](architecture/06-auth-and-utils.md) | HTTP Basic Auth、三个后台子进程、邮件告警 |

## 二、改造方案（`dopilot/`）

| 文档 | 内容 |
|------|------|
| [`00-requirements.md`](dopilot/00-requirements.md) | **北极星**：需求、决策表、四阶段路线、部署图 |
| [`01-gap-executors.md`](dopilot/01-gap-executors.md) | 多类型执行器抽象（Scrapy/脚本/Docker）—— 方案 A |
| [`02-gap-scheduling-nodes-push.md`](dopilot/02-gap-scheduling-nodes-push.md) | 定时 + 节点策略(指定/全部/随机) + 推模式 |
| [`03-gap-realtime-logs.md`](dopilot/03-gap-realtime-logs.md) | 实时日志 —— SSE + LogSource 抽象 |
| [`04-gap-i18n.md`](dopilot/04-gap-i18n.md) | 国际化（默认中文）—— Flask-Babel + vue-i18n |
| [`05-dev-setup-and-known-issues.md`](dopilot/05-dev-setup-and-known-issues.md) | 环境搭建 + `pkg_resources` 等已知坑 |
| [`06-frontend-rewrite.md`](dopilot/06-frontend-rewrite.md) | 前端整体重构（Vue 3 + Element Plus + 渐进式） |
| [`07-testing-baseline.md`](dopilot/07-testing-baseline.md) | 测试与回归基线（零回归安全网） |
| [`08-docker-deployment.md`](dopilot/08-docker-deployment.md) | server/agent Docker 化 + 数据持久化 |
| [`09-package-rename.md`](dopilot/09-package-rename.md) | scrapydweb→dopilot 改名影响面 |
| [`10-roadmap.md`](dopilot/10-roadmap.md) | **综合改造路线图（总纲）** |

## 决策速查

- **三类被调度对象**：Scrapy(scrapyd) → Python 脚本 → Docker 长连接（按此优先级分期）
- **部署**：server（调度中心+Web）/ agent（worker 节点），均 Docker
- **推模式**：主动下发到指定 worker 立即执行
- **认证**：单用户唯一管理员
- **前端**：Vue 3 + Element Plus + Vite + TS，前后端分离，渐进式 strangler
- **实时日志**：SSE（单向流，纯 WSGI 可跑）
- **镜像发布**：构建推送到 Docker Hub `rabbir/dopilot:latest`（agent 为 `rabbir/dopilot-agent:latest`）；镜像命名空间 `rabbir` ≠ git origin `senjianlu`
- **仓库结构**：monorepo —— server + agent 同仓开发，`reference/scrapydweb/` 仅基线参考、不参与构建
