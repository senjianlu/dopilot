# dopilot —— 开发环境搭建与已知问题

> 记录本地导入、依赖安装、以及当前已发现的兼容性问题与修复方案。

## 1. 仓库与远程

本仓库为 **monorepo**（`00-requirements.md` 决策 8）：server 与 agent 同仓开发，`reference/` 仅作基线参考、不参与构建。

```
/workspaces/dopilot/            <- dopilot 仓库（origin: senjianlu/dopilot）
├── reference/
│   └── scrapydweb/             <- scrapydweb 1.6.0 本体（参考代码，保留上游目录结构，不参与构建）
│       ├── scrapydweb/         <- 应用包
│       ├── setup.py / requirements.txt / tests/ / screenshots/
│       └── UPSTREAM_README.md / README_CN.md / LICENSE / MANIFEST.in
├── README.md                   <- dopilot 自己的 README
├── docs/                       <- 本套文档（architecture/ 现状 + dopilot/ 改造）
│
│   # —— 以下为阶段 0 起逐步落地的 dopilot 自身代码（monorepo，当前尚未创建）——
├── dopilot/                    <- 应用包（scrapydweb 改名而来，见 09-package-rename.md）
├── agent/                      <- worker 执行器（阶段 2 起，见 01-gap-executors.md）
├── frontend/                   <- Vue3 + Element Plus + Vite SPA（见 06-frontend-rewrite.md）
├── Dockerfile.server / Dockerfile.agent / .dockerignore   <- 镜像构建（见 08 §7）
└── .github/workflows/docker.yml                           <- CI 推送 rabbir/dopilot:latest（见 08 §7.4）
```

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

```bash
cd /workspaces/dopilot
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip wheel
pip install -e reference/scrapydweb   # editable 安装 scrapydweb 及其依赖（代码现位于 reference/ 下）
# 关键修复（见下文「已知问题」）：
pip install "setuptools<81"
```

依赖均能在 Python 3.12 上正常编译安装（含旧版 SQLAlchemy 1.3.24、MarkupSafe 2.0.0、tzlocal 1.5.1 的 C 扩展 wheel 构建）。

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

建议后续把选定方案固化进 `requirements.txt`（例如 pin `setuptools<81`，或改 `APScheduler>=3.10,<4`）。

## 5. 首次运行（待补）

scrapydweb 首次运行会在工作目录生成默认 `scrapydweb_settings_v11.py` 配置文件（文件名硬编码于 `scrapydweb/vars.py:29` `SCRAPYDWEB_SETTINGS_PY`），需在其中配置 `SCRAPYD_SERVERS` 等。完整启动步骤待依赖问题修复、跑通后补充到本文。

相关：配置加载顺序见 `docs/architecture/01-bootstrap-and-config.md`。

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
| `playwright` | 仓库根 `.mcp.json`(项目级、已签入 git) | 驱动浏览器测试 Vue3 + Element Plus 前端功能点 | 靠 `npx -y @playwright/mcp@latest` 拉起,需先装 Node |

> 选型：相比 chrome-devtools MCP,Playwright MCP 更通用、可自带下载 Chromium,适合常规页面功能点测试。后续若需深挖 SSE 实时日志的 EventStream/网络面板,可再叠加 chrome-devtools MCP。
> Docker 侧刻意**不引入 Docker MCP**——目标 ② 全程用 Bash 调 Docker CLI 即可,且 `08-docker-deployment.md` 已规划好 `Dockerfile.server` / `Dockerfile.agent` / compose。

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
