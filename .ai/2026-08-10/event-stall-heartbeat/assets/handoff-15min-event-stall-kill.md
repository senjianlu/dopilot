# dopilot:运行超过 15 分钟的任务会被「事件停滞」误杀

> 交接给 dopilot 仓库。**爬虫侧(steammarket-spider)不需要改动。**
> 调查日期 2026-08-10;代码基线 dopilot `b2f2ad2`。

---

## 一、现象

`steammarket-spider` 的 `steamcommunity` 爬虫每轮需要约 **49 分钟**,但**每次都在
第 15 分钟被 SIGINT 杀掉**,只跑完约三分之一。

关键点:**任务本身是健康的** —— 代理池充足、错误率极低、吞吐稳定。
它不是「卡住了」,只是「跑得久」。

---

## 二、决定性证据(线上日志,2026-08-10 07:00 UTC 那轮)

| 证据 | 数值 | 说明 |
|---|---|---|
| `start_time` | `07:00:06` | |
| `Received SIGINT, shutting down gracefully` | `07:15:06` | **正好 +900 秒** |
| `elapsed_time_seconds` | **901.24** | |
| `finish_reason` | `shutdown` | 外部信号,非自主结束 |
| 代理池 | 起始健康 **327**,结束仍剩 **269 可用** | **完全没有耗尽** |
| `response_status_count/429` | **18** | 限流几乎没发生 |
| `downloader/exception_count` | 58(全 `DownloadFailedError`) | 与 327−269=58 个封禁吻合 |
| 进度 | `scheduler/dequeued 1107` / `enqueued 3598` | 才跑完 ~31% |
| 实测吞吐 | 1107 请求 / 901 秒 = **1.23 req/s** | 跑完 3598 个请求需 ≈ **49 分钟** |

原始日志片段:

```
2026-08-10 07:00:06 [steamcommunity] INFO: 🚚 任务开始 — task_id=9b2e8992...
2026-08-10 07:00:06 [app.middlewares.commonProxyPool] INFO: 🔀 节点表已更新：健康 327 个，已封禁 0 个，可用 327 个
...
2026-08-10 07:15:06 [scrapy.crawler] INFO: Received SIGINT, shutting down gracefully. Send again to force
2026-08-10 07:15:06 [scrapy.core.engine] INFO: Closing spider (shutdown)
2026-08-10 07:15:06 [scrapy.extensions.logstats] INFO: Crawled 1029 pages (at 82 pages/min), scraped 10290 items
...
{'downloader/exception_count': 58,
 'downloader/response_status_count/200': 1031,
 'downloader/response_status_count/429': 18,
 'elapsed_time_seconds': 901.2407408419531,
 'finish_reason': 'shutdown',
 'scheduler/dequeued': 1107,
 'scheduler/enqueued': 3598,
 'start_time': datetime.datetime(2026, 8, 10, 7, 0, 6, 879307, tzinfo=timezone.utc)}
```

全程节点封禁日志最后一条停在 `剩余可用 269 个`,**从未出现**「无可用节点」
「全部节点处于冷却」等池子耗尽的信号。

---

## 三、根因(代码定位)

### 1. 判定在这里

`apps/server/dopilot_server/redis/reconcile.py:152-172`

```python
baseline = (
    _aware(execution.last_event_at)
    or _aware(execution.started_at)
    or _aware(execution.created_at)
)
idle = (now - baseline).total_seconds() if baseline is not None else 0.0

if idle >= lost_after:                                    # :160
    if await mark_lost(session, execution, LOST_EVENT_STALL, now):
        ...
        outbox_svc.create_stop_outbox(
            session, ..., intent=StopIntent.reclaim,       # → 杀进程
        )
elif idle >= stall and execution.stalled_at is None:
    execution.stalled_at = now                            # 5 分钟只是告警
```

- `lost_after` = `settings.agents.lost_after_stalled_seconds`(reconcile.py:122)
- 默认值 **900** —— `apps/server/dopilot_server/config/settings.py:126`
- 另有 `stalled_attempt_seconds: int = 300`(settings.py:125),5 分钟起只打告警

### 2. 但 `last_event_at` 在运行期**永远不会被刷新**

`apps/server/dopilot_server/services/events.py:58`

```python
_EVENT_TO_EXEC = {
    AgentEventType.accepted:  states.EXEC_PENDING,
    AgentEventType.running:   states.EXEC_RUNNING,
    AgentEventType.finished:  states.EXEC_FINISHED,
    AgentEventType.failed:    states.EXEC_FAILED,
    AgentEventType.canceled:  states.EXEC_CANCELED,
    AgentEventType.lost:      states.EXEC_LOST,
}
```

**六种事件全是状态转换,没有任何「进度 / 心跳」类事件。**
attempt 一旦进入 `running`,在它自己结束之前不会再产生任何事件,
`last_event_at` 就永远停在启动那一刻,`idle` 单调增长。

### 3. 于是 900 秒后必被 reclaim

链路:
`reconcile` 判定 `LOST_EVENT_STALL`
→ `create_stop_outbox(intent=StopIntent.reclaim)`
→ agent `runners/scrapyd.py:113` `await self._client.cancel(project, job_id)`
→ scrapyd 对 crawl 进程发 **SIGINT**
→ Scrapy 打印 `Received SIGINT, shutting down gracefully`

**结论:`lost_after_stalled_seconds` 名义上是「卡死检测」,实际效果是
「任务运行时长硬上限」。任何跑满 15 分钟的 scrapyd 任务都会被杀,
与它是否健康、是否在正常产出完全无关。**

---

## 四、影响面

**不止 steamcommunity。** 任何单轮超过 15 分钟的爬虫都会中招 ——
`lisskins`(单轮实测 25609 条)、`haloskins`(29308 条)、`skinport`、
`uuyp prices` 等,只要数据量涨到跑够 15 分钟就会开始被截断。

症状具有迷惑性:日志里看不到任何错误,只有一个 `finish_reason: shutdown`
和不完整的数据,很容易被误判成目标站限流或代理问题
(**我自己第一轮就误判成了「代理池耗尽」,直到拿到完整日志才排除**)。

---

## 五、方案 A:调大阈值(纯配置,不改代码)

`lost_after_stalled_seconds` 已经是可配置项:

- 配置段:`[agents] lost_after_stalled_seconds`
- 环境变量:**`DOPILOT_LOST_AFTER_STALLED_SECONDS`**
  (映射见 `apps/server/dopilot_server/config/loader.py:81-85`)

改成 3600(1 小时)或更大即可立刻止血。

**代价**:真正卡死的任务也要等这么久才被回收。所以 A 是止血,不是根治 ——
它把「卡死检测」的灵敏度一起牺牲掉了。

**建议**:即使做 B,也先把默认值调大,因为 900 秒对「一个批处理任务多久没
产生状态转换事件才算异常」而言本来就偏短。

---

## 六、方案 B:补运行期心跳事件(根治)

### 核心发现:server 侧可能**不需要改**

`apps/server/dopilot_server/services/events.py:218`:

```python
    # agent produced an event -> it is alive; reset the event-stall clock.
    execution.last_event_at = now
    execution.stalled_at = None
```

这两行在整个 `if / elif` 分支链**之外**,即**无论事件是否被采纳
(哪怕 `running → running` 被判为无效转换、走 `OUTCOME_SKIPPED_TERMINAL`),
`last_event_at` 都会被刷新**。

所以最小改动可能是:**agent 侧对仍在 running 的 attempt 周期性重发一次
`running` 事件**(比如每 60~120 秒一次)。现成的发射函数已经有了:

- `apps/agent/dopilot_agent/redis/events.py` 的 `emit_running(task_id,
  execution_id, remote_job_id)`(约 :236-243)

### 落地时要确认的几点

1. **重发是否会污染状态机 / 审计**:`_apply_status` 不会被调用(转换无效),
   但 `_audit(...)` 每次都会写一条 `OUTCOME_SKIPPED_TERMINAL` 审计记录 ——
   高频重发会把审计表撑大。若不可接受,更干净的做法是**新增一个
   `heartbeat` / `progress` 事件类型**,在 `apply_event` 里只刷新
   `last_event_at` 且不写状态审计。
2. **心跳频率**要明显小于 `stalled_attempt_seconds`(300),否则 5 分钟的
   stalled 告警仍会误报。建议 60~120 秒。
3. **心跳必须由 agent 判断进程真的活着才发**(例如 scrapyd `listjobs`
   仍列为 running、或子进程存活),否则就把「卡死检测」彻底废掉了 ——
   那还不如直接用方案 A。这是 B 的关键点:**心跳的意义在于「我确认它还
   活着」,不是「我还在」**。
4. 现有的 `stalled_at` 一次性告警语义要一并想清楚:有了心跳后,
   `stalled` 的含义会从「没有状态转换」变成「进程真的没响应」,这才是
   它本来该有的意思。

---

## 七、方案 C(已否决,记录备查)

爬虫侧把 3522 页按 offset 区间拆成多个任务,各自在 15 分钟内跑完。

**不推荐**:15 分钟这个上限本身不合理,不该让每个爬虫去迁就它;而且
调度复杂度、失败重扫、跨分片去重都会跟着变复杂。

---

## 八、附:与本次一同修掉的另一个问题(爬虫侧,已完成)

同一份日志里还有一个 **独立** 的故障:

```
psycopg.errors.CardinalityViolation: ON CONFLICT DO UPDATE command cannot
affect row a second time
```

发生在 `close_spider` 的批量写库 —— 与 SIGINT **没有因果关系**
(它在引擎已决定关闭之后才执行;抓取过程中根本不碰数据库),
但它会让**已抓到的那部分数据全部丢失**(COPY→upsert 是单原子事务)。

根因是 Steam 用 offset 分页抓**活数据**(实测 `total_count` 6 分钟内在
35207/35208 之间反复变化),翻页期间挂单增删让页边界条目重复出现。
已在 steammarket-spider 侧修复(写入前按主键去重,commit `3f9d4a4`,
decisions/0020)。**dopilot 侧无需为此做任何事**,此处仅作背景说明:
修复后,即便任务仍被 15 分钟截断,已抓到的 ~10000 条也能正常落库。
