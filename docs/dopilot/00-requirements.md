# dopilot —— 需求与目标（北极星文档）

> 本文记录 dopilot 的产品目标与改造需求，是后续所有架构/改造文档的依据。
> 内容来自用户口述，已标注我方理解与**待确认点**。如与用户最新意见冲突，以用户为准。

## 1. 背景

dopilot 是在开源项目 [scrapydweb](https://github.com/my8100/scrapydweb)（Flask 实现的 Scrapyd 集群管理 / 调度 Web 平台）基础上改造而来的**私有调度平台**。

- scrapydweb 本体作为**参考代码**置于 `reference/scrapydweb/`（保留上游完整目录结构）；dopilot 自身文档/代码在仓库根，保留 dopilot git 历史（origin: `senjianlu/dopilot`）。
- 上游以 `upstream` 远程保留（`my8100/scrapydweb`），便于后续 diff / cherry-pick 修复，但不合并其历史。
- 导入快照版本：scrapydweb `1.6.0`，上游 commit `1341cf9`（该 hash 来自上游仓库；本仓库为压缩后的单个 `Initial commit`，需 `git fetch upstream` 后才能 `git show 1341cf9` 核对）。

## 2. 需要支持的「被调度对象」（三类）

| # | 类型 | 说明 | scrapydweb 现状 |
|---|------|------|----------------|
| 1 | **Scrapy 框架爬虫** | 经由 scrapyd 部署(egg)与调度 | ✅ 原生支持 |
| 2 | **Docker 容器内长连接爬虫** | 运行在 Docker 容器中的**长连接 / 常驻进程**（不是跑完即退） | ❌ 不支持，需新增执行器 |
| 3 | **简单 Python3 脚本** | 一次性的普通 Python 脚本任务 | ❌ 不支持，需新增执行器 |

> 核心架构挑战：scrapydweb 完全围绕 scrapyd 协议（egg 部署 + schedule API）。类型 2、3 需要引入**执行器（Executor / Runner）抽象层**，详见 `docs/dopilot/01-gap-executors.md`。

## 3. 需要支持的「平台功能」（五项）

| # | 功能 | 要点 | scrapydweb 现状（待 workflow 核实） |
|---|------|------|--------------------------------|
| 1 | **实时日志** | 实时日志流，而非刷新页面看日志文件 | 现为 logparser 解析日志文件 + 轮询/iframe，非实时流 |
| 2 | **定时任务设置** | cron / interval 定时调度 | ✅ 已有基于 APScheduler 的 timer task，可复用扩展 |
| 3 | **节点选择策略** | 可指定 worker 节点；可选「指定节点**全部**执行」或「**随机**选一个节点执行」 | 支持多节点选择执行，随机策略待确认 |
| 4 | **推模式指定执行** | push 模式：主动下发任务到指定节点执行 | 待核实现状语义 |
| 5 | **多语言 i18n** | 预留国际化框架，**当前只需中文** | 模板存在中英文案，需引入正式 i18n 框架 |

## 4. 已确认的关键决策（用户拍板，2026-06-17）

| # | 问题 | 决策 |
|---|------|------|
| 1 | Docker 长连接爬虫管理边界 | 通过 **Docker / K3s API SDK** 启停容器。**优先级最低**：等 Scrapy 与 Python 脚本两类都支持并稳定后才开发。 |
| 2 | 「推模式」语义 | **下发到指定 worker 立即执行**（平台主动 push，与定时/拉相对）。 |
| 3 | worker 节点形态 | **暂时仅 scrapyd 唯一节点**。待 Scrapy 爬虫稳定后，再加入对「类型 3 Python 脚本」的 worker 节点支持；节点预计以**完整 Docker 容器**形式部署。 |
| 4 | 用户 / 权限体系 | **单用户、唯一管理员**。无需多用户/角色，保留并简化为单管理员认证即可。 |
| 5 | dopilot 自身部署形态 | 分 **server**（调度中心 + Web）与 **agent**（worker 节点）两种部署角色，**均使用 Docker 部署**。 |
| 6 | 前端技术栈（整体重构） | **Vue 3 + Element Plus + Vite + TypeScript**；走**前后端分离**（Flask 收敛为 `/api/v1/*` JSON API）；**渐进式 strangler** 迁移（搭 SPA 骨架后按页迁移，新旧共存）。归属**阶段 0**。详见 `docs/dopilot/06-frontend-rewrite.md`。 |

## 5. 分期路线（由决策推导）

> 核心原则：**一类一类做，做稳一类再上下一类**。

| 阶段 | 目标 | 被调度对象 | 节点形态 | 说明 |
|------|------|-----------|---------|------|
| 阶段 0 | 平台基座 | —— | —— | 改名 dopilot、单管理员认证、i18n(中文)、server/agent 的 Docker 化部署骨架、实时日志框架 |
| 阶段 1 | Scrapy 优先跑稳 | 类型 1（Scrapy） | scrapyd（唯一） | 复用 scrapydweb 既有能力 + 定时 + 节点策略(指定/全部/随机) + 推模式立即下发 |
| 阶段 2 | 接入脚本 | 类型 3（Python 脚本） | 新增脚本 worker agent（Docker 容器） | 引入执行器抽象，agent 角色落地 |
| 阶段 3 | 接入长连接 | 类型 2（Docker 长连接爬虫） | Docker / K3s API SDK | 容器生命周期管理，最后开发 |

### server / agent 部署形态（初步）

```
┌─────────────────────────────┐        ┌──────────────────────────┐
│  dopilot-server (Docker)    │  push  │  dopilot-agent (Docker)  │
│  - Flask Web + 调度中心     │ ─────► │  - scrapyd (阶段1)       │
│  - APScheduler 定时         │        │  - 脚本 worker (阶段2)   │
│  - DB / 实时日志聚合        │ ◄───── │  - 容器管理 (阶段3)      │
│  - 单管理员认证             │  日志  │                          │
└─────────────────────────────┘        └──────────────────────────┘
                                  (agent 可多实例 = 多 worker 节点)
```

## 6. 文档导航

- 现状架构：`docs/architecture/`（总览、启动配置、数据模型、调度引擎、视图前端、scrapyd 通信、认证工具）
- 改造分析：`docs/dopilot/`（执行器、定时+节点+推模式、实时日志、i18n、本需求文档、开发环境）
