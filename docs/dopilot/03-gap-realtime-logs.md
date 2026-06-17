# 改造分析：实时日志

> 面向 dopilot 改造工程师。本文区分「现状事实」（基于源码核实，标注 `file:line`）与「改造建议 / 开放问题」。
> 目标：为三类被调度对象（Scrapy/scrapyd 爬虫、Docker 常驻爬虫、Python 一次性脚本）提供统一的**真·实时日志流**。

---

## 0. 结论速览（TL;DR）

| 维度 | 现状事实 | 改造方向 |
| --- | --- | --- |
| 传输方式 | 整段拉取 + 前端 `location.reload(true)` 硬刷新，注释自承「SLOW」 | 服务端持续推送增量行（SSE 为主线） |
| 读取方式 | 一次性全量 `f.read()` / 整段 GET，无 tail/offset/follow | 增量 tail（本地 seek + 远程 offset 轮询） |
| scrapyd 日志 | 「伪实时」支持（唯一支持的执行器） | 复用文件源，包一层增量 tail |
| Docker stdout | **零支持** | 新增 `DockerLogSource`（docker SDK / `docker logs -f`） |
| Python 脚本 stdout | **零支持**（无 job 概念、无落盘位置） | stdout 重定向落盘 + 文件 tail |
| 日志源抽象 | 无，`LogView` 硬编码 scrapyd URL/本地文件 + logparser | 新增 `LogSource` 抽象层（三类执行器统一接口） |
| 运行环境 | Werkzeug dev server（threaded），无 SSE/WS 设施，`.venv` 无相关依赖 | MVP 零依赖跑 SSE；生产换 gunicorn gevent worker |

**推荐**：以「方案A：SSE + LogSource 抽象层」为主线，分两步走（先 scrapyd + 脚本，再补 Docker），并务必**先落地 `LogSource` 抽象**，避免三类执行器各改一遍 `LogView` 主流程。

---

## 1. 现状事实：logparser + 硬刷新轮询

scrapydweb **当前并无真正的「实时日志流」**。其日志能力完全建立在 scrapyd 的「日志文件 + logparser 解析」模型上，并且是**拉取式 + 整段读取 + 前端硬刷新**。

### 1.1 唯一的日志页：`LogView`

文件：`/workspaces/dopilot/scrapydweb/views/files/log.py`

`LogView` 按 `opt` 分三种模式（`log.py:89-96`）：

| opt | 含义 | 关键行 |
| --- | --- | --- |
| `utf8` | 原始日志，`self.utf8_realtime=True` | `log.py:89-91` |
| `stats` | LogParser 统计页；`?realtime=True` 时现场 parse | `log.py:92-94` |
| `report` | 返回 JSON 统计（无模板） | `log.py:74-75, 95-96` |

路由注册（`/workspaces/dopilot/scrapydweb/__init__.py:245-246`）：

```python
from .views.files.log import LogView
register_view(LogView, 'log', [('log/<opt>/<project>/<spider>/<job>', None)])
```

`register_view`（`__init__.py:148-159`）默认 `with_node=True`，自动加 `/<int:node>/` 前缀并补尾斜杠，最终 URL 形如：

```
/<int:node>/log/<opt>/<project>/<spider>/<job>/
```

`LogView` 继承 `BaseView`（`log.py:17,45`），由基类按 `self.node` 索引选定 scrapyd 节点，并预解析出 `self.SCRAPYD_SERVER / self.AUTH / self.log_path / self.url` 等定位信息（`log.py:56-57`）。job 唯一标识：

```python
# log.py:52
self.job_key = '/%s/%s/%s/%s' % (self.node, self.project, self.spider, self.job)
```

### 1.2 日志获取是「整段一次性」

```
                     dispatch_request (log.py:116-170)
                                │
              ┌─────────────────┴──────────────────┐
              ▼                                     ▼
   read_local_scrapy_log (log.py:221-234)   request_scrapy_log (log.py:236-248)
   本地优先：f.read() 读整个文件             否则：make_request 整段 GET
   (log.py:228-229)                          http://<scrapyd>/logs/.../job.log
```

- 本地：`read_local_scrapy_log()` 用 `f.read()` **读整个文件**（`log.py:228-229`）。
- 远程：`request_scrapy_log()` 用 `make_request` **一次性 GET 整个** `job.log`（`log.py:236-248`）。

**没有 tail、没有 offset 增量、没有 follow。** 长日志会越读越慢且每次重复传输全部内容。

### 1.3 所谓「real-time」实为前端硬刷新

模板 `/workspaces/dopilot/scrapydweb/templates/scrapydweb/utf8.html`：

```html
<!-- utf8.html:51-53 -->
<div id="log">
  <pre>{{ text }}</pre>     <!-- 整段日志一次性渲染进 <pre> -->
</div>
```

后端对未结束的 job 设刷新链接（`log.py:348-355`）：

```python
# log.py:352-355
if self.job_finished or self.job_key in job_finished_key_dict[self.node]:
    self.kwargs['url_refresh'] = ''
else:
    self.kwargs['url_refresh'] = 'javascript:location.reload(true);'
```

前端配一个 `setInterval` 计数器（`utf8.html:84-90`），文案直白承认慢：

```javascript
// utf8.html:88
my$('#refresh_button').innerHTML = "Loaded ... secs ago, click to hard reload (SLOW)";
```

stats 页同理靠 `location.reload`（`log.py:376`）。移动端 `utf8_mobileui.html:36,39-40` 结构相同（`<pre>{{ text }}</pre>` + `url_refresh` + `forceLoader`），**两套布局都要改**。

### 1.4 stats 的 `realtime` 分支仍是全量 + reload

`opt=stats&realtime=True`（`log.py:92-94`）只是跳过 logparser 缓存，每次请求用 `logparser.parse(self.text)` **重新解析整段日志**（`log.py:145-150`）：

```python
# log.py:149-150
self.logger.warning('Parse the whole log')
self.stats = parse(self.text)
```

仍是「全量拉取 + reload」，**非流式**。

### 1.5 后台 Poll 与「页面看日志」无关

`/workspaces/dopilot/scrapydweb/utils/poll.py` 是独立子进程，周期（`POLL_ROUND_INTERVAL` 默认 **300s**，`default_settings.py:290`；`poll.py:161` `time.sleep`）抓 scrapyd `/jobs` HTML（`poll.py:188-192`），再 POST 触发 `log.py` 的统计/告警（`poll.py:81,123-142`；`log.py:168` `if self.ENABLE_MONITOR and self.POST`）。它**只服务监控告警，与「页面实时看日志」无关**。

### 1.6 运行环境：无任何流式设施

| 事实 | 位置 |
| --- | --- |
| Werkzeug 内置开发服务器（threaded 默认开）`use_reloader=False` | `run.py:119-120` |
| 全局 Basic Auth 钩子（`@app.before_request def require_login`，依赖 `ENABLE_AUTH`），**无 session** | `run.py:51-58` |
| `setup.py` 钉死 `Flask==2.0.0` / `Werkzeug==2.0.0`（实际运行 Python **3.12.1**） | `setup.py:39,56` |
| `.venv` 中**无** flask-sock / flask-socketio / gevent / eventlet / simple-websocket / docker SDK | 实测 `site-packages` 无匹配 |
| `make_request` 仅 `session.get(url, ..., timeout)`，**无 `stream=True` / `iter_lines`** | `baseview.py:285-308` |
| 全局连接池 session（`pool_connections/maxsize=1000`）+ `basic_auth_header` 凭证 | `common.py:18-20,54` |

**结论**：对三类执行器，目前只有 scrapyd 文件这一种被「伪实时」支持，Docker 与脚本**完全无日志通道**。要做统一的真·实时日志流，需要**新增流式端点**与**日志源抽象层**。

---

## 2. 三类执行器的日志来源差异

| 维度 | ① Scrapy / scrapyd | ② Docker 常驻爬虫 | ③ Python 一次性脚本 |
| --- | --- | --- | --- |
| 日志产出位置 | scrapyd `/logs/<project>/<spider>/<job>.log` 文件 | 容器 **stdout/stderr** | 进程 **stdout/stderr** |
| 进程生命周期 | 跑完即退出（finite） | **常驻 / 长连接**（long-running，不退出） | 跑完即退出（finite，一次性） |
| 现状对接 | 「伪实时」（本地文件 / 远程 GET） | **零支持** | **零支持** |
| 是否有 job 概念 | 有（`job_key`，`log.py:52`） | 需自定义（container id / 任务 id） | **无**，需新建任务标识 |
| 落盘位置 | scrapyd 已落盘 | 默认在容器内，需采集 | **无落盘位置**，需新增 |
| 适配的 follow 机制 | 本地 `seek+tail` / 远程 offset 轮询或 Range | `docker logs --follow` / SDK `container.logs(stream=True, follow=True)` | stdout 重定向落盘后 `tail` |
| logparser 适用性 | 适用（scrapy 日志格式） | **不适用** | **不适用** |
| 日志增长边界 | 有限（job 结束即定长） | **无限增长**（需轮转/截断/保留策略） | 有限 |

### 关键差异图

```
①scrapyd  : [spider] --写--> job.log 文件 --(scrapyd 静态服务/本地盘)--> dopilot 拉取
②Docker   : [容器进程] --stdout--> docker daemon 日志驱动 --(docker API/CLI follow)--> dopilot 采集
③脚本      : [python 进程] --stdout--> ??? (现状无落盘) --需 Popen 重定向落盘--> dopilot tail
```

三者的统一编址可复用现有 `job_key='/node/project/spider/job'` 约定（`log.py:52`），在不同执行器间统一标识；落盘后统一走「文件 tail」是把②③拉齐到①的最短路径。

---

## 3. 统一实时日志流方案对比（WebSocket / SSE / 轮询）

核心抽象（无论选哪种传输）都建议引入 **`LogSource`** 接口，例如：

```
LogSource (抽象基类)
  ├─ open(job_key)
  ├─ iter_incremental()  -> 增量行迭代器（generator）
  └─ close()
       实现：
       ├─ ScrapydFileLogSource  本地 seek+tail / 远程 requests stream=True 或 offset 轮询
       ├─ DockerLogSource       docker SDK container.logs(stream,follow) 或 `docker logs -f`
       └─ ScriptLogSource       tail 脚本 stdout 落盘文件
```

> 现状事实：以上抽象与三类实现**均不存在**，需新建（建议 `/workspaces/dopilot/scrapydweb/utils/log_source.py`）。

### 方案对比

| 方案 | 传输方式 | 新依赖 | 与现状契合度 | 工作量 | 适用性（三类执行器） |
| --- | --- | --- | --- | --- | --- |
| **A. SSE + LogSource**（推荐基线） | `Response(stream_with_context(gen), mimetype='text/event-stream')` 单向推送 | **无**（纯 WSGI 可跑） | 高（与 `LogView`/`utf8.html` 同构） | 中 | 经 `LogSource` 后统一支持 |
| **B. WebSocket** | flask-sock / flask-socketio 双向 | 有（flask-sock+simple-websocket 或 gevent/eventlet） | 中（需验证 Flask2.0 兼容） | 中→高 | 经 `LogSource` 后统一支持 |
| **C. 增量轮询** | JSON 端点 `?offset=N` + 前端 `setInterval` fetch | **无** | 高（最小改造） | 低→中 | 需落盘成可 offset 读的文件 |
| **D. 节点 agent 推流 + 中心聚合** | 各节点 agent 采集 → 中心 → 浏览器 | 有（自研 agent 协议） | 低（平台级架构） | 高 | 分布式一致采集 |

### 各方案要点

**方案A：SSE（Server-Sent Events）** —— 推荐基线
- 做法：新增 `LogStreamView`（或 `opt='stream'`），返回 `text/event-stream`；后端实现 `LogSource` 三实现；前端 `utf8.html` 用 `EventSource` append 增量行 + 自动滚底；鉴权用 query token。
- 优点：单向推送对「看日志」足够；**纯 WSGI/Werkzeug threaded 下用 `stream_with_context` 即可直接跑，零新依赖**；浏览器原生 `EventSource` **自动重连**；改动集中、与现有结构同构。
- 缺点：SSE 单向（不能交互）；每条长连接占一个线程，dev server 连接数受限；远程 scrapyd 无原生 follow，文件源需自做 tail/offset；生产仍需换 gunicorn(gevent worker)。

**方案B：WebSocket（flask-sock / flask-socketio）**
- 优点：双向通道，未来可做日志搜索/过滤/暂停跟随等交互；同样可接 `LogSource`。
- 缺点：**新增依赖**，与钉死的 Flask2.0/Werkzeug2.0 需验证兼容；握手/心跳/重连要自管；丢失 EventSource 自动重连优势；运维需支持 WS 反代。

**方案C：增量轮询（offset-based，最小改造）**
- 做法：新增 JSON 端点 `/log/tail?offset=N` 返回从 offset 起的新增内容与新 offset；前端 `setInterval(1~2s)` fetch 增量 append（取代整页 reload）。文件源 `seek(offset)`，远程 scrapyd 用 Range 头或带 offset 请求。
- 优点：改造最小、风险最低；纯 WSGI 无长连接压力；不引入新依赖；**可作为不支持 SSE 环境的兜底**。
- 缺点：非真流式，有轮询延迟；Docker/脚本仍需落盘成可 offset 读的文件；远程 scrapyd 的 Range 支持取决于其静态文件服务；高频轮询有额外开销。

**方案D：节点 agent 推流 + 中心聚合（分布式正解）**
- 优点：真正分布式，对三类执行器一致；解耦采集与展示；可加缓冲/轮转/落库；契合 dopilot 多节点 push 模式。
- 缺点：工作量最大，需开发并部署 agent 协议与运维；中心需做连接管理与背压；**超出「实时日志」单点范围，属平台级架构**。

---

## 4. 推荐方案（分两步走）

> 以**方案A（SSE + LogSource 抽象层）为主线**，先做 scrapyd 与 Python 脚本两类，再补 Docker。

### 第一步（MVP）

1. 实现 `LogSource` 抽象接口 + `ScriptLogSource` + `ScrapydFileLogSource`。
2. 新增 `LogStreamView`（`opt='stream'`），用 `stream_with_context` 返回 `text/event-stream`。
3. 前端 `utf8.html`：把 `location.reload` 轮询替换为 `EventSource` 增量 append + 自动滚底（复用 `#log` 容器、`goLogBottom`/`go-bottom` 控件，`utf8.html:51-78`）。
4. 脚本日志：用 `sub_process.py` 的 `Popen + prctl(PR_SET_PDEATHSIG)` 范式（`sub_process.py:8,21-40,73-78`）拉起进程，把 stdout/stderr 重定向到 `SCRIPT_LOGS_PATH` 下文件，统一走文件 tail。

> **为什么选 SSE**：在现有 Werkzeug threaded WSGI 下**零新依赖即可跑**；浏览器原生重连；与现有 `LogView`/`utf8.html` 结构最贴近，改动集中可控。

### 第二步

1. 增加 `DockerLogSource`（docker SDK 或 `docker logs -f` 子进程）。
2. 把鉴权适配到 SSE（query token，因 `EventSource` 不能带自定义头）。

### 兜底与边界

- 同时提供**方案C 的 offset 增量轮询 JSON 端点**（与 `LogSource` 接口共用），作为不支持 SSE 环境的降级路径。
- **第一步明确不做** 方案B/D：WebSocket 与新依赖/服务器兼容性需额外验证（Flask2.0 钉死）；分布式 agent 属平台级架构演进，待执行器落地后再评估。
- **生产化**：把 dev server 换成 gunicorn gevent worker 以支撑长连接数（独立部署事项，见 §6 GAP-5）。

> ⚠️ **务必先落地 `LogSource` 抽象**，避免三类执行器各改一遍 `LogView` 主流程。

---

## 5. 改动文件清单（Touch Points）

| 文件 | 性质 | 改动要点 |
| --- | --- | --- |
| `/workspaces/dopilot/scrapydweb/views/files/log.py` | 改 | 新增 `opt='stream'`（或新建 `LogStreamView`）分支，`Response(stream_with_context(gen), mimetype='text/event-stream')` 返回 SSE；调用 `LogSource`，替代/补充整段 `read_local_scrapy_log`/`request_scrapy_log`（`log.py:221-248`） |
| `/workspaces/dopilot/scrapydweb/utils/log_source.py` | **新增** | `LogSource` 抽象基类（`open/iter_incremental/close`）+ 三实现 `ScrapydFileLogSource` / `DockerLogSource` / `ScriptLogSource` |
| `/workspaces/dopilot/scrapydweb/__init__.py` | 改 | `register_view` 注册流式/增量端点（如 `logstream`），保持 `/<int:node>/` 前缀与 node 语义（仿 `__init__.py:245-246`） |
| `/workspaces/dopilot/scrapydweb/templates/scrapydweb/utf8.html` | 改 | 把 `url_refresh=location.reload(true)` 硬刷新 + `setInterval` 计数器（`utf8.html:55-90`）替换为 `EventSource`：`onmessage` 时向 `#log` append 增量行并 `goLogBottom` 自动滚动；保留 `go-top/go-bottom` |
| `/workspaces/dopilot/scrapydweb/templates/scrapydweb/utf8_mobileui.html` | 改 | 移动端日志页同步替换为流式 append（`utf8_mobileui.html:36,39-40`） |
| `/workspaces/dopilot/scrapydweb/vars.py` | 改 | 新增 `SCRIPT_LOGS_PATH` / `DOCKER_LOGS_PATH` 等 data 子目录（仿 `STATS_PATH` 在 import 期 mkdir，`vars.py:57,59-62`），供脚本/容器 stdout 落盘 tail |
| `/workspaces/dopilot/scrapydweb/views/baseview.py` | 改 | 加 `stream=True` 的 `make_request` 变体（`session.get(stream=True)+iter_lines`，现状 `baseview.py:285-308` 无此能力），给 `ScrapydFileLogSource` 做远程增量；SSE 端点适配 query token 鉴权 |
| `/workspaces/dopilot/scrapydweb/run.py` | 改 | `require_login`（`run.py:51-58`）放行/适配 SSE 端点 token 鉴权（`EventSource` 不能带自定义头）；生产部署改用 gunicorn gevent worker 承载长连接（注释/文档，`run.py:119-120`） |
| `/workspaces/dopilot/scrapydweb/utils/sub_process.py` | 改 | 脚本/容器执行器用 `Popen+prctl` 范式（`sub_process.py:73-78`）拉起进程时，stdout/stderr 重定向到 `SCRIPT_LOGS_PATH` 下日志文件，使其可被统一 tail |
| `/workspaces/dopilot/scrapydweb/common.py` | 复用 | 流式拉取复用全局 `requests.Session`（连接池 1000）与 `basic_auth_header` 凭证（`common.py:18-20,54`） |
| `/workspaces/dopilot/setup.py` | 改（条件） | 若选 WebSocket（方案B）或 `DockerLogSource`，新增 flask-sock/simple-websocket 或 docker SDK，并验证与钉死的 `Flask==2.0.0`/`Werkzeug==2.0.0`（`setup.py:39,56`）兼容（**SSE 方案A 不需新依赖**） |
| `/workspaces/dopilot/scrapydweb/default_settings.py` | 改 | 新增实时日志配置（`LOG_STREAM_ENABLED` / `LOG_STREAM_POLL_INTERVAL` / `LOG_TAIL_LINES` / 脚本容器日志保留轮转策略），并在 `check_app_config.py` 加校验 |

> 复用提示：`LogView` 的 node 解析 / opt 分派骨架、`BaseView.__init__` 已解析的 `self.node/self.SCRAPYD_SERVER/self.AUTH/self.log_path/self.url`、`get_selected_nodes`（`baseview.py:257-262`）的 node 选择逻辑，均可直接复用，避免重写节点寻址。

---

## 6. GAP 清单（现状缺口）

| 编号 | GAP | 为什么是缺口（依据） |
| --- | --- | --- |
| GAP-1 | 完全没有流式传输通道（无 SSE/无 WebSocket） | 整段拉取 + `location.reload(true)` 硬刷新（`utf8.html:55-91`、`log.py:348-355`），延迟大、整页重载、对 long-running 进程不可用 |
| GAP-2 | 日志读取一次性全量，无 tail/follow/offset | `read_local_scrapy_log` 用 `f.read()`（`log.py:228`），`request_scrapy_log` 整段 GET（`log.py:236-248`）；长日志越读越慢且重复传输 |
| GAP-3 | Docker 容器 stdout 无任何对接 | 所有路径假定 scrapyd `/logs/<project>/<spider>/<job>.log` 结构；容器日志在 stdout，需 `docker logs --follow` / SDK attach，现状零支持 |
| GAP-4 | Python 一次性脚本 stdout 无任何对接 | 脚本无 scrapyd job 概念，也无落盘位置；缺少捕获 stdout/stderr 的机制 |
| GAP-5 | 日志源无抽象层（executor-agnostic） | `LogView` 硬编码 scrapyd URL/本地文件 + logparser；三类执行器需统一接口，否则每类都得改主流程 |
| GAP-6 | WSGI dev server + threaded 不适合大量长连接 | `run.py:119` Werkzeug threaded dev server，每个 SSE/WS 长连接占一线程；多人同看会耗尽线程池；生产不应用 dev server；WS 在纯 WSGI 下需 flask-sock 或换 ASGI/gevent |
| GAP-7 | long-running 日志生命周期与轮转未定义 | 常驻容器日志无限增长，需轮转/截断/保留 + 「从最后 N 行起播」；现有 `KEEP_*_RESULT` 只针对 task result，不覆盖日志 |
| GAP-8 | 鉴权与流式端点内部调用链 | `require_login` 是全局 Basic Auth 钩子（`run.py:51-58`）；`EventSource` 不能带自定义头，需 query token 或 cookie session 适配（**现状无 session**） |
| GAP-9 | 前端 i18n 与日志页文案硬编码英文 | `utf8.html` 文案如 "Click to refresh"（`utf8.html:56`）硬编码；dopilot 需中文 + i18n 框架（当前无） |

---

## 7. 开放问题（待决策）

1. **传输选型**：SSE 还是 WebSocket？是否接受为 WS 引入新依赖并验证与 Flask2.0/Werkzeug2.0（实际 Python3.12）兼容？还是先 SSE 零依赖落地？
2. **部署形态**：生产换成 gunicorn(gevent/eventlet worker) 还是继续 Werkzeug dev server？长连接数上限与背压策略如何定？
3. **远程 scrapyd 真增量**：scrapyd 静态文件服务是否支持 HTTP Range？不支持时是否接受 offset 轮询 / 在每节点装 agent？
4. **Docker 日志采集路径**：dopilot 中心直连各节点 docker daemon（SDK/远程 API），还是每节点装 agent 推流？容器是远程还是与 dopilot 同机？
5. **脚本/Docker 落盘**：stdout 落盘位置、轮转/保留/截断策略与「从最后 N 行起播」如何定义？
6. **流式端点鉴权**：`EventSource` 无法带自定义头，是否引入基于 session 的登录或 query token（现状仅 Basic Auth，无 session）？
7. **是否解析/高亮**：实时日志要 logparser 风格统计/高亮，还是纯 raw 文本流？Docker/脚本无 scrapy 日志格式，logparser 不适用——是否只对 scrapyd 保留统计页？
8. **多人共享同一 job**：是否做服务端共享缓冲/广播，避免对同一文件/容器重复打开 N 个 follow 流？
