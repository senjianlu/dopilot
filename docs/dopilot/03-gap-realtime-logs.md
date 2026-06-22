# 改造分析：实时日志

> **【scrapydweb 参考边界】** scrapydweb 仅作**功能层/行为参考**与**测试 oracle**；其代码写法、目录结构、模块划分、命名、依赖、配置形态**一律不得作为 dopilot 的设计依据**。dopilot 为 greenfield、按 `apps/`+`packages/` 自有领域 structure-first 设计（权威布局见 `05-dev-setup-and-known-issues.md` §1），**不对 scrapydweb 做改名/git mv**。详见 `00-requirements.md` 决策表。
>
> **【已被通信重构取代 / superseded】** 本文 dopilot 侧的「server 主动 pull 调 agent tail/status/cleanup」日志模型已被 `docs/refactor/00-redis-streams-agent-communication.md` 翻案：日志由 **agent 经 Redis log stream（`dopilot:server:logs`）主动推增量，server 消费后落盘**，`LogSource` 抽象保留但实现由 `AgentTailLogSource` 换为 `RedisLogSource`。本文 dopilot 段已据该 refactor 同步；scrapydweb 现状事实（§1、§2「现状对接」、§6「为什么是缺口」依据、文末「scrapydweb 行为参考」）为行为参考，不随重构改动。细节以该 refactor 文档为准。
>
> 本文区分「现状事实」（基于 scrapydweb 参考基线源码核实，标注 `file:line`——**这些路径相对上游 scrapydweb 1.6.0 / commit `1341cf9`，是外部行为参考引用，不是 dopilot 源码位置（本仓库不保留本地快照）**）与「改造建议 / 开放问题」。实时日志能力由 dopilot 全新实现，采用 **agent 经 Redis log stream 主动推、server 消费落盘** 模型：agent tail 本地日志并 `XADD` 到 `dopilot:server:logs`（base64 字节，带 `offset`/`size_bytes`/`eof`）；server 端的 log consumer 消费该 stream，按 offset 落盘并更新 PG，`LogSource` 抽象在 `apps/server/dopilot_server/`（`logs/`、`api/v1/`）保留但**数据源由 Redis log stream 驱动**（实现为 `RedisLogSource`）；server 把日志正文写入本地文件卷 `/server-data/logs`，把索引 / offset / 状态写入 **PostgreSQL**（`execution_log_files` 表，PG 不存正文），并通过 **SSE** 单向推给 Vue SPA（原生 `EventSource`）。跨进程协议在 `packages/protocol/`，配置在 `configs/`（toml）。
> 第一版**仍完全不使用 WebSocket、server→web 仍单向 SSE、正文仍落 `/server-data/logs`、PG 仍只存索引/offset/状态**（决策 #11 的四不变量）。日志 **RPO≠0**：server 长停或 Redis log stream 超出保留窗口会导致日志缺片（`log_integrity=partial`），业务执行状态收敛与日志完整性分离，缺片不阻塞 attempt 进入 terminal。
> 目标：为三类被调度对象（Scrapy/scrapyd 爬虫、Docker 常驻爬虫、Python 一次性脚本）提供统一的**真·实时日志流**。

---

## 0. 结论速览（TL;DR）

| 维度 | 现状事实 | 改造方向 |
| --- | --- | --- |
| 传输方式 | 整段拉取 + 前端 `location.reload(true)` 硬刷新，注释自承「SLOW」 | **agent 经 Redis log stream 主动推增量**（`dopilot:server:logs`，base64 字节），server 消费后落盘；server→web 仍使用 SSE 推给浏览器（无 WebSocket） |
| 读取方式 | 一次性全量 `f.read()` / 整段 GET，无 tail/offset/follow | agent tail 本地日志按 byte offset 增量 `XADD`，server consumer 按 `offset == last_pulled_offset` 追加；offset 消费进度权威在 server PG `last_pulled_offset` |
| scrapyd 日志 | 「伪实时」支持（唯一支持的执行器） | 复用文件源，agent 侧 tail `job.log` 增量推到 log stream |
| Docker stdout | **零支持** | 新增 `DockerLogSource`（docker SDK / `docker logs -f`） |
| Python 脚本 stdout | **零支持**（无 job 概念、无落盘位置） | stdout 重定向落盘 + 文件 tail |
| 日志源抽象 | 参考基线无此抽象，`LogView` 硬编码 scrapyd URL/本地文件 + logparser | dopilot 从零实现 `LogSource` 抽象层（三类执行器统一接口，canon phase0/1 三大 seam 之一） |
| 运行环境 | Werkzeug dev server（threaded），无 SSE/WS 设施，`.venv` 无相关依赖 | dopilot 使用 FastAPI/ASGI；**单容器 + uvicorn workers=1 + 单 APScheduler 实例**（不支持多副本/多 worker，未来也不做），承载 server→web SSE 长连接 |

**推荐**：以「**agent 经 Redis log stream 主动推（server log consumer 消费）+ server 本地文件存正文 + PostgreSQL 存索引/offset/状态/完整性（`execution_log_files`，新增 `log_integrity` 列）+ server→web SSE + LogSource 抽象层**」为主线，分两步走（先 scrapyd + 脚本，再补 Docker），并务必**先落地 dopilot 自有的 `LogSource` 抽象**（在 `apps/server/dopilot_server/logs/` 从零实现统一接口，实现为 `RedisLogSource`，各 executor/runner 接其上），避免三类执行器分别实现取数主流程。任务结束检测改为 server **消费 `attempt.*` 状态事件**（见 `00-redis-streams-agent-communication.md`），不再轮询 agent status API。

---

## 1. 现状事实：logparser + 硬刷新轮询

scrapydweb 参考基线 **并无真正的「实时日志流」**。其日志能力完全建立在 scrapyd 的「日志文件 + logparser 解析」模型上，并且是**拉取式 + 整段读取 + 前端硬刷新**。以下为对该参考基线行为的核实，**所有 `file:line` 相对上游 scrapydweb 1.6.0 / commit `1341cf9`，是外部行为参考、非 dopilot 源码路径**。

### 1.1 唯一的日志页：`LogView`（参考基线行为）

参考文件：上游 `scrapydweb/views/files/log.py`

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

**结论**：参考基线对三类执行器只有 scrapyd 文件这一种被「伪实时」支持，Docker 与脚本**完全无日志通道**。dopilot 要做统一的真·实时日志流，需在 `apps/server`（log consumer 消费 `dopilot:server:logs` + `LogSource`/`RedisLogSource` 抽象、本地正文落盘 + PG 索引/完整性、SSE 端点）与 `apps/agent`（log publisher：tail 本地日志并 `XADD` 到 log stream；脚本/容器 stdout 采集落盘）从零实现。

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
  -> server 同事务写 execution/attempt/command_outbox，dispatcher XADD run command 到 dopilot:agent:{agent_id}:commands
  -> agent consumer group 消费 run command（attempt_id 幂等），调本机 scrapyd /schedule.json
  -> scrapyd 启动 scrapy process 并写 job.log
  -> agent 建立 execution_id -> scrapyd job_id -> job.log 路径映射（落 /agent-data/state/executions/{attempt_id}.json）
  -> agent log publisher tail job.log，按 byte offset 增量 XADD 到 dopilot:server:logs（base64 字节，带 offset/size_bytes/eof）
  -> server log consumer 消费该 stream，按 offset == last_pulled_offset 追加；offset gap 则插入 gap marker 并标 log_integrity=partial
  -> server 写正文到 /server-data/logs/.../{attempt_id}.{stream}.log
  -> server 更新 PG execution_log_files（last_pulled_offset/size_bytes/status/log_integrity...），并 SSE 推给 Vue
  -> server 消费 attempt.* 事件检测结束 -> finalizing -> bounded drain -> complete -> XADD cleanup_logs command
```

关键点：Scrapy 进程由 scrapyd 启动，agent 不强行 attach scrapy 子进程 stdout；最稳定的日志源是本机 scrapyd 产出的 `job.log`。scrapy/scrapyd 只产生 **stream=log**（单一 `job.log`，不天然拆 stdout/stderr）。**消费进度 offset 权威在 server**（PG `last_pulled_offset`，记 agent 逻辑字节 offset）；日志由 agent 端单一顺序生产者按 offset 严格递增 `XADD`（含 outbox 重放也按 offset 排序），server 对同一 attempt 串行处理避免虚假 gap。日志字节 offset gap → `partial` 黏性完整性标记（不会因后续连续自动恢复 `complete`）；重复片段（`offset < last_pulled_offset`）丢弃。agent 重启后只要 `/agent-data` 的 job.log 还在，log publisher 按本地进度继续从 job.log 增量推。典型路径由 agent 配置管理，例如：

```text
/agent-data/scrapyd/logs/{project}/{spider}/{job}.log
```

直接由 server 读取 scrapyd `/logs/.../job.log` 只允许作为本地 spike/连通性验证，不作为第一版目标架构（现成 scrapyd 镜像同理仅本地 spike）。

---

## 3. 已锁定架构：agent Redis log stream 推 + server 消费落盘 + PG 索引 + SSE

> 传输模型在决策 #11 + 通信重构（`docs/refactor/00-redis-streams-agent-communication.md`）下锁定，**不再做 WebSocket / 多方案选型**：agent tail 本地日志并经 Redis log stream（`dopilot:server:logs`）主动 `XADD` 增量，server log consumer 消费后落盘，server→web 仍单向 SSE。四个不变量保持：第一版不用 WebSocket、server→web SSE、正文落 `/server-data/logs`、PG 只存索引/offset/状态。本节描述该锁定架构的组件与参数；下面保留的「曾考虑过的传输形态」仅作历史背书，不是待选项。

核心抽象 **`LogSource`** 接口保留（统一三类执行器的取数语义），但**数据源由 Redis log stream 驱动**（实现为 `RedisLogSource`），`iter_incremental()` 的数据来源是「server log consumer 从 `dopilot:server:logs` 消费、按 offset 落盘后的增量」而非「server 调 agent tail API 拉回的增量」：

```
LogSource (抽象基类，server 侧；实现 RedisLogSource)
  ├─ open(execution_id, attempt_id, stream)
  ├─ iter_incremental()  -> 增量行迭代器（数据来自 server 消费 Redis log stream 后落盘的增量）
  └─ close()
       实现（数据源统一为 server 消费 dopilot:server:logs 后落盘的本地正文）：
       ├─ ScrapydFileLogSource  agent tail job.log（stream=log）XADD，server 消费落盘
       ├─ DockerLogSource       agent tail 容器 stdout/stderr 落盘文件 XADD，server 消费落盘
       └─ ScriptLogSource       agent tail 脚本 stdout/stderr 落盘文件 XADD，server 消费落盘
```

> 落点（dopilot 自有结构，不复用 scrapydweb 的 `utils/` 目录划分）：`LogSource`/`RedisLogSource` 抽象与各 source 的 server 侧归 `apps/server/dopilot_server/logs/`（如 `source.py`），log consumer 与 Redis 基础设施归 `apps/server/dopilot_server/redis/`；agent log publisher 与采集侧归 `apps/agent/dopilot_agent/logs/`，agent Redis 客户端/publisher 归 `apps/agent/dopilot_agent/redis/`；跨进程消息 schema（`AgentLogEvent` 等）归 `packages/protocol/dopilot_protocol/streams.py`。参考基线中无此抽象与实现，dopilot 从零新建。

### 3.1 agent log publisher + 命令 / 事件（agent 主动经 Redis）

agent **主动**向 Redis 推日志与状态、主动消费命令，不再提供 server 拉的 tail/status/cleanup 主路径 HTTP API（`AgentTailLogSource` 主路径删除）：

| 通道 | 方向 | 关键 |
| --- | --- | --- |
| `dopilot:server:logs`（log publisher `XADD`） | agent → server | 增量日志事件，base64 字节，带 `offset`/`size_bytes`/`eof`；同一 attempt 单一顺序生产者按 offset 严格递增发布 |
| `dopilot:server:agent-events`（status publisher `XADD`） | agent → server | `attempt.accepted/running/finished/failed/canceled/lost`；server 据 terminal 事件检测结束（**不再轮询 agent status API**） |
| `dopilot:agent:{agent_id}:commands`（consumer group 消费） | server → agent | `run` / `stop`（带 `intent`）/ `cleanup_logs`；`cleanup_logs` 替代旧 cleanup HTTP，按 `attempt_id` 幂等，server bounded drain 完成前不发 |

agent log publisher 在 `XACK` / outbox 语义下保证日志至少一次到达 Redis；`eof=true` 日志事件作清理优化信号但非清理前置条件。agent 重启从 `/agent-data/state/executions/{attempt_id}.json` 恢复 `execution_id ↔ scrapyd job_id ↔ log_path` 映射并续推；TTL 兜底删除（completed 3 天 / orphan 7 天）。agent `/health` 降级为容器本地 healthcheck，不再作 server 节点发现/健康来源（健康改由 agent 主动 POST heartbeat、server 以 `last_seen_at` 判定）。

### 3.2 server log consumer + reconcile

- **消费驱动**：server log consumer 持续从 `dopilot:server:logs` 消费日志事件并落盘，不再按窗口频率拉取；agent 侧推送频率与窗口解耦（agent 始终增量推）。Web 开窗只影响 server→web SSE fan-out 是否对该 execution 推送，不再驱动 server→agent 拉取频率升降。
- **offset 处理**：server 只追加 `offset == last_pulled_offset` 的片段并推进 `last_pulled_offset = offset + size_bytes`；`offset < last_pulled_offset` 丢弃；`offset > last_pulled_offset` 视为缺片 → 插入可见 gap marker、记 expected/actual offset、标 `log_integrity=partial`（黏性）后写入。`last_pulled_offset` 记 agent 逻辑字节进度，`final_offset` 记 server 文件物理大小（含 gap marker）。
- **结束检测**：server **消费 `attempt.*` 状态事件**（不再轮询 agent status）。收到 terminal 事件 → `finalizing` → 进入 **bounded drain 窗口**（`log_drain_timeout_seconds`，默认 30s）消费当前可见日志事件落盘 → drain timeout 或 `eof` 信号 → `complete`（并把 `log_integrity` 收口为 `complete`/`partial`），随后 `XADD cleanup_logs` command。
- **多窗复用**：多窗口看同一 execution 复用**一个 log consumer 落盘 + 单进程内存 SSE fan-out**，不重复打开 N 个消费/广播循环。
- **消费幂等/恢复**：log consumer 用 consumer group 消费、按 offset 去重，`XACK` 已处理消息；server 重启后从 pending / 未 ack 处续消费，仍按 offset 收敛。

### 3.3 server→web SSE

- server 通过 FastAPI SSE 端点（`text/event-stream`）把增量单向推给浏览器原生 `EventSource`。
- 事件携带 `id:<seq>`，配合 `Last-Event-ID` 支持断线重连补洞；管理员认证开启时用短期 `stream_token`（POST 换取、TTL 60s、仅校验建连、连接最长寿命如 30min）。
- 可选反代约束：dopilot 自身不内置 nginx；若用户在外层接反向代理（nginx 等），SSE 路径必须关闭 buffering。FastAPI SSE 响应加 `X-Accel-Buffering: no`、`Cache-Control: no-cache`。

### 3.4 曾考虑过的传输形态（历史背书，非待选项）

> **【superseded 注】** 早期曾锁定「server 主动 pull 调 agent tail/status/cleanup」为 agent→server 日志主路径；通信重构（`docs/refactor/00-redis-streams-agent-communication.md`）已破坏性翻案为「agent 经 Redis log stream 主动推、server 消费」。以下记录各形态取舍，**当前胜出形态是 Redis log stream 推**。

第一版**不采用**以下 agent→server 日志形态：

- **server pull 调 agent tail/status/cleanup HTTP（旧主路径）**：已废弃。曾因「agent 无状态、offset 权威集中在 server」入选，但要求 server 主动可达每个 agent、调度/状态/日志全耦合在 agent HTTP 可达性上、缺统一消息语义；重构后改为 agent 主动经 Redis 推，server 不再主动连 agent。
- **agent→server WebSocket / chunk 序号双向 ack**：仍不采用。Redis log stream 已提供 at-least-once 传输与 byte offset 语义，server 侧按 offset 去重/补 gap，无需自建推流连接管理与背压。
- **浏览器直连 WebSocket**：浏览器只读日志不需要双向；server→web 仍用 SSE，更简单、原生自动重连，且 server 单实例下足够。
- **引入 Redis 做多副本 HA / fan-out / 分布式锁**：仍不采用。Redis 在 dopilot 仅作**单实例 server↔agent 通信总线**（消息传输，非业务持久化），**不**用于多副本 active-active、跨进程 fan-out 或分布式锁；server→web SSE fan-out 仍在**单进程内存**内完成。**不引入 NATS / PG LISTEN-NOTIFY** 做 fan-out。单容器 + uvicorn workers=1 + 单 APScheduler 实例的硬约束不变。

---

## 4. 落地方案（分两步走）

> 以**锁定架构（agent 经 Redis log stream 主动推 + server log consumer 消费落盘 + server 本地正文 + PG `execution_log_files` 索引/`log_integrity` + server→web SSE + LogSource/`RedisLogSource` 抽象层）为主线**，先做 scrapyd 与 Python 脚本两类，再补 Docker。dopilot-agent 阶段 1 即落地。

### 第一步（MVP）

1. 在 `apps/server/dopilot_server/logs/` 实现 dopilot 自有的 `LogSource` 抽象接口 + `RedisLogSource`（数据源为 server 消费 Redis log stream 后落盘的正文）；log consumer 与 Redis 客户端落 `apps/server/dopilot_server/redis/`（`client.py`、`consumers.py`）。
2. 在 `apps/agent/dopilot_agent/logs/`（log publisher：tail 本地日志、按 byte offset 增量 `XADD`）与 `apps/agent/dopilot_agent/redis/` 实现 agent 侧推送；`packages/protocol/dopilot_protocol/streams.py` 定义 `AgentLogEvent`（base64 字节，带 `offset`/`size_bytes`/`eof`）等 schema。agent 重启从 `/agent-data/state/executions/{attempt_id}.json` 恢复映射并按本地进度续推。
3. 在 `apps/server/dopilot_server/api/v1/`（logs 路由）新建 FastAPI SSE 端点；server log consumer 消费 `dopilot:server:logs`、按 `offset == last_pulled_offset` 写 `/server-data/logs/.../{attempt_id}.{stream}.log`（缺片插 gap marker 标 `log_integrity=partial`）、更新 PG `execution_log_files`、再经内存 SSE fan-out 推给浏览器。结束由消费 `attempt.*` terminal 事件 + bounded drain 触发。
4. 前端：dopilot Web（Vue3 SPA）在 `apps/web/src/`（pages/components）新建日志页组件，用浏览器原生 `EventSource` 订阅 `/api/v1/executions/{id}/logs/stream`，处理 `id:<seq>` / `Last-Event-ID` 重连补洞，前端自行实现增量 append、自动滚底（无 scrapydweb Jinja 模板可复用）。开窗/关窗只影响 server→web SSE 是否对该 execution 推送，不再驱动 server→agent 拉取频率（agent 始终经 log stream 增量推）。
5. 脚本日志：dopilot agent 的 `ScriptRunner`（`apps/agent/dopilot_agent/runners/script.py`）自行实现进程拉起，把 stdout/stderr 重定向到 agent 工作区（`apps/agent/dopilot_agent/workspace/`）落盘文件，由 agent log publisher 按 stream=stdout/stderr tail 并增量 `XADD` 到 `dopilot:server:logs`。**移植注意**：进程拉起须遵守 `prctl(PR_SET_PDEATHSIG)` 父进程死亡信号语义，并使用 glibc（slim/debian）基础镜像而非 Alpine（musl 不满足 `libc.so.6` prctl）——此约束以参考基线 `sub_process.py:8,21-40,73-78` 行为为参照，dopilot 在 runner 中自行实现，不复用/修改该文件。

> **为什么是 Redis log stream 推 + SSE**：agent 主动经 Redis 推增量，免去 server 主动连每个 agent 与拉取调度；Redis log stream 提供 at-least-once 传输与 byte offset 语义，server 按 offset 去重/补 gap、消费进度（`last_pulled_offset`）权威仍集中在 server PG；浏览器只负责看日志，server→web 仍 SSE 单向、原生自动重连且在 server 单实例下足够。日志 RPO≠0 为已接受设计（缺片 `partial` 不阻塞执行状态收敛）。

### 第二步

1. 在 `apps/agent/dopilot_agent/logs/` 增加 `DockerLogSource` 采集侧（docker SDK 或 `docker logs -f` 子进程落盘），同样由 agent log publisher tail 后增量 `XADD` 暴露 stdout/stderr。
2. dopilot `auth/` 模块按两套语义实现鉴权：**机器认证 config-present-or-off**（agent `shared_token` 非空才启用 agent 认证）；**Web 管理员认证 fail-closed**（阶段 2.2：`admin_username`+`admin_password`+`token_secret` 三者齐全且非空时启用，缺失则启动失败，仅显式 `DOPILOT_AUTH_DISABLED=true` 才匿名直连）。Web 认证启用时，SSE 用短期 `stream_token`（POST 换取、TTL 60s、仅校验建连）。内网防误操作策略，非互联网零信任。

### 兜底与边界

- **offset 增量轮询 JSON 端点**（读 server 已落盘正文 + `execution_log_files` offset）可与 SSE 共存，作为不支持 SSE 环境的浏览器降级**读取**路径；但**不引入浏览器 WebSocket**（agent→server 日志走 Redis log stream 推，此处仅指 web→server 读取通道）。
- **单实例硬约束**：server = 单容器 + uvicorn workers=1 + 单 APScheduler 实例，不支持多副本/多 worker，且未来也不做。**不引入 Redis 做多副本 HA / fan-out / 分布式锁**，**不引入 NATS / PG LISTEN-NOTIFY** 做 fan-out，server→web SSE fan-out 在单进程内存内完成；Redis 仅作单实例 server↔agent 通信总线（含日志 stream），不改变单实例约束。
- **备份**：必须同时覆盖 PostgreSQL（索引）+ `/server-data/logs` 卷（正文）。

> ⚠️ **务必先落地 dopilot 自有的 `LogSource` 抽象**（`apps/server/dopilot_server/logs/`），避免三类执行器分别实现日志取数主流程。

---

## 5. dopilot 新建文件清单（apps 布局）

> 实时日志能力由 dopilot 在 `apps/` 下**全新实现**；下表是 dopilot 要新建的文件/模块，**不是改 scrapydweb**。参考基线对应行为另见文末「scrapydweb 行为参考（只读）」。

| dopilot 位置 | 性质 | 实现要点 |
| --- | --- | --- |
| `apps/server/dopilot_server/api/v1/`（logs 路由） | 新建 | FastAPI SSE 流式端点（`text/event-stream`，`id:<seq>`/`Last-Event-ID`）+ offset 增量轮询 JSON 端点（读已落盘正文，降级用）+ `stream_token` 换取端点；**web→server 不含任何 WebSocket 端点**；调用 `LogSource`（`RedisLogSource`）取增量行；节点选择经 `nodes/`/`services/` |
| `apps/server/dopilot_server/logs/`（如 `source.py`） | 新建 | dopilot 自有 `LogSource` 抽象（`open/iter_incremental/close`）+ `RedisLogSource`（数据源为 server 消费 Redis log stream 后落盘正文）；正文写 `/server-data/logs`、索引/完整性写 PG `execution_log_files`（含 `log_integrity`/gap 字段） |
| `apps/server/dopilot_server/redis/`（`client.py`、`consumers.py` 等） | 新建 | log consumer 消费 `dopilot:server:logs`（offset 去重/补 gap/落盘/`XACK`）、event consumer 消费 `attempt.*`（结束检测）；server reconcile 改为 heartbeat/event 对账，不再访问 agent HTTP status |
| `apps/agent/dopilot_agent/logs/` + `apps/agent/dopilot_agent/redis/` | 新建 | **log publisher**：tail 本地日志按 byte offset 增量 `XADD` 到 `dopilot:server:logs`（base64 字节，单一顺序生产者 offset 递增，含 outbox 重放排序）+ `ScriptLogSource` / `DockerLogSource` 采集侧（脚本 stdout 落盘；容器 `docker logs -f` / SDK `container.logs(stream,follow)` 落盘）；`/agent-data/state/executions/{attempt_id}.json` 映射恢复 + TTL 兜底 |
| `apps/agent/dopilot_agent/runners/script.py`、`docker.py` | 新建 | runner 自行实现进程/容器拉起，stdout/stderr 重定向到 `apps/agent/dopilot_agent/workspace/` 落盘以供 log publisher tail；进程拉起遵守 `prctl(PR_SET_PDEATHSIG)` + glibc 基础镜像约束（见文末行为参考） |
| `apps/web/src/`（pages/components + api） | 新建 | Vue3 日志页组件，浏览器原生 `EventSource` 订阅 `/api/v1` SSE（`id:<seq>`/`Last-Event-ID` 重连补洞），前端实现增量 append/自动滚底；开窗/关窗只影响 server→web SSE 是否推送该 execution；不支持 SSE 时降级到 offset 分页 fetch |
| `apps/server/dopilot_server/auth/` | 新建 | 机器认证 config-present-or-off：agent→server `server_shared_token`（不复用 server→agent 旧 token）；Web 管理员认证 fail-closed（阶段 2.2，缺凭据则启动失败，仅 `DOPILOT_AUTH_DISABLED=true` 匿名）；前端 SSE 短期 `stream_token`（POST 换取、TTL 60s、仅校验建连，`EventSource` 不能带自定义头） |
| `packages/protocol/dopilot_protocol/streams.py` | 新建 | server↔agent stream 消息 schema：`AgentLogEvent`（base64 字节，`offset`/`size_bytes`/`eof`）/ `AgentCommand` / `AgentEvent` / `AgentHeartbeatRequest`/`Response`；统一任务/日志标识定义。既有 `TailRequest`/`TailResponse`/`AgentRunRequest`/`AgentStatusResponse` 标 legacy，不再代表当前协议 |
| `apps/server/dopilot_server/models/`（如 `execution_log_files`） + Alembic 迁移 | 新建 | PG 索引表 `execution_log_files`（见 §5.1），新增 `log_integrity` 列 + gap 字段；SQLAlchemy + **裸 Alembic**（FastAPI 无 Flask app，非 Flask-Migrate），新增放 `0003+`；APScheduler jobstore 落 PG |
| `configs/server.example.toml` + `apps/server/dopilot_server/config/` | 新建 | 实时日志配置项写入 toml：`[redis]`（`url`/`stream_maxlen_logs`/`log_retention_seconds`/`consumer_name`/`require_aof`）、`[logs].log_drain_timeout_seconds=30`、EOF 稳定 3s、容器日志保留轮转策略；由 dopilot 的 toml 加载器解析与校验 |
| `apps/server/pyproject.toml` / `apps/agent/pyproject.toml` | 新建 | server 侧声明 FastAPI/uvicorn（workers=1）/SQLAlchemy/Alembic/asyncpg 或 psycopg/redis 客户端等依赖；agent 侧声明 redis 客户端、heartbeat HTTP 客户端、docker SDK 等采集依赖；版本由 dopilot 自定 |

> 节点寻址与日志取数：dopilot 在 `apps/server/dopilot_server/nodes/` 与 `services/` 自行实现节点选择与日志取数（agent 启动携带稳定 `agent_id` 并**主动 POST `/api/v1/agents/{agent_id}/heartbeat`**，server 以 `healthy = now - nodes.last_seen_at <= heartbeat_timeout_seconds` 判健康、upsert `nodes`，只选择健康 agent；`nodes.last_seen_at` 由 agent heartbeat 写入，不再由 server 轮询 `/health` 回填）；日志增量由 agent 经 Redis log stream 推、server log consumer 消费落盘（不直连裸 scrapyd、不再 server 拉 agent tail），消息 schema 经 `packages/protocol/dopilot_protocol/streams.py`。

### 5.1 存储模型（正文文件 + PG 索引）

**正文（server 本地文件卷，PG 不存正文）**：

```text
/server-data/logs/YYYY/MM/{execution_id}/{attempt_id}.{stream}.log
# stream=log 时即 {attempt_id}.log
```

**索引（PostgreSQL 唯一库，表 `execution_log_files`）**：

- 主键：`(execution_id, attempt_id, stream)`
- 列：`storage_path` / `size_bytes` / `last_pulled_offset`（消费进度权威，记 agent 逻辑字节 offset） / `final_offset`（server 文件物理大小，含 gap marker） / `status`（生命周期） / `log_integrity`（完整性，与生命周期分离） / gap 字段（如 `gap_count` / `first_gap_expected_offset` / `first_gap_actual_offset`，或独立 gap 明细表） / `started_at` / `finished_at` / `retained_until` / `created_at` / `updated_at`
- `status`（生命周期）枚举：`active` / `finalizing` / `complete` / `missing` / `expired`
- `log_integrity`（完整性，**与 `status` 分离**，黏性 `partial` 不因后续连续自动回到 `complete`）枚举：`complete` / `partial` / `missing` / `expired`。业务状态与日志完整性独立：任务可 `complete`、日志可 `partial`
- `stream` 枚举：`log` / `stdout` / `stderr` / `system`（schema/API 从第一版即支持；scrapy/scrapyd 只产 `log`，脚本阶段用 `stdout`/`stderr`）
- 新增列经 Alembic `0003+` 迁移，不塞进既有 `0001`/`0002`

`execution_id` / `attempt_id` 由 server 生成并下发 agent。

### scrapydweb 行为参考（只读，移植时对照的语义点）

以下为 scrapydweb 参考基线在该领域的行为/语义，仅供 dopilot 移植时对照，**`file:line` 相对上游 scrapydweb 1.6.0 / commit `1341cf9`，不是 dopilot 待改文件**：

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
> **【superseded 注】** 其中「日志取数=server pull 调 agent tail」「每秒增量 pull」相关锁定已被通信重构（`docs/refactor/00-redis-streams-agent-communication.md`）翻案为「agent 经 Redis log stream 推、server 消费」；下方已据此同步，四个不变量（不用 WebSocket、server→web SSE、正文落盘、PG 只存索引/offset/状态）保持。

**已锁定（不再讨论）：**

- ~~多副本日志广播~~ → 单容器 + uvicorn workers=1 + 单 APScheduler 实例，不支持多副本，未来也不做；**不引入 Redis 做多副本 HA/fan-out/分布式锁、不引入 NATS/PG LISTEN-NOTIFY**，server→web SSE fan-out 在单进程内存内完成（Redis 仅作单实例 server↔agent 通信总线，含日志 stream）。
- ~~部署形态~~ → uvicorn workers=1 单实例。
- ~~远程 scrapyd 真增量 / Docker 采集路径~~ → 不直连裸 scrapyd / docker daemon；统一由本机 dopilot-agent log publisher tail 后经 Redis log stream 推（agent 子进程拉起本机 scrapyd，scrapyd 仅监听容器内部端口）。
- ~~流式端点鉴权~~ → 机器认证 config-present-or-off（agent→server 用 `server_shared_token`，不复用 server→agent 旧 token；Redis 启用 AUTH/ACL）；Web 管理员认证 fail-closed（阶段 2.2，缺凭据则启动失败，仅 `DOPILOT_AUTH_DISABLED=true` 匿名），启用时 SSE 用短期 `stream_token`（TTL 60s、仅校验建连）。
- ~~多人共享同一 job~~ → 多窗口复用一个 log consumer 落盘 + 单进程内存 SSE fan-out。

**新增锁定：**

1. **落盘与截断**：server 本地日志默认保留 30 天；单次 execution 的单个 stream 文件默认最大 100MB，超过后停止继续追加正文并把 `execution_log_files.truncated=true`、`status` 保持可读状态。agent 已完成任务日志保留 3 天，孤儿日志保留 7 天，作为 server cleanup 失败时的兜底。
2. **首屏 tail**：打开 Web 日志窗口时，server 先从本地（已由 log consumer 落盘的）文件返回最后 2000 行或最后 1MB（取先达到的边界），随后将该 execution 经 log consumer 落盘的增量经 SSE fan-out 推送；agent 始终经 Redis log stream 增量推，开窗/关窗只影响 server→web 是否推送，不再驱动 server→agent 拉取频率升降。任务结束由消费 `attempt.*` terminal 事件触发 bounded drain 收口。
3. **显示形态**：第一版只做 raw text 显示与 `log/stdout/stderr/system` stream 分流，不做 logparser 风格解析、统计或高亮；scrapy 第一版仅产 `stream=log`。
4. **过期联动**：PG `retained_until` 与本地文件清理同步。清理任务先把 `execution_log_files.status` 置为 `expired`，再删除 `/server-data/logs` 正文；若读取时索引存在但文件缺失，返回 `status=missing` 并在 UI 标记日志正文已不可用。
