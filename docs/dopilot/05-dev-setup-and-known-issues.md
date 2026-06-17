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
