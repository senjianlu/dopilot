# dopilot —— 测试与回归基线

> 这是 dopilot 多篇 gap 文档（`01`/`02`/`06`/`10`）反复承诺"零回归 / strangler 渐进重构"却一直缺失的那份**护栏文档**。
> `10-roadmap.md:39` 把本文件列为"一切改造的前置安全网"，`10-roadmap.md:73` 写明"测试基线(07) ──► 一切改造的前置安全网"，`01-gap-executors.md:263` 把 `ScrapydExecutor` 迁移定性为"行为不变，可立即合入"——能不能"立即合入"取决于有没有一条能复跑、能判绿的回归线。本文负责把这条线讲清楚。
>
> 本文严格区分【现状事实】（已 Read/Grep 核实，引用 `file:line`）与【改造建议 / 开放问题】（待决策）。

---

## 0. 一句话结论

| 维度 | 结论 |
|------|------|
| 测试是否存在 | 是。`tests/` 下 20 个 `test_*.py`，共 **146 个 `test_` 函数**（`grep -rh "^def test_" tests/test_*.py \| wc -l`）。 |
| 是不是真单测 | 不是。**绝大多数是集成测试**，依赖一个真实运行的 Scrapyd（`127.0.0.1:6800`，账号 `admin/12345`）。 |
| 当前能否在 Python 3.12 跑通 | **不能，开箱即挂**。`import scrapydweb` 因 `pkg_resources` 缺失直接抛 `ModuleNotFoundError`（已复现，见 §3）。且当前 `.venv` 未装测试依赖（无 pytest/scrapy/scrapyd）。 |
| 作为零回归安全网够不够 | 方向够（覆盖了部署/调度/API/日志/告警/任务全链路），但**有结构性缺口**：强依赖外部 Scrapyd、依赖外网（QQ/Slack/Telegram）、断言绑死 HTML 文案、无独立的 executor 层单测。详见 §4–§5。 |

---

## 1. 现有 `tests/` 覆盖范围（逐文件）

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
> 含义：**这是一套"文案级 + JSON 契约级"的黑盒断言**。后端逻辑等价但 HTML 文案/结构一变，测试就红——这对 strangler 重构既是护栏也是摩擦（见 §4.3）。

---

## 2. 如何运行

### 2.1 硬前置（现状事实）

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

### 2.3 本地最小复跑步骤（建议，基于上面的事实）

```bash
cd /workspaces/dopilot
source .venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-tests.txt
pip install "setuptools<81"        # 关键：修 pkg_resources，见 §3 / docs/05 §4.1
mkdir -p ~/logs                    # 否则 setup_env() 会 sys.exit

# 起本地 Scrapyd（另一个终端，账号必须与 conftest.py 一致）
cd ~ && printf "[scrapyd]\nusername = admin\npassword = 12345\n" > scrapyd.conf && scrapyd

# 回到仓库跑测试
coverage run --source=scrapydweb -m pytest -s -vv -l --disable-warnings tests
```

> **告警类 pass 用例默认跳过**：无 `EMAIL_PASSWORD` / `SLACK_TOKEN` / `TELEGRAM_TOKEN` 时，`test_send_text.py` 与 `test_a_factory.py` 的邮件 pass 分支会 early-return（`test_send_text.py:12`、`test_a_factory.py:80`），不会失败。dopilot 单管理员场景**通常不需要补这些外网凭据**。

---

## 3. 当前在 Python 3.12 能否跑通？

**结论：不能开箱跑通。已实测复现两道坎。**

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

【开放问题 ❓】CI 的 py312 job 是否真能绿？两种可能：(a) CI 镜像 `cimg/python:3.12` 自带的 setuptools 仍 < 81，碰巧避开了；(b) 该 job 实际是红的或被忽略。**dopilot 要把 py312 当作支持基线，就必须把 `setuptools<81`（方案 A）或 `APScheduler>=3.10,<4`（方案 B，docs/05 推荐的长期解）固化进 `requirements.txt`**，否则"本地按文档装 = 必挂"。

---

## 4. 作为 strangler 重构 + 执行器抽象迁移的"零回归"安全网

### 4.1 它为什么是 dopilot 的关键护栏

`10-roadmap.md` 与 `01-gap-executors.md` 的整套叙事建立在一个假设上：**把现网 scrapyd 下发链路收敛进 `BaseExecutor`/`ScrapydExecutor` 时"行为不变"**（`01-gap-executors.md:263`、`10-roadmap.md:46`）。"行为不变"不能靠人眼承诺，只能靠**一条能复跑、能判绿的回归线**来证伪。本套 `tests/` 就是这条线：它从 HTTP 入口到 Scrapyd 应答做了端到端黑盒断言，恰好覆盖了执行器抽象要包裹的那条链路。

### 4.2 执行器抽象迁移：改造前后**必须复跑**的用例（最高优先级）

`01-gap-executors.md` 计划把"部署 + 下发 + 取状态 + 取日志 + 停止"收敛进执行器层。这条链路在测试里对应（视图侧入口见 `scrapydweb/views/api.py`、`views/operations/deploy.py`、`scrapyd_deploy.py`、`execute_task.py`、`schedule.py`）：

| 链路环节 | 必复跑的测试文件 | 为什么是它 |
|----------|------------------|------------|
| Scrapyd API 透传（daemonstatus/start/stop/forcestop/list*/del*） | `test_api.py`（10）、`test_z_cleantest.py`（1） | 执行器要替换的就是这层 HTTP 调用，JSON 契约一变即红。 |
| 部署/打包/上传 egg | `test_deploy.py`（9）、`test_deploy_single_scrapyd.py`（7）、`test_projects.py`（3） | `ScrapydExecutor` 的"部署"能力，含多节点/单节点/各平台包。 |
| 调度下发（立即运行 + 取 stats + pending） | `test_schedule.py`（7）、`test_schedule_single_scrapyd.py`（6） | 执行器"运行 spider"能力，telnet/pending 等运行态。 |
| 定时任务执行（fire→execute→记录结果） | `test_tasks.py`（9）、`test_tasks_single_scrapyd.py`（27） | `execute_task.py` 经执行器下发；**这是用例最密集的护栏（36 例）**。 |
| 运行态日志/统计 | `test_log.py`（10）、`test_aa_logparser.py`（4）、`test_reports.py`（3） | 执行器"取日志/取统计"能力 + LogParser 集成。 |

→ **执行器迁移的最小回归集 = 上述 9 个文件，约 96 个用例。** 改造分支与 master 在**同一 Scrapyd 环境**各跑一遍，结果必须逐字一致（含 dump 出的 `response.html` 不应出现新差异）。

### 4.3 strangler 各阶段的复跑映射

| 改造动作（来自 gap 文档） | 改造后必复跑 | 备注 |
|---------------------------|--------------|------|
| 引入 `BaseExecutor` + `ScrapydExecutor`（`01` §6.4，"行为不变"） | §4.2 全部 96 例 | 这是"零回归"成立与否的判定线。 |
| 调度/节点策略/推模式（`02-gap-scheduling-nodes-push.md`） | `test_schedule*`、`test_tasks*`、`test_metadata.py`（调度器状态机 `:82`）、`test_reports.py` | 节点选择与推送会改下发路径。 |
| 前端重写 M1~M3（`06-frontend-rewrite.md`） | ⚠️ `test_page*`、`test_metadata.py`、`test_mobileui.py`、`test_send_text.py` 的 `ins=` HTML 断言**会大面积失效** | 见下方【开放问题】。 |
| i18n（`04-gap-i18n.md`） | 同上：所有基于英文文案的 `ins=`/`nos=` 断言 | 文案一改即红。 |
| 数据库后端切换（sqlite/pg/mysql） | `test_system.py`（2） + 全量在对应后端各跑一遍 | CI 已有矩阵（`.circleci/config.yml:316-353`）。 |

【开放问题 ❓ —— 安全网与重构的根本张力】：`req()` 是**文案级黑盒断言**（`utils.py:129-186` 按子串匹配 HTML）。`06`/`04` 的前端重写与 i18n 一旦动 HTML 结构/英文文案，`test_page*`、`test_mobileui.py`、`test_metadata.py` 等就会**因为"对的改动"而变红**，安全网反过来阻碍重构。
建议拆成两层（见 §5）：把"后端契约层"（JSON / 重定向 / Scrapyd 应答）与"前端表现层"（HTML 文案）分离断言；执行器迁移阶段**只依赖契约层**，前端层在重写阶段单独维护。

---

## 5. 建议的回归流程与 CI（改造建议）

### 5.1 立即要做的（让安全网先能用）

1. **修复 Py3.12 跑通**（前置中的前置）：把 docs/05 §4.1 方案落到 `requirements.txt`——优先方案 B（`APScheduler>=3.10,<4`，去历史包袱）；若怕回归，先方案 A（`setuptools<81`）保命。**做完后必须复跑 §4.2 全集验证 APScheduler 升级本身没引入回归**（尤其 `test_tasks*` 与 `test_metadata.py:82` 调度器状态机）。
2. **打基线快照**：在 master + 修好的环境上，把 §4.2 的 96 例跑绿一次，记录覆盖率数字（`coverage report`）作为 dopilot 的 0 号基线。**这是"零回归"的参照物**——之前从没存在过，这正是本文要补的护栏。
3. **CI 平台决策**：现仓库是 CircleCI（`.circleci/config.yml`）。dopilot 远程在 GitHub（docs/05 §1），`.github/` 已存在（git status 显示 `?? .github/`）。【开放问题 ❓】确认 CircleCI 是否还接 dopilot 仓库；若要迁 GitHub Actions，需要把"起 Scrapyd + mkdir ~/logs + setuptools pin + coverage 驱动 pytest"这套步骤照搬过去。

### 5.2 推荐的回归分级

| 级别 | 范围 | 触发时机 | 是否需要 Scrapyd |
|------|------|----------|------------------|
| L0 冒烟 | `test_a_factory.py` + `test_system.py` + `flake8 E9,F63,F7,F82` | 每次 commit / PR | 否（factory 的 check_app_config 会试连，但能容错） |
| L1 契约回归 | §4.2 的 96 例（执行器链路） | 每个 executor/scheduling PR | **是**（CI 内起本地 Scrapyd） |
| L2 全量 | `tests` 全部 146 例 × 后端矩阵 | 合并到 master / 发版 | 是 |
| L3 外网告警 | `test_send_text.py` pass 分支 | 手动 / 配了 secrets 时 | 是 + 外网凭据 |

### 5.3 中期：把安全网做"抗重构"

- **拆契约层 vs 表现层断言**（针对 §4.3 张力）：给 `req()` 增加"只断言 JSON / 重定向 / status_code"的模式，执行器迁移只跑契约层；HTML 文案断言归入单独的前端测试集，随 `06` 重写演进。
- **降低对真实 Scrapyd 的硬依赖**：当前几乎全集成。建议为 `ScrapydExecutor` 单独写**可 mock 的执行器层单测**（不经 HTTP、直接断言执行器对 Scrapyd HTTP 的请求构造与响应解析），这样执行器逻辑能脱离外部 Scrapyd 独立回归——这是现 `tests/` 的最大结构缺口（**0 个纯 executor 单测**，因为 executor 抽象还不存在）。
- **`docker` 阶段（roadmap 阶段 3）的执行器**：现 `tests/` 完全不覆盖 docker 长连接执行器。新执行器类型必须自带与 `ScrapydExecutor` 对等的回归集，且复用 §5.3 的可 mock 执行器单测框架。

### 5.4 一句话给改造工程师

> 动 executor / scheduling 之前：先 `pip install "setuptools<81"` + 起本地 Scrapyd，把 §4.2 的 96 例在 master 跑绿存为基线；改完在同环境再跑一遍，**逐字 diff 必须为空**。HTML 文案类红灯先判断是不是 `06`/`04` 预期内的表现层变化——是就更新断言，不是就回退。这就是"零回归"的全部含义。

---

## 附录 A：用例分布速查

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
