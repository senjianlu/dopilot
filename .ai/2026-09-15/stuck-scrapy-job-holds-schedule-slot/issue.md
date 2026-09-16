# 问题记录:scrapy 任务卡在关闭阶段、进程不退 → 该调度被并发闸一直跳过

- 状态:**问题记录,尚未进入 rawf-plan**(不含方案、不改代码),供在 dopilot 侧讨论要不要改、改哪里。
- 来源:steammarket-spider 会话,2026-09-15。用户原话:「将这次的问题在 dopilot 那里开个新的日期、任务并落到证据中，我去那边和 ai
  讨论改修必要。」
- 爬虫侧的根因修复另立任务:steammarket-spider `.ai/2026-09-15/profit-alert-pg-timeouts/`(只给卡住的那条 PG 连接加客户端超时 /
  保活,不改环境变量)。本文件只记录 dopilot 侧暴露出来的问题。

## 现象与时间线(UTC)

| 时间 | 事件 | 证据 |
|---|---|---|
| 02:04 ~ 03:28:15 | SWAPGG 730(`*/10`、max_concurrency 1)每 10~20 分钟完成一轮,每轮约 8,107 条 | `evidence/valkey-swapgg-result-timeline.txt` |
| 03:30:08 | scrapyd job `bb521998b0b511f1b7dd36e28bd6996d` 启动 | `evidence/swapgg-730-job-log.txt` 首行 |
| 03:36:48 | 68 页翻完,产出 8107 条 | 同上 |
| 03:36:50 | `Closing spider (finished)`,COPY 写库 8107 条完成;之后最后一行是 realtimeMonitor 的 Valkey 写入 —— **再无任何输出**:没有 `Dumping Scrapy stats`、没有 `Spider closed`,结果计数也没写 | 同上(文件末尾) |
| 03:40 起 | 每次 730 触发都因并发闸被跳过(440 / 252490 照常) | 时间线里 03:28:15 之后再无约 8,1xx 条的记录 |
| 05:31 | 仍无 730 完成的轮次(已卡约 2 小时) | 时间线文件末尾 `now 05:31:07` |

## 根因(爬虫侧,已定位)

steammarket-spider 的 `ProfitAlertExtension`(`app/extensions/profitAlert.py`,commit `dd5d936` 时的行号)在 spider_opened 把 `_load`
(读 `profit_configs` 与 `f_sell_reference_profile`)放进一条串行线程链(`_enqueue`,183-184 行;`_load`,225-231 行起),spider_closed
**返回这条链**让 Scrapy 等它收束(220-222 行)。该轮日志里既没有正常轮在 opened 后约 3 秒打出的「🧩 利润比价就绪」,也没有「利润比价加载
失败」⇒ `_load` 从 03:30:09 起就没返回,关闭时 Scrapy 永远等不到链收束。

- 查询本身不慢:同一查询只读计时 14224 行 1.49 s(`evidence/pg-timeouts-and-query-timing.txt`);05:04 的 `pg_stat_activity` 里已没有那个
  时段的会话 ⇒ 服务端早已结束,客户端卡在 socket 读上(连接被网络静默断开的典型表现)。
- 两端都没有兜底:连接串只带 `sslmode`(无 `connect_timeout` / keepalive);服务端 `statement_timeout`、`lock_timeout`、
  `idle_in_transaction_session_timeout`、`idle_session_timeout` 均为 0,`tcp_keepalives_idle` 7200(同一证据文件)。
- 就算关闭流程不等这条链,进程也退不出:Twisted 线程池工作线程非守护、`stop()` 无超时 `join`(`evidence/twisted-threadpool-join.txt`)。

## dopilot 侧暴露的问题(事实,详见 `evidence/dopilot-code-facts.md`)

1. **没有单任务运行时长上限**:以前 900 s 曾充当事实上的上限,引入 attempt 心跳后按设计去掉了(server `config/settings.py:144-150`)。
2. **心跳按 scrapyd 列表续命**:只要 scrapyd `listjobs` 还把 job 列为 running,agent 就每 ~60 s 发 attempt 心跳,任务永不判 stalled / lost;
   卡在关闭阶段、没有任何日志输出的进程与正常运行无法区分,一直占着该调度的并发槽。
3. **取消只发 TERM,并立即判 canceled、释放槽位**(agent `redis/commands.py:1000-1016`,`scrapyd/client.py:137-148`):不确认进程是否
   退出、不升级 KILL(wheel runner 才有 TERM → 10 s → SIGKILL)。本次这类进程多半不响应 TERM,取消后会成为 dopilot 看不见的残留进程。
4. **唯一会升级到 KILL 的是日志刷屏看门狗**:本次进程没有日志输出,不会触发。

## 当前处置(需人工)

在 dopilot 取消该任务后,到 agent 上确认 scrapyd job `bb521998b0b511f1b7dd36e28bd6996d` 的进程已退出;没退就 `kill -9`,或直接对
scrapyd `cancel.json` 发 `signal=KILL`。想先坐实根因可在 kill 前 `py-spy dump --pid <pid>`,看工作线程是否停在 psycopg 的读调用上。

## 待讨论的改修选项(未决,仅供讨论)

- **A. 调度 / 任务级最长运行时长**:可按调度配置,到点 TERM → 等待 → KILL,并判 failed(或新的 timeout 状态)。注意 steammarket-spider
  的 decisions/0044 去掉过爬虫侧的 `CLOSESPIDER_TIMEOUT`,理由是被掐断的正常轮次会被判「出错」、连续 5 次自动停用调度 —— 阈值必须明显
  宽于各调度最长的正常轮次(SWAPGG 730 正常 5~21 分钟,STEAMCOMMUNITY 等更长),默认关闭或按调度设置更稳妥。
- **B. scrapy 取消升级到 KILL**:TERM 之后轮询 `listjobs`,N 秒仍在就 `signal=KILL`,确认退出后再判 canceled(与 wheel runner 对齐)。
  改动面小,且能消除「取消后残留进程」这个盲区。
- **C. 卡死探测**:job 日志长时间(如 N 分钟)无增长而进程仍在 → 告警,或并入 A 的处置。能区分「在跑但慢」与「完全不动」,但需要为
  长时间静默的正常任务留豁免。
- **D. 前端提示**:运行中任务显示已运行时长,超阈值高亮,方便人工发现。
- **E. dopilot 暂不改**:爬虫侧修复后同类问题的概率会下降,但 dopilot 仍无法兜底其他原因造成的卡死。

## 证据索引(`evidence/`)

| 文件 | 内容 |
|---|---|
| `swapgg-730-job-log.txt` | 用户提供的该 job 完整日志(仅 Telnet 口令脱敏) |
| `valkey-swapgg-result-timeline.txt` | 只读 Valkey:SWAPGG 每轮结束时刻与条数,02:00 ~ 05:31 UTC |
| `pg-timeouts-and-query-timing.txt` | 只读 PG:连接串参数名、服务端默认超时 / 保活、`f_sell_reference_profile` 计时 |
| `twisted-threadpool-join.txt` | Twisted 26.4.0 线程池源码片段:工作线程非守护、`stop()` 无超时 join |
| `dopilot-code-facts.md` | dopilot 源码事实(运行上限、心跳、并发闸、取消、日志刷屏看门狗),逐条标注亲核 / 子代理 |
