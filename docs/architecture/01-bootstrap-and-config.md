# 01 应用启动、CLI 与配置

> 面向后续把 scrapydweb 改造为私有调度平台 **dopilot** 的工程师。
>
> 本文描述 **现状事实**（基于代码实测，标注 `file:line`）与 **改造建议 / 开放问题**（明确标识）。
> 所有路径均为仓库内绝对路径。本文不涉及任务执行、日志解析等子系统的内部细节（另见后续文档）。

---

## 0. 一句话总览

scrapydweb 通过 setuptools `console_scripts` 暴露 `scrapydweb` 命令，入口是
`/workspaces/dopilot/scrapydweb/run.py` 的 `main()`。它用 **app factory 模式**
创建 Flask app，按 **4 层 + 1 旁路** 的优先级加载配置，做断言式校验并触发一堆运行时副作用
（建表、连通性检查、起子进程、注册定时 job），最后用 **werkzeug 内置开发服务器** 阻塞运行。

关键反直觉点（后面 §7 详述）：

- **APScheduler 调度器在 `import` 阶段就 `start(paused=True)`**，不是在 `main()` 里启动。
- **大量副作用发生在 `import` 期**（`vars.py` 一被导入就 mkdir、建库、清目录）。
- **首次运行会强制 `sys.exit`**（拷贝模板配置后退出，要求用户填好再重启）。
- **无 scrapyd 可连通时会启动失败**（`assert any(results)`）——这是 dopilot 接入非 scrapyd 对象的首个拦路虎。

---

## 1. 进程入口与打包

| 项 | 现状值 | 文件:行 |
|---|---|---|
| console_scripts 命令名 | `scrapydweb = scrapydweb.run:main` | `setup.py:59-63` |
| 包名 / 分发名 | `scrapydweb`（取自 `__title__`） | `setup.py:20` ← `__version__.py:3` |
| 版本号 | `1.6.0` | `scrapydweb/__version__.py:4` |
| 版本号读取方式 | `setup.py` 用 `exec(f.read(), about)` 读 `__version__.py` | `setup.py:11-13` |
| python 要求 | `python_requires=">=3.6"` | `setup.py:34` |
| `python -m` 入口 | `run.py` 末尾 `if __name__ == '__main__': main()` | `run.py:267-268` |

### 1.1 被钉死的依赖版本（重要约束）

`setup.py:35-57` 把核心依赖**精确钉死**到旧版本，引入新依赖（Flask-Babel / Docker SDK 等）时必须考虑兼容性：

| 依赖 | 钉死版本 | 对 dopilot 的意义 |
|---|---|---|
| Flask | `==2.0.0` | 较新扩展可能要求 Flask>=2.2/3.x，引 Babel 时需挑选兼容旧版的版本 |
| Werkzeug | `==2.0.0` | 与 Flask 2.0 配套；升级二者牵一发动全身 |
| Jinja2 / MarkupSafe / itsdangerous | `==3.0.0 / ==2.0.0 / ==2.0.0` | 与 Flask 2.0 配套锁定 |
| Flask-SQLAlchemy | `==2.4.0` | `handle_db` 用了 2.x 的 `db.app = app` 全局绑定，3.x 已移除（见 §7 gotcha） |
| SQLAlchemy | `==1.3.24` | DB 后端层；升级 Flask-SQLAlchemy 3.x 会连带要求 SQLAlchemy 1.4+ |
| APScheduler | `==3.6.0` | 定时调度核心，cron/interval 已原生支持 |
| Flask-Compress | `==1.4.0` | 响应压缩；接 Babel 时在它附近 init |
| logparser | `>=0.8.4` | 唯一非精确钉死项；scrapy 日志解析子进程 |

> **改造建议**：dopilot 若要长期演进，建议先做一次依赖现代化（Flask 3.x + Flask-SQLAlchemy 3.x），
> 否则后续每引一个扩展都要在旧版本里"凑"兼容点。但这是一次性大改，需评估 `handle_db` 等强依赖旧 API 的代码（见 §7）。

---

## 2. 启动序列图

下图是**实际执行顺序**（含 import 期副作用）。注意第 ① 步在解释器加载包链时就发生，早于 `main()`。

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ ① IMPORT 期副作用（解释器加载 scrapydweb 包链时自动执行，早于 main()）        │
│                                                                               │
│   vars.py  (import 即执行)                                                     │
│     ├─ import_module('scrapydweb_settings_v11')  只取 DATA_PATH / DATABASE_URL │
│     ├─ 计算 ROOT_DIR / DATA_PATH 及 7 个子目录，mkdir                          │
│     ├─ 清理 PARSE / DEPLOY / SCHEDULE 目录下的旧文件                           │
│     ├─ setup_database()  → 派生 4 个 URI                                       │
│     │     (APSCHEDULER_DATABASE_URI / SQLALCHEMY_DATABASE_URI / _BINDS / ...)  │
│     └─ setup_logfile()   建历史日志文件                                        │
│                                                                               │
│   utils/scheduler.py  (import 即执行)                                          │
│     ├─ 创建 BackgroundScheduler(SQLAlchemyJobStore + MemoryJobStore +          │
│     │                            ThreadPoolExecutor(20))                       │
│     ├─ add_listener(my_listener, ...)                                          │
│     ├─ scheduler.start(paused=True)   ★ 调度器此刻已运行（暂停态）             │
│     └─ atexit.register(shutdown_scheduler)                                     │
└─────────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ ② console_scripts → run.py:main()                                             │
│   ├─ apscheduler_logger.setLevel(ERROR)   暂时压住调度器告警                   │
│   ├─ main_pid = os.getpid()                                                    │
│   │                                                                           │
│   ├─ ③ create_app()  (app factory, __init__.py:64)                            │
│   │     ├─ Flask(__name__, instance_relative_config=True)                      │
│   │     ├─ from_mapping(SECRET_KEY='dev')        ← 第1层a（硬编码！）          │
│   │     ├─ from_object('scrapydweb.default_settings')  ← 第1层b（默认值）      │
│   │     ├─ from_pyfile('config.py', silent=True)      ← 第2层（instance，可选）│
│   │     ├─ handle_db(app)     建库建表、写 Metadata 版本行                     │
│   │     ├─ handle_route(app)  注册 ~20 个 MethodView + 3 个 Blueprint          │
│   │     ├─ handle_template_context(app)  注入静态资源/版本号                   │
│   │     ├─ register_error_handler(500), regex_replace 过滤器                   │
│   │     ├─ jinja 变量分隔符改为 '{{ ' / ' }}'（带空格！）                      │
│   │     └─ Compress().init_app(app)                                            │
│   │                                                                           │
│   ├─ handle_metadata('main_pid', ...)  写 DB                                   │
│   ├─ 写 MAIN_PID / DEFAULT_SETTINGS_PY_PATH / SCRAPYDWEB_SETTINGS_PY_PATH      │
│   ├─ load_custom_settings(config)   ← 第3层（cwd 的 scrapydweb_settings_v11.py)│
│   │     └─ 找不到 → copyfile 模板 + sys.exit  ★首次运行在此退出               │
│   ├─ parse_args(config)             argparse 定义全部 CLI 参数                 │
│   ├─ update_app_config(config,args) ← 第4层（CLI，最高优先级）                 │
│   │                                                                           │
│   ├─ ④ check_app_config(config)   (utils/check_app_config.py:38)              │
│   │     ├─ check_assert 逐项类型/范围校验 + setdefault                         │
│   │     ├─ check_scrapyd_servers() 解析→4个并行列表，连通性 assert any(...)    │
│   │     ├─ 按节点 create_jobs_table + db.create_all(bind='jobs')               │
│   │     ├─ if scheduler_state != PAUSED: scheduler.resume()                    │
│   │     ├─ add_job('jobs_snapshot', interval)  内置定时 job（memory store）    │
│   │     ├─ add_job('delete_task_result', interval)  内置定时 job               │
│   │     └─ init_subprocess() → 起 LogParser / Monitor 子进程（Popen）          │
│   │     失败抛 AssertionError → main 捕获 → sys.exit 提示改 settings           │
│   │                                                                           │
│   ├─ @app.before_request require_login  Basic Auth 钩子                        │
│   ├─ @app.context_processor inject_variable  注入 SCRAPYD_SERVERS 等模板变量   │
│   ├─ os.environ['FLASK_DEBUG'] = '1'/'0'                                       │
│   ├─ 按 ENABLE_HTTPS 决定 ssl_context = (cert, key) | None                     │
│   ├─ print("Visit ScrapydWeb at ...")                                          │
│   └─ ⑤ app.run(host=BIND, port=PORT, ssl_context=ctx, use_reloader=False)     │
│         werkzeug 开发服务器，threaded 默认开启，阻塞运行                       │
└─────────────────────────────────────────────────────────────────────────────┘
```

**主入口逐步对照**：`main()` 在 `run.py:26-120`，各步与上图一一对应。

---

## 3. CLI 参数表

定义于 `run.py:parse_args()`（`run.py:153-232`），合并于 `update_app_config()`（`run.py:235-264`）。
help 文本会**动态显示当前生效值**（如 `current: ...`）。除 `-b/-p/-ss` 外，其余均为 `store_true` 开关。

| 短参 | 长参 | 默认/类型 | 作用（合并逻辑见 `update_app_config`） | 覆盖的 config 键 |
|---|---|---|---|---|
| `-b` | `--bind` | str，默认 `SCRAPYDWEB_BIND` | 绑定地址；**总是覆盖** | `SCRAPYDWEB_BIND` |
| `-p` | `--port` | str/int，默认 `SCRAPYDWEB_PORT` | 端口；**总是覆盖** | `SCRAPYDWEB_PORT` |
| `-ss` | `--scrapyd_server` | `action='append'`，可多次 | 追加 scrapyd 节点；**仅当非空才覆盖** | `SCRAPYD_SERVERS` |
| `-da` | `--disable_auth` | store_true | 关闭 Web 基础认证 | `ENABLE_AUTH=False` |
| `-dc` | `--disable_check_scrapyd` | store_true | **跳过 scrapyd 连通性检查** | `CHECK_SCRAPYD_SERVERS=False` |
| `-dlp` | `--disable_logparser` | store_true | 启动时不拉起 LogParser 子进程 | `ENABLE_LOGPARSER=False` |
| `-sw` | `--switch_scheduler_state` | store_true | **翻转** DB metadata 的 `scheduler_state`（持久化） | metadata.`scheduler_state`（非 config） |
| `-dm` | `--disable_monitor` | store_true | 关闭 Monitor/poll 子进程 | `ENABLE_MONITOR=False` |
| `-d` | `--debug` | store_true | 开启 debug 模式 | `DEBUG=True` |
| `-v` | `--verbose` | store_true | 日志级别 INFO→DEBUG | `VERBOSE=True` |
| `-h` | `--help` | — | 打印帮助并退出（`scrapydweb -h` 在 `parse_args` 内返回） | — |

> 注意 `-sw` 改的是 **DB 持久化状态**（`run.py:254-258` 调 `handle_metadata`），不是进程内开关，重启后仍生效。

### 3.1 对 dopilot 的 CLI 改造点

- **命令名**：`-dc` 是开发期绕过 scrapyd 连通性硬断言的现成开关；dopilot 在无 scrapyd 的纯 Docker/脚本环境下必须用它，或改造该断言（见 §7）。
- **新增参数**：dopilot 若增加节点策略默认值、worker 类型过滤等，应在 `parse_args` 加 `add_argument`，并在 `update_app_config` 加合并分支，保持"CLI 优先级最高"的一致语义。

---

## 4. App Factory 与路由 / Blueprint 注册

### 4.1 create_app（app factory）

`create_app(test_config=None)`，`__init__.py:64-107`。典型 app factory，配置加载分三步（见 §5）：

```
from_mapping(SECRET_KEY='dev')                ← §7 gotcha：硬编码密钥
from_object('scrapydweb.default_settings')    ← 默认值
from_pyfile('config.py', silent=True)         ← instance 目录（test_config 非空时改用 from_mapping）
```

随后依次：`handle_db` → `handle_route` → `handle_template_context`，注册 500 handler、`regex_replace` 过滤器、
改 Jinja 分隔符、`Compress().init_app(app)`，返回 `app`。

> **事实补充**：`create_app` 内还注册了一个 `/hello` 路由（`__init__.py:79-81`，返回 "Hello, World!"），
> 是遗留的脚手架路由。dopilot 清理时可删。

> **关键**：用户自定义 settings 的**最终覆盖不在 `create_app` 内**，而在 `run.py:load_custom_settings()`（第3层）与 CLI（第4层）。`create_app` 只负责前两层。

### 4.2 两种路由注册方式并存

scrapydweb **混用** 两种注册机制（`handle_route`，`__init__.py:147-297`）：

**(A) class-based MethodView + `add_url_rule`（主力）**

内部 `register_view(view, endpoint, url_defaults_list, with_node=True, trailing_slash=True)`：

- `with_node=True` 时，每条 rule 前缀 `/<int:node>/`（节点维度，node 从 1 起）；
- `with_node=False` 时，rule 不带 node 前缀，但 `defaults` 补 `node=1`。

注册的视图（节选，`__init__.py:161-297`）：

| 分组 | 视图 | endpoint | 备注 |
|---|---|---|---|
| 首页 | `IndexView` | `index` | 手动 add_url_rule，带/不带 node 两条 |
| API | `ApiView` | `api` | scrapyd API 代理 |
| 元数据 | `MetadataView` | `metadata` | 来自 baseview.py |
| Overview | `ServersView` / `MultinodeView` | `servers` / `multinode` | **多节点同时操作**（节点策略相关） |
| Overview | `TasksView` / `TasksXhrView` | `tasks` / `tasks.xhr` | 定时任务结果 |
| Dashboard | `JobsView` / `JobsXhrView` | `jobs` / `jobs.xhr` | 作业列表 |
| Dashboard | `NodeReportsView` / `ClusterReportsView` | `nodereports` / `clusterreports` | 统计报表 |
| Operations | `DeployView` 系列 | `deploy*` | 部署 |
| Operations | `ScheduleView` 系列（5个） | `schedule*` | **任务下发/节点选择核心** |
| Files | `LogView` / `LogsView` / `ItemsView` / `ProjectsView` | `log` / `logs` / `items` / `projects` | 日志/产出文件 |
| Utilities | `UploadLogView` / `UploadedLogView` | `parse.*` | 日志解析 |
| Utilities | `SendTextView` / `SendTextApiView` | `sendtext` / `sendtextapi` | 告警发送（`with_node=False`） |
| System | `SettingsView` | `settings` | 配置查看页 |

**(B) 真正的 Flask Blueprint（3 个）**

| Blueprint | 来源文件 | 注册行 |
|---|---|---|
| `bp_tasks_history` | `views/overview/tasks.py` 的 `bp` | `__init__.py:205-206` |
| `bp_schedule_history` | `views/operations/schedule.py` 的 `bp` | `__init__.py:241-242` |
| `bp_parse_source` | `views/utilities/parse.py` 的 `bp` | `__init__.py:274-275` |

> **改造建议（dopilot 新增三类被调对象）**：新增"Docker 常驻爬虫""一次性 Python 脚本"的页面与下发逻辑时，
> 在 `handle_route` 里新增对应 MethodView 或 Blueprint（如 `docker` / `script` 视图）。
> 建议**统一用 Blueprint** 收敛，逐步淘汰 MethodView+add_url_rule 的混用，降低维护成本。
> 新视图同样可继承 `BaseView`（`views/baseview.py`）以复用配置读取。

### 4.3 handle_db / handle_template_context

| 函数 | 文件:行 | 职责要点 |
|---|---|---|
| `handle_db` | `__init__.py:110-144` | 设 `SQLALCHEMY_DATABASE_URI/_BINDS`（来自 vars.py）；`db.app = app`（旧版 2.x 用法）→ `db.init_app` → `db.create_all`；注册 `teardown_request` 做 session rollback/remove；写 Metadata 版本行；维护 `last_check_update_timestamp` / `pageview` |
| `handle_template_context` | `__init__.py:300-348` | 用 `@app.context_processor` 注入版本号、GitHub URL、Python/Scrapy/Scrapyd 版本，以及一大批 `url_for(static, ...)` 静态资源路径（按 `VERSION='v'+版本号去点` 取目录） |

> **i18n 接入点**：`handle_template_context` 是注入"当前 locale"等模板变量的天然位置；
> `create_app` 里 `Compress().init_app(app)` 附近是 `babel.init_app(app)` 的天然位置（见 §6）。

---

## 5. 配置加载与覆盖顺序

### 5.1 优先级（从低到高，后者覆盖前者）

```
                       低 ──────────────────────────────────────────► 高
  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐  ┌──────────────┐  ┌──────────┐
  │ 0. import 旁路│  │ 1. 默认值     │  │ 2. instance 配置  │  │ 3. 自定义文件  │  │ 4. CLI    │
  │  (vars.py)    │  │ default_      │  │ instance/config.py│  │ scrapydweb_   │  │ -b -p -ss │
  │  DATA_PATH /  │  │ settings.py   │  │ from_pyfile       │  │ settings_v11  │  │ -da ...   │
  │  DATABASE_URL │  │ from_object   │  │ (silent=True)     │  │ .py (cwd)     │  │ update_   │
  │  (早于 config)│  │               │  │ 一般不用          │  │ from_pyfile   │  │ app_config│
  └──────────────┘  └──────────────┘  └──────────────────┘  └──────────────┘  └──────────┘
        │                  │                   │                    │                │
   importlib 直接读    create_app()        create_app()        load_custom_      parse_args()+
   不经 app.config    __init__.py:70      __init__.py:74      settings()        update_app_config()
                                                              run.py:123        run.py:235
```

| 层 | 机制 | 文件:行 | 说明 |
|---|---|---|---|
| 0（旁路） | `importlib.import_module('scrapydweb_settings_v11')` | `vars.py:29-40` | **只取 `DATA_PATH` / `DATABASE_URL` 两键**，在 app 之前确定数据目录与库位置 |
| 1a | `from_mapping(SECRET_KEY='dev')` | `__init__.py:66-68` | 硬编码密钥（见 §7 gotcha） |
| 1b | `from_object('scrapydweb.default_settings')` | `__init__.py:70` | 加载全部大写默认值 |
| 2 | `from_pyfile('config.py', silent=True)` | `__init__.py:74` | Flask instance 目录，可选，一般为空 |
| 3 | `find_scrapydweb_settings_py` + `from_pyfile(path)` | `run.py:124-129` | cwd 的 `scrapydweb_settings_v11.py` |
| 4 | `update_app_config(config, args)` | `run.py:235-264` | CLI 参数，**最高优先级** |

随后 `check_app_config(config)`（`check_app_config.py:38`）做校验并**派生回写** `config`（如把 `SCRAPYD_SERVERS` 规整成并行列表）。

### 5.2 自定义配置文件的发现规则（容易踩坑）

| 事实 | 文件:行 |
|---|---|
| 文件名硬编码且带版本号：`SCRAPYDWEB_SETTINGS_PY = 'scrapydweb_settings_v11.py'` | `vars.py:29` |
| 发现逻辑**只在 `os.getcwd()` 当前目录查找，不向上递归**（递归实现已注释废弃） | `common.py:30-38` |
| 找不到 → `copyfile(default_settings.py)` 到 cwd 后 **`sys.exit`**（不会用默认值继续跑） | `run.py:130-150` |

### 5.3 DATA_PATH / DATABASE_URL 的双读取路径（重要）

这两个键有**两条独立读取链**，改造时两处都要照顾，否则数据目录/库位置不一致：

1. **import 期旁路**：`vars.py:32` 用 `importlib.import_module` 直接从自定义文件读 `DATA_PATH` / `DATABASE_URL`（在 `create_app` 之前就要确定）。优先用 `default_settings` 的值，其次 custom（见 `vars.py:45`、`vars.py:72` 的合并逻辑）。
2. **app.config 链**：其余配置走 `from_object` / `from_pyfile`。

`vars.py:73` 调 `setup_database(DATABASE_URL, DATABASE_PATH)` 派生出
`APSCHEDULER_DATABASE_URI / SQLALCHEMY_DATABASE_URI / SQLALCHEMY_BINDS`。

---

## 6. 关键配置分组表

下表按 `default_settings.py` 的注释分组整理，列出每项含义与**对 dopilot 的意义**。
（校验规则与派生逻辑见 `check_app_config.py`；运行期消费入口见 `views/baseview.py:51-114`。）

### 6.1 ScrapydWeb（服务自身）

| 配置项 | 默认值 | 含义 | 对 dopilot 的意义 |
|---|---|---|---|
| `SCRAPYDWEB_BIND` | `'0.0.0.0'` | Web 绑定地址 | 私有部署直接复用；`-b` 可覆盖 |
| `SCRAPYDWEB_PORT` | `5000` | Web 端口 | `-p` 可覆盖 |
| `ENABLE_AUTH` | `False` | 是否开启 Web 基础认证 | dopilot 若需多用户/角色，从这里扩展（见 §6.2 改造建议） |
| `USERNAME` / `PASSWORD` | `''` / `''` | 单账户凭据 | 当前是单账户 HTTP Basic Auth |
| `ENABLE_HTTPS` | `False` | HTTPS 开关 | 私有内网通常关；需要时配合下面两项 |
| `CERTIFICATE_FILEPATH` / `PRIVATEKEY_FILEPATH` | `''` | 证书/私钥路径 | `app.run(ssl_context=...)` 使用 |

### 6.2 Scrapyd / 节点（dopilot 改造核心）

| 配置项 | 默认值 | 含义 | 对 dopilot 的意义 |
|---|---|---|---|
| `SCRAPYD_SERVERS` | `['127.0.0.1:6800', ('username','password','localhost','6801','group')]` | 被调度节点列表，支持 `usr:psw@ip:port#group` 字符串或 5 元组 | **被调度对象的唯一声明来源**；dopilot 需扩成既能描述 scrapyd 也能描述 docker/脚本 worker |
| `CHECK_SCRAPYD_SERVERS` | `True` | 启动时是否检查 scrapyd 连通性 | **无 scrapyd 时必须设 False（或用 `-dc`）**，否则 `assert any(results)` 启动失败 |
| `LOCAL_SCRAPYD_SERVER` | `''` | 与 ScrapydWeb 同机的 scrapyd 标识 | 直接读本地日志文件用；dopilot 容器场景多数无意义 |
| `LOCAL_SCRAPYD_LOGS_DIR` | `''` | 本地 scrapy 日志目录 | 日志直读优化；Docker/脚本任务需另设日志机制 |
| `SCRAPYD_LOG_EXTENSIONS` | `['.log','.log.gz','.txt']` | 定位日志文件的扩展名序列 | 实时日志改造时需扩展或绕过 |
| `SCRAPYD_SERVERS_PUBLIC_URLS` | `None` | 反代场景的公网 URL，与 `SCRAPYD_SERVERS` **等长对齐** | 任何节点列表扩展都必须保持等长同序 |

> **派生事实**：`check_scrapyd_servers()`（`check_app_config.py:360-395`）会对 `SCRAPYD_SERVERS`
> 做 **排序 + set 去重 + 整体重写回 config**（变成 `'ip:port'` 字符串列表），并生成 4 个**靠下标对齐**的并行列表：
> `SCRAPYD_SERVERS` / `SCRAPYD_SERVERS_GROUPS` / `SCRAPYD_SERVERS_AUTHS` / `SCRAPYD_SERVERS_PUBLIC_URLS`。
> 后续按 `node` 索引（`SCRAPYD_SERVERS[node-1]`）取 URL/认证。**扩展节点模型时必须保持这四个列表等长且同序，否则会错位。**

> **改造建议（节点模型）**：dopilot 建议并行引入 `WORKER_NODES` 概念，节点可声明能力
> （`scrapyd` / `docker` / `python-script`）与连接方式（HTTP / docker daemon / SSH / 自研 agent）。
> 可复用 `check_scrapyd_servers` 的"解析→规范化并行列表"模式，但需放宽连通性硬断言（见 §7）。

### 6.3 Scrapy / 部署

| 配置项 | 默认值 | 含义 | 对 dopilot 的意义 |
|---|---|---|---|
| `SCRAPY_PROJECTS_DIR` | `''` | 本地 scrapy 项目目录（免打包直接选项目部署） | 仅 scrapy 类对象相关 |

### 6.4 Timer Tasks（定时任务）

| 配置项 | 默认值 | 含义 | 对 dopilot 的意义 |
|---|---|---|---|
| `JOBS_SNAPSHOT_INTERVAL` | `300` | 每 N 秒后台快照 Jobs 页并入库；0 关闭 | 注册为 interval job（memory store），见 `check_app_config.py:306` |
| `CHECK_TASK_RESULT_INTERVAL` | `300` | 每 N 秒清理过期任务结果 | 注册为 interval job，见 `check_app_config.py:329` |
| `KEEP_TASK_RESULT_LIMIT` | `1000` | 保留最近 N 条任务结果 | 与上配合 |
| `KEEP_TASK_RESULT_WITHIN_DAYS` | `31` | 保留最近 N 天任务结果 | 与上配合 |

> **改造建议（cron/interval）**：底层 APScheduler 已**原生支持 `interval` 与 `cron` 触发器**
> （`check_app_config.py` 内即用 `trigger='interval'` 注册）。dopilot 新增定时任务类型时
> **复用同一全局 `scheduler`**（`utils/scheduler.py:45`），新增 `add_job` 并把 `func` 指向新的
> Docker/脚本 executor。**加 cron 前务必显式设定时区**（见 §7：`timezone` 参数被注释掉了）。

### 6.5 Run Spider（运行参数默认值）

`SCHEDULE_EXPAND_SETTINGS_ARGUMENTS` / `SCHEDULE_CUSTOM_USER_AGENT` / `SCHEDULE_USER_AGENT` /
`SCHEDULE_ROBOTSTXT_OBEY` / `SCHEDULE_COOKIES_ENABLED` / `SCHEDULE_CONCURRENT_REQUESTS` /
`SCHEDULE_DOWNLOAD_DELAY` / `SCHEDULE_ADDITIONAL`（`default_settings.py:154-182`）。

> 这些是 scrapy 任务下发表单的默认值，对 dopilot 的 Docker/脚本对象基本不适用，可保留供 scrapy 路径使用。

### 6.6 Page Display（页面显示）

| 配置项 | default_settings.py | check_app_config 默认 | 对 dopilot 的意义 |
|---|---|---|---|
| `SHOW_SCRAPYD_ITEMS` | `True` | `True` | 是否显示 Items 页 |
| `SHOW_JOBS_JOB_COLUMN` | **`True`** (L191) | **`False`** (L189) | **⚠ 两处默认值不一致**（见 §7） |
| `JOBS_FINISHED_JOBS_LIMIT` | `0`（不限） | `0` | 非 DB 视图显示的已完成作业数 |
| `JOBS_RELOAD_INTERVAL` | `300` | `300` | Jobs 页自动刷新秒数 |
| `DAEMONSTATUS_REFRESH_INTERVAL` | `10` | `10` | 节点负载刷新秒数 |

> Page Display 配置 dopilot 可整体保留。i18n 改造时把页面**硬编码文案**替换为 `{{ _('...') }}`（见 §6.9）。

### 6.7 Send Text（消息发送）

Slack（`SLACK_TOKEN` / `SLACK_CHANNEL`）、Telegram（`TELEGRAM_TOKEN` / `TELEGRAM_CHAT_ID`）、
Email（`EMAIL_SUBJECT` / `EMAIL_USERNAME` / `EMAIL_PASSWORD` / `EMAIL_SENDER` / `EMAIL_RECIPIENTS`）、
SMTP（`SMTP_SERVER` / `SMTP_PORT` / `SMTP_OVER_SSL` / `SMTP_CONNECTION_TIMEOUT`），见 `default_settings.py:207-277`。

> **改造建议**：私有平台只需中文环境，可保留 `EMAIL_*` 邮件告警，按需精简 Slack/Telegram。

### 6.8 Monitor & Alert（监控告警）

`ENABLE_MONITOR`、`POLL_ROUND_INTERVAL` / `POLL_REQUEST_INTERVAL`、
`ENABLE_SLACK/TELEGRAM/EMAIL_ALERT`、`ALERT_WORKING_DAYS` / `ALERT_WORKING_HOURS`、
`ON_JOB_RUNNING_INTERVAL` / `ON_JOB_FINISHED`、以及 6 类 `LOG_<LEVEL>_THRESHOLD/TRIGGER_STOP/TRIGGER_FORCESTOP`
（`default_settings.py:280-361`）。

> **改造建议**：`LOG_xxx` 阈值触发器是针对 **scrapy 日志统计** 的，对 Docker 常驻进程/一次性脚本
> 不适用，需另设**健康检查 / 退出码 / 心跳超时**告警。

### 6.9 System（系统）

| 配置项 | 默认值 | 含义 | 对 dopilot 的意义 |
|---|---|---|---|
| `DEBUG` | `False` | debug 模式（浏览器显示交互调试器） | `-d` 可覆盖 |
| `VERBOSE` | `False` | 日志 INFO→DEBUG | `-v` 可覆盖 |
| `DATA_PATH` | `os.environ.get('DATA_PATH','')` | 程序数据根目录 | **import 期旁路读取**，改造两处都要兼容（见 §5.3） |
| `DATABASE_URL` | `os.environ.get('DATABASE_URL','')` | 数据库后端（默认 SQLite，可 MySQL/PG） | 多节点高并发建议改 MySQL/PG；同样 import 期旁路读取 |

> **i18n 现状与建议**：当前**没有 i18n 框架**，模板文案中英混排在 `templates/` 内（现状事实）。
> dopilot 接入建议：
> 1. `setup.py:install_requires` 加 `Flask-Babel`（注意与 Flask 2.0 兼容性，见 §1.1）；
> 2. `create_app` 里 `Compress().init_app(app)` 附近 `babel.init_app(app)`，配置 `BABEL_DEFAULT_LOCALE='zh'` 与 `locale_selector`；
> 3. `default_settings.py` 新增 `LANGUAGE` / `DEFAULT_LOCALE`（默认 `'zh'`）；
> 4. 模板硬编码文案改 `{{ _('...') }}`，在 `handle_template_context` 注入当前 locale。
> 当前需求只需中文，但应先把框架搭好，预留多语言扩展位。

---

## 7. 现状陷阱与改造风险（Gotchas）

> 区分清楚哪些是**现状事实**、哪些是**改造建议**，避免踩坑。

| # | 类别 | 内容 | 证据 | 对 dopilot 影响 / 建议 |
|---|---|---|---|---|
| G1 | 事实 | **生产服务器**：`app.run()` 用 werkzeug 内置开发服务器，`threaded` 默认开、`use_reloader=False` 写死，非生产级 | `run.py:119-120` | 生产化改 gunicorn/uwsgi；但多 worker 下 BackgroundScheduler 与子进程会被**重复启动**，必须保证单 worker 或外置调度 |
| G2 | 事实 | **调度器在 import 时启动**，非 main 显式启动；只要 import 了 `scheduler` 就已运行（paused），`check_app_config` 仅负责 `resume` | `utils/scheduler.py:90`；`check_app_config.py:288-290` | 别误以为能在 `main` 控制调度器生命周期 |
| G3 | 事实 | **强制 scrapyd 连通性断言**：所有节点都连不上 → `AssertionError` → `sys.exit` | `check_app_config.py:429`（`assert any(results)`）→ `run.py:43-48` | dopilot 无 scrapyd 时直接启动失败；**用 `-dc` 或改造该断言**（按节点类型分流，仅对 scrapyd 类节点做连通性检查） |
| G4 | 事实 | **首次运行强制退出**：找不到 `scrapydweb_settings_v11.py` 时拷模板 + `sys.exit`，首次不会真正起服务 | `run.py:130-150` | 部署脚本/容器镜像需预置好该文件再启动；或改造为"无文件时用默认值继续" |
| G5 | 事实 | **import 期副作用重**：`vars.py` 一被导入即 mkdir、`setup_database()`、清 PARSE/DEPLOY/SCHEDULE 目录、`setup_logfile()` | `vars.py:59-74`、`vars.py:138` | 单测/二次封装难以纯函数化；改造时若需 import 而不触发副作用，需重构 vars.py |
| G6 | 事实/风险 | **依赖严格钉死**（Flask 2.0、Werkzeug 2.0、SQLAlchemy 1.3.24、Flask-SQLAlchemy 2.4.0、APScheduler 3.6.0 等） | `setup.py:35-57` | 引 Flask-Babel / Docker SDK 等需挑兼容旧版的版本，或先做依赖现代化 |
| G7 | 风险 | **`db.app = app`** 依赖旧版 Flask-SQLAlchemy 2.x 全局绑定，3.x 已移除 | `__init__.py:123` | 升级 Flask-SQLAlchemy 3.x 时此处会破裂，需改用 `init_app` + app_context 模式 |
| G8 | 事实 | **两套配置文件机制**：`from_pyfile('config.py')` 是 instance 目录；真正面向用户的是 cwd 的 `scrapydweb_settings_v11.py`（在 run.py 加载） | `__init__.py:74`；`run.py:124-129` | 容易混淆；dopilot 文档/部署需明确说明用户只需关心后者 |
| G9 | 事实 | **Jinja 变量分隔符被改成 `'{{ '` / `' }}'`（带空格）** | `__init__.py:100-101` | 新增模板必须遵循此约定，否则变量不渲染 |
| G10 | 事实 | **`-sw` 翻转的是 DB metadata 持久化状态**（`scheduler_state`），非进程内开关，重启仍生效 | `run.py:254-258` | 调试调度器开关时注意状态来源是 DB 不是 config |
| G11 | 事实 | **`SHOW_JOBS_JOB_COLUMN` 两处默认值不一致**：`default_settings.py:191`=`True`，`check_app_config.py:189` 的 `check_assert` 默认=`False` | 见证据列 | 实际加载 `default_settings.py`(True) 为准，但用户文件没设且某路径只走 check_assert 默认时可能拿到 False；改造时统一 |
| G12 | 事实 | **`SECRET_KEY` 硬编码为 `'dev'`** | `__init__.py:66-67` | 生产/私有部署应覆盖为安全随机值，否则 session 不安全 |
| G13 | 事实 | **`scheduler` 的 `timezone` 参数被注释掉**（用系统默认时区） | `utils/scheduler.py:44-45` | dopilot 加 cron 调度前最好显式设定时区，避免容器内 UTC 跨时区踩坑 |
| G14 | 事实 | **节点选择（指定/全部）不是静态配置项**，而是每次请求经表单 `checked_amount` / `selected_nodes` 传入并存进 task 表 | `views/operations/schedule.py`（消费点） | "随机选一个节点"策略要在**请求处理/任务模型层**加（如策略字段 `all`/`specified`/`random`），不能只加一个 settings 项 |
| G15 | 事实 | **子进程随父进程退出**：Linux 下用 `prctl(PR_SET_PDEATHSIG)` 保证父死子随之退出，`atexit` 注册 `kill_child` | `utils/sub_process.py:36-38`、`utils/sub_process.py:57`、`utils/sub_process.py:89` | 用 WSGI 容器多 worker 时此机制行为需重新评估 |

---

## 8. dopilot 改造点速查（按需求 A/B 映射）

| dopilot 需求 | 主要改造位置（文件:行） | 现状基础 | 关键注意 |
|---|---|---|---|
| 命令名 `scrapydweb→dopilot` | `setup.py:59-63`、`__version__.py:3` | console_scripts | 仅改命令名最省事；彻底重命名包需改全部 import |
| 三类被调对象（scrapy/docker/script） | `__init__.py:147` `handle_route`；`check_app_config.py:484` `init_subprocess` | 现全部假定经 scrapyd HTTP API | 新增 docker/script 视图；放宽 G3 连通性断言；新建 executor 替代 scrapyd schedule API |
| 实时日志流 | 现依赖 `LOCAL_SCRAPYD_LOGS_DIR`+logparser | scrapyd 日志文件 | 容器 stdout 需新机制（SSE/WebSocket）；扩展或绕过 `SCRAPYD_LOG_EXTENSIONS` |
| 定时任务（cron/interval） | `utils/scheduler.py:45`；`check_app_config.py:306/329`；`views/operations/schedule.py`、`execute_task.py` | APScheduler 原生支持 | 复用同一 scheduler；func 指向新 executor；显式设时区(G13) |
| 节点策略（指定/全部/随机） | `views/operations/schedule.py`（`selected_nodes`/`first_selected_node`）；`<int:node>` 维度 | 多选全部下发已有 | 新增策略字段，random 从候选随机取一个；可加 `DEFAULT_NODE_STRATEGY` 默认配置 |
| 推模式下发指定节点 | `views/operations/schedule.py`（POST `schedule.json`） | 对 scrapyd 天然是 push（HTTP POST） | docker/脚本节点需实现等价 push 通道（向 worker agent POST），按节点类型分流 |
| i18n（仅中文） | `create_app`（`__init__.py`）init babel；`handle_template_context` 注入 locale；`templates/` | 当前无 i18n | 加 Flask-Babel 依赖(注意 G6)；`BABEL_DEFAULT_LOCALE='zh'`；文案改 `{{ _('...') }}` |
| 绑定/端口/HTTPS/调试 | `run.py:107-120` `app.run`；`default_settings.py` System/ScrapydWeb 块 | 现成 | 生产化替换 WSGI 容器(G1) |
| 数据库后端 | `default_settings.py:387` `DATABASE_URL`；`vars.py:72-74` | 默认 SQLite | 多节点建议 MySQL/PG；注意 import 期旁路双读取(G5/§5.3) |

---

## 9. 关键文件清单

| 文件 | 角色 |
|---|---|
| `/workspaces/dopilot/setup.py` | 打包、console_scripts 入口、钉死依赖 |
| `/workspaces/dopilot/scrapydweb/run.py` | CLI 入口与主启动序列（`main` / `parse_args` / `load_custom_settings` / `update_app_config`） |
| `/workspaces/dopilot/scrapydweb/__init__.py` | app factory（`create_app` / `handle_db` / `handle_route` / `handle_template_context`） |
| `/workspaces/dopilot/scrapydweb/vars.py` | import 期全局初始化（目录、DB URI、常量、历史日志） |
| `/workspaces/dopilot/scrapydweb/__version__.py` | 元数据单一来源（`__title__` / `__version__` 等） |
| `/workspaces/dopilot/scrapydweb/default_settings.py` | 默认配置模板（首次运行被拷到 cwd） |
| `/workspaces/dopilot/scrapydweb/utils/check_app_config.py` | 配置校验 + 派生 + 运行时副作用（建表/连通性/起子进程/注册定时 job） |
| `/workspaces/dopilot/scrapydweb/utils/scheduler.py` | 全局 BackgroundScheduler（import 时 `start(paused=True)`） |
| `/workspaces/dopilot/scrapydweb/utils/sub_process.py` | LogParser/Monitor 子进程管理（Popen + prctl + atexit） |
| `/workspaces/dopilot/scrapydweb/common.py` | `find_scrapydweb_settings_py` / `handle_metadata` / `authenticate` |
| `/workspaces/dopilot/scrapydweb/views/baseview.py` | 配置消费统一入口（app.config → self.*） |
| `/workspaces/dopilot/scrapydweb/views/system/settings.py` | `/settings` 配置查看页（密码脱敏） |
| `/workspaces/dopilot/scrapydweb/views/operations/schedule.py` | 任务下发 / 节点选择实际消费点 |
