# 06 认证、安全与跨切面工具

> **【scrapydweb 行为参考·边界】** 本文描述 **scrapydweb 现状行为/语义**，作为 dopilot 的**功能层参考**；其代码写法、目录结构、模块划分**不得作为 dopilot 设计依据**。文中 `file:line` 路径均**相对 `reference/scrapydweb/`**（如 `scrapydweb/run.py` 即 `reference/scrapydweb/scrapydweb/run.py`；该目录只读、不被 import、不参与构建、不改名）。任何“改造切入点/复用/保留”类措辞，一律理解为“dopilot 需在 `apps/` 下**全新复刻其行为语义**”，而非改动或照搬 scrapydweb 文件。详见 `../dopilot/00-requirements.md` 决策表。
>
> 面向 dopilot 改造工程师。本文描述 scrapydweb 现有的**认证、安全、后台进程、告警监控与全局工具**这一横切层，并指出 dopilot 落地“真实用户体系 / 实时日志 / 定时任务 / 推模式 / 多节点策略 / i18n”时需要全新复刻其行为语义的行为参考点。
>
> 全文严格区分 **【现状事实】**（已读源码核实，标注 `文件:行`）与 **【改造建议 / 开放问题】**（dopilot 待办，未实现）。

---

## 1. 子系统概览

这一层是“所有请求都要穿过、所有 view 都要复用”的横切基础设施，由五块组成：

| 模块 | 关键文件 | 职责 |
|------|----------|------|
| 全局认证 | `scrapydweb/run.py` `scrapydweb/common.py` | 单账号 HTTP Basic Auth（before_request 拦截） |
| 跨切面工具 | `scrapydweb/common.py` `scrapydweb/views/baseview.py` | Session 连接池、内部互调、Metadata 读写、统一对外 HTTP |
| 后台进程 | `scrapydweb/utils/sub_process.py` `scrapydweb/utils/poll.py` `scrapydweb/utils/scheduler.py` | poll 子进程、logparser 子进程、APScheduler 后台线程 |
| 告警监控 | `scrapydweb/views/files/log.py` `scrapydweb/utils/send_email.py` | 阈值判定 + Slack/Telegram/Email 三路下发 |
| 启动校验 | `scrapydweb/utils/check_app_config.py` `scrapydweb/default_settings.py` `scrapydweb/models.py` | 配置校验、账号落库、周期任务注册、拉起后台进程 |

```
                        浏览器 / poll子进程 / test_client
                                   │  (每个 HTTP 请求)
                                   ▼
            ┌──────────────────────────────────────────────┐
            │  run.py  @app.before_request require_login()   │  ← 唯一认证关卡
            │  ENABLE_AUTH? 取 request.authorization         │
            │  与 config.USERNAME/PASSWORD 明文字符串相等比较  │
            │  不匹配 → common.authenticate() 返回 401        │
            └──────────────────────────────────────────────┘
                                   │ 通过
                                   ▼
                        BaseView (baseview.py)
              读全部 config / 构造 EMAIL_KWARGS / 解析 node
              get_response_from_view()  make_request()  get_selected_nodes()
                       │                       │                  │
          内部互调(test_client)         对外(scrapyd HTTP)     节点选择
```

---

## 2. 现有 HTTP Basic Auth 机制

### 2.1 唯一认证关卡：`require_login`

**【现状事实】** 全站只有一个认证点——`run.py:51-58` 的 `@app.before_request`：

```python
# scrapydweb/run.py:51-58
@app.before_request
def require_login():
    if app.config.get('ENABLE_AUTH', False):
        auth = request.authorization
        USERNAME = str(app.config.get('USERNAME', ''))  # May be 0 from config file
        PASSWORD = str(app.config.get('PASSWORD', ''))
        if not auth or not (auth.username == USERNAME and auth.password == PASSWORD):
            return authenticate()
```

认证失败时调用 `common.authenticate()`（`common.py:24-27`），返回 `401 + WWW-Authenticate: Basic realm="..."`，浏览器据此弹出原生 Basic Auth 登录框。

### 2.2 认证模型的本质特征

| 维度 | 现状 | 位置 |
|------|------|------|
| 账号数量 | **单一**全站账号（USERNAME/PASSWORD） | `default_settings.py:22-26` |
| 比较方式 | **明文字符串相等**（无哈希、无常量时间比较） | `run.py:57` |
| 会话机制 | **无** session / cookie（每请求都带 Basic 头） | — |
| 角色 / 权限 | **无** RBAC，全有或全无 | — |
| CSRF 防护 | **无** | — |
| 用户表 | **无** `User` 表 | `models.py`（仅 Metadata/Task/TaskResult/TaskJobResult） |
| 开关 | `ENABLE_AUTH`（False 时完全放行） | `default_settings.py:23` |

### 2.3 配置来源与优先级链

**【现状事实】** 配置三级覆盖（后者覆盖前者）：

```
default_settings.py (ENABLE_AUTH/USERNAME/PASSWORD, 第22-26行)
        │  from_object / from_pyfile
        ▼
scrapydweb_settings_v*.py  (用户自定义, run.py:123-129 load_custom_settings)
        │  update_app_config
        ▼
命令行  --disable_auth (-da)   →  run.py:248-249  config['ENABLE_AUTH'] = False
```

启动期校验在 `check_app_config.py:75-82`：若 `ENABLE_AUTH=True`，断言 USERNAME/PASSWORD 非空，然后 **明文落库到 Metadata 表**：

```python
# scrapydweb/utils/check_app_config.py:78-82
check_assert('USERNAME', '', str, non_empty=True)
check_assert('PASSWORD', '', str, non_empty=True)
handle_metadata('username', config['USERNAME'])
handle_metadata('password', config['PASSWORD'])
logger.info("Basic auth enabled with USERNAME/PASSWORD: '%s'/'%s'", ...)  # 日志里也明文打印
```

### 2.4 局限性（安全风险点）

| # | 局限 | 证据 |
|---|------|------|
| L1 | 单账号、明文比较，无哈希 | `run.py:57` |
| L2 | Metadata 表明文存 username/password | `models.py:31-32`，`check_app_config.py:80-81` |
| L3 | 账号密码被写入启动日志 | `check_app_config.py:82` |
| L4 | poll 子进程命令行明文带账号（`ps` 可见） | `sub_process.py:99-100` |
| L5 | 无角色 / 无 CSRF / 无审计 | 全局缺失 |
| L6 | 内部互调依赖账号传递，改认证易漏 | `common.py:48-54`、见 §3 |

---

## 3. 跨切面工具与内部互调（auth 传递陷阱）

### 3.1 `get_response_from_view` —— 进程内 view 互调

**【现状事实】** scrapydweb 用 `app.test_client()` 在**同一进程内**让一个 view 调另一个 view（`common.py:48-80`）。因为请求仍会穿过 `require_login`，所以内部调用**必须自带 Basic Auth 头**：

```python
# scrapydweb/common.py:48-54
def get_response_from_view(url, auth=None, data=None, as_json=False):
    client = app.test_client()
    if auth is not None:
        headers = {'Authorization': basic_auth_header(*auth)}   # w3lib
    ...
```

`BaseView` 把它包装为带 auth 的方法（`baseview.py:253-255`）：

```python
def get_response_from_view(self, url, data=None, as_json=False):
    auth = (self.USERNAME, self.PASSWORD) if self.ENABLE_AUTH else None
    return get_response_from_view(url, auth=auth, data=data, as_json=as_json)
```

依赖此内部互调的链路：

| 调用方 | 目标 view | 用途 | 位置 |
|--------|-----------|------|------|
| `log.set_monitor_flag` | `api` (stop/forcestop) | 阈值触发自动停爬 | `log.py:482,487` |
| `log.send_alert` | `sendtextapi` | Slack / Telegram 告警 | `log.py:517,521` |
| `execute_task` (定时任务) | `schedule/task` | 定时调度真正下发 | `execute_task.py:88,135` |

### 3.2 三个 auth 凭证来源（dopilot 必须同步改造）

**【现状事实 + 陷阱】** 同一对账号密码在三个不同位置被消费，改认证体系时**任何一处漏改都会导致内部互调或监控回调 401 静默失效**：

| 凭证消费点 | 取值来源 | 文件:行 |
|------------|----------|---------|
| Web 请求校验 | `app.config['USERNAME'/'PASSWORD']` | `run.py:55-56` |
| BaseView 内部互调 | `self.USERNAME/PASSWORD`（来自 config） | `baseview.py:86-87,254` |
| **定时任务回调** | **`handle_metadata()`（读 Metadata 表，非 config）** | `execute_task.py:158-167` |
| **poll 子进程回调** | **`sys.argv`（命令行参数）** | `poll.py:48-53`，`sub_process.py:99-100` |

> 注意：`execute_task` 是独立 APScheduler 线程里跑的，它**不读 app.config**，而是从 Metadata 表取 username/password（`execute_task.py:159-160`）。这就是为什么 §2.3 要在启动时 `handle_metadata` 落库——**否则定时任务的内部互调会拿不到凭证**。

### 3.3 `handle_metadata` —— 跨进程 / 跨请求共享状态通道

**【现状事实】** `common.py:83-95`，读写 Metadata **单行表**（按 `version` 过滤），是 pid、scheduler_state、url、username/password 等全局状态的唯一共享通道：

```python
# scrapydweb/common.py:83-88
def handle_metadata(key=None, value=None):
    with db.app.app_context():
        metadata = Metadata.query.filter_by(version=__version__).first()
        if key is None:
            return dict(...)   # 读全部
        else:
            setattr(metadata, key, value); db.session.commit()   # 写单键
```

Metadata 表存的全局单行状态（`models.py:16-36`）：

| 字段 | 含义 |
|------|------|
| `main_pid` / `poll_pid` / `logparser_pid` | 三个进程的 pid（生命周期管理） |
| `username` / `password` | **明文**账号密码 |
| `scheduler_state` | 调度器暂停 / 运行 |
| `url_scrapydweb` / `url_jobs` / `url_schedule_task` / `url_delete_task_result` | 内部回调 URL 模板 |

### 3.4 其它共享工具

| 工具 | 文件:行 | 说明 |
|------|---------|------|
| 全局 `requests.Session`（连接池 1000） | `common.py:18-20` | 所有对外 HTTP 复用 |
| `BaseView.make_request()` | `baseview.py:285-` | **统一对外（scrapyd）HTTP 封装**：support `auth=(u,p)`、as_json、check_status、timeout |
| `get_selected_nodes()` | `baseview.py:257-262` | 解析表单勾选的 1-based 节点编号（`form['1'..'N']=='on'`） |
| node 断言 | `baseview.py:191-192` | `assert 0 < node <= SCRAPYD_SERVERS_AMOUNT`，越界 500 |
| `json_dumps` / `handle_slash` | `common.py:98-106` | JSON 序列化（默认 `ensure_ascii=False`）、Windows 路径反斜杠归一 |

---

## 4. 后台进程：poll / logparser / scheduler

### 4.1 三个后台执行体一览

**【现状事实】** scrapydweb 主进程（Flask 单进程多线程，`run.py:119-120` `use_reloader=False`）之外还有三个后台执行体：

| 执行体 | 类型 | 启动点 | 生命周期绑定 |
|--------|------|--------|--------------|
| logparser | 子进程（Popen） | `sub_process.py:53-82` init/start_logparser | prctl + atexit |
| poll | 子进程（Popen） | `sub_process.py:85-125` init/start_poll | prctl + atexit + pid 检测 |
| APScheduler | 主进程内**后台线程** | `scheduler.py:90` 模块导入即 `start(paused=True)` | atexit `shutdown_scheduler` |

```
   主进程 (Flask, main_pid)
   ├── APScheduler BackgroundScheduler 线程  (scheduler.py:45,90)
   │       SQLAlchemyJobStore 持久化 + ThreadPoolExecutor(20)
   │       jobs: execute_task(定时任务) / jobs_snapshot / delete_task_result
   │
   ├── Popen ── logparser 子进程   (logparser.run -m, 解析本地 scrapy 日志)
   │
   └── Popen ── poll 子进程        (poll.py, 监控轮询)
            prctl(PR_SET_PDEATHSIG, SIGKILL)  父死子亡（仅 Linux）
            check_exit(): pid_exists / os.kill(main_pid,0) 自杀检测
```

### 4.2 子进程启动范式（dopilot 全新复刻其行为语义）

**【现状事实】** `sub_process.py` 是平台“常驻后台进程”的统一启动范式：

- `Popen(args)` 拉起子进程；
- Linux 用 `preexec_fn=on_parent_exit('SIGKILL')`（`sub_process.py:26-42`，调 `libc.prctl(PR_SET_PDEATHSIG)`）实现**父进程死亡时子进程被内核 SIGKILL**；
- `atexit.register(kill_child, ...)` 注册主进程退出时杀子进程（`sub_process.py:57,89`）。

**【陷阱】** prctl 仅 Linux 可用（`sub_process.py:115` 判 `platform.system()=='Linux'`）。Windows/macOS 下 `preexec_fn` 不支持、`libc.so.6` 找不到，会退化为普通 Popen，**清理可能不彻底**（注释见 `sub_process.py:109-114`）。`run.py:120` 的 `app.run(..., use_reloader=False)` 正是为避免 debug 重载导致 pid / 子进程错乱（`run.py:98` 为对应的提示日志）。

### 4.3 poll 监控轮询子进程

**【现状事实】** `poll.py` 是独立运行的脚本（`main(sys.argv[1:])`，`poll.py:230-250`）：

1. 每 `POLL_ROUND_INTERVAL` 秒（`poll.py:160-161`），对每个 scrapyd 服务器 GET `http://<server>/jobs` HTML 页（`poll.py:188`）；
2. 用正则 `JOB_PATTERN`（`poll.py:28-41`）解析出 running / finished 任务；
3. 对每个任务 POST 到 **scrapydweb 自身** `/<node>/log/stats/<project>/<spider>/<job>/?job_finished=...`（`poll.py:81,123-146`）——**这个 POST 才是触发告警的开关**；
4. `check_exit()`（`poll.py:83-99`）用 `pid_exists` / `os.kill(main_pid,0)` 检测主进程存活，主进程没了就 `sys.exit`。

**【陷阱 / 改造点】** poll 携带两套凭证：`self.auth=(username,password)` 回调 scrapydweb 自身（`poll.py:53`，来自命令行明文），`self.scrapyd_servers_auths` 访问各 scrapyd（`poll.py:56`）。这种“**轮询 + 正则解析 scrapyd 的 /jobs HTML 页**”模式**仅适用于 scrapy/scrapyd**，对 dopilot 的长连接容器爬虫和一次性脚本完全不适用（见 §7）。

### 4.4 APScheduler 定时任务引擎

**【现状事实】** `scheduler.py`：

- 全局单例 `BackgroundScheduler`（`scheduler.py:45`），jobstore 用 `SQLAlchemyJobStore` **持久化**（`scheduler.py:31-33`），executor 用 `ThreadPoolExecutor(20)`；
- 模块导入时即 `scheduler.start(paused=True)`（`scheduler.py:90`），atexit 注册 `shutdown_scheduler`（`scheduler.py:111`，优雅等待运行中任务结束）；
- 定时任务（`trigger=cron/interval/date`，`models.py:94`）通过 `schedule.py:481` `scheduler.add_job(func=execute_task, ...)` 注册；触发时跑 `execute_task`（`execute_task.py:150-172`）写 `Task/TaskResult/TaskJobResult`；
- 两个周期管家任务也注册在此：`jobs_snapshot`（`check_app_config.py:306`）、`delete_task_result`（`check_app_config.py:329`）。

**【陷阱】** `run.py:140-141` 明确警告：**升级后旧的 timer task 可能报错**，需重启并手动编辑恢复——SQLAlchemyJobStore 序列化的任务与版本 / schema 强绑定，迁移须谨慎。

---

## 5. 邮件告警与任务监控

### 5.1 告警触发条件（极易静默）

**【现状事实】** 告警分支只有 poll 子进程的 POST 才进得去（`log.py:168`）：

```python
# scrapydweb/views/files/log.py:168-169
if self.ENABLE_MONITOR and self.POST:  # Only poll.py would make POST request
    self.monitor_alert()
```

**【陷阱】** 只要满足下面任一条件，**整条告警链路静默无错**：`ENABLE_MONITOR=False`、poll 子进程没起来（非 Linux prctl 不可用 / main_pid 检测误判）、或 poll 无法访问 scrapyd 的 /jobs 页。

### 5.2 告警判定与下发流程

```
poll POST → log.py monitor_alert() (log.py:404-417)
   │
   ├─ set_email_content_kwargs()  组装邮件正文 (419)
   ├─ set_monitor_flag()          按 LOG_*_THRESHOLD 判定 flag (456)
   │     可触发 stop/forcestop → get_response_from_view(api) (480-487)
   ├─ send_alert()                按工作日/时过滤后三路下发 (492)
   └─ handle_data()               更新内存状态机 (531)
```

`set_monitor_flag`（`log.py:456-490`）按 `ALERT_TRIGGER_KEYS = [CRITICAL, ERROR, WARNING, REDIRECT, RETRY, IGNORE]` 逐项比对阈值 `LOG_*_THRESHOLD`；命中且配置了 `LOG_*_TRIGGER_FORCESTOP/STOP` 时，经 `get_response_from_view` 调 `api` view 自动停爬（`log.py:478-487`）。

`send_alert`（`log.py:492-529`）先按 `ALERT_WORKING_DAYS / ALERT_WORKING_HOURS` 过滤（`log.py:494-495`），再**三路下发**：

| 渠道 | 机制 | 位置 |
|------|------|------|
| Slack | `get_response_from_view` 调 `sendtextapi`（进程内） | `log.py:514-517` |
| Telegram | 同上 | `log.py:518-521` |
| Email | **`Popen` 起独立 `send_email.py` 进程**（异步） | `log.py:522-529` |

### 5.3 内存状态机（横向扩展障碍）

**【现状事实 + 陷阱】** 每个任务的统计快照与触发状态保存在**模块级全局内存变量**：

```python
# scrapydweb/views/files/log.py:30,33
job_data_dict = {}                              # job_key -> (stats, triggered_list, has_been_stopped, last_send_ts)
job_finished_key_dict = defaultdict(OrderedDict)
```

`monitor_alert` 用 `job_data_dict.setdefault` 取上一轮快照并 diff（`log.py:406-412`），`handle_data` 写回（`log.py:535`）。**不持久化**——重启即丢；且 Flask 多线程共享存在并发写风险。**因此 scrapydweb 不能简单横向扩成多实例**（dopilot 若要多副本必须改造这块）。

### 5.4 邮件发送的两条路径

**【现状事实 + 陷阱】** `send_email()`（`send_email.py:17-`，纯函数，`smtplib.SMTP_SSL` 或 `SMTP+starttls`，失败重试一次 `send_email.py:69-70`）有两个调用方：

| 路径 | 调用方式 | 失败影响 |
|------|----------|----------|
| 启动自检 `check_email()` | **同步直接调** `send_email()` | 失败 `assert` **阻断启动**（除非 TEST_ON_CIRCLECI） |
| 告警发送 | `Popen` 起独立 `send_email.py` 进程，参数为 json 序列化的 `EMAIL_KWARGS` | 失败只在子进程日志，**主流程无感知** |

`EMAIL_KWARGS` 在 `baseview.py:163-174` 构造，含 `email_password / smtp_server` 等敏感信息，经 `json_dumps(ensure_ascii=True)` 作为命令行参数传给子进程（`log.py:526-527`）——**又一个凭证以命令行传递的点**。

---

## 6. 启动期校验与初始化（`check_app_config`）

**【现状事实】** `check_app_config.py:38` 是启动总入口（`run.py:44` 调用），按序：

```
check_app_config(config)                         (check_app_config.py:38)
 ├─ check_assert(...)  逐项校验所有 config
 ├─ ENABLE_AUTH → 校验 USERNAME/PASSWORD 非空 → handle_metadata 落库   (75-82)
 ├─ handle_metadata('url_scrapydweb', ...)        (96)
 ├─ EMAIL_PASSWORD → check_email() 发测试邮件      (203-, 460-)
 ├─ ENABLE_MONITOR → 校验阈值；                    (226-)
 │     ENABLE_SLACK/TELEGRAM_ALERT → check_slack_telegram() 发测试消息  (263-268)
 ├─ scheduler.add_job('jobs_snapshot', ...)        (306)
 ├─ scheduler.add_job('delete_task_result', ...)   (329)
 └─ init_subprocess(config)                        (334, 484-495)
        ├─ init_logparser → LOGPARSER_PID → handle_metadata           (486-489)
        └─ init_poll      → POLL_PID      → handle_metadata           (492-495)
```

> scrapydweb 中改任何认证 / 告警 / 后台进程配置都会经过这里；dopilot 在 `apps/` 下全新复刻其行为语义时，新增的后台采集进程 / 校验项应对标这一启动总入口的行为。

---

## 7. dopilot 横切能力的行为参考点

> 以下均为 **【改造建议 / 开放问题】**，scrapydweb 现状未实现；dopilot 全新实现这些能力时需复刻的行为语义。各小节中“切入点 / 主切入点 / 复用 / 保留 / 必须同步”等措辞，均指 dopilot 在 `apps/` 下全新复刻对应行为语义时需对标的 scrapydweb 行为参考点，而非改动 scrapydweb 文件。

### 7.1 用真实用户体系替换 HTTP Basic Auth ★核心

| 项 | 内容 |
|----|------|
| 主切入点 | `run.py:51-58` `require_login()` + `common.py:24-27` `authenticate()` |
| 数据模型 | `models.py` 新增 `User` 表（`password_hash` / `role` / `is_active`）；废弃 / 哈希化 Metadata 的明文 `username/password`（`models.py:31-32`） |
| 改法 | dopilot 不沿用 Flask `before_request`；FastAPI `auth/` 模块采用 config-present-or-off 的单管理员登录，返回 Bearer opaque token；失败返回 API 错误码，由 Vue 登录页处理。保留“认证可关闭”的内网部署语义 |
| **必须同步** | 内部互调凭证：`baseview.get_response_from_view`（`baseview.py:254`）、`execute_task` 从 Metadata 取凭证（`execute_task.py:158-167`）、`poll.py` 命令行凭证（`sub_process.py:99-100`）。**三处全改为 service token**，否则监控告警 / 定时任务 / 跨 view 调用全部 401（见 §3.2） |
| 安全 | 修复 L2/L3/L4：账号不再明文落库 / 进日志 / 进命令行 |

### 7.2 多语言 i18n 框架预留（当前仅中文）

| 项 | 内容 |
|----|------|
| 切入点 | `__init__.py:64-101` `create_app()`（jinja env 配置处，第 100-101 行附近）+ `templates/` + `baseview.py` |
| 改法 | dopilot i18n 走**前端 vue-i18n**(`apps/web`,见 `../dopilot/04-gap-i18n.md`),**不引入 Flask-Babel**。后端面向用户的文案(如 `common.authenticate()` 提示 `common.py:26`、`log.py` 告警 subject `log.py:504`)以错误码/结构化字段返回,由前端本地化;左列 scrapydweb 文案位置仅作行为参考 |
| 参考 | `default_settings.py` 已有中英双语注释块（如第 34-37 行），可作文案抽取参考 |

### 7.3 扩展节点选择策略（全部执行 / 随机一个）

| 项 | 内容 |
|----|------|
| 切入点 | `baseview.py:257-262` `get_selected_nodes()` + `schedule.py` / `execute_task.py` |
| 现状 | 仅支持表单勾选“指定节点”（`form['1'..'N']=='on'`） |
| 改法 | 新增策略字段 `all / random / specified`；在选节点处按策略从 `SCRAPYD_SERVERS` 计算目标集合（random 用 `random.choice`） |
| **约束** | node 是 **1-based**，`baseview.py:191-192` 有硬断言 `0 < node <= SCRAPYD_SERVERS_AMOUNT`，越界直接 500。新策略必须遵守 1-based 约定 |

### 7.4 长连接容器爬虫 / 一次性脚本的监控告警

| 项 | 内容 |
|----|------|
| 切入点 | `poll.py` + `log.py:404-417` `monitor_alert()` |
| 问题 | poll 只懂 scrapyd `/jobs` HTML 页与 scrapy 日志统计（§4.3），**不适用常驻进程 / 脚本** |
| 改法 | 为新对象类型提供独立状态采集（容器健康检查 / 心跳、脚本退出码），复用 `send_alert` 三路下发与 `job_data_dict` 状态机思路；可沿用 `sub_process.py` 的 Popen + prctl 范式新增采集子进程 |
| 注意 | `job_data_dict` 内存态不持久化（§5.3），新采集器若要多实例须改持久化 |

### 7.5 推模式：主动下发任务到指定节点

| 项 | 内容 |
|----|------|
| 切入点 | `common.py` / `baseview.py:285` `make_request` + `execute_task.py` |
| 现状 | 所有调度均为 scrapydweb 主动 HTTP POST 到目标 scrapyd（addversion/schedule） |
| 改法 | （原构想：新增直达 worker 的 push 通道、复用 `make_request` 统一 HTTP+auth 封装与 `SCRAPYD_SERVERS_AUTHS` per-node 凭证 `baseview.py:102,196`）**dopilot v1 已翻案**：下发改走 Redis command stream(`dopilot:agent:{agent_id}:commands`)、agent 主动消费，鉴权走 Redis AUTH/ACL + agent→server `server_shared_token`，不再复用 scrapydweb 的 HTTP+auth 主路径。见 [`../refactor/00-redis-streams-agent-communication.md`](../refactor/00-redis-streams-agent-communication.md) |

### 7.6 实时日志流

| 项 | 内容 |
|----|------|
| 切入点 | `log.py` + `poll.py`（当前为拉取轮询，非真正流式） |
| 改法 | dopilot v1 见决策 #11(已由 [`../refactor/00-redis-streams-agent-communication.md`](../refactor/00-redis-streams-agent-communication.md) 翻案):**agent 经 Redis log stream(`dopilot:server:logs`)主动推增量、server log consumer 消费落盘(`RedisLogSource`,非 server pull)**,再 server→web SSE 流式推送(**不引入 WebSocket**);对容器爬虫从容器 stdout / log 流式读取。auth 与 node 解析在 dopilot 全新实现 |

---

## 8. 关键陷阱速查（务必收藏）

| # | 陷阱 | 证据 |
|---|------|------|
| G1 | 认证“全有或全无”、单账号、明文比较，无 session/角色/CSRF | `run.py:51-58` |
| G2 | Metadata 明文存账号密码 | `models.py:31-32` `check_app_config.py:80-81` |
| G3 | 内部互调依赖 auth 传递，三处凭证来源不同，漏改即 401 静默 | `common.py:48-54` `execute_task.py:158-167` `poll.py:48-53` |
| G4 | poll 子进程命令行明文带账号，`ps` 可见 | `sub_process.py:99-100` |
| G5 | 告警仅由 poll POST 触发，ENABLE_MONITOR=False 或 poll 没起来即全程静默 | `log.py:168` |
| G6 | 告警状态在内存全局变量，重启即丢、并发写风险、无法简单横向扩展 | `log.py:30,33` |
| G7 | 三后台执行体生命周期耦合 main_pid；prctl 仅 Linux，跨平台清理不彻底 | `sub_process.py:115` `poll.py:83-99` `scheduler.py:90` |
| G8 | 邮件两路径：启动 check_email 失败阻断启动；告警 Popen 失败主流程无感知 | `send_email.py` `log.py:522-529` |
| G9 | EMAIL_KWARGS（含 email_password）以命令行参数传子进程 | `log.py:526-527` `baseview.py:163-174` |
| G10 | APScheduler SQLAlchemyJobStore 持久化与版本/schema 强绑定，升级旧 task 可能报错 | `run.py:140-141` |
| G11 | node 1-based，硬断言越界 500 | `baseview.py:191-192` |
