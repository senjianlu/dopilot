# 改造分析：实时日志

> **【scrapydweb 参考边界】** scrapydweb 仅作**功能层/行为参考**与**测试 oracle**；其代码写法、目录结构、模块划分、命名、依赖、配置形态**一律不得作为 dopilot 的设计依据**。dopilot 为 greenfield、按 `apps/`+`packages/` 自有领域 structure-first 设计（权威布局见 `05-dev-setup-and-known-issues.md` §1），**不对 scrapydweb 做改名/git mv**。详见 `00-requirements.md` 决策表。
>
> 本文区分「现状事实」（基于 scrapydweb 参考基线源码核实，标注 `file:line`——**这些路径相对 `reference/scrapydweb/`，是行为参考引用，不是 dopilot 源码位置**）与「改造建议 / 开放问题」。实时日志能力由 dopilot 全新实现，采用 **server 主动 pull 模型**：agent 提供 HTTP 的 **tail / status / cleanup** API（无状态、不主动推送）；server 端的 reconcile loop 按需从 agent tail API **拉取**日志增量，`LogSource` 抽象在 `apps/server/dopilot_server/`（`logs/`、`api/v1/`）保留但**传输由 server pull 驱动**；server 把日志正文写入本地文件卷 `/server-data/logs`，把索引 / offset / 状态写入 **PostgreSQL**（`execution_log_files` 表，PG 不存正文），并通过 **SSE** 单向推给 Vue SPA（原生 `EventSource`）。跨进程协议在 `packages/protocol/`，配置在 `configs/`（toml）。
> 第一版**完全不使用 WebSocket、agent 不主动推 chunk、不做 chunk 序号 ack 协议**（决策 #11）。
> 目标：为三类被调度对象（Scrapy/scrapyd 爬虫、Docker 常驻爬虫、Python 一次性脚本）提供统一的**真·实时日志流**。

---

## 0. 结论速览（TL;DR）

| 维度 | 现状事实 | 改造方向 |
| --- | --- | --- |
| 传输方式 | 整段拉取 + 前端 `location.reload(true)` 硬刷新，注释自承「SLOW」 | **server 主动 pull**：server 调 agent HTTP tail API 拉日志增量；server→web 使用 SSE 推给浏览器（agent 不主动推、无 WebSocket） |
| 读取方式 | 一次性全量 `f.read()` / 整段 GET，无 tail/offset/follow | 增量 tail（agent 按 offset 返回增量，offset 权威在 server 的 PG `last_pulled_offset`） |
| scrapyd 日志 | 「伪实时」支持（唯一支持的执行器） | 复用文件源，包一层增量 tail |
| Docker stdout | **零支持** | 新增 `DockerLogSource`（docker SDK / `docker logs -f`） |
| Python 脚本 stdout | **零支持**（无 job 概念、无落盘位置） | stdout 重定向落盘 + 文件 tail |
| 日志源抽象 | 参考基线无此抽象，`LogView` 硬编码 scrapyd URL/本地文件 + logparser | dopilot 从零实现 `LogSource` 抽象层（三类执行器统一接口，canon phase0/1 三大 seam 之一） |
| 运行环境 | Werkzeug dev server（threaded），无 SSE/WS 设施，`.venv` 无相关依赖 | dopilot 使用 FastAPI/ASGI；**单容器 + uvicorn workers=1 + 单 APScheduler 实例**（不支持多副本/多 worker，未来也不做），承载 server→web SSE 长连接 |

**推荐**：以「**server pull（调 agent tail/status/cleanup API）+ server 本地文件存正文 + PostgreSQL 存索引/offset/状态（`execution_log_files`）+ server→web SSE + LogSource 抽象层**」为主线，分两步走（先 scrapyd + 脚本，再补 Docker），并务必**先落地 dopilot 自有的 `LogSource` 抽象**（在 `apps/server/dopilot_server/logs/` 从零实现统一接口，各 executor/runner 接其上），避免三类执行器分别实现取数主流程。

---

## 1. 现状事实：logparser + 硬刷新轮询

scrapydweb 参考基线 **并无真正的「实时日志流」**。其日志能力完全建立在 scrapyd 的「日志文件 + logparser 解析」模型上，并且是**拉取式 + 整段读取 + 前端硬刷新**。以下为对该参考基线行为的核实，**所有 `file:line` 相对 `reference/scrapydweb/`，是行为参考、非 dopilot 源码路径**。

### 1.1 唯一的日志页：`LogView`（参考基线行为）

参考文件：`reference/scrapydweb/scrapydweb/views/files/log.py`

`LogView` 按 `opt` 分三种模式（`log.py:89-96`）：

| opt | 含义 | 关键行 |
| --- | --- | --- |
| `utf8` | 原始日志，`self.utf8_realtime=True` | `log.py:89-91` |
| `stats` | LogParser 统计页；`?realtime=True` 时现场 parse | `log.py:92-94` |
| `report` | 返回 JSON 统计（无模板） | `log.py:74-75, 95-96` |

路由注册（`__init__.py:245-246`）：

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

参考基线模板 `templates/scrapydweb/utf8.html`（dopilot 前端为 Vue SPA，无此 Jinja 模板，仅作行为对照）：

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

参考基线 `utils/poll.py` 是独立子进程，周期（`POLL_ROUND_INTERVAL` 默认 **300s**，`default_settings.py:290`；`poll.py:161` `time.sleep`）抓 scrapyd `/jobs` HTML（`poll.py:188-192`），再 POST 触发 `log.py` 的统计/告警（`poll.py:81,123-142`；`log.py:168` `if self.ENABLE_MONITOR and self.POST`）。它**只服务监控告警，与「页面实时看日志」无关**。

### 1.6 运行环境：无任何流式设施

| 事实 | 位置 |
| --- | --- |
| Werkzeug 内置开发服务器（threaded 默认开）`use_reloader=False` | `run.py:119-120` |
| 全局 Basic Auth 钩子（`@app.before_request def require_login`，依赖 `ENABLE_AUTH`），**无 session** | `run.py:51-58` |
| `setup.py` 钉死 `Flask==2.0.0` / `Werkzeug==2.0.0`（实际运行 Python **3.12.1**） | `setup.py:39,56` |
| `.venv` 中**无** flask-sock / flask-socketio / gevent / eventlet / simple-websocket / docker SDK | 实测 `site-packages` 无匹配 |
| `make_request` 仅 `session.get(url, ..., timeout)`，**无 `stream=True` / `iter_lines`** | `baseview.py:285-308` |
| 全局连接池 session（`pool_connections/maxsize=1000`）+ `basic_auth_header` 凭证 | `common.py:18-20,54` |

**结论**：参考基线对三类执行器只有 scrapyd 文件这一种被「伪实时」支持，Docker 与脚本**完全无日志通道**。dopilot 要做统一的真·实时日志流，需在 `apps/server`（reconcile pull loop + agent tail/status/cleanup 客户端、SSE 端点 + `LogSource` 抽象、本地正文落盘 + PG 索引）与 `apps/agent`（tail/status/cleanup HTTP API、脚本/容器 stdout 采集落盘）从零实现。

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

三者的统一编址由 dopilot 在自有数据模型（`apps/server/dopilot_server/models/` 与 `packages/protocol/`）定义统一的任务/日志标识；scrapyd 的 `(node, project, spider, job)` 四元组（参考基线 `job_key`，`log.py:52`，标识一次运行的**语义**）仅作为 scrapyd 类型对象的语义映射来源，不直接把其字符串约定当 dopilot 全局编址。落盘后统一走「文件 tail」是把②③拉齐到①的最短路径。

### 2.1 第一版 Scrapy 日志输送路径

第一版正式架构按 **dopilot-agent 包装本机 scrapyd** 实现，不让 server 直接把裸 scrapyd 当 agent：

```text
server 生成 execution_id/attempt_id
  -> server 选择健康 node 并 push 给 dopilot-agent
  -> agent 调本机 scrapyd /schedule.json
  -> scrapyd 启动 scrapy process 并写 job.log
  -> agent 建立 execution_id -> scrapyd job_id -> job.log 路径映射（落 /agent-data/state/executions/{attempt_id}.json）
  -> server reconcile loop 按 offset 调 agent tail API 拉增量（无窗 30s / 开窗 1s）
  -> server 写正文到 /server-data/logs/.../{attempt_id}.{stream}.log
  -> server 更新 PG execution_log_files（last_pulled_offset/size_bytes/status...），并 SSE 推给 Vue
  -> server 轮询 agent status API 检测结束 -> finalizing -> final drain -> complete -> 调 agent cleanup API
```

关键点：Scrapy 进程由 scrapyd 启动，agent 不强行 attach scrapy 子进程 stdout；最稳定的日志源是本机 scrapyd 产出的 `job.log`。scrapy/scrapyd 只产生 **stream=log**（单一 `job.log`，不天然拆 stdout/stderr）。**offset 权威在 server**（PG `last_pulled_offset`）；agent 无状态、无 ack/去重队列；agent 重启后只要 `/agent-data` 的 job.log 还在，server 按 offset 继续拉。典型路径由 agent 配置管理，例如：

```text
/agent-data/scrapyd/logs/{project}/{spider}/{job}.log
```

直接由 server 读取 scrapyd `/logs/.../job.log` 只允许作为本地 spike/连通性验证，不作为第一版目标架构（现成 scrapyd 镜像同理仅本地 spike）。

---

## 3. 已锁定架构：server pull + 本地正文 + PG 索引 + SSE

> 传输模型已在决策 #11 锁定，**不再做 WebSocket / 多方案选型**：server 主动 pull，agent 提供无状态 HTTP API，server→web 单向 SSE。本节描述该锁定架构的组件与参数；下面保留的「曾考虑过的传输形态」仅作历史背书，不是待选项。

核心抽象 **`LogSource`** 接口保留（统一三类执行器的取数语义），但**传输由 server pull 驱动**，`iter_incremental()` 的数据来源是「server 调 agent tail API 拉回的增量」而非「agent 主动推来的流」：

```
LogSource (抽象基类，server 侧)
  ├─ open(execution_id, attempt_id, stream)
  ├─ iter_incremental()  -> 增量行迭代器（数据来自 server pull 回的 tail 响应）
  └─ close()
       实现：
       ├─ ScrapydFileLogSource  经 agent tail API 按 offset 拉 job.log（stream=log）
       ├─ DockerLogSource       经 agent tail API 拉容器 stdout/stderr 落盘文件
       └─ ScriptLogSource       经 agent tail API 拉脚本 stdout/stderr 落盘文件
```

> 落点（dopilot 自有结构，不复用 scrapydweb 的 `utils/` 目录划分）：`LogSource` 抽象与各 source 的 server 侧归 `apps/server/dopilot_server/logs/`（如 `source.py`、`reconcile.py`）；agent tail/status/cleanup API 与采集侧归 `apps/agent/dopilot_agent/logs/`；跨进程协议（tail/status/cleanup 请求响应 schema）归 `packages/protocol/`。参考基线中无此抽象与实现，dopilot 从零新建。

### 3.1 agent HTTP API（无状态，server 拉）

agent **不主动推、不维护 ack/去重队列**，只提供以下 HTTP 端点供 server 调用：

| 端点 | 作用 | 关键 |
| --- | --- | --- |
| `GET /logs/tail?execution_id&attempt_id&stream&offset` | 返回从 offset 起的增量 | 响应 `{start_offset, end_offset, content, eof, finished}`；单次最多 `max_tail_bytes_per_pull=262144`（256KB） |
| status API | server 轮询任务是否结束 | 返回 running/finished/failed/canceled（**结束检测不依赖 agent 回调**） |
| `POST /executions/{attempt_id}/logs/cleanup` | server 标记 complete 后通知 agent 删 job.log | agent 在 server final drain 完成前**不得**删 job.log |

agent 重启从 `/agent-data/state/executions/{attempt_id}.json` 恢复 `execution_id ↔ scrapyd job_id ↔ log_path` 映射；TTL 兜底删除（completed 3 天 / orphan 7 天）。

### 3.2 server reconcile pull loop

- **拉取频率**：active execution 后台 reconcile loop 每 `background_drain_interval_seconds=30` 低频 drain；打开 Web 日志窗口该 execution 升到 `realtime_drain_interval_seconds=1`；关窗降回低频；任务结束做 **final drain**。
- **offset 权威在 server**：每次 tail 带 PG `last_pulled_offset`，拉回后推进 offset 并落 PG；agent 无状态。
- **结束检测**：server 轮询 agent status API（不依赖 agent 回调）。`finished/failed/canceled` → `finalizing` → final drain → **EOF 稳定（默认 3s）或 hard timeout（30s）→ complete**，随后调 agent cleanup API。
- **多窗复用**：多窗口看同一 execution 复用**一个 pull loop + SSE fan-out**，不重复打开 N 个拉取循环。

### 3.3 server→web SSE

- server 通过 FastAPI SSE 端点（`text/event-stream`）把增量单向推给浏览器原生 `EventSource`。
- 事件携带 `id:<seq>`，配合 `Last-Event-ID` 支持断线重连补洞；管理员认证开启时用短期 `stream_token`（POST 换取、TTL 60s、仅校验建连、连接最长寿命如 30min）。
- 可选反代约束：dopilot 自身不内置 nginx；若用户在外层接反向代理（nginx 等），SSE 路径必须关闭 buffering。FastAPI SSE 响应加 `X-Accel-Buffering: no`、`Cache-Control: no-cache`。

### 3.4 曾考虑过的传输形态（历史背书，非待选项）

第一版**不采用**以下形态，仅记录为何 pull 模型胜出：

- **agent→server WebSocket / agent 主动推 chunk / chunk 序号 ack**：已废弃。pull 模型让 agent 无状态、offset 权威集中在 server，agent 重启即可按 offset 续拉，免去推流连接管理、ack/去重与背压。
- **浏览器直连 WebSocket**：浏览器只读日志不需要双向；SSE 更简单、原生自动重连，且 server 单实例下足够。
- **节点 agent 推流 + 中心 pub/sub 聚合**：dopilot **单容器 + uvicorn workers=1 + 单 APScheduler 实例**，不支持多副本/多 worker 且未来也不做，因此**不引入 Redis/NATS/PG LISTEN-NOTIFY fan-out**；SSE fan-out 在单进程内存内完成。

---

## 4. 落地方案（分两步走）

> 以**锁定架构（server pull 调 agent tail/status/cleanup API + server 本地正文 + PG `execution_log_files` 索引 + server→web SSE + LogSource 抽象层）为主线**，先做 scrapyd 与 Python 脚本两类，再补 Docker。dopilot-agent 阶段 1 即落地。

### 第一步（MVP）

1. 在 `apps/server/dopilot_server/logs/` 实现 dopilot 自有的 `LogSource` 抽象接口 + `ScrapydFileLogSource`（经 agent tail API 拉取）；reconcile pull loop（`reconcile.py`）。
2. 在 `apps/agent/dopilot_agent/logs/` 与 `packages/protocol/` 定义 **tail / status / cleanup HTTP API** 与请求响应 schema：tail 返回 `{start_offset, end_offset, content, eof, finished}`，单次 ≤ 256KB；agent 无状态，offset 由 server 在请求里给出。agent 重启从 `/agent-data/state/executions/{attempt_id}.json` 恢复映射。
3. 在 `apps/server/dopilot_server/api/v1/`（logs 路由）新建 FastAPI SSE 端点；server reconcile loop 按频率（无窗 30s / 开窗 1s / 结束 final drain）拉增量、写 `/server-data/logs/.../{attempt_id}.{stream}.log`、更新 PG `execution_log_files`、再经内存 SSE fan-out 推给浏览器。
4. 前端：dopilot Web（Vue3 SPA）在 `apps/web/src/`（pages/components）新建日志页组件，用浏览器原生 `EventSource` 订阅 `/api/v1/executions/{id}/logs/stream`，处理 `id:<seq>` / `Last-Event-ID` 重连补洞，前端自行实现增量 append、自动滚底（无 scrapydweb Jinja 模板可复用）。开窗/关窗驱动 server 把该 execution 的拉取频率升到 1s / 降回 30s。
5. 脚本日志：dopilot agent 的 `ScriptRunner`（`apps/agent/dopilot_agent/runners/script.py`）自行实现进程拉起，把 stdout/stderr 重定向到 agent 工作区（`apps/agent/dopilot_agent/workspace/`）落盘文件，按 stream=stdout/stderr 供 server tail API 拉取。**移植注意**：进程拉起须遵守 `prctl(PR_SET_PDEATHSIG)` 父进程死亡信号语义，并使用 glibc（slim/debian）基础镜像而非 Alpine（musl 不满足 `libc.so.6` prctl）——此约束以参考基线 `sub_process.py:8,21-40,73-78` 行为为参照，dopilot 在 runner 中自行实现，不复用/修改该文件。

> **为什么是 server pull + SSE**：agent 保持无状态、offset 权威集中在 server PG，agent 重启即可按 offset 续拉，免去推流连接管理与 ack；浏览器只负责看日志，SSE 单向、原生自动重连且在 server 单实例下足够。

### 第二步

1. 在 `apps/agent/dopilot_agent/logs/` 增加 `DockerLogSource` 采集侧（docker SDK 或 `docker logs -f` 子进程落盘），同样经 tail API 暴露 stdout/stderr。
2. dopilot `auth/` 模块按 **config-present-or-off** 实现鉴权：agent `shared_token` 非空才启用 agent 认证；Web 认证（`admin_username`+`admin_password`+`token_secret` 三者齐全且非空）开启时，SSE 用短期 `stream_token`（POST 换取、TTL 60s、仅校验建连）。内网防误操作策略，非互联网零信任。

### 兜底与边界

- **offset 增量轮询 JSON 端点**可与 SSE 共存（与 `LogSource`/`execution_log_files` offset 共用），作为不支持 SSE 环境的降级读取路径；但**不引入浏览器 WebSocket、不引入 agent 主动推**。
- **单实例硬约束**：server = 单容器 + uvicorn workers=1 + 单 APScheduler 实例，不支持多副本/多 worker，且未来也不做；**不引入 Redis/NATS/PG LISTEN-NOTIFY fan-out**，SSE fan-out 在单进程内存内完成。
- **备份**：必须同时覆盖 PostgreSQL（索引）+ `/server-data/logs` 卷（正文）。

> ⚠️ **务必先落地 dopilot 自有的 `LogSource` 抽象**（`apps/server/dopilot_server/logs/`），避免三类执行器分别实现日志取数主流程。

---

## 5. dopilot 新建文件清单（apps 布局）

> 实时日志能力由 dopilot 在 `apps/` 下**全新实现**；下表是 dopilot 要新建的文件/模块，**不是改 scrapydweb**。参考基线对应行为另见文末「scrapydweb 行为参考（只读）」。

| dopilot 位置 | 性质 | 实现要点 |
| --- | --- | --- |
| `apps/server/dopilot_server/api/v1/`（logs 路由） | 新建 | FastAPI SSE 流式端点（`text/event-stream`，`id:<seq>`/`Last-Event-ID`）+ offset 增量轮询 JSON 端点（降级用）+ `stream_token` 换取端点；**不含任何 WebSocket / agent 推流接入端点**；调用 `LogSource` 取增量行；节点选择经 `nodes/`/`services/` |
| `apps/server/dopilot_server/logs/`（如 `source.py`、`reconcile.py`） | 新建 | dopilot 自有 `LogSource` 抽象（`open/iter_incremental/close`）+ `ScrapydFileLogSource`；reconcile pull loop（无窗 30s / 开窗 1s / final drain）+ agent tail/status/cleanup 客户端；正文写 `/server-data/logs`、索引写 PG `execution_log_files` |
| `apps/agent/dopilot_agent/logs/` | 新建 | **tail/status/cleanup HTTP API**（无状态，server 拉）+ `ScriptLogSource` / `DockerLogSource` 采集侧（脚本 stdout 落盘；容器 `docker logs -f` / SDK `container.logs(stream,follow)` 落盘）；`/agent-data/state/executions/{attempt_id}.json` 映射恢复 + TTL 兜底 |
| `apps/agent/dopilot_agent/runners/script.py`、`docker.py` | 新建 | runner 自行实现进程/容器拉起，stdout/stderr 重定向到 `apps/agent/dopilot_agent/workspace/` 落盘以供 tail；进程拉起遵守 `prctl(PR_SET_PDEATHSIG)` + glibc 基础镜像约束（见文末行为参考） |
| `apps/web/src/`（pages/components + api） | 新建 | Vue3 日志页组件，浏览器原生 `EventSource` 订阅 `/api/v1` SSE（`id:<seq>`/`Last-Event-ID` 重连补洞），前端实现增量 append/自动滚底；开窗/关窗驱动 server 拉取频率升降；不支持 SSE 时降级到 offset 分页 fetch |
| `apps/server/dopilot_server/auth/` | 新建 | config-present-or-off 鉴权：agent `shared_token`；前端 SSE 短期 `stream_token`（POST 换取、TTL 60s、仅校验建连，`EventSource` 不能带自定义头） |
| `packages/protocol/` | 新建 | server↔agent **tail/status/cleanup** 协议 schema（含 `{start_offset,end_offset,content,eof,finished}`）；统一任务/日志标识定义；**无推流/ack 协议** |
| `apps/server/dopilot_server/models/`（如 `execution_log_files`） + Alembic 迁移 | 新建 | PG 索引表 `execution_log_files`（见 §5.1），SQLAlchemy + **裸 Alembic**（FastAPI 无 Flask app，非 Flask-Migrate）；APScheduler jobstore 落 PG |
| `configs/server.example.toml` + `apps/server/dopilot_server/config/` | 新建 | 实时日志配置项（`background_drain_interval_seconds=30` / `realtime_drain_interval_seconds=1` / `max_tail_bytes_per_pull=262144` / EOF 稳定 3s / hard timeout 30s / 容器日志保留轮转策略）写入 toml，由 dopilot 的 toml 加载器解析与校验 |
| `apps/server/pyproject.toml` / `apps/agent/pyproject.toml` | 新建 | server 侧声明 FastAPI/uvicorn（workers=1）/SQLAlchemy/Alembic/asyncpg 或 psycopg 等依赖；agent 侧声明 HTTP server（tail/status/cleanup）、docker SDK 等采集依赖；版本由 dopilot 自定 |

> 节点寻址与日志取数：dopilot 在 `apps/server/dopilot_server/nodes/` 与 `services/` 自行实现节点选择与日志取数（第一版 `[nodes].agents=["agent:6800"]` 只作初始发现地址；agent 启动携带稳定 `agent_id`，server 轮询 agent `GET /health` 后 upsert `nodes` 表，并只选择健康 agent）；日志增量读取经 agent tail API（不直连裸 scrapyd），由 dopilot 自有 HTTP 客户端或 `packages/protocol/` 层实现。

### 5.1 存储模型（正文文件 + PG 索引）

**正文（server 本地文件卷，PG 不存正文）**：

```text
/server-data/logs/YYYY/MM/{execution_id}/{attempt_id}.{stream}.log
# stream=log 时即 {attempt_id}.log
```

**索引（PostgreSQL 唯一库，表 `execution_log_files`）**：

- 主键：`(execution_id, attempt_id, stream)`
- 列：`storage_path` / `size_bytes` / `last_pulled_offset`（offset 权威） / `final_offset` / `status` / `started_at` / `finished_at` / `retained_until` / `created_at` / `updated_at`
- `status` 枚举：`active` / `finalizing` / `complete` / `missing` / `expired`
- `stream` 枚举：`log` / `stdout` / `stderr` / `system`（schema/API 从第一版即支持；scrapy/scrapyd 只产 `log`，脚本阶段用 `stdout`/`stderr`）

`execution_id` / `attempt_id` 由 server 生成并下发 agent。

### scrapydweb 行为参考（只读，移植时对照的语义点）

以下为 scrapydweb 参考基线在该领域的行为/语义，仅供 dopilot 移植时对照，**`file:line` 相对 `reference/scrapydweb/`，不是 dopilot 待改文件**：

- `log.py:89-96, 116-170, 221-248`：`LogView` 的 `opt`（utf8/stats/report）分派、node 寻址、整段一次性读取（`f.read()` / 整段 GET）——dopilot 以其取数**语义**为参考，自行实现增量 tail。
- `__init__.py:245-246`、`baseview.py:257-262`：`register_view` / `with_node` 路由风格与 `get_selected_nodes` 节点选择**语义**——dopilot 在 `api/v1` 与 `nodes/` 自有路由/选择逻辑实现，不沿用其路由写法。
- `baseview.py:285-308`、`common.py:18-20,54`：参考基线 `make_request` 无 `stream=True`/`iter_lines`，全局 `requests.Session` + `basic_auth_header`——增量远程读取作为**行为参考**，dopilot 在自有 HTTP 客户端/protocol 层实现。
- `run.py:51-58, 119-120`：全局 Basic Auth `require_login` 钩子（无 session）、Werkzeug threaded dev server——鉴权与部署作为**行为约束参考**，dopilot 在 `auth/` 与部署层重做。
- `sub_process.py:8,21-40,73-78`：`Popen + prctl(PR_SET_PDEATHSIG)` 父进程死亡信号 + 必须 glibc 基础镜像——**进程拉起行为约束**，dopilot agent runner 移植时必须遵守，但不复用/修改该文件。
- `vars.py:57,59-62`：参考基线在模块 import 期 mkdir（且会删 transient 目录）——dopilot 不采用 import 期建目录的副作用写法，改由 config（toml）定义日志落盘目录、由显式初始化创建。
- `default_settings.py`、`check_app_config.py`、`setup.py:39,56`：参考基线的硬编码 Python settings + cwd 加载 + setup.py 钉死 Flask/Werkzeug——dopilot 不继承，配置走 `configs/`（toml）、依赖走各 `pyproject.toml`。
- `utf8.html` / `utf8_mobileui.html`：参考基线 Jinja 日志模板（`location.reload` 硬刷新、`#log`/`go-bottom` 控件）——dopilot 前端为 Vue SPA greenfield，无 Jinja 共存，仅作交互行为对照。

---

## 6. GAP 清单（现状缺口）

| 编号 | GAP | 为什么是缺口（依据） |
| --- | --- | --- |
| GAP-1 | 完全没有流式传输通道（无 SSE/无 WebSocket） | 整段拉取 + `location.reload(true)` 硬刷新（`utf8.html:55-91`、`log.py:348-355`），延迟大、整页重载、对 long-running 进程不可用 |
| GAP-2 | 日志读取一次性全量，无 tail/follow/offset | `read_local_scrapy_log` 用 `f.read()`（`log.py:228`），`request_scrapy_log` 整段 GET（`log.py:236-248`）；长日志越读越慢且重复传输 |
| GAP-3 | Docker 容器 stdout 无任何对接 | 所有路径假定 scrapyd `/logs/<project>/<spider>/<job>.log` 结构；容器日志在 stdout，需 `docker logs --follow` / SDK attach，现状零支持 |
| GAP-4 | Python 一次性脚本 stdout 无任何对接 | 脚本无 scrapyd job 概念，也无落盘位置；缺少捕获 stdout/stderr 的机制 |
| GAP-5 | 日志源无抽象层（executor-agnostic） | `LogView` 硬编码 scrapyd URL/本地文件 + logparser；三类执行器需统一接口，否则每类都得改主流程 |
| GAP-6 | reference 的 WSGI dev server 不适合长连接 | `run.py:119` Werkzeug threaded dev server，每个长连接占一线程；dopilot 不继承，改用 FastAPI/ASGI（单容器 + uvicorn workers=1）承载 server→web SSE 长连接 |
| GAP-7 | long-running 日志生命周期需要 dopilot 自行实现 | 常驻容器日志无限增长；v1 已定义保留/截断/首屏 tail 策略（server 30 天、agent completed 3 天/orphan 7 天、单 stream 100MB、首屏最后 2000 行或 1MB），实现时不能复用 reference 的 `KEEP_*_RESULT` |
| GAP-8 | 鉴权与流式端点内部调用链 | `require_login` 是全局 Basic Auth 钩子（`run.py:51-58`）；`EventSource` 不能带自定义头，dopilot 用短期 `stream_token`（Web 认证开启时 POST 换取、TTL 60s、仅校验建连）适配（**现状无 session**） |
| GAP-9 | 日志页文案需 i18n | 参考基线 `utf8.html` 文案如 "Click to refresh"（`utf8.html:56`）硬编码英文、无 i18n；dopilot Web SPA 日志页文案统一走 `apps/web/src/i18n`（中文为主），无 Jinja 模板硬编码问题 |

---

## 7. 已锁定日志细节

> 以下原列项已由 v1 锁定 spec / 决策 #11 与后续用户确认收口；本节作为实现约束。

**已锁定（不再讨论）：**

- ~~多副本日志广播~~ → 单容器 + uvicorn workers=1 + 单 APScheduler 实例，不支持多副本，未来也不做；**不引入 Redis/NATS/PG LISTEN-NOTIFY**，SSE fan-out 在单进程内存内完成。
- ~~部署形态~~ → uvicorn workers=1 单实例。
- ~~远程 scrapyd 真增量 / Docker 采集路径~~ → 不直连裸 scrapyd / docker daemon；统一经本机 dopilot-agent 的 tail API（agent 子进程拉起本机 scrapyd，scrapyd 仅监听容器内部端口）。
- ~~流式端点鉴权~~ → config-present-or-off；Web 认证开启时 SSE 用短期 `stream_token`（TTL 60s、仅校验建连）。
- ~~多人共享同一 job~~ → 多窗口复用一个 pull loop + SSE fan-out。

**新增锁定：**

1. **落盘与截断**：server 本地日志默认保留 30 天；单次 execution 的单个 stream 文件默认最大 100MB，超过后停止继续追加正文并把 `execution_log_files.truncated=true`、`status` 保持可读状态。agent 已完成任务日志保留 3 天，孤儿日志保留 7 天，作为 server cleanup 失败时的兜底。
2. **首屏 tail**：打开 Web 日志窗口时，server 先从本地文件返回最后 2000 行或最后 1MB（取先达到的边界），随后按 `last_pulled_offset` 每秒增量 pull 对应 execution；未打开窗口时只执行 30s 低频后台 drain，任务结束后 final drain。
3. **显示形态**：第一版只做 raw text 显示与 `log/stdout/stderr/system` stream 分流，不做 logparser 风格解析、统计或高亮；scrapy 第一版仅产 `stream=log`。
4. **过期联动**：PG `retained_until` 与本地文件清理同步。清理任务先把 `execution_log_files.status` 置为 `expired`，再删除 `/server-data/logs` 正文；若读取时索引存在但文件缺失，返回 `status=missing` 并在 UI 标记日志正文已不可用。
