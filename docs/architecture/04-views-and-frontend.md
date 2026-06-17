# 04 · Web 视图、路由与前端

> 面向后续 dopilot 改造工程师。本篇覆盖 scrapydweb 的 Flask Web 层（视图 / 路由）与前端（模板 / 静态资源），并标注 dopilot 三类被调度对象、实时日志、定时调度、节点选择、推模式、i18n 的改造切入点。
>
> 文中区分两类内容：
> - **【现状】** = 已 Read/Grep 核实的事实，附 `file:line`。
> - **【建议】 / 【开放问题】** = 改造方案与待决策项，**尚未实现**。

---

## 0. 速读：这一层是什么

【现状】scrapydweb 的 Web 层不是"清一色 Blueprint"。绝大多数页面与端点是 `MethodView`/`flask.views.View` 的子类（统一继承 `BaseView`），在 `scrapydweb/__init__.py` 的 `handle_route()` 内用一个 `register_view()` 帮助函数 + `app.add_url_rule()` 集中注册。只有 `tasks`、`schedule`、`parse` 三个是**真正的 Flask Blueprint**，且各自只挂一个 `send_file` 子路由（history / source）。

```
浏览器请求
   │
   ▼
run.py  @app.before_request require_login()      ← 唯一全局鉴权(HTTP Basic Auth, 可选)
   │                                                注意:只在 run.py main() 里注册,见 §3
   ▼
URL 路由 (__init__.py handle_route)
   ├── /<int:node>/...   ← register_view() 注册的 MethodView 规则 (占绝大多数)
   └── /tasks/history/ · /schedule/history/ · /parse/source/<f>  ← 三个真 Blueprint
   │
   ▼
命中的 View 实例化 → BaseView.__init__()
   ├── 读取全部 config
   ├── 解析并 assert 校验 self.node (1..SCRAPYD_SERVERS_AMOUNT)
   ├── 据 node 选出 self.SCRAPYD_SERVER / AUTH / GROUP / public_url
   └── update_g() 注入侧边栏菜单 URL → flask g
   │
   ▼
dispatch_request()
   ├── 页面类: make_request()/get_response_from_view() 取数 → render_template → HTML
   └── API/XHR 类: json_dumps(as_response=True) → JSON
```

---

## 1. Blueprint 与路由全目录表

### 1.1 注册中枢：`register_view()`

【现状】`scrapydweb/__init__.py:148-159`

```python
def register_view(view, endpoint, url_defaults_list, with_node=True, trailing_slash=True):
    view_func = view.as_view(endpoint)
    for url, defaults in url_defaults_list:
        rule = '/<int:node>/%s' % url if with_node else '/%s' % url
        if trailing_slash:
            rule += '/'
        if not with_node:
            ... defaults['node'] = 1   # with_node=False 时默认 node=1
        app.add_url_rule(rule, defaults=defaults, view_func=view_func)
```

要点：
- `with_node=True`（默认）→ 规则带 `/<int:node>/` 前缀。
- `with_node=False` → 规则形如 `/<url>` 且写死 `defaults['node']=1`（目前仅 `SendTextApiView` 用，见 `__init__.py:280-293`）。
- 一个 View 可注册多条 URL + 默认参数，实现可选路径段。
- **endpoint 名里带点号（如 `'schedule.run'`、`'jobs.xhr'`）并不代表它是 Blueprint**，只是命名约定。

### 1.2 路由全表

【现状】下表逐条对应 `__init__.py:161-297`。除特别标注外，规则均带 `/<int:node>/` 前缀、带尾斜杠、`node` 默认 1。"类型"列 H=返回 HTML 页面、J=返回 JSON、F=`send_file`/`send_from_directory`。

| 分组 | endpoint | 代表 URL（去掉 `/<int:node>/` 前缀） | 视图类 | 文件 | 类型 |
|---|---|---|---|---|---|
| 根 | `index` | `/`（`__init__.py:162-164` 特例，非 register_view） | `IndexView` | `views/index.py` | 重定向 |
| 根 | `api` | `api/<opt>/<project>/<version_spider_job>` | `ApiView` | `views/api.py` | J |
| 根 | `metadata` | `metadata` | `MetadataView` | `views/baseview.py:432` | J |
| Overview | `servers` | `servers/<opt>/<project>/<version_job>/<spider>` | `ServersView` | `views/overview/servers.py` | H(+POST) |
| Overview | `multinode` | `multinode/<opt>/<project>/<version_job>` | `MultinodeView` | `views/overview/multinode.py` | H（POST only） |
| Overview | `tasks` | `tasks/<int:task_id>/<int:task_result_id>` | `TasksView` | `views/overview/tasks.py` | H |
| Overview | `tasks.xhr` | `tasks/xhr/<action>/<int:task_id>/<int:task_result_id>` | `TasksXhrView` | `views/overview/tasks.py` | J |
| **Blueprint** `tasks` | `tasks.tasks_history` | `/tasks/history/`（无 node） | 函数 `tasks.py:22` | `views/overview/tasks.py` | F |
| Dashboard | `jobs` | `jobs` | `JobsView` | `views/dashboard/jobs.py` | H（`?listjobs=True`→J） |
| Dashboard | `jobs.xhr` | `jobs/xhr/<action>/<int:id>` | `JobsXhrView` | `views/dashboard/jobs.py` | J |
| Dashboard | `nodereports` | `nodereports` | `NodeReportsView` | `views/dashboard/node_reports.py` | H |
| Dashboard | `clusterreports` | `clusterreports/<project>/<spider>/<job>` | `ClusterReportsView` | `views/dashboard/cluster_reports.py` | H |
| Operations | `deploy` | `deploy` | `DeployView` | `views/operations/deploy.py` | H |
| Operations | `deploy.upload` | `deploy/upload` | `DeployUploadView` | `views/operations/deploy.py` | H（POST 结果页） |
| Operations | `deploy.xhr` | `deploy/xhr/<eggname>/<project>/<version>` | `DeployXhrView` | `views/operations/deploy.py` | J |
| Operations | `schedule` | `schedule/<project>/<version>/<spider>` | `ScheduleView` | `views/operations/schedule.py` | H 表单页 |
| Operations | `schedule.check` | `schedule/check` | `ScheduleCheckView` | `views/operations/schedule.py` | J |
| Operations | `schedule.run` | `schedule/run` | `ScheduleRunView` | `views/operations/schedule.py` | H 结果页 |
| Operations | `schedule.xhr` | `schedule/xhr/<filename>` | `ScheduleXhrView` | `views/operations/schedule.py` | J |
| Operations | `schedule.task` | `schedule/task` | `ScheduleTaskView` | `views/operations/schedule.py` | J |
| **Blueprint** `schedule` | `schedule.schedule_history` | `/schedule/history/`（无 node） | 函数 `schedule.py:48` | `views/operations/schedule.py` | F |
| Files | `log` | `log/<opt>/<project>/<spider>/<job>` | `LogView` | `views/files/log.py` | H（`opt=report`→J） |
| Files | `logs` | `logs/<project>/<spider>` | `LogsView` | `views/files/logs.py` | H |
| Files | `items` | `items/<project>/<spider>` | `ItemsView` | `views/files/items.py` | H |
| Files | `projects` | `projects/<opt>/<project>/<version_spider_job>` | `ProjectsView` | `views/files/projects.py` | H |
| Utilities | `parse.upload` | `parse/upload` | `UploadLogView` | `views/utilities/parse.py` | H |
| Utilities | `parse.uploaded` | `parse/uploaded/<filename>` | `UploadedLogView` | `views/utilities/parse.py` | H |
| **Blueprint** `parse` | `parse.parse_source` | `/parse/source/<filename>`（无 node） | 函数 `parse.py:18` | `views/utilities/parse.py` | F |
| Utilities | `sendtext` | `sendtext` | `SendTextView` | `views/utilities/send_text.py` | H |
| Utilities | `sendtextapi` | `slack/<...>` `telegram/<...>` `tg/<...>` `email/<...>`（**无 node、无尾斜杠**） | `SendTextApiView` | `views/utilities/send_text.py` | J |
| System | `settings` | `settings` | `SettingsView` | `views/system/settings.py` | H（只读） |

### 1.3 三个真 Blueprint 一览

【现状】

| Blueprint 变量 | 定义处 | `url_prefix` | 唯一路由 | 作用 |
|---|---|---|---|---|
| `bp = Blueprint('tasks', ...)` | `tasks.py:19` | `'/'` | `/tasks/history/` → `send_file` | 定时任务历史日志下载 |
| `bp = Blueprint('schedule', ...)` | `schedule.py:45` | `'/'` | `/schedule/history/` → `send_file` | Run Spider 历史日志下载 |
| `bp = Blueprint('parse', ...)` | `parse.py:15` | `'/'` | `/parse/source/<filename>` → `send_from_directory` | 上传日志源文件读取 |

> **gotcha**：查 URL 全表只能看 `__init__.py`，不要去各文件里找 Blueprint —— 99% 的端点不在 Blueprint 里。

### 1.4 dopilot 改造挂载点

【建议】新增"Docker 常驻爬虫""一次性 Python 脚本"两类对象的页面与端点时，统一从 `handle_route()` 里 `register_view()` 挂载（保持 `<int:node>` 语义），不要另起 Blueprint 体系以免割裂路由全表。详见 §10。

---

## 2. 视图基类与公共行为（`BaseView`）

【现状】`scrapydweb/views/baseview.py`。`class BaseView(View)`，`methods = ['GET', 'POST']`（baseview.py:46）。所有视图继承它，`__init__()` 在每次请求实例化时执行下列共享逻辑：

| 行为 | 位置 | 说明 |
|---|---|---|
| 读取全部 config | baseview.py:48-187 | 把 `app.config` 几十个键拷成 `self.*`（路径、Scrapyd 列表、调度、通知、监控阈值等） |
| 解析并校验 node | baseview.py:189-192 | `self.node = view_args['node']`；`assert 0 < node <= SCRAPYD_SERVERS_AMOUNT`，越界 → `AssertionError` → 被 500 处理 |
| 按 node 选目标节点 | baseview.py:193-197 | `self.SCRAPYD_SERVER / IS_LOCAL_SCRAPYD_SERVER / GROUP / AUTH / SCRAPYD_SERVER_PUBLIC_URL`——**节点选择底座** |
| UA / 移动端检测 | baseview.py:199-216 | `IS_MOBILE / IS_IPAD / IS_IE_EDGE / USE_MOBILEUI`（`?ui=mobile`） |
| 计算 FEATURES 串 | baseview.py:217-237 | 给埋点/调试用的功能位（A/D/L/Sl/…） |
| `update_g()` | baseview.py:240、356-383 | 注入侧边栏菜单 URL 到 `flask g`（见 §6.3） |

### 2.1 关键公共方法

| 方法 | 位置 | 作用 / 改造相关性 |
|---|---|---|
| `make_request()` | baseview.py:285-354 | 统一下游 HTTP（`session.get/post` + auth + timeout=60 + JSON 解析 + 错误 tip）。**所有视图向 Scrapyd 转发都经它**——接入 Docker/脚本后端时是需要旁路或抽象的关键点 |
| `get_response_from_view()` | baseview.py:253-255 | 应用内"自调用"（带上自身 auth 回打本应用某端点），`TaskExecutor` 依赖它 |
| `get_selected_nodes()` | baseview.py:257-262 | 收集 `request.form[str(n)]=='on'` 的节点编号列表——多节点勾选解析入口（§5） |
| `json_dumps(as_response=True)` | baseview.py:268-279 | 统一 JSON 响应（`Response(..., mimetype='application/json')`）；`as_response=False` 时返回字符串 |
| `update_g()` | baseview.py:356-383 | 见 §6.3 |
| `safe_walk()` | baseview.py:391-429 | 容忍非法文件名的 `os.walk` 包装 |

### 2.2 `MetadataView`

【现状】baseview.py:432-438，与 `BaseView` 同文件。`GET /<node>/metadata/` 直接 `json_dumps(handle_metadata(), as_response=True)`，是个纯 JSON 端点。

---

## 3. 鉴权：在 `run.py` 而非视图层

【现状】`scrapydweb/run.py:51-58`

```python
@app.before_request
def require_login():
    if app.config.get('ENABLE_AUTH', False):
        auth = request.authorization
        ... if not auth or not (auth.username == USERNAME and auth.password == PASSWORD):
            return authenticate()
```

| 事实 | 影响 |
|---|---|
| 唯一全局鉴权钩子，只做 HTTP Basic Auth | 无会话、无角色、无端点粒度 |
| **`require_login` 在 `run.py` 的 `main()` 里注册，`create_app()`（`__init__.py`）不注册它** | **直接用 `create_app` 起服务（如 WSGI 部署、测试）将完全没有鉴权** |
| `BaseView` 里的 `ENABLE_AUTH/USERNAME/PASSWORD`（baseview.py:85-87） | 是用于**向下游 Scrapyd 转发认证**，与上面这个面向浏览器的 Basic Auth 是两回事，别混淆 |

【开放问题】dopilot 私有平台若需要登录态/RBAC/审计，须在此重构鉴权（迁移到 `create_app`、引入会话/JWT、加端点粒度），这是安全基线决策。

---

## 4. 各视图职责速查（按分组）

【现状】

**根级**
- `IndexView`（index.py）：`/` 与 `/<node>/` 纯重定向（单节点/移动端→jobs；多节点→servers）。
- `ApiView`（api.py）：JSON API 代理。把内部 `opt`（daemonstatus/listprojects/listversions/listspiders/listjobs/start/stop/forcestop/delversion/delproject/liststats）翻译并转发到**单个**节点的 Scrapyd `*.json`。前端单节点操作统一入口。主流程 `dispatch_request`：`update_url → update_data → get_result → handle_result`。

**Overview**
- `ServersView`：多节点总览 HTML，聚合各节点 daemonstatus，POST 时 `get_selected_nodes()` 收集勾选。
- `MultinodeView`：`methods=['POST']` 的 HTML 结果页，对 `selected_nodes` 批量 stop/delversion/delproject（前端再逐节点调 api）——**"指定节点全部执行"的核心**。
- `TasksView` / `TasksXhrView`：定时任务三层分页页面（Task / TaskResult / TaskJobResult）+ JSON 操作（enable/disable 调度器、pause/resume/remove/delete/fire/dump/list，分发在 `TasksXhrView.generate_response`）。

**Dashboard**
- `JobsView` / `JobsXhrView`：作业看板（database/classic/mobileui 三套模板；`?listjobs=True`→JSON），抓 Scrapyd `/jobs` 入库；Xhr 按 id 软删记录。
- `NodeReportsView`：单节点报告，内部回调 `jobs?listjobs=True` 汇总 pending/running/finished。
- `ClusterReportsView`：按 project/spider/job 跨节点聚合。

**Operations**
- `DeployView` / `DeployUploadView` / `DeployXhrView`：列可部署项目 / 打 egg 上传 `addversion.json`（可跨多节点）/ 按 eggname 转发。
- `ScheduleView` 等 5 个：Run Spider 与定时调度核心，见 §7。
- `TaskExecutor`（execute_task.py）：**非 HTTP 视图**，由 APScheduler 触发，推模式执行体，见 §8。

**Files**
- `LogView`（log.py）：实时日志核心，见 §9。
- `LogsView` / `ItemsView`：列日志目录 / items 目录（共用 `logs_items.html`）。
- `ProjectsView`：项目管理，`opt=listprojects/listversions/listspiders`，删版本/删项目。

**Utilities / System**
- `UploadLogView` / `UploadedLogView`：离线日志上传与 LogParser 解析展示。
- `SendTextView`（HTML 测试表单）/ `SendTextApiView`（JSON，无 node、无尾斜杠：`/slack /telegram /tg /email`）。
- `SettingsView`：只读展示当前 app 全部配置（`settings.html`）。

---

## 5. 节点选择策略（指定 / 全部 / 随机 / 推送）

### 5.1 现状

【现状】

| 能力 | 实现 | 位置 |
|---|---|---|
| 指定多节点"全部执行" | 前端复选框 → `get_selected_nodes()` 收集 `selected_nodes` 列表 → `MultinodeView` / `TaskExecutor` 逐节点下发 | baseview.py:257-262；multinode.py；execute_task.py:42-60 |
| 即时运行取首个节点 | `ScheduleRunView` 对即时运行取 `first_selected_node` | schedule.py（`handle_action`） |
| "随机选一个节点" | **不存在** | — |
| 节点策略持久化字段 | **不存在**（Task 表无 `node_strategy` 列） | — |

### 5.2 改造建议

【建议】
1. 前端：在 `include_multinodes_checkboxes.html` 或 `schedule.html` 增加策略单选 `el-radio`：`all` / `random` / `push`。
2. 后端持久化：给 `Task` 模型加 `node_strategy` 列，并在 `ScheduleCheckView.update_data_for_timer_task` 的 `__task_data` 里带上它。
3. 执行：在 `TaskExecutor.main()`（execute_task.py:42）遍历前，对 `self.selected_nodes` 做策略归约——`random` 时 `random.choice(selected_nodes)`，`all` 时保持全集。
4. 即时运行路径（`ScheduleRunView`）同步支持随机。

---

## 6. 模板继承结构 / 导航 / 品牌

### 6.1 模板目录与继承

【现状】`scrapydweb/templates/`

```
templates/
├── base.html              ← 桌面端主布局 (layout)，所有桌面页 {% extends %} 它
├── base_mobileui.html     ← 移动端主布局，jobs/stats/utf8/fail 的 _mobileui 版 extends 它
├── 500.html               ← 独立 500 错误页，【不继承 base】，自带 <head> 与硬编码 'ScrapydWeb'
└── scrapydweb/            ← 35 个页面/片段模板
    ├── 页面: servers/jobs(.classic/.mobileui)/tasks/schedule/deploy/projects/
    │         logs_items/utf8(.mobileui)/stats(.mobileui)/settings/send_text/parse/...
    ├── 结果页: schedule_results/deploy_results/multinode_results/fail(.mobileui)/...
    └── include 片段: include_multinodes_checkboxes / include_methods_sortruntime /
                       include_reports_* 等
```

继承链：

```
base.html  (桌面 layout: <head> 资源 + <nav> 品牌/节点 + <aside> 菜单 + block body)
   ├── scrapydweb/jobs.html         {% extends 'base.html' %}
   ├── scrapydweb/schedule.html     {% extends 'base.html' %}  (Vue2 + Element-UI 表单)
   ├── scrapydweb/tasks.html        {% extends 'base.html' %}  (Vue2 + Element-UI 表格)
   └── ... 其余桌面页

base_mobileui.html  (移动 layout: 精简 nav, 无 aside)
   ├── scrapydweb/jobs_mobileui.html
   ├── scrapydweb/stats_mobileui.html
   ├── scrapydweb/utf8_mobileui.html
   └── scrapydweb/fail_mobileui.html

500.html  (孤立, 不 extends —— 改名时易遗漏)
```

> **gotcha**：桌面 / 移动两套布局各有独立 nav、品牌、title；`jobs/stats/utf8/fail` 各有 `_mobileui` 版本，改名与 i18n 须**两边都改**。

### 6.2 导航与品牌位置（改名 dopilot 的切入点）

【现状】

| 位置 | 文件:行 | 内容 |
|---|---|---|
| 桌面 `<title>` | `base.html:7` | `{% block title %}{% endblock %} - ScrapydWeb` |
| 桌面品牌块 | `base.html:57` | `<a class="title" target="_blank" href="{{ GITHUB_URL }}">ScrapydWeb</a>` |
| 移动端 `<title>` | `base_mobileui.html:7` | 含 ` - ScrapydWeb - mobileui` |
| 500 页 | `500.html`（`:6,:19` 等） | 自带 `<head>` 与硬编码 `ScrapydWeb` |
| 品牌块样式 | `static/v160/css/style.css` | `nav>.title`（width 160px、橙色背景 `#feb324`、三角伪元素、`.version` 子元素） |
| favicon / touch icon | `__init__.py:344-346` | `static_icon=.../icon/fav.ico`、`static_icon_apple_touch=.../icon/spiderman.png` |
| 底部 GitHub 按钮 | `base.html:293` | `<a class="github-button" href="{{ GITHUB_URL.replace('/scrapydweb','') }}">GitHub</a>` |

【建议】
- 引入全局 `BRAND_NAME` 变量（在 `__init__.py` 的 `inject_variable()` 注入），模板里改用 `{{ BRAND_NAME }}` 替代硬编码 `ScrapydWeb`。
- 替换 `static/v160/icon/` 下 `fav.ico` / `spiderman.png`，改 `style.css` 的 `nav>.title` 配色。
- `GITHUB_URL` 改为内部仓库或移除底部 GitHub 按钮（`base.html:293`）。
- 注意区分：UI 文案里的 `ScrapydWeb`（应改）与后端契约变量 `SCRAPYDWEB_VERSION` / `scrapydweb_version`（**不可改**，改了破坏 metadata/埋点契约）。

### 6.3 侧边栏菜单（`<aside>`）与 `update_g()`

【现状】桌面菜单在 `base.html:134-315`，分六组（`<h3>`）：

| 组（`<h3>` 行） | 菜单项 id / 文案（`<span>`） |
|---|---|
| Overview（:136） | `menu_servers` Servers · `menu_tasks` Timer Tasks |
| Dashboard（:157） | `menu_jobs` Jobs · `menu_nodereports` Node Reports · `menu_clusterreports` Cluster Reports |
| Operations（:188） | `menu_deploy` Deploy Project · `menu_schedule` Run Spider |
| Files（:209） | `menu_projects` Projects · `menu_logs` Logs · `menu_items` Items |
| Utilities（:240） | `menu_sendtext` Send Text · `menu_parse` Parse Log |
| System（:261） | `menu_settings` Settings（+ mobileui 链接 :272） |

每个菜单项的 `href` 取自 `g.url_menu_*`，由 `BaseView.update_g()` 每请求构建（baseview.py:356-383）：`g.url_menu_servers/jobs/nodereports/clusterreports/tasks/deploy/schedule/projects/logs/items/sendtext/parse/settings/mobileui`，外加 `g.url_daemonstatus`、`g.scheduler_state_*`（菜单计时器图标变色）。图标来自 `static/v160/js/icons_menu.js`（约 30 个 SVG symbol，`<use xlink:href="#icon-...">`）。

【建议】新增三类对象菜单：在 `<aside>` 相应 `<h3>` 组下加 `<li>`（复用现有 SVG 或新增 symbol），在 `update_g()` 挂 `g.url_menu_xxx`，再 `register_view` 注册对应页面。

---

## 7. 定时调度（cron / interval）

### 7.1 现状链路

【现状】`views/operations/schedule.py`

```
ScheduleView (HTML 表单页, 可从 Task 回填编辑)
   │ 提交
   ▼
ScheduleCheckView (JSON): prepare_data() 写 .pickle 暂存 → update_data_for_timer_task() 组装 __task_data → 生成 curl
   │
   ▼
ScheduleRunView.handle_action  ← 分叉点
   ├── 有 __task_data → db_insert_update_task() + add_update_task()  (scheduler.add_job, func=execute_task)
   └── 无 __task_data → make_request() 立即运行一次 schedule.json
```

### 7.2 trigger 硬编码 'cron'

【现状】**关键事实**：trigger 在两处被写死 `'cron'`，表单 `trigger` 字段看似可选但后端忽略：

```python
# schedule.py:189  (ScheduleView.update_kwargs)
self.kwargs['trigger'] = 'cron'

# schedule.py:299-300  (ScheduleCheckView.update_data_for_timer_task)
# trigger=request.form.get('trigger') or 'cron',   ← 原始可选写法被注释掉
trigger='cron',
```

`update_data_for_timer_task`（schedule.py:291-328）组装的 `__task_data` 含 APScheduler cron 全字段：`year/month/day/week/day_of_week/hour/minute/second/start_date/end_date/timezone/jitter/misfire_grace_time/coalesce/max_instances`。

### 7.3 支持 interval 的改造

【建议】
1. 表单（`schedule.html`）：增加 `trigger` 选择（cron/interval）与 interval 字段（weeks/days/hours/minutes/seconds）。
2. 后端：改 `schedule.py:189` 与 `schedule.py:300` 两处，改读 `request.form.get('trigger')`；`update_data_for_timer_task` 按 trigger 分支组装不同字段。
3. `scheduler.add_job(...)` 传 `trigger='interval'` + interval 参数。
4. `Task` 模型加列以持久化 trigger 类型与 interval 字段。

> **gotcha**：只改表单不改这两处后端，trigger 仍恒为 cron。

---

## 8. 推模式：主动下发到指定节点

### 8.1 现状

【现状】`views/operations/execute_task.py`，`class TaskExecutor`（execute_task.py:19）——**不是 HTTP 视图**，由 APScheduler 后台进程到点调用。

```
APScheduler 到点
   ▼
TaskExecutor.main()  (execute_task.py:42)
   ├── get_task_result_id()
   └── for nodes in [selected_nodes, nodes_to_retry]:      ← 已内建失败重试集
          for node in nodes:
              schedule_task(node)   ← 主动 POST 该节点 schedule.json (push)
              db_insert_task_job_result(result)  → 写 TaskResult / TaskJobResult
```

要点：
- 已具 push 雏形：调度器进程**主动**逐节点下发，含 `nodes_to_retry` 重试（execute_task.py:39,44）与结果入库。
- **应用内自调用耦合**：`TaskExecutor` 通过 `get_response_from_view`（execute_task.py:8 导入）回打本应用的 `schedule.task` 端点，存在 self-request。

### 8.2 改造为 Docker/脚本类型

【建议】保留 `main()` 的"遍历 selected_nodes + 重试 + 入库"骨架，把 `schedule_task()` 里对 Scrapyd `schedule.json` 的 HTTP 调用替换/分派为对节点 **agent** 的下发接口（按对象类型路由：Scrapy→schedule.json，Docker→容器启动 API，脚本→脚本执行 API），复用现有重试与 `TaskResult/TaskJobResult` 入库逻辑。详见 §10。

---

## 9. 实时日志流（real-time）

### 9.1 现状：非真流式

【现状】`views/files/log.py`，`class LogView`（log.py:42）。`LogView.dispatch_request` 主流程按 `opt` 分支：

| `opt` | 行为 |
|---|---|
| `utf8` | 返回原始日志 HTML |
| `stats` | `?realtime=True` 实时解析，否则用 LogParser 缓存结果 |
| `report` | 返回 JSON（基于 `job_finished_report_dict` 等模块级缓存，log.py:35） |

数据来源：本地优先读 `LOCAL_SCRAPYD_LOGS_DIR`（log.py:57），否则请求 Scrapyd `/logs/...`（log.py:56）。`ENABLE_MONITOR` + POST 触发告警。

前端现状：`scrapydweb/templates/scrapydweb/utf8.html` 是服务端渲染 `<pre>{{ text }}</pre>` + "点击刷新"按钮的 **HTTP 轮询刷新**模式（依赖 `JOBS_RELOAD_INTERVAL` / `DAEMONSTATUS_REFRESH_INTERVAL`），**没有** EventSource / WebSocket。

### 9.2 改造建议

【建议】
1. 后端：在 `log.py` 加 `opt=stream` 分支（或新建专用视图），用 `flask.Response(stream_with_context(...))` 做 SSE，或引入独立 WS/ASGI 服务。
2. Docker 常驻进程：接其 stdout / `docker logs --follow`（经节点 agent 回传，见 §10）。
3. 前端：在 `utf8.html`（或新页）引入 `EventSource`/WebSocket 客户端 JS，追加日志行并自动滚动（可复用现有 `goLogBottom`/`go-bottom`）。

---

## 10. 三类被调度对象（Scrapy / Docker 常驻 / Python 脚本）

### 10.1 现状

【现状】所有执行/查询路径（`ApiView` / `schedule` / `TaskExecutor` / `LogView`）都**假定下游是 Scrapyd 的 `*.json` HTTP 接口**，经 `BaseView.make_request()`（baseview.py:285）统一发出。Docker 常驻/长连接进程与一次性 Python 脚本**完全没有现成支持**。

### 10.2 改造结构建议

【建议】

```
              ┌─────────────────────────── dopilot Web 层 ──────────────────────────┐
              │  register_view 注册新页面/端点 (__init__.py handle_route)            │
              │  BaseView 之上抽象 make_request → 多后端分派器                       │
              └───────────┬───────────────┬───────────────────┬─────────────────────┘
                          │ Scrapy        │ Docker 常驻        │ Python 脚本
                          ▼               ▼                    ▼
                   Scrapyd *.json   节点 agent: docker run   节点 agent: 执行脚本
                                    + docker logs --follow   + 回传 stdout
                          └───────────────┴───────────────────┘
                                 结果统一写 TaskResult / TaskJobResult
```

落地步骤：
1. 在 `handle_route()` 用 `register_view()` 注册三类对象各自的页面与端点（参考 `schedule.html` 的 Vue 表单、`tasks.html` 的 `el-table` 列表）。
2. 新增**节点侧 agent**：负责下发 Docker/脚本任务 + 回传实时日志。
3. 在 `BaseView`（或其上）把 `make_request` 抽象成多后端分派器，兼容非 Scrapyd 后端；`TaskExecutor.schedule_task` 按对象类型路由（§8.2）。

【开放问题】节点 agent 的协议（HTTP/gRPC/消息队列）、容器编排粒度（直连 Docker / k8s）、长连接进程的健康检查与重连策略，均待设计。

---

## 11. 静态资源与版本目录

### 11.1 现状

【现状】

| 事实 | 位置 |
|---|---|
| 静态根 | `scrapydweb/static/v160/{css, js, icon, element-ui@2.4.6}` |
| 目录名 `v160` 由版本号推导 | `__init__.py:302` `VERSION = 'v' + __version__.replace('.', '')` |
| 版本号来源 | `__version__.py:4` `__version__ = '1.6.0'` → `v160` |
| 资源 URL 注入 | `__init__.py:300-347` `handle_template_context()` 的 `@app.context_processor inject_variable()`，注入全部 `static_css_* / static_js_* / static_icon_*` + `GITHUB_URL / SCRAPYDWEB_VERSION / PYTHON/SCRAPY/SCRAPYD_VERSION` |

主要 JS（`static/v160/js/`）：`common.js`（392 行原生 JS 工具：`my$`、`showLoader`、`refreshDaemonstatus`、`jobsXHR/taskXHR/deleteRowXHR`、`switchNode` 配套等）、`icons_menu.js`（SVG 雪碧图）、`echarts.min.js`、`vue.min.js`、`jquery.min.js`、`stats.js`、`multinode.js`、`stacktable.js`、`github_buttons.js`。Element-UI 整树在 `element-ui@2.4.6/`（含 `theme-chalk/fonts/element-icons.woff`，体积大）。

### 11.2 双交互体系

【现状】前端是 **MPA 多页应用 + 双交互体系**，不是 SPA：
- 普通页面：原生 JS + jQuery（loader、daemonstatus 轮询、菜单高亮、节点切换 `switchNode`）。
- 表单/表格页（schedule/tasks/servers/jobs/projects）：Vue2 + Element-UI，初始 data 由 Jinja2 `{{ }}` 内联注入（如 `schedule.html` 的 Vue `data` 约在 530-567 行），并用 `|replace|safe` 手工转义。

### 11.3 改造建议

【建议】
- **解耦目录名与版本号**：固定独立常量（如 `ASSET_VERSION`）替代 `'v'+__version__...`，否则改 dopilot 自己的 `__version__` 会让 `static/v160` 全部 404（须同步物理重命名整个目录树，含 `element-ui@2.4.6` 子树和 `icon`）。
- 新增 Vue 页时复刻 `schedule.html` 的 `|replace|safe` 转义模式以防 XSS / 语法破坏。

---

## 12. i18n 国际化（当前仅中文）

### 12.1 现状：完全缺失

【现状】**项目无任何 i18n 框架**——无 Flask-Babel、无 gettext、无 `{% trans %}`、`<html>` 标签（`base.html:2`）无 `lang` 属性。所有文案硬编码英文，分布在：

| 文案位置 | 例子 / 位置 | i18n 覆盖难度 |
|---|---|---|
| 模板 title / 品牌 | `base.html:7,57`；`base_mobileui.html:7`；`500.html` | 模板可覆盖 |
| 侧边栏菜单 `<span>` | `base.html:134-315`（Servers/Timer Tasks/Jobs/Deploy Project/Run Spider/...） | 模板可覆盖 |
| 各页面正文 | `templates/scrapydweb/*.html` | 模板可覆盖 |
| `flash()` / 视图字符串 | 各 `views/**/*.py` | 需后端 `gettext`/`_()` |
| **JS 内联文案** | `common.js` 的 `alert`、`schedule.html`/`deploy.html` 内联 `<script>`（如 'Check out the log of ScrapydWeb'、'No projects found...'） | **纯模板 i18n 覆盖不到，须单独处理** |
| Vue data / JS 变量里的品牌 | 如 `stats.html` `var by='ScrapydWeb'` | 需区分 UI 文案 vs 变量名 |

> **gotcha**：grep `_(` 或 `i18n` 命中的全部是 element-ui/vue/echarts/jquery 等压缩库，**不是**已有 i18n 基础，勿误判。

### 12.2 改造建议

【建议】
1. 引入 **Flask-Babel**：在 `create_app()` 初始化 Babel + locale selector（当前固定 `zh`），`<html lang="zh">`。
2. 模板英文串改 `{{ _('...') }}` / `{% trans %}`，提取 `.po`/`.mo` 并提供 zh 翻译。
3. 后端 `flash()`/字符串包 `gettext`。
4. JS 文案单独维护中文字典或由后端注入（模板 i18n 覆盖不到 JS）。
5. 首批集中替换点：`base.html` 的 title / nav / `<aside>` 菜单。

> **gotcha（Jinja 定界符）**：`__init__.py:100-101` 把 Jinja 变量定界符改成了 `variable_start_string = '{{ '`（带尾随空格）、`variable_end_string = ' }}'`（带前导空格）。即模板里必须写 `{{ var }}`（两侧带空格），写 `{{var}}` 不会被解析。自定义模板 / 翻译片段时务必遵守此非标准定界符。

---

## 13. 其它 gotchas 清单

【现状】

| # | 注意点 | 依据 |
|---|---|---|
| 1 | 几乎所有 URL 带 `<int:node>` 前缀且默认 node=1；`BaseView.__init__` 会 `assert 0<node<=AMOUNT`，越界 → AssertionError(500)。新视图务必经 `register_view` 注册以保 node 语义 | baseview.py:191-192 |
| 2 | 页面 vs JSON 看返回方式：`render_template`→HTML，`json_dumps(as_response=True)`→JSON。存在混合端点：`JobsView ?listjobs`、`LogView opt=report` 返回 JSON；`ServersView`/`ScheduleView` 同 URL 兼 GET 页面与 POST 处理 | §1.2 类型列 |
| 3 | 纯 JSON 端点：`ApiView`、`MetadataView`、所有 `*Xhr*`、`SendTextApiView`、`ScheduleCheck/Xhr/Task` | §1.2 |
| 4 | 外网埋点/版本检查：`jobs.html:18` / `servers.html:38` / `jobs_mobileui.html:42` / `jobs_classic.html:18` 内嵌 `https://my8100.pythonanywhere.com/check_update?...`；底部 `github_buttons.js`。**私有化 dopilot 应移除**，否则内网/离线环境失败请求 + 隐私外泄 | grep 已核实 |
| 5 | `metadata`（pageview/per_page/style 等）以**模块级 dict** 缓存在多个视图（jobs/tasks/servers），跨请求共享、可变；多进程部署会不一致 | log.py:30-37 同类模式 |
| 6 | `TaskExecutor` 非 HTTP 视图，由 APScheduler 后台进程调用，且经 `get_response_from_view` 回打本应用 `schedule.task`，存在应用内自调用耦合 | execute_task.py:8,42 |
| 7 | `500.html` 不继承 `base.html`，自带 `<head>` 与硬编码品牌，改名易遗漏 | §6.1 |

---

## 14. 改造切入点总表（一页速查）

| 需求 | 主要文件:符号 | 现状 | 改造动作 |
|---|---|---|---|
| 实时日志流 | `views/files/log.py` `LogView.dispatch_request`（log.py:42）；`templates/scrapydweb/utf8.html` | HTTP 轮询，非流式 | 加 `opt=stream`/新视图 + SSE/WS；前端 EventSource |
| 定时 cron/interval | `views/operations/schedule.py:189, 300`；`tasks.py` | trigger 硬编码 cron | 改两处 + 表单 + Task 模型加列 |
| 节点策略(全部/随机) | `baseview.py:257 get_selected_nodes`；`execute_task.py:42 main` | 仅"全部/取首个" | main 前策略归约 + node_strategy 字段 |
| 推模式下发 | `execute_task.py:42 main / schedule_task` | Scrapyd push 雏形 | schedule.json 替换为 agent 下发，复用重试/入库 |
| 三类调度对象 | `__init__.py handle_route register_view`；`baseview.py make_request` | 仅 Scrapyd | 注册新页面 + 节点 agent + 后端分派抽象 |
| 改名 dopilot | `base.html:7,57`；`base_mobileui.html:7`；`500.html`；`style.css nav>.title`；`icon/` | 硬编码 ScrapydWeb | BRAND_NAME 变量 + 换 icon/配色 + 移除 GitHub |
| i18n（中文） | 全模板 + 视图 flash + JS 文案；`__init__.py:100 jinja 定界符` | 无框架 | Flask-Babel + `_()`/`{% trans %}` + JS 字典 |
| 资源版本目录 | `__init__.py:302 VERSION`；`static/v160/` | 目录名绑版本号 | 引入独立 ASSET_VERSION 常量 |
| 鉴权 | `run.py:51 require_login` | 仅 Basic Auth，且 create_app 不注册 | 迁入 create_app + 会话/RBAC |
