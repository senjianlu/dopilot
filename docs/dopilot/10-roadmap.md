# dopilot —— 综合改造路线图（总纲）

> 本文串联**现状**（`docs/architecture/`）+ **差距分析**（`docs/dopilot/0x-gap-*`）+ **用户决策**（`00-requirements.md`），给出分阶段 backlog 与依赖顺序。
> 细节不在此复述，请点进对应文档。区分：✅ 复用现状 / 🟡 扩展现状 / 🆕 全新。

## 0. 总览

分期沿用 `00-requirements.md`：**阶段0 基座 → 阶段1 Scrapy 跑稳 → 阶段2 Python 脚本 → 阶段3 Docker 长连接**。核心原则：**一类做稳再上下一类**。

```
抽象先行(贯穿)   ┌─ BaseExecutor 执行器抽象 ─┬─ LogSource 日志源抽象 ─┬─ node_strategy 节点策略 ─┐
                │   (01-gap §6 方案A)        │  (03-gap §4 SSE)       │  (02-gap §3 方案A)        │
阶段0 基座 ─────┼────────────────────────────┴────────────────────────┴──────────────────────────┤
阶段1 Scrapy ───┤  ScrapydExecutor(收敛现网,零回归) + 定时 + 节点策略 + 推模式 + 前端 M1~M3        │
阶段2 脚本 ─────┤  ScriptExecutor + dopilot-agent worker 落地 + 脚本日志源                         │
阶段3 长连接 ───┤  DockerExecutor(Docker/K3s SDK) + 容器生命周期 + 容器日志源                      │
                └─────────────────────────────────────────────────────────────────────────────────┘
```

## 1. 贯穿全程的三条抽象主线（务必"先抽象"）

> 这三条是避免"三类执行器各改一遍"的关键，应在阶段0/1 就立好接口。

| 抽象 | 作用 | 来源 | 推荐方案 |
|------|------|------|---------|
| **`BaseExecutor`** | 按 `task_type` 多态分派下发/运行；scrapyd / 脚本 / docker 各实现一个 | `01-gap-executors.md` §6 | 方案 A（抽象 + 多态）；通道集中式先用方案 C，终态分布式走方案 B(worker agent) |
| **`LogSource`** | 统一三类日志来源（scrapyd 日志文件 / 脚本 stdout / 容器 logs）为同一流 | `03-gap-realtime-logs.md` §4 | **SSE**（纯 WSGI、单向推送）+ LogSource 抽象，分两步 |
| **`node_strategy`** | 节点选择三态：指定 / 全部 / 随机；触发时动态归约 | `02-gap-scheduling-nodes-push.md` §3 | 方案 A（Task 加 `node_strategy`，默认 `all`，random→`random.choice`） |

## 2. 阶段 0：平台基座

| Epic | 类型 | 说明 | 文档 |
|------|------|------|------|
| 改名 scrapydweb→dopilot | 🟡 | 评估影响面后决定全量改包 vs 仅改 UI/命令名 | `09-package-rename.md` |
| 单管理员 token 认证 | 🟡 | HTTP Basic → token 登录（单用户，无需 RBAC） | `06-frontend-rewrite.md` §5、`architecture/06-auth-and-utils.md` |
| 前端骨架 M0 | 🆕 | Vite+Vue3+EP+TS + 登录/布局/菜单 + axios + SSE 客户端 | `06-frontend-rewrite.md` §2 |
| i18n 框架 | 🆕 | 过渡期：旧 Jinja2 用 Flask-Babel(方案B)；新 SPA 用 vue-i18n；默认中文 | `04-gap-i18n.md` §7、`06-frontend-rewrite.md` §7 |
| server/agent Docker 化 | 🆕 | 两种镜像 + 卷持久化（注意 `vars.py` 启动清目录坑） | `08-docker-deployment.md` |
| 镜像构建发布 + CI | 🆕 | Dockerfile.server/agent + `.dockerignore`（排除 `reference/`）+ GitHub Actions 推送 `rabbir/dopilot:latest`（决策 7、monorepo 决策 8） | `08-docker-deployment.md` §7 |
| 测试回归基线 | ✅ | 固化 `tests/` 为"零回归"安全网，明确复跑方式 | `07-testing-baseline.md` |
| 实时日志框架(第一步) | 🆕 | SSE + LogSource 主干，先打通 scrapyd | `03-gap-realtime-logs.md` §4 |

## 3. 阶段 1：Scrapy 跑稳（scrapyd 唯一节点）

| Epic | 类型 | 说明 | 文档 |
|------|------|------|------|
| `ScrapydExecutor` | 🟡 | 把现有 scrapyd 下发链路收敛进 `BaseExecutor`，**保证现网零回归** | `01-gap-executors.md` §6.4 |
| 定时任务 | ✅ | 复用现有 APScheduler + Task 双存储，**不重写** | `02-gap` §2.5、`architecture/03-scheduler-engine.md` |
| 节点策略(指定/全部/随机) | 🟡 | Task 加 `node_strategy`，触发动态归约 | `02-gap` §3 |
| 推模式(立即下发) | 🟡 | Executor 抽象 + 独立推送端点，下发到指定节点立即执行 | `02-gap` §4 |
| 前端迁移 M1~M3 | 🆕 | servers/jobs(M1) → 实时日志/stats(M2) → schedule/tasks(M3，含节点策略+推模式 UI) | `06-frontend-rewrite.md` §2 |

## 4. 阶段 2：Python 脚本（新 dopilot-agent worker）

| Epic | 类型 | 说明 | 文档 |
|------|------|------|------|
| `ScriptExecutor` | 🆕 | 一次性 Python3 脚本执行器 | `01-gap-executors.md` §6 |
| dopilot-agent worker | 🆕 | 终态分布式通道落地（方案B），Docker 容器形态 | `01-gap` §6.3、`08-docker-deployment.md` |
| 脚本日志源 | 🆕 | LogSource 接 stdout | `03-gap-realtime-logs.md` §2 |
| 定时/节点/推模式 | ✅ | 复用阶段1 已建能力 | `02-gap` |

## 5. 阶段 3：Docker 长连接爬虫（最后）

| Epic | 类型 | 说明 | 文档 |
|------|------|------|------|
| `DockerExecutor` | 🆕 | Docker / K3s API SDK 启停容器 | `01-gap-executors.md` §6 |
| 容器生命周期 | 🆕 | 常驻语义，**注意与 scrapyd finished 状态机冲突** | `01-gap` §1.6、§2 |
| 容器日志源 | 🆕 | LogSource 接容器 logs | `03-gap-realtime-logs.md` §2 |
| "定时"语义定义 | ❓ | 定时启新容器 vs 对常驻容器发指令——先定义再实现 | `02-gap` §2.3 开放问题 |

## 6. 关键依赖顺序

```
测试基线(07) ──► 一切改造的前置安全网
改名评估(09) ─┐
token认证 ────┼─► 前端骨架 M0 ──► 前端迁移 M1~M3
Docker化(08) ─┘
BaseExecutor 抽象 ──► ScrapydExecutor(阶段1) ──► ScriptExecutor(阶段2) ──► DockerExecutor(阶段3)
LogSource+SSE 抽象 ──► scrapyd日志 ──► 脚本stdout ──► 容器logs
node_strategy ──► (阶段1 起对所有 Executor 生效)
```

## 7. 跨文档开放问题（实作前需逐一确认）

> 完整清单见各 gap 文档末节"开放问题"。以下为影响架构的关键项：

| # | 开放问题 | 来源 | 现状 |
|---|---------|------|------|
| 1 | worker agent 与 server 的通信协议（HTTP 回调 / 消息队列） | `01-gap` §8 | 待定 |
| 2 | Docker 长连接的"定时"语义（启新容器 vs 发指令） | `02-gap` §2.3 | 待定（阶段3 前定） |
| 3 | JS 文案 i18n 策略（context_processor 注入字典 为推荐） | `04-gap` §4 | 倾向注入字典 |
| 4 | SPA 托管：Flask 内置 vs 镜像内 nginx | `06-frontend` §9 | 待定 |
| 5 | token 形式：JWT vs 服务端 session token | `06-frontend` §9 | 待定（单用户都可） |
| 6 | 改名范围：阶段0 全量改包 vs 仅 UI/命令名 | `09-package-rename` | 待评估面后定 |
| 7 | 容器持久化卷边界（哪些目录随卷、哪些可清） | `08-docker` | 待定 |

## 8. 文档矩阵（按阶段查阅）

| 阶段 | 必读现状 | 必读改造 |
|------|---------|---------|
| 阶段0 | `architecture/00,01,06` | `dopilot/05,06,07,08,09` |
| 阶段1 | `architecture/02,03,04,05` | `dopilot/01,02,03,06` |
| 阶段2 | `architecture/01,02` | `dopilot/01,08` |
| 阶段3 | `architecture/05` | `dopilot/01,02,03` |
