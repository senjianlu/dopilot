# dopilot —— 测试基线：reference 行为 oracle + dopilot 自有测试

> **【scrapydweb 参考边界】** scrapydweb 仅作**功能层/行为参考**与**测试 oracle**；其代码写法、目录结构、模块划分、命名、依赖、配置形态**一律不得作为 dopilot 的设计依据**。dopilot 为 greenfield、按 `apps/`+`packages/` 自有领域 structure-first 设计（权威布局见 `05-dev-setup-and-known-issues.md` §1），**不对 scrapydweb 做改名/git mv**。详见 `00-requirements.md` 决策表。

> 本文有两个清晰层次，**不要混淆**：
> - **(A) scrapydweb 测试 = reference 基线行为的 oracle / 行为预期对照**。scrapydweb 的 `tests/` 验证的是 reference 自身的基线行为；dopilot 移植某个域（executors / logs / scheduler / API）时，读它、提取其"输入→输出语义"作为对照清单，用来校验 dopilot 全新实现的行为语义是否与 reference 等价。它**不是** dopilot 的回归网，也不是任何"立即合入"的门禁。
> - **(B) dopilot 自有测试基线**。dopilot 从第一天起就在 `apps/server/tests/`、`apps/agent/tests/`、`apps/web`（vitest/e2e）、`packages/protocol`（schema 校验）中写自己的测试，绑定 dopilot CI 门禁。这才是 dopilot 的回归网。
>
> 本文严格区分【reference 行为事实】（已 Read/Grep 核实，引用 `file:line`，路径相对上游 scrapydweb 1.6.0 / commit `1341cf9`；本仓库不保留本地快照）与【dopilot 测试设计 / 开放问题】（待决策）。

> **⚠️【阶段 2.1 前端测试栈已更新】** 自**阶段 2.1**起前端迁移为 **Next.js（静态导出）+ shadcn/ui + Recharts + react-i18next**，对应**前端单测/组件测试用 vitest + @testing-library/react + jsdom**（旧 Vue Test Utils 已弃用），**e2e 仍为 Playwright** 但选择器由 Element Plus 类（`el-tag--*` 等）改为 `data-tone`/`data-testid`，任务详情路由为 `/tasks/detail?id=<id>`，前端 lint 为 `eslint .`（flat config）。下文涉及前端测试框架、选择器、目录与命令的旧 Vue/Vite/Element Plus 指引一律以阶段 2.1 为准；权威说明见 `docs/dopilot/06-frontend-rewrite.md` 顶部对照表与 `docs/phases/phase-2.1/01-claude-implementation-report.md`。

---

## 0. 一句话结论

| 维度 | 结论 |
|------|------|
| 测试是否存在 | 是。`tests/` 下 20 个 `test_*.py`，共 **146 个 `test_` 函数**（`grep -rh "^def test_" tests/test_*.py \| wc -l`）。 |
| 是不是真单测 | 不是。**绝大多数是集成测试**，依赖一个真实运行的 Scrapyd（`127.0.0.1:6800`，账号 `admin/12345`）。 |
| 当前能否在 Python 3.12 跑通 | **不能，开箱即挂**。`import scrapydweb` 因 `pkg_resources` 缺失直接抛 `ModuleNotFoundError`（已复现，见 §3）。且当前 `.venv` 未装测试依赖（无 pytest/scrapy/scrapyd）。 |
| 作为 reference 行为 oracle 的覆盖面 | 方向够：覆盖了 reference 的部署/调度/API/日志/告警/任务全链路行为语义，便于 dopilot 各域移植时对照。但作为 oracle 有局限：强依赖外部 Scrapyd、依赖外网（QQ/Slack/Telegram）、断言绑死 HTML 文案、无 executor 层语义单测——因此只能对照 reference 的**黑盒行为**，无法给出内部契约。dopilot 自己的回归由 `apps/*/tests/` 承担，详见 §4–§5。 |

---

## 1. scrapydweb `tests/` 覆盖了哪些 reference 行为语义（逐文件 oracle 清单）

> 本节逐文件梳理 scrapydweb 测试**锁定了 reference 的哪些行为语义**，作为 dopilot 各域移植时的"行为预期对照清单"。这些是对上游 scrapydweb（外部查阅）的只读观测，**不是 dopilot 的用例**——dopilot 在 `apps/*/tests/` 中针对相应语义点编写自己的测试。

### 1.1 目录与支撑文件

| 文件 | 行数/大小 | 作用（现状事实） |
|------|-----------|------------------|
| `tests/__init__.py` | 空 | 让 `tests` 成为包，使 `from tests.utils import ...` 可用（`conftest.py:7`）。 |
| `tests/conftest.py` | 120 行 | 全局 fixture 与测试环境初始化。定义 `custom_settings`（`conftest.py:15`）、`app`/`client`/`runner` 三个 fixture，并在导入时调用 `setup_env()`（`conftest.py:50`）。 |
| `tests/utils.py` | 308 行 | 测试工具库：`Constant` 常量类（`utils.py:21`）、核心断言函数 `req()`（`utils.py:102`）、`setup_env()`（`utils.py:227`）、`upload_file_deploy()`（`utils.py:285`）、`switch_scrapyd()`/`set_single_scrapyd()` 等。 |
| `tests/data.zip` | 277 KB / 206 文件 | 测试夹具数据，由 `setup_env()` 解压到 `tests/data/`（`utils.py:255-256`）。 |

**`data.zip` 里有什么（已 `unzip -l` 核实）**：

- **Scrapy 项目源码包**：`demo/`、`demo - 副本/`（中文名，测 Unicode）、`demo_only_scrapy_cfg/`、`demo_without_scrapy_cfg/` 等 14 个项目（`test_deploy.py:18` 断言 `(14 projects)`）。
- **各平台/编码打包产物**：`.zip` / `.tar.gz` / `.egg`，覆盖 Win7CN、Win10cp936/cp1252、Ubuntu、macOS 多组合（`test_deploy.py:118-126` 的 `filenames` 列表逐一上传）。
- **预生成日志/统计夹具**：`data/ScrapydWeb_demo.log`（15868 字节，真实 scrapy 运行日志），`setup_env()` 据此派生 `ScrapydWeb_demo.log` 与 `ScrapydWeb_demo_unfinished.log`（把 `'finish_reason'` 替换成 `'finish_reason_removed'` 造未完成态，`utils.py:264-270`），喂给 LogParser 相关测试。
- **多种 egg 变体**：`ScrapydWeb_demo.egg`、`..._no_delay.egg`、`..._no_request.egg`、`..._no_request_no_logstats.egg`，用于构造不同运行结果以测告警/统计分支。

### 1.2 逐个 `test_*.py` 文件作用

> 命名前缀决定 pytest 收集/执行顺序（按文件名字母序），下表已标注关键的顺序依赖。

| 文件 | 用例数 | 覆盖对象（现状事实，引用 file:line） |
|------|:---:|------|
| `test_a_factory.py` | 8 | **App 工厂 + 配置校验**。`test_config` 验 `create_app()` 的 TESTING 开关（`:13`）；`test_hello` 命中 `/hello` 烟雾路由（`:18`）；`test_check_app_config` 跑 `check_app_config()` 全流程、验 `LOGPARSER_PID`/`POLL_PID` 进程是否拉起（`:38-75`）；`test_check_email_*` 验邮件配置校验（无密码时直接 return，`:80`）；`test_scrapyd_group`/`test_scrapyd_auth` 验分组与鉴权脱敏显示（`:110-115`）。文件名带 `a` → **最先跑**，先把 app/config 这层冒烟过一遍。 |
| `test_aa_logparser.py` | 4 | **LogParser 集成 + Stats 页面**。`test_stats_with_logparser_disabled`（`:24`）、`test_enable_logparser`（真起 LogParser 子进程并 `sleep()` 等它写出 `stats.json`，断言 `runtime == '0:01:08'`，`:34-62`）、`test_stats_with_logparser_enabled`（`:65`）、`test_stats_with_file_deleted`（穷举本地/备份/远端 stats 各种缺失与版本不匹配分支，`:96-169`）。文件名 `aa` → 紧跟 factory 之后，**因为它会启动 LogParser 进程**，需在干净环境下做。 |
| `test_api.py` | 10 | **Scrapyd JSON API 透传层**（`scrapydweb/views/api.py`）。`daemonstatus`/`stop`/`forcestop`/`listprojects`/`listversions`/`listspiders`/`listjobs`/`delversion`/`delproject`/`liststats`，断言返回 JSON 的 `status=='ok'` 与关键键（`:9-95`）。**全部需要真实 Scrapyd 应答。** |
| `test_deploy.py` | 9 | **多节点部署链路**（`views/operations/deploy.py`、`scrapyd_deploy.py`）。自动打包 select 选项（`:16`）、坏 egg 报错（`:35`）、auto packaging（`:51`）、Unicode 项目名（`:68`）、`scrapy.cfg` 各种残缺（`:81`）、首节点不存在的降级（`:95`）、上传各平台包（`:115`）、`deploy.xhr`（`:152`）。 |
| `test_deploy_single_scrapyd.py` | 7 | 同 deploy，但强制 `single_scrapyd`（`set_single_scrapyd()`，`utils.py:200`）走**单节点路径**。 |
| `test_log.py` | 10 | **日志/Stats 页面 + 轮询 + 告警**。真实 deploy → `start` 一个 spider → `sleep()` 等运行 → 抓 utf8/stats 页（`:15`）；`test_poll_py` 直接调 `scrapydweb.utils.poll.main`（`:234`）；`test_monitor_alert` 验监控告警（`:253`）；还含 `parse.upload` 上传日志解析（`:175-227`）。 |
| `test_metadata.py` | 5 | **元数据接口 + 持久化偏好**。`metadata` 视图返回键集（`:15`）、每页条数 set/get（`:55`）、jobs 展示风格切换（`:72`）、APScheduler 调度器 enable/disable 状态机（`:82`，引 `STATE_RUNNING`/`STATE_PAUSED`）。 |
| `test_mobileui.py` | 7 | **移动端 UI 重定向与渲染**。index 按 UA 重定向到 mobile（`:10`）、jobs/log 的 mobile 模板（`:16-55`）。中途真起一个 spider（`test_api_start`，`:21`）。 |
| `test_multinode.py` | 3 | **多节点批量操作页**（`views/operations` 的 multinode）。stop/delproject/delversion 的确认页渲染（`:11-23`）。 |
| `test_page.py` | 9 | **各主要页面 GET 冒烟**。按 `cst.VIEW_TITLE_MAP`（`utils.py:77`）逐页验标题；UA 嗅探（IE/EDGE/iPhone/iPad）；`checkLatestVersion` 注入；items 目录；节点切换；Cluster Reports 入口存在（`:88`）。 |
| `test_page_single_scrapyd.py` | 9 | 同上，单节点路径；末尾 `test_cluster_reports_not_exists` 验单节点时**没有**集群报表入口（`:84`）。 |
| `test_projects.py` | 3 | **Projects 页面**（list projects / versions / spiders + del）。先 deploy `demo.zip`（`:11`），再验列表与删除文案（`:9-73`）。 |
| `test_reports.py` | 3 | **节点报表 / 集群报表**（nodereports / clusterreports）。验 URL 拼接、成功与 `status_code: -1` 失败页（`:7-51`）。 |
| `test_schedule.py` | 7 | **多节点调度（立即运行）**。`schedule.check` 生成 `.pickle`（`:35`）、`run` 真正下发（`:49`）、telnet 取 stats（`:145`）、pending jobs（`:181`）、失败分支、`schedule.xhr`（`:205`）。引 `scrapy.__version__`。 |
| `test_schedule_single_scrapyd.py` | 6 | 同 schedule，单节点；含默认版本、history（`:21-126`）。 |
| `test_send_text.py` | 7 | **告警通道**（sendtext / sendtextapi）。Email / Slack / Telegram 各一组 pass/fail（`:11-269`）。**pass 用例需要真实凭据**（`EMAIL_PASSWORD`/`SLACK_TOKEN`/`TELEGRAM_TOKEN`），无凭据时早 return（`:12`）。 |
| `test_system.py` | 2 | **DATA_PATH / DATABASE_URL 落地校验**。验 `DATA_PATH`、`DATABASE_URL` 环境变量对 `APSCHEDULER_DATABASE_URI`、`SQLALCHEMY_DATABASE_URI`、`SQLALCHEMY_BINDS` 的影响（`:8-23`，引 `scrapydweb.vars`）。这是少数**不需要 Scrapyd 应答**的纯配置测试。 |
| `test_tasks.py` | 9 | **定时任务（APScheduler 持久化任务）多节点**。check→run with task、结果查询、编辑任务、切模板、`task_start_execute_end` 端到端、孤儿 apscheduler job 自动清理、执行异常、运行中删除（`:35-317`）。 |
| `test_tasks_single_scrapyd.py` | **27** | 单节点定时任务，**全套最大文件（45 KB）**，覆盖任务 CRUD、触发器、fire、结果分页、边界等最细分支。 |
| `test_z_cleantest.py` | 1 | **收尾清场**。`test_cleantest` 遍历所有测试项目名（`:5-24`），forcestop 运行中作业 + delproject，把 Scrapyd 恢复干净（`:27-35`）。文件名 `z` → **最后跑**，同时被 `test_a_factory.py:9` 复用作前置清场。 |

> **关键机制：`req()` 断言器（`utils.py:102-192`）**。几乎所有用例都通过它发请求并断言。它支持 `ins`（响应文本须包含）、`nos`（须不含）、`jskws`（JSON 键值匹配）、`jskeys`（JSON 须含键）、`location`（重定向目标）、`mobileui` 等。**断言失败时会把响应 dump 到 `response.html`**（`utils.py:188`）便于排错。
> 含义：**这是一套"文案级 + JSON 契约级"的黑盒断言**。其中只有 **JSON / 重定向 / Scrapyd 应答**这部分语义对 dopilot 有参考价值（可作为 `/api/v1` 契约 oracle）；**HTML 文案级 `ins=`/`nos=` 断言对 dopilot 无意义**——dopilot 前端是 SPA（`apps/web`），不复用任何 scrapydweb Jinja 模板/HTML 文案（见 §4.3）。

---

## 2. 如何在仓库外克隆上游 scrapydweb 复跑其自带测试

> 本节描述的是**在仓库外的上游 scrapydweb 克隆内复跑其自带测试**所需的前置与命令（用于观测 reference 基线行为；本仓库不保留本地快照）。这些 `requirements-tests.txt`、CircleCI 命令、`~/logs` 前置等都是 **scrapydweb 自身的测试形态**（路径相对上游 scrapydweb 1.6.0 / commit `1341cf9`），**不构成 dopilot 的测试/CI 设计依据**——dopilot 的测试与 CI 见 §5。

### 2.1 硬前置（reference 行为事实）

| 前置 | 来源 | 说明 |
|------|------|------|
| 一个真实运行的 Scrapyd | `conftest.py:16-17` | 默认 `127.0.0.1:6800`，鉴权 `('admin','12345')`。**没有它，绝大多数用例直接失败**（API/deploy/schedule/log 全靠它应答）。CircleCI 里现起一个：写 `scrapyd.conf` 设账号后 `nohup scrapyd`（`.circleci/config.yml:174-183`）。 |
| `~/logs` 目录存在 | `utils.py:239-244` | `LOCAL_SCRAPYD_LOGS_DIR` 默认指向 `~/logs`，**不存在会 `sys.exit()` 直接终止整轮测试**（`utils.py:244`）。CI 里 `mkdir ~/logs`（`.circleci/config.yml:73`）。 |
| `data.zip` 解压 | `utils.py:255-256` | **无需手动解压**：`setup_env()` 在导入 `conftest` 时自动 `extractall` 到 `tests/data/`。每轮会先 `rmtree` 旧 `tests/data/`（`utils.py:251-254`）。 |
| 测试依赖已安装 | `requirements-tests.txt` | 见下表。**当前 `.venv` 未安装这些**（已核实，§3）。 |

`requirements-tests.txt` 内容（已 Read）：

```
pip>=19.1.1
flake8
coverage
pytest
# pytest-cov   ← 被注释，CI 用 coverage 直接驱动 pytest，不用 pytest-cov
coveralls
allure-pytest

scrapy        ← 测试要 import scrapy（test_schedule.py:5）并需要真 scrapyd
scrapyd       ← 起本地 Scrapyd 实例

pymysql>=0.9.3    ← 仅 MySQL 后端矩阵需要
psycopg2>=2.7.7   ← 仅 PostgreSQL 后端矩阵需要
```

> **注意**：`setup.py` 没有 `tests_require` 也没有 `extras_require`（已 Read 全文，`setup.py:19-76` 只有 `install_requires` 与 `entry_points`）。**测试依赖完全独立靠 `requirements-tests.txt` 安装**，不能用 `pip install .[test]` 这类写法。

### 2.2 标准运行命令（与 CI 对齐）

CI 的权威命令（`.circleci/config.yml:184-193`）：

```bash
# 1) 静态门禁：只挑致命语法/未定义错误
flake8 . --count --exclude=./venv* --select=E9,F63,F7,F82 --show-source --statistics

# 2) 清空覆盖率
coverage erase

# 3) 跑全量测试并统计覆盖率（注意是 coverage 驱动 pytest，不是 pytest-cov）
coverage run --source=scrapydweb -m pytest -s -vv -l --disable-warnings --alluredir=allure-results tests
```

`-s` 不吞 print（用例里大量 `print` 调试信息），`-vv -l` 详细 + 显示局部变量，`--alluredir` 产出 Allure 结果。

报告生成（`.circleci/config.yml:194-205`）：`coverage report` / `coverage html` / `coverage xml` / `coveralls`。

`.coveragerc`（已 Read，全文仅 2 行有效）：

```
[run]
include = scrapydweb/*
```

→ 只统计 `scrapydweb/` 包的覆盖率。

`.codecov.yml`（已 Read）：覆盖率展示区间 `70...100`（`.codecov.yml:8`），`require_changes: no`、`require_ci_to_pass: yes`——即覆盖率本身不卡门禁，但 CI 必须先绿。

### 2.3 在仓库外克隆上游 scrapydweb 复跑其自带测试以观测基线行为

> ⚠️ 这**不是 dopilot 的测试入口**。下面步骤仅用于在**仓库之外**复跑上游 scrapydweb 自带测试，目的是**读懂/对照 reference 的基线行为**（提取行为预期作 oracle）。本仓库**已移除本地快照**,需观察时外部克隆上游公开仓库(scrapydweb `1.6.0` / commit `1341cf9`),切勿把上游代码拷回本仓库。
> dopilot 自己的测试入口是 `apps/server/tests`（pytest）、`apps/agent/tests`（pytest）、`apps/web`（vitest/e2e）、`packages/protocol`（schema 校验），见 §5。

```bash
# 在 dopilot 仓库之外克隆上游,工作目录是上游包根,而非本仓库
git clone https://github.com/my8100/scrapydweb /tmp/scrapydweb-ref
cd /tmp/scrapydweb-ref && git checkout 1341cf9
python3 -m venv .venv-ref && source .venv-ref/bin/activate
pip install -e .
pip install -r requirements-tests.txt
pip install "setuptools<81"        # 关键：修 pkg_resources，见 §3 / docs/05 §4.1
mkdir -p ~/logs                    # 否则 setup_env() 会 sys.exit

# 起本地 Scrapyd（另一个终端，账号必须与 conftest.py 一致）
cd ~ && printf "[scrapyd]\nusername = admin\npassword = 12345\n" > scrapyd.conf && scrapyd

# 在仓库外的上游 scrapydweb 克隆下跑其自带测试，观测基线行为
coverage run --source=scrapydweb -m pytest -s -vv -l --disable-warnings tests
```

> **告警类 pass 用例默认跳过**：无 `EMAIL_PASSWORD` / `SLACK_TOKEN` / `TELEGRAM_TOKEN` 时，`test_send_text.py` 与 `test_a_factory.py` 的邮件 pass 分支会 early-return（`test_send_text.py:12`、`test_a_factory.py:80`），不会失败。dopilot 单管理员场景**通常不需要补这些外网凭据**。

---

## 3. 在 Python 3.12 下复跑 scrapydweb 测试的两道坎（功能层实现注意事项）

**结论：scrapydweb 测试不能开箱跑通。已实测复现两道坎——这两道坎也是 dopilot 移植 scheduler 依赖时必须知道的功能层约束（与 CLAUDE.md 已锁的 `pkg_resources` 坑一致）。**

### 3.1 坎 1：`pkg_resources` 缺失（致命，import 即挂）

实测（`.venv/bin/python -c "import scrapydweb"`）：

```
File ".../scrapydweb/vars.py", line 9, in <module>
    from apscheduler.schedulers.base import STATE_PAUSED, STATE_RUNNING, STATE_STOPPED
File ".../site-packages/apscheduler/__init__.py", line 1, in <module>
    from pkg_resources import get_distribution, DistributionNotFound
ModuleNotFoundError: No module named 'pkg_resources'
```

根因与方案见 **`docs/dopilot/05-dev-setup-and-known-issues.md` §4.1**：APScheduler 3.6.0（`setup.py:36`）顶层 `import pkg_resources`，而当前 `.venv` 里 `setuptools 82.0.1`（实测 `pip list`）已移除内置 `pkg_resources`。

- **影响范围**：`conftest.py:6` `from scrapydweb import create_app` → 触发 `vars.py:9` → import 失败 → **整轮 pytest 在 collection 阶段就崩，146 个用例一个都跑不了**。
- **快速修复**（docs/05 方案 A）：`pip install "setuptools<81"`。docs/05 §4.1 注明该命令"在本次会话中被用户取消，尚未执行"——**截至本文写作，`.venv` 仍处于挂掉状态**（实测确认）。

### 3.2 坎 2：测试依赖未安装

实测 `pip list`：`.venv` 里**没有 pytest、scrapy、scrapyd、coverage、flake8**（只装了 `requirements.txt`，未装 `requirements-tests.txt`）。所以即使修了 `pkg_resources`，也要先 `pip install -r requirements-tests.txt` 才能跑。

### 3.3 矛盾点：CI 声称支持 3.12，但本地装法会踩坑

| 事实 | 出处 |
|------|------|
| `setup.py` 分类器声明支持到 3.13 | `setup.py:73-74` |
| CircleCI 有 `py312` / `py312-scrapyd-v143` / `py313` job | `.circleci/config.yml:358-369, 395-398` |
| CI 没有 pin `setuptools<81` | `.circleci/config.yml:139-149` 只 `pip install -r requirements*.txt` |

【开放问题 ❓】scrapydweb 的 py312 job 是否真能绿？两种可能：(a) CI 镜像 `cimg/python:3.12` 自带的 setuptools 仍 < 81，碰巧避开了；(b) 该 job 实际是红的或被忽略。

> **dopilot 的实现注意事项（功能层约束，保留）**：dopilot scheduler 域移植 APScheduler 时，应**选 `APScheduler>=3.10,<4`**（去 `pkg_resources` 历史包袱，docs/05 推荐的长期解），把该依赖约束写进 **`apps/server/pyproject.toml`**（scheduler 依赖处），而非任何单一根级扁平依赖文件——dopilot 依赖按 `apps/*/pyproject.toml` + `packages/*/pyproject.toml` 的 monorepo 组织。`setuptools<81`（方案 A）仅作复跑 scrapydweb 时的临时保命手段，不进 dopilot 依赖。

---

## 4. 以 scrapydweb 测试为行为 oracle：dopilot executors 域移植的语义对照

### 4.1 为什么 reference 测试是 executors 域移植的好 oracle

`10-roadmap.md` 与 `01-gap-executors.md` 的执行器抽象（缝① `BaseExecutor`）规划了"部署 + 下发 + 取状态 + 取日志 + 停止"这条链路。dopilot 在 `apps/server/dopilot_server/executors/`（`base.py` / `scrapyd.py` / `script.py` / `docker.py`）**全新实现** `BaseExecutor`/`ScrapydExecutor`，需要保证其行为语义与 reference 等价。scrapydweb 的 `tests/` 恰好从 HTTP 入口到 Scrapyd 应答对这条链路做了端到端黑盒断言——它锁定的"输入→输出语义"正好可作为 dopilot 新实现的**对照清单 / 语义验收点**。

> 注意定位：reference 测试是 **oracle**，不是 dopilot 的回归网。dopilot 的实际回归由 `apps/server/tests` 下**自写**的测试承担（见 §5）。

### 4.2 executors 域移植的行为对照清单（reference 锁定了哪些语义）

reference 中下列测试文件分别锁定了执行器链路各环节的行为语义（reference 视图侧入口见 `scrapydweb/views/api.py`、`views/operations/deploy.py`、`scrapyd_deploy.py`、`execute_task.py`、`schedule.py`，仅作行为参考引用）。dopilot 在 `apps/server/tests` 中针对这些语义点编写**自己的**测试：

| 链路环节 | 参考 reference 测试 | 锁定的行为语义（dopilot 验收点） |
|----------|------------------|------------|
| Scrapyd API 透传（daemonstatus/start/stop/forcestop/list*/del*） | `test_api.py`（10）、`test_z_cleantest.py`（1） | 透传层的 JSON 契约：`status=='ok'` 与各操作的关键键。dopilot `ScrapydExecutor` 对 Scrapyd 的请求构造与响应解析应保持同一契约。 |
| 部署/打包/上传 egg | `test_deploy.py`（9）、`test_deploy_single_scrapyd.py`（7）、`test_projects.py`（3） | 部署语义：多节点/单节点/各平台包、Unicode 项目名、坏 egg / 残缺 `scrapy.cfg` 的报错与降级。 |
| 调度下发（立即运行 + 取 stats + pending） | `test_schedule.py`（7）、`test_schedule_single_scrapyd.py`（6） | "运行 spider"语义：下发、telnet 取 stats、pending jobs、失败分支。 |
| 定时任务执行（fire→execute→记录结果） | `test_tasks.py`（9）、`test_tasks_single_scrapyd.py`（27） | 定时任务语义：`fire→execute→记录结果`、孤儿 job 清理、运行中删除等（reference 用例最密集，36 例，对应语义点也最细）。 |
| 运行态日志/统计 | `test_log.py`（10）、`test_aa_logparser.py`（4）、`test_reports.py`（3） | "取日志/取统计"语义 + LogParser 集成（含未完成态日志、节点/集群报表）。 |

→ 上述 9 个文件构成 **executors/logs/scheduler 域移植的语义验收点清单**（约 96 个 reference 用例所覆盖的语义）。dopilot 不复跑这些 scrapydweb 用例作为门禁，而是在 `apps/server/tests` 中按这些语义点写 dopilot 自己的契约级测试，必要时用临时 Scrapyd 容器或 mock 做集成校验，把 reference 的行为预期当 oracle 对照。

> **⚠️ 通信模型已被取代（superseded-by）**：上表"取状态/取日志"等链路在 scrapydweb 里是 **server 主动 HTTP** 形态（reference 行为事实，保留）。dopilot **自身** server↔agent 通信已翻案为 **Redis Streams**：server 不再 HTTP pull agent status/tail，改为 server `XADD` command、agent 主动消费命令并 `XADD` 推状态/日志、agent 主动 POST heartbeat。权威口径见 `docs/refactor/00-redis-streams-agent-communication.md`。**reference 表本身只描述 scrapydweb→Scrapyd 的行为语义，不受影响**；但 dopilot 在 Redis 模型下多出一整片 **scrapydweb 无对应物的可靠性域**，下表 §4.2.1 单列，scrapydweb oracle 不覆盖、不参与。

### 4.2.1 dopilot 独有域：Redis 通信可靠性测试矩阵（scrapydweb 无对应 oracle）

> 这一域是 dopilot 翻案为 Redis Streams 通信后**新增**的语义，scrapydweb（HTTP pull 模型）**完全没有对应行为**，因此**无 reference oracle 可对照**——这些测试从第一天起就是 dopilot 自写、并直接绑定 dopilot CI 门禁。语义细节以 `docs/refactor/00-redis-streams-agent-communication.md`「测试要求」为准，本表只做归类与落点映射。

| 可靠性语义 | dopilot 测试落点 | 验收点（细节见 refactor 文档） |
|------------|------------------|--------------------------------|
| command ack / pending 恢复 | `apps/agent/tests` + `apps/server/tests` | server `XADD` `run` 后 agent 经 consumer group 消费并启动；agent 读 command 后崩溃，重启认领超时 pending command 后继续按 `attempt_id` 幂等处理，任务不永久卡住。 |
| `attempt_id` 执行幂等（重复 run 不重复启动） | `apps/agent/tests` | agent 重复读到同一 `attempt_id` 的 `run`（pending 认领 / 重复 command / 同进程并发 / 跨重启）不重复启动；本地已有状态文件则只重发当前状态事件、可 `XACK`；接管前先取 attempt 锁，state file 两阶段 CAS（`reserved`→`started`）兜跨重启防重复。 |
| status event 重复不回退 / terminal 不被回退 | `apps/server/tests` | server 以 `event_id` + stream message id 去重；重复 event 允许、状态更新单调；terminal 不被非 terminal 回退；server 推断的 `lost`（软 terminal）可被 agent 权威 terminal 覆盖并记 `reconciled_from=lost`，`finished`/`failed`/`canceled` 之间不可互转。 |
| log offset 追加 / 重复丢弃 / gap 显式 partial | `apps/server/tests` | `offset == last_pulled_offset` 追加；`offset < last_pulled_offset` 重复片段丢弃；`offset > last_pulled_offset` 缺片标 `log_integrity=partial`（黏性，不自动转 `complete`）+ 记 expected/actual offset + 插可见 gap marker，`last_pulled_offset` 推进到 `offset + size_bytes`；gap 不阻塞 execution 进 terminal；单一顺序生产者按 offset 严格递增，乱序/重放不造虚假 gap。 |
| heartbeat 超时不选节点 | `apps/server/tests` | node selection 以 `healthy = now - nodes.last_seen_at <= heartbeat_timeout_seconds` 判健康；超时 agent 即使 Redis 可用也不再被投递新任务（健康来源由 server 轮询 `/health` 翻转为 agent heartbeat 写 `last_seen_at`）。 |
| Redis 不可用降级（手动 503 / 定时 queued+dispatch_timeout） | `apps/server/tests` | 手动/同步 run 请求内 `try_dispatch` 失败 → execution/attempt/outbox 标 failed `dispatch_unavailable` 返回 503；`XADD` 成功但 `sent` 标记 DB 更新失败 → 返回 202 `dispatch_unknown`、execution 维持 `queued`、由后续 `attempt.running` 收敛；定时/异步触发进 queued + pending outbox，超 `max_retry`/`expire_at` 转 failed `dispatch_timeout`；定时 coalesce 抑制同源堆积。 |
| 取消投 stop | `apps/server/tests` | 取消 queued execution 先 CAS 置未 sent outbox 为 `canceled`、任何投递路径投递前重读 status 不投已取消 command；取消 `dispatch_unknown`/未 sent attempt 时同时投 `stop(intent=cancel)`，agent 无论进程是否仍在都回 `attempt.canceled`（不回 `lost`），execution 终结 `canceled`、不被 rollup 成 `lost`、不留僵尸。 |
| lost reason 区分 | `apps/server/tests` + `apps/agent/tests` | API/Web 能据 reason 区分 server 推断（`heartbeat_timeout` / `event_stall`）与 agent 上报本地恢复失败（`state_missing` / `process_missing` / `runner_recovered_unknown`）三类成因；server 生成 lost 前短路检查 terminal、按 `attempt_id` upsert 不重复。 |
| reconcile / cleanup | `apps/server/tests` + `apps/agent/tests` | reconcile loop 凭 heartbeat 超时 / event stall 推断 lost（`event_stall` 同时投 `stop(intent=reclaim)` 回收进程，`stalled` 是一次性告警非 terminal）；server-reconciled lost 的 attempt，agent 恢复后先 reconcile 重发 `attempt.running` → server 先 stop、再 drain + `cleanup_logs`，不在进程仍活时删其日志/状态文件；terminal event + drain timeout 触发 `cleanup_logs`，不依赖有损 `eof`。 |
| 协议 schema 校验 | `packages/protocol`（schema 校验） | `AgentCommand` / `AgentEvent` / `AgentLogEvent` / `AgentHeartbeatRequest`/`Response`（`packages/protocol/dopilot_protocol/streams.py`）的字段/枚举/编解码（含 log `content_b64` base64 字节、offset/size_bytes/eof）；既有 `AgentRunRequest`/`AgentStatusResponse`/`TailRequest`/`TailResponse` 已标 **legacy**、不再代表当前协议、不作主路径契约。 |

> 落点小结：以上语义归 **`apps/server/tests`**（command outbox / dispatcher / event consumer / log consumer / reconcile / heartbeat 健康判断）、**`apps/agent/tests`**（command consumer / 幂等 / 状态文件 CAS / event outbox / log publisher / heartbeat worker / 本地 reconcile）、**`packages/protocol`** schema 校验三处。**scrapydweb tests 对本域无任何 oracle 贡献**——HTTP pull 模型里不存在 command outbox、attempt 幂等、event/log stream、heartbeat 健康判断、lost reason、reconcile 这些语义。

### 4.3 各域移植对照 reference 时的注意事项（前端无 Jinja 共存）

| dopilot 移植动作（来自 gap 文档） | 可对照的 reference 行为 | 备注 |
|---------------------------|--------------|------|
| 全新实现 `BaseExecutor` + `ScrapydExecutor`（缝①，`01` §6.4） | §4.2 的 API/部署/下发/日志语义 | dopilot 在 `apps/server/executors/` 新写，行为语义对照 reference。 |
| 调度/节点策略/推模式（`02-gap-scheduling-nodes-push.md`） | `test_schedule*`、`test_tasks*`、`test_metadata.py`（调度器状态机 `:82`）、`test_reports.py` 锁定的下发/状态机语义 | dopilot 在 `apps/server/scheduler/`+`nodes/` 新写，节点选择与推送语义可对照。 |
| 前端 SPA 分阶段交付（`06-frontend-rewrite.md`） | 仅 reference 的 **JSON / 重定向 / Scrapyd 应答** 语义可作 `/api/v1` 契约 oracle | dopilot 前端是 **greenfield SPA**（`apps/web`，阶段 2.1 起为 Next.js 静态导出 + shadcn/ui + Recharts），**不存在** Jinja↔Vue 共存或按页 strangler；reference 的 HTML 文案级 `ins=`/`nos=` 断言对 dopilot **无意义**，`test_mobileui.py` 这类移动端 Jinja 模板测试 dopilot 无对应物（响应式由 shadcn/ui + Tailwind 处理；阶段 2.1 前为 Element Plus）。 |
| i18n（`04-gap-i18n.md`） | reference 文案断言**不可参考**；dopilot i18n 由前端承担，测组件渲染 | dopilot 不继承英文 HTML 文案断言。阶段 2.1 起 i18n 用 react-i18next（前为 vue-i18n，`apps/web/src/i18n`）。 |
| 数据库后端（PostgreSQL） | `test_system.py`（2）锁定的 `DATA_PATH`/`DATABASE_URL`→连接串映射语义 | dopilot 在 `apps/server/config/` 新写配置层，并固定 PostgreSQL 为唯一数据库；reference 的 sqlite/pg/mysql 映射只作为历史行为参考。 |

> **要点**：dopilot 后端测 `/api/v1` JSON 契约（`apps/server/tests`），前端测组件/页面（`apps/web` vitest/e2e）。reference 的 HTML 文案级断言不进入 dopilot 任何层——dopilot 没有继承来的 Jinja 页，只有全新 SPA。

---

## 5. dopilot 自有测试基线与 CI（dopilot 测试设计）

### 5.1 立即要做的

1. **观测并记录 reference 基线行为（oracle 快照）**：按 §2.3 在仓库外的上游 scrapydweb 克隆下复跑其测试套（先 `setuptools<81` 或在装好的环境里），把 §4.2 各语义点的行为预期记录下来，作为 dopilot 各域移植时的对照 oracle。这是**对上游的外部观测**，不是 dopilot 回归基线。
2. **建立 dopilot 自有 0 号基线**：从第一个移植的功能（`ScrapydExecutor`）起，就在 `apps/server/tests` 与 `apps/agent/tests` 中写 dopilot 自己的测试，覆盖 §4.2 的语义验收点（契约级，非 HTML 文案级）。dopilot 的回归基线就此建立、随 dopilot 代码演进。scheduler 域移植 APScheduler 时选 `3.10.x` 避开 `pkg_resources` 坑（见 §3.3）。
3. **dopilot CI**：在 `.github/workflows/` 下运行 **dopilot 自有测试矩阵**——`apps/server`（pytest，需要时用 fixture/mock 或临时 Scrapyd 容器）、`apps/agent`（pytest）、`apps/web`（阶段 2.1 起：`eslint .` flat config + vitest + @testing-library/react + Next.js 静态导出构建 + Playwright e2e；前为 vue-tsc + vitest + Vite 构建）、`packages/protocol`（schema 校验）。**不照搬** scrapydweb 的 CircleCI 步骤（`coverage --source=scrapydweb` / `mkdir ~/logs` / 起本地 Scrapyd 跑 scrapydweb tests）；scrapydweb 的 CI 仅在需要观测 reference 行为时,于仓库外的上游克隆内单独运行，与 dopilot CI 完全解耦。

### 5.2 dopilot 回归分级（基于 dopilot 自有测试）

| 级别 | 范围（dopilot 自有测试） | 触发时机 | 是否需要 Scrapyd | 可对照的 reference oracle |
|------|------|----------|------------------|------|
| L0 冒烟 | `apps/server` config/app 工厂单测 + `packages/protocol` schema 校验（含 §4.2.1 `streams.py` 的 `AgentCommand`/`AgentEvent`/`AgentLogEvent`/`AgentHeartbeat*`）+ lint | 每次 commit / PR | 否 | `test_a_factory.py`、`test_system.py` 锁定的配置语义；通信可靠性 schema **无 oracle** |
| L1 契约回归 | `apps/server/tests` 的 executors/scheduler 契约测试（Scrapyd 用容器或 mock） | 每个 executor/scheduling PR | 否（mock）/ 可选容器 | §4.2 的 API/部署/下发/日志语义 |
| **L1.5 Redis 通信可靠性（dopilot 独有域）** | §4.2.1 矩阵：`apps/server/tests`（command outbox/dispatcher/event consumer/log consumer/reconcile/heartbeat 健康判断）+ `apps/agent/tests`（command consumer/幂等/状态文件 CAS/event outbox/log publisher/heartbeat worker）；Redis 用容器或假实现 | 每个 Redis 通信 / 调度 / 日志 / 节点 PR | 否（Scrapyd）；需 Redis（容器/假实现） | **无**——scrapydweb HTTP pull 模型无对应行为 |
| L2 全量 | dopilot 全量：`apps/server` + `apps/agent` + `apps/web`（vitest/e2e）× 后端矩阵（含 L1.5 全套可靠性矩阵） | 合并到 master / 发版 | 视集成测试而定 | §4.2 全部语义点（§4.2.1 仍无 oracle） |
| L3 外部告警通道 | dopilot 告警通道测试（pass 分支） | 手动 / 配了凭据时 | 否 | `test_send_text.py` 的通道语义 |

> 表中"可对照的 reference oracle"列仅供编写 dopilot 测试时参考行为预期；触发门禁绑定的始终是 **dopilot 自己的测试**。**L1.5 行的 reference oracle 列为"无"是实质结论**：command ack/pending 恢复、`attempt_id` 幂等、event 单调/terminal 不回退、log offset gap→partial、heartbeat 健康判断、Redis 不可用降级、取消投 stop、lost reason 区分、reconcile/cleanup 均为 dopilot 翻案 Redis Streams 后新增、scrapydweb 无对应物，权威口径见 `docs/refactor/00-redis-streams-agent-communication.md`。

### 5.3 dopilot 测试设计原则

- **后端测契约，不测文案**：dopilot 后端用标准 pytest + FastAPI TestClient/httpx 直接断言 `/api/v1` 的 JSON 契约 / 重定向 / status_code，**不引入** HTML 文案级黑盒断言（scrapydweb 的 `req()` 文案匹配器只读、不继承）。前端的页面/组件断言归 `apps/web`（阶段 2.1 起：单测/组件测试用 vitest + @testing-library/react + jsdom，e2e 用 Playwright，选择器走 `data-tone`/`data-testid`；前为 vitest + Vue Test Utils + Element Plus 类选择器）。
- **executor 可 mock、不依赖外部 Scrapyd**：dopilot 为各执行器写**可 mock 的执行器层单测**（不经 HTTP、直接断言执行器对 Scrapyd 的请求构造与响应解析），使执行器逻辑能脱离外部 Scrapyd 独立回归。这是合理的工程主张，落点是 `apps/server/tests`（而非改 scrapydweb；scrapydweb 缺这层单测，正好是 dopilot 要补齐的）。
- **`docker` 执行器（roadmap 阶段 3）**：docker 长连容器执行器是 **dopilot 独有域**，scrapydweb 无对应行为可参考。其测试从一开始就在 `apps/server/tests` + `apps/agent/tests` 中自写，与 `script`/`scrapyd` 执行器共用 dopilot 自有的可 mock 执行器测试基座，不引用 scrapydweb tests 作为基准。
- **Redis 通信可靠性域无 oracle、必须自给自足（dopilot 独有域）**：dopilot 翻案为 Redis Streams 后（server `XADD` command、agent 主动消费 + 主动 `XADD` 推状态/日志 + 主动 POST heartbeat，删除 server→agent HTTP run/status/tail 主路径与 `AgentTailLogSource` 主路径），多出 §4.2.1 一整片 scrapydweb **无对应物**的可靠性语义。这些测试不得指望任何 reference oracle，必须用 **Redis 容器或假实现 + 注入式时间/崩溃点**自构造：① 命令侧——`XADD`→consumer group 消费→`XACK`、pending 认领、`attempt_id` 幂等（重复 run/同进程并发/跨重启不重复启动）、状态文件两阶段 CAS（`reserved`/`started`）；② 状态侧——event `event_id` + message id 去重、terminal 不被回退、server 推断 `lost` 软 terminal 被 agent 权威 terminal 覆盖（记 `reconciled_from=lost`）、lost reason 区分；③ 日志侧——offset 追加/重复丢弃/gap→`log_integrity=partial`（黏性、不阻塞 terminal、单一顺序生产者不造虚假 gap）；④ 降级侧——Redis 不可用时手动 run 503 `dispatch_unavailable` / `dispatch_unknown` 202、定时 queued+outbox `dispatch_timeout`、取消投 `stop(intent=cancel)`、reconcile/cleanup 不删活进程日志。语义细节以 `docs/refactor/00-redis-streams-agent-communication.md`「测试要求」为准；**禁止**用 scrapydweb 的 HTTP status/tail 行为反推这片域的预期。
- **协议 schema 是这片域的 L0 守门**：`packages/protocol/dopilot_protocol/streams.py` 的 `AgentCommand`/`AgentEvent`/`AgentLogEvent`/`AgentHeartbeatRequest`/`AgentHeartbeatResponse` 必须有 schema 校验测试（字段/枚举/base64 字节编解码/offset 语义），并把既有 `AgentRunRequest`/`AgentStatusResponse`/`TailRequest`/`TailResponse` 当 **legacy** 看待——不为其新增主路径契约断言，避免误把旧 HTTP 协议当现行通信协议测。

### 5.4 一句话给实现工程师

> 实现某域（如 `ScrapydExecutor`）前：先读 reference 对应测试，提取其行为预期（输入→输出语义）作为验收清单；在 `apps/server/tests` 写 dopilot 自己的测试覆盖这些语义（JSON 契约级，非 HTML 文案级）；必要时起 Scrapyd 容器或 mock 做集成校验。reference 是行为 oracle，dopilot 的回归网始终是 `apps/*/tests`。
> **但 Redis 通信可靠性域（§4.2.1）例外**：它无任何 reference oracle——实现 command outbox/dispatcher/event consumer/log consumer/reconcile/heartbeat 或 agent command consumer/幂等/状态文件 CAS/event outbox/log publisher 前，直接以 `docs/refactor/00-redis-streams-agent-communication.md`「测试要求」为验收清单，用 Redis 容器/假实现自构造，不要去 scrapydweb 找对照。

---

## 附录 A：scrapydweb 用例分布速查（reference oracle 清单，非 dopilot 用例）

| 文件 | 用例数 | 需真实 Scrapyd | 顺序敏感 |
|------|:---:|:---:|------|
| test_a_factory.py | 8 | 部分（容错） | 最先（`a`） |
| test_aa_logparser.py | 4 | 是（且起 LogParser 子进程） | 早期（`aa`） |
| test_api.py | 10 | 是 | — |
| test_deploy.py | 9 | 是 | — |
| test_deploy_single_scrapyd.py | 7 | 是 | — |
| test_log.py | 10 | 是（起 spider + poll） | — |
| test_metadata.py | 5 | 部分 | — |
| test_mobileui.py | 7 | 是（起 spider） | — |
| test_multinode.py | 3 | 是 | — |
| test_page.py | 9 | 是 | — |
| test_page_single_scrapyd.py | 9 | 是 | — |
| test_projects.py | 3 | 是 | — |
| test_reports.py | 3 | 是 | — |
| test_schedule.py | 7 | 是 | — |
| test_schedule_single_scrapyd.py | 6 | 是 | — |
| test_send_text.py | 7 | 是（pass 分支需外网凭据，否则跳过） | — |
| test_system.py | 2 | 否（纯配置） | — |
| test_tasks.py | 9 | 是 | — |
| test_tasks_single_scrapyd.py | 27 | 是 | — |
| test_z_cleantest.py | 1 | 是（清场） | 最后（`z`） |
| **合计** | **146** | | |

> 数据来源：`grep -c '^def test_' tests/test_*.py`，总数经 `grep -rh "^def test_" tests/test_*.py | wc -l` 复核 = 146。
