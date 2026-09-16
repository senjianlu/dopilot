---
status: approved
task: no-progress-stall-detection
date: 2026-09-16
approved_at: 2026-09-16 16:47:18 +0900
plan_review_max_rounds: 8
impl_fix_max_rounds: 8
---

# 方案:无活动(无进度)卡死探测 + 取消升级到 KILL

> 轮次上限说明:用户于 2026-09-16 明确要求「plan 和改修的 review 都上升到
> 最大 8 轮」,故本任务 frontmatter 覆盖默认的 3 轮为 8 轮。

## 背景与目标

问题记录见 `.ai/2026-09-15/stuck-scrapy-job-holds-schedule-slot/`:2026-09-15 一个
SWAPGG 730 job 在 Scrapy 关闭阶段卡死,日志彻底静默却仍被 scrapyd 列为 running,
于是 agent 每 60s 照发心跳、server 永远判不了 stalled,该调度唯一的并发槽被占了
两小时;而人工取消只发一次 TERM 就立刻判 canceled 并释放槽位,进程很可能根本没死,
变成 dopilot 看不见的残留进程。

用户在 2026-09-16 选定路线:**无活动超时** ——「复用 agent 已有的 job.log 字节数
信号:日志 N 分钟零增长且进程仍在 → 判 stalled → 通知,可配置是否自动 TERM→KILL」;
并确认「取消升级到 KILL」一并做。

### 根因(已核源码,HEAD 9b86f21)

1. `emit_heartbeat(task_id, execution_id)`(`apps/agent/dopilot_agent/redis/events.py:251`)
   **不携带任何进度信息**;agent 只要看到 scrapyd `listjobs` 列着 job 就发
   (`redis/commands.py:325-329`)。
2. server 收到心跳就刷新 `last_event_at`、清空 `stalled_at`
   (`services/events.py:198-207`),事件停滞永远到不了
   `lost_after_stalled_seconds`(3600s)。
3. 即:**心跳证明的是「scrapyd 还列着」,不是「进程在干活」**。
4. 取消对 scrapy 只发一次默认 TERM 便判 canceled(`redis/commands.py:999-1015`),
   不确认退出、不升级 KILL;同 agent 的 wheel runner 早已是 TERM→10s→SIGKILL。

### 目标

1. server 能区分「活着」与「在干活」,对长时间零进度的执行**标记 + 告警**。
2. 取消 / reclaim 一个 scrapy 执行时确认进程真的死了,不死就升级 KILL。
3. **默认不改变任何现有的自动终止行为**——自动停止是显式开关,默认关闭。

### 安全底线(本方案最重要的约束)

**`lost` 判定与 reclaim 触发链完全不动。** `last_event_at` 仍由心跳无条件刷新,
`heartbeat_timeout` / `event_stall` → `lost` → `create_stop_outbox(reclaim)` 一行不改。
新增的「无进度」信号走**独立字段**,只用于标记与通知(以及一个默认关闭的可选停止),
**永远不会把执行判成 lost**。

于是即便某个正常任务长时间不写日志,最坏结果也只是一条通知,绝不会被杀 —— 这正是
steammarket-spider `decisions/0044` 废弃 `CLOSESPIDER_TIMEOUT` 时踩过的坑。

### 明确不做

- **不新增任务级/调度级硬超时**(`max_runtime`):用户选的是「无活动超时」,不夹带。
- **不改 `failed` / `lost` 判定口径,不新增终止态**。因此
  `consecutive_error_count` 与 `auto_disable_after_errors`(`services/outcomes.py:209`)
  语义不受影响——「无进度」不是一次失败,不会把调度推向自动停用。
- **不做前端新页面/新列**(用户未选「D. 前端提示」);告警走已有消息中心。
- 不动 wheel runner 的终止链(它已经是对的)。

## 改动范围

| 文件 | 改动 |
|---|---|
| `packages/protocol/dopilot_protocol/streams.py` | 心跳携带 `log_bytes` 的语义说明(`AgentEvent.log_bytes` 字段已存在,不加字段) |
| `apps/agent/dopilot_agent/redis/events.py` | `emit_heartbeat` 增加可选 `log_bytes`;`republish_current` 增加停止意图约束(停止期间不自行上报终态) |
| `apps/agent/dopilot_agent/runners/scrapyd.py` | 新增 `is_job_alive`(停止确认专用的存活查询,区分「不可达」与「确认不在跑」),不改 `_resolve_status` 语义 |
| `apps/agent/dopilot_agent/state/store.py` | `AttemptState` 增加 `stop_intent` / `stop_requested_at` / `stop_escalation` / `cleanup_pending` + `mark_stop_requested` / `mark_stop_escalation` / `mark_cleanup_pending`(照 `log_flood_*` 既有模式) |
| `apps/agent/dopilot_agent/redis/commands.py` | 新增 `_sample_log_size`(与 flood 开关解耦)并把读数喂给心跳;`_flood_watchdog` 改为接收读数;stop 改为**跨 tick 状态机**(`_handle_stop` 不再等待),新增 `_stop_watchdog`;`_handle_cleanup` 拆出 `_do_cleanup` 并在停止未收尾时改置 `cleanup_pending` |
| `apps/agent/dopilot_agent/config/settings.py` | `stop_kill_after_seconds`(默认 10)、`stop_confirm_timeout_seconds`(默认 120)、`kill_retry_interval_seconds`(默认 60) |
| `apps/server/dopilot_server/models/execution.py` | 新增 `last_progress_at` / `last_progress_sample_at` / `no_progress_at` |
| `apps/server/migrations/versions/0015_execution_progress_tracking.py` | 三个 nullable 列 |
| `apps/server/dopilot_server/services/events.py` | 心跳只在 `log_bytes` **增长**时推进 `last_progress_at`;带读数即推进 `last_progress_sample_at`;有进度时清空 `no_progress_at` |
| `apps/server/dopilot_server/redis/reconcile.py` | 新增第 3 步:无进度检测 → 一次性打标 + 通知(+ 开关控制的一次性停止) |
| `apps/server/dopilot_server/config/settings.py` | `no_progress_stall_seconds`(默认 1800,0=关)、`no_progress_sample_max_age_seconds`(默认 300)、`auto_stop_on_no_progress`(默认 **False**) |
| `apps/server/dopilot_server/models/notification.py` | `TYPE_ATTEMPT_NO_PROGRESS` |
| `configs/server.example.toml` | 三个新键 + 风险注释 |
| `docs/architecture/03-execution-and-logs.md` | 回写取消时序:`attempt.canceled` 仍必达,但改为**确认进程退出后**才上报(最长 `stop_confirm_timeout_seconds`),并说明 TERM→KILL 升级与延期清理 |
| `apps/web/components/layout/notification-bell.tsx` | 新类型落地路由 → `/tasks/detail?id=` |
| `apps/web/lib/i18n/locales/{zh,en}.ts` | `notifications.types.attempt_no_progress` 文案 |
| `apps/server/tests/`(2 个文件) | events 进度语义、reconcile 无进度检测 |
| `apps/agent/tests/`(2 个文件) | stop 状态机(KILL 升级、确认、不阻塞、reclaim 语义、cleanup 交错、信号失败重试);日志采样与心跳载荷 |
| `apps/web/components/layout/__tests__/notification-bell.test.tsx` | 新类型渲染与路由 |

预计触及 **约 22 个文件 > 10**,按 CLAUDE.md 硬规则,确认闸之前必须先过 plan 评审。

## 实现方案

### 1. 心跳携带进度证据,且与 flood 开关解耦(agent → server,回应 R-04)

**不能**直接复用 `_flood_watchdog` 的读数:它在 `self._log_cap <= 0`(即
`max_job_log_bytes` 关闭日志大小保护,一种合法配置)时**在读 `log_size` 之前就
return**,那样心跳会永远带 `log_bytes=None`,无进度检测整个失效。

因此把「采样」与「flood 判定」拆开,在 tick 里显式采一次样:

```python
# reconcile_started_attempts,scrapy 分支
size = await self._sample_log_size(state)      # 与 _log_cap 无关,只看 log_path
state = await self._flood_watchdog(state, size) or state   # cap<=0 时内部直接返回
resp = await self._runner.status(execution_id, state.task_id)
...
if resp.status == AttemptStatus.running:
    await self._maybe_emit_heartbeat(state.task_id, execution_id, log_bytes=size)
```

- `_sample_log_size` 读不到文件(不存在/权限/IO 错误)→ 返回 `None`。
- `_flood_watchdog` 改为接收这个读数(不再自己读),`cap <= 0` 时仍立即返回,行为不变。
- 每 tick 每执行仍只读一次文件大小,IO 量与今天持平。
- `emit_heartbeat(..., log_bytes: int | None = None)` 写入 `AgentEvent.log_bytes`;
  wheel runner 分支不采样,保持 `None`。

### 2. 进度语义与「采样有效性」(server,回应 R-01 of round 01)

历史 `log_bytes` 不能证明当前仍有可用信号(先报过大小、随后一直报 None 的执行,
若只用 `log_bytes IS NULL` 豁免会被误告警)。故分成两个时间戳:

| 字段 | 何时推进 | 含义 |
|---|---|---|
| `last_progress_sample_at` | 收到**带 `log_bytes` 读数**的心跳(无论是否增长) | 「当前仍能读到这个执行的日志大小」 |
| `last_progress_at` | 读数 **>** 已记录的 `log_bytes`;以及任何非心跳的生命周期事件 | 「上次真的有进展」 |

`apply_event` 规则:

- **心跳**:`last_event_at` 无条件刷新、`stalled_at` 照旧清空(lost 判定不变)。
  - `log_bytes is None` → 三者(`sample_at` / `progress_at` / `log_bytes`)**都不动**。
  - 有读数 → `last_progress_sample_at = now`;若 `> (execution.log_bytes or 0)` 则
    `last_progress_at = now`、`log_bytes = 读数`、**清空 `no_progress_at`**。
- **非心跳事件** → `last_progress_at = now`,清空 `no_progress_at`。
- 基线回退:`last_progress_at` 为空时依次取 `started_at` → `created_at`(同
  `reconcile.py:176-181` 的写法)。

### 3. 无进度检测(server reconcile,回应 round-01 的 R-02/R-03)

在现有两步**之后**加第 3 步(会被判 lost 的执行走不到这里):

```
3) no-progress(心跳新鲜、未判 lost,即进程确认活着):
   no_progress_stall_seconds > 0
   且 last_progress_sample_at 非空 且 now - last_progress_sample_at <= sample_max_age
        # 采样仍有效 —— 我们确实「看得见」日志且它没长
   且 now - progress_baseline >= no_progress_stall_seconds
   且 no_progress_at IS NULL                      # 一次性
   -> no_progress_at = now;发通知;
      若 auto_stop_on_no_progress 则 create_stop_outbox(intent=cancel) 恰一次
```

- **`no_progress_at` 是持久的一次性标记**,**不被心跳清空**(与 `stalled_at` 不同),
  只在第 2 节的「有进度 / 生命周期事件」时清空。它同时守住通知与 stop 的幂等:
  - `notify` 的唯一索引限定 `read_at IS NULL`,用户读过就会再插一条,所以**不能**
    靠 `dedupe_key` 做一次性;改由本字段保证。`dedupe_key` 仍照给,用于「无进度→
    恢复→再无进度」时合并计数。
  - stop 只在 `no_progress_at` 由 NULL 变非 NULL 的那一次入队,**恰一次**;之后的投递
    可靠性由既有 outbox dispatcher 负责(它本就重投),server 不再重复入队。
- **采样有效性窗口** `no_progress_sample_max_age_seconds` 默认 300s(约 agent 心跳
  间隔 60s 的 5 倍);读数中断超过它就停止判定(宁可不报)。
- `no_progress_stall_seconds = 0` → 整特性关闭。默认 1800s,明显宽于 SWAPGG 730 的
  正常轮次(5~21 分钟)。
- report 新增 `no_progress` 计数器,与既有 `stalled` 分开;**不碰 `stalled_at`**。

### 4. Stop 状态机:不阻塞的 TERM→KILL→确认(agent,回应 R-01~R-03)

`_run` 的一轮是 `reconcile_started_attempts()` + `drain_once(block=5000ms)`,两者串行,
`drain_once` 又逐条 `await _process`。**在 stop 里等 10+30 秒会把整批取消变成十分钟
的阻塞**,期间所有执行的心跳与 flood watchdog 全停 —— 这是 round-01 R-04 指出的真实
缺陷。故改为**跨 tick 状态机**(tick 周期约 5s),与既有 log-flood 看门狗同构。

#### 4.1 新增的 `AttemptState` 字段(照 `log_flood_*` 模式)

| 字段 | 含义 |
|---|---|
| `stop_intent` | `"cancel"` / `"reclaim"`,停止意图 |
| `stop_requested_at` | 意图**持久化**的时刻 = 总期限起点 |
| `stop_escalation` | `None` = **TERM 尚未成功发出**;`"term"` = TERM 已成功;`"kill"` = KILL 已成功 |
| `cleanup_pending` | 停止未收尾期间收到过 `cleanup_logs`,回收完成后补做清理 |
| `kill_pending` | **终态已按契约报告,但进程尚未确认退出**;回收未完,映射必须保留 |
| `kill_last_attempt_at` | 上次重发 KILL 的时刻(回收重试节流) |
| `terminal_pending` | **终态已落盘但尚未进入 `emit`**;重启后必须补发(round-07 R-01) |

`mark_done` 增加 `kill_pending` / `terminal_pending` 参数,使
「phase=done + result + kill_pending + terminal_pending」成为**一次原子写入**
(round-06 R-02);`mark_cleanup_pending` / `mark_kill_attempt` /
`clear_kill_pending` / `clear_terminal_pending` 同样是单次写入。

#### 4.2 `_handle_stop`(scrapy 分支)只做一步,立即返回

0. **`state is None`(本地无状态)—— 按 intent 分叉,保持今天的契约**(round-03 R-01):
   - `intent == cancel` → **仍上报权威 canceled**:调一次 `runner.stop`(无 state 时它
     返回 `no_state`,不是错误)、`mark_done(result="canceled")`、
     `emit_terminal(canceled)`,**不进入状态机**(没有 state 可承载)。这条路径是
     `commands.py:1009` 注释「scrapy (or missing state) -> authoritative canceled」
     与 `docs/architecture/03-execution-and-logs.md:28` 的明文要求——**尚未启动就被
     取消的执行全靠这个事件收敛**,绝不能退化成忽略。
   - `intent == reclaim` → 幂等忽略(`process_missing`,与今天一致)。
0b. **`phase != "started"`(执行已在本地收尾,例如自然完成后被
    `reconcile_started_attempts` 标为 `done`,但 `cleanup_logs` 还没到)——
    不进入状态机**,按既有契约直接收尾(round-05 R-02):
   - `intent == cancel` → 照今天上报**权威 `canceled`**,**不把 `phase` 改回
     `started`**(绝不重新激活一个已结束的执行)。
   - `intent == reclaim` → 已有真实终态则 re-emit 之,否则忽略;同样不重新激活。
1. 已有 `stop_requested_at` → **幂等忽略**(重投递的 stop 不重复发信号)。
2. `intent == reclaim`:先查一次 `status`。**此时尚未发过任何信号,`state.canceled`
   仍为假,所以这次读到的终态是「停止前已观察到的权威终态」**,可信 —— 有终态则走
   既有 `_finish_scrapy_attempt`(agent>server 覆盖),结束。
3. **先持久化意图**:写 `stop_intent` / `stop_requested_at=now` /
   `stop_escalation=None`,`phase` 保持 `"started"`。
   **这一步必须在任何网络请求之前**——`_process` 即使 handler 抛异常也会 XACK
   (`commands.py:633-637`),命令不会重投,意图丢了就再也没人推进(round-02 R-03)。
4. 尽力发一次 TERM(`cancel.json` 不带 signal);成功才置 `stop_escalation="term"`,
   失败/异常只记 WARNING —— watchdog 下一 tick 会重试。

#### 4.3 `_stop_watchdog(state)`,在 tick 的 `_flood_watchdog` 之后调用

**顺序是契约的一部分:硬期限检查排在所有可能提前返回的分支之前**,否则 scrapyd
持续不可达时每个 tick 都会从 `unknown` 分支提前返回,永远走不到期限检查,
`cleanup_pending` 也永远释放不掉(round-03 R-02)。

```
1. 未设 stop_requested_at -> return                       # 正常执行零开销
2. elapsed = now - stop_requested_at
3. if elapsed >= stop_confirm_timeout_seconds:            # ← 硬期限,最先判
       # 持久化边界:done + result + kill_pending 必须是【同一次原子写入】,
       # 且发生在 emit 之前。先 mark_done 再单独写 kill_pending 的话,两次写入之间
       # 崩溃会留下 done + kill_pending=False 的 state —— 4.7 不会再去杀它,
       # 若 cleanup_pending 为真还会直接删掉映射(round-06 R-02)。
       store.mark_done(result=..., kill_pending=True, terminal_pending=True)  # 一次写入
       按 4.4 emit 终态;emit 返回后 clear_terminal_pending()
       不执行延期清理             # 删了 scrapyd job 映射就再也回收不了(round-05 R-01)
       WARNING 记明未能确认;return
   #   这一条覆盖 unknown / 信号发送失败 / 一直 running 的所有路径
4. 补发或升级信号(只有发送成功才推进 stop_escalation):
       stop_escalation is None                        -> 重试 TERM(不带 signal)
       == "term" 且 elapsed >= stop_kill_after_seconds -> 发 signal=KILL
       返回 cancel_failed / 抛异常 -> WARNING,不推进 escalation,下一 tick 重试
5. 调 runner.is_job_alive() 判断是否已退出(见下):
       True  (仍在 running/pending 列表) -> return,继续等
       False (listjobs 成功且两张表都没有) -> 确认已退出 -> 收尾(4.4)
       None  (listjobs 失败,不可达)      -> 既不当作已消失也不收尾;return,等下一 tick
```

**为什么不能复用 `status()`**(round-07 R-02):`_resolve_status`
(`runners/scrapyd.py:190-216`)在 **listjobs 成功、job 不在任何列表、且 job.log 不存在**
时同样返回 `unknown` —— 一个还在 `pending`、尚未产生日志的 job 被取消后正是这种情况。
若用 `status()` 做确认,它会被永远当成「不可达」等下去,超时后进入 `kill_pending`,
而后每个 tick 仍是 `unknown`,标记永不清除、延期清理永不执行。

因此为停止确认提供**独立的存活查询** `ScrapyRunner.is_job_alive(execution_id)`,
**不改动 `_resolve_status` 的终态推断语义**:

```
listjobs 抛 ScrapydError                     -> None   # 查询失败,不可知
job 在 running 或 pending 列表               -> True   # 确认还活着
listjobs 成功且两张表里都没有                 -> False  # 确认不在跑了
```

它只回答「还在不在跑」,不推断终态种类 —— 这同时绕开了另一个陷阱:`runner.stop()`
成功发出 TERM 后会 `mark_canceled`(`runners/scrapyd.py:148`),此后 `_resolve_status`
会把离开列表的 job 报成 `canceled`,那是我们自己造的,不是权威终态(round-02 R-02)。

#### 4.4 收尾语义严格按 `stop_intent` 分开(回应 round-02 R-02)

| intent | 收尾 |
|---|---|
| `cancel` | `mark_done(result="canceled")` + `emit_terminal(canceled)` —— 与今天一致,「取消是权威终态」不变 |
| `reclaim` | `mark_done(result="lost")`,**不 emit 任何事件**,execution 保持 lost —— 与今天 `commands.py:1029-1032` 一致。真实终态的覆盖只可能发生在 4.2 第 2 步(发信号之前),发信号之后一律不覆盖 |

**两条收尾路径都遵循同一个持久化次序**(round-06 R-02 / round-07 R-01):

```
store.mark_done(result=..., kill_pending=<见下>, terminal_pending=<cancel 时 True>)
emit(按上表;reclaim 不 emit)
clear_terminal_pending()          # 只有 emit 真正返回后才清
```

- **已确认进程退出**(4.3 第 5 步)→ `kill_pending=False`;若 `cleanup_pending` 为真
  则执行延期清理(见 4.5)。
- **到硬期限仍未确认**(4.3 第 3 步)→ 终态照样按上表报告(契约不退化),但
  `kill_pending=True`、**不清理**,转入 4.7 的回收待办继续追。

`reclaim` 不 emit 任何事件,故 `terminal_pending` 恒为假;`cancel` 的 `canceled` 是
必达契约,所以必须挂 `terminal_pending`,由 4.7 负责重启后补发。

#### 4.5 与日志清理链的冲突处理(回应 round-02 R-01 plan-blocker)

server 的 `finalize_drained_logs`(`reconcile.py:308-321`)在 **reclaim 已入队且
`log_drain_timeout_seconds`(默认 30s)过后**就会发 `cleanup_logs`;而本状态机的确认
期最长 120s。agent 的 `_handle_cleanup` 会直接 `self._store.delete(execution_id)`,
**停止状态机会被连根删掉,再没有 tick 能重试或升级 KILL**。

处理:把清理动作与命令解耦,并给它一个**独立于停止状态机的恢复入口**。

1. 抽出 `_do_cleanup(execution_id)`,内含今天 `_handle_cleanup` 的全部清理逻辑
   (删 job.log、删 workspace、`store.delete`、`_release_execution`)。它必须**幂等**:
   文件删除吞 `FileNotFoundError`、`rmtree(ignore_errors=True)`、`store.delete` 对
   不存在的 id 无副作用。
2. `_handle_cleanup` 改为:若该执行的**停止或回收尚未完成**,就持久置
   `cleanup_pending=True` 并**立即返回**(命令照常 ACK,意图已落盘,不依赖重投);
   否则照旧 `_do_cleanup`。判据是**两个**条件的并集(round-06 R-01):

   ```
   停止中:  phase == "started" and stop_requested_at is not None
   回收中:  kill_pending is True            # 已超时收尾、终态已报、进程还没死
   ```

   第二个条件不能漏:`cancel` 的 `cleanup_logs` **通常正是在终态报告之后才到达**
   (server 的 `finalize_drained_logs` 以 `finished_at` 起算 drain 窗口),那时 state
   已经是 `done` + `kill_pending=True`。若此时直接 `_do_cleanup`,就与第 5 条
   「`kill_pending` 期间禁止清理」自相矛盾;若只是跳过而不置 `cleanup_pending`,
   命令被 ACK 后就再没有人清理了。
3. `_stop_watchdog` 收尾后,若 `cleanup_pending` → 调 `_do_cleanup`;**清理抛异常时
   保留 `cleanup_pending`**,交给第 4 条的恢复入口重试。
4. **恢复入口(round-03 R-03)**:`mark_done` 与 `_do_cleanup` 是两步,中间进程退出、
   或 `_do_cleanup` 首次失败,都会留下 `phase == "done"` 且 `cleanup_pending == True`
   的残留;而 `reconcile_started_attempts` 今天只处理 `phase == "started"`,
   `cleanup_logs` 命令又早已 ACK —— 没有恢复入口就永远没人清。因此把 tick 的遍历改为:
   **先**把 `phase == "done"` 的 state 交给 4.7 的 `_reclaim_watchdog` 处理,**再**
   `continue` 跳过其余非 `started` 状态。该入口对「刚重启」「上次清理失败」「回收未完」
   是同一条路径,天然幂等。
5. **清理的前置条件**:`_do_cleanup` 会删掉 scrapyd job 映射,因此**只有在
   `kill_pending` 为假(即进程已确认退出)时才允许执行**。这是 round-05 R-01 的核心:
   先删映射再谈回收,等于亲手制造一个不可见的残留进程。
6. 若 `cleanup_logs` 在 stop **之前**到达(state 已被删除),后续 stop 走 4.2 第 0 步:
   `cancel` 仍上报权威 canceled,`reclaim` 幂等忽略。

#### 4.6 停止期间的命令重投必须让路给状态机(回应 round-04 R-01)

保留 `phase == "started"` 换来了跨 tick 推进,但也开了一个今天不存在的窗口:
`_handle_run` 对已存在的执行走 `republish_current`(`commands.py:670-673`),后者对
started 的 scrapy attempt **直接按 `runner.status` 上报终态**
(`redis/events.py:351-357`)。若 TERM 已生效、job 已离开列表、而 watchdog 还没收尾,
`_resolve_status` 会因 `mark_canceled` 返回 `canceled` —— 于是一次 run 重投就把
server 上的 `lost` 覆盖成了 `canceled`,绕过 4.4 的 intent 语义。

约束:**停止状态机激活期间(`stop_requested_at` 非空且 `phase == "started"`),
`republish_current` 不 emit 任何事件**,直接返回。

- 理由:终态的唯一出口是 4.4 的收尾入口,而 4.3 第 3 步的硬期限保证状态机在
  `stop_confirm_timeout_seconds`(默认 120s)内**必定**给出终态,server 不会悬着;
  重投期间多 emit 一次反而会抢在收尾之前给出错误语义。
- 这条约束对 `cancel` 与 `reclaim` **一视同仁**:`cancel` 的权威 `canceled` 由收尾
  发出(只是延后),`reclaim` 则始终不 emit、保持 lost。
- 不影响停止状态机之外的任何重投:未处于停止中的执行,`republish_current` 行为一字不变。

#### 4.7 回收待办:终态有界,回收不封顶(回应 round-05 R-01 plan-blocker)

本任务的目标之一就是**消除 dopilot 看不见的残留进程**。若在硬期限到点后直接
`mark_done` + 清理,就会删掉 `project` / `scrapyd_job_id` 映射,进程万一还活着便再没有
任何人能重试 —— 恰好把要消灭的问题又造了一遍。

所以把两条生命周期**拆开**:

| | 期限 | 行为 |
|---|---|---|
| **终态报告** | 有界(`stop_confirm_timeout_seconds`,默认 120s) | 到点必报,契约不退化:`cancel` 报 `canceled`,`reclaim` 保持 lost |
| **进程回收** | **不封顶** | 未确认退出就一直留着 `kill_pending` + job 映射,按节奏重试 KILL 直到确认 |

`_reclaim_watchdog(state)`——tick 里对 `phase == "done"` 的 state 执行:

```
0. if terminal_pending:                     # ← 最先做:终态必达优先于回收与清理
       重新 emit 已落盘的 result(events 的 outbox 保证 at-least-once)
       成功 -> clear_terminal_pending()
       失败 -> 保留标记,下一 tick 再补发
   # 这一步覆盖「mark_done 已落盘、但进程在进入 emit 之前就退出」的窗口:
   # 那时 event outbox 里什么都没有(emit 的 _persist 发生在 emit 内部,
   # redis/events.py:140-141),原 stop 命令又早已 ACK,没有它就永远补不上。

1. if kill_pending:
       is_job_alive()
         False (确认不在跑) -> kill_pending = False
                               若 cleanup_pending 且 terminal_pending 已清 -> _do_cleanup
         True  (仍在跑)     -> 距 kill_last_attempt_at >= kill_retry_interval_seconds
                               (默认 60)时重发一次 signal=KILL,更新 kill_last_attempt_at,
                               并记 WARNING(「execution X 的 scrapyd job Y 仍未退出」)
         None  (不可达)     -> 本 tick 不动,等 scrapyd 恢复
       return            # kill_pending 未清除前,绝不清理、绝不删 state
2. if cleanup_pending and not terminal_pending:
       _do_cleanup       # 失败保留标记,下一 tick 重试
```

⚠ 清理的前置条件是**三个**:`kill_pending` 已清(进程确认退出)、`terminal_pending`
已清(终态确认已交给 outbox)、`cleanup_pending` 为真。少一个都可能删掉还需要的
state —— 映射没了就没法回收,`result` 没了就补发不了终态。

- **重试不封顶**是刻意的:每 tick 一次 `listjobs`、每 60s 一次 KILL,成本极低,而代价
  (残留进程无人知晓)极高。WARNING 按重试节奏输出,既可检索又不刷屏。
- agent 重启后,`phase == "done" 且 kill_pending` 的 state 由本入口继续追;
  `phase == "started" 且 stop_requested_at 非空` 的 state 由 4.3 的状态机继续推进 ——
  **三个窗口(停止中 / 回收中 / 待清理)都有人管**。
- 新增配置 `kill_retry_interval_seconds`(默认 60)。

### 5. 通知与前端

- `TYPE_ATTEMPT_NO_PROGRESS = "attempt_no_progress"`,severity `warning`。
- payload:`task_id` / `execution_id` / `agent_id` / `log_bytes` / `idle_seconds` /
  `threshold` / `auto_stopped`(bool)。
- `notificationHref` 加 case,与 `log_flood` 同组落到 `/tasks/detail?id=<task_id>`。
- zh「执行长时间无进度」/ en「Execution made no progress」,正文带空转时长、阈值、
  日志字节数,并说明是否已自动停止。

### 6. 配置样例

`configs/server.example.toml` 补三个键并注明:调小 `no_progress_stall_seconds` 会误报;
`auto_stop_on_no_progress` 开启后会真的杀任务,务必先用告警观察一段时间再开。

## 测试用例

> agent 侧凡涉及 stop 的用例,一律用**真实 `ScrapyRunner` + 假 `ScrapydClient`**
> 驱动(round-02 R-02 明确要求),以便覆盖 `stop()` 成功后 `mark_canceled` 污染
> `_resolve_status` 的真实路径;不允许只 mock 抽象的 `status()` 返回值。

### A. server:进度语义(events)

| 编号 | 档位 | 前置条件 | 步骤 | 预期结果 | 证据形态 |
|---|---|---|---|---|---|
| TC-01 | A | running execution,`log_bytes=100` | 施加 `log_bytes=500` 的心跳 | `last_event_at`、`last_progress_sample_at`、`last_progress_at` 均推进;`log_bytes==500` | 命令 + 完整输出 + 退出码 |
| TC-02 | A | 同上(**关键反例**) | 施加 `log_bytes=100`(无增长)的心跳 | `last_event_at` **推进**、`stalled_at` 被清空(lost 判定不受影响)、`last_progress_sample_at` **推进**,但 `last_progress_at` **不变** | 命令 + 完整输出 + 退出码 |
| TC-03 | A | 同上(**读数缺失**) | 施加 `log_bytes=None` 的心跳 | `last_progress_sample_at` / `last_progress_at` / `log_bytes` 三者**都不变**;不报错 | 命令 + 完整输出 + 退出码 |
| TC-04 | A | 非心跳事件(`attempt.running`) | 施加该事件 | `last_progress_at` 推进,`no_progress_at` 被清空 | 命令 + 完整输出 + 退出码 |

### B. server:无进度检测(reconcile)

| 编号 | 档位 | 前置条件 | 步骤 | 预期结果 | 证据形态 |
|---|---|---|---|---|---|
| TC-05 | A | 心跳新鲜、采样新鲜、空转 > 阈值、`no_progress_at IS NULL` | 跑一次 reconcile | `report.no_progress == 1`;写入 1 条 `attempt_no_progress` 通知;`no_progress_at` 置上;**execution 仍 active、未判 lost、无 stop outbox** | 命令 + 完整输出 + 退出码 |
| TC-06 | A | 紧接 TC-05(**去重**) | 再跑两次 reconcile | 通知仍 1 行,`report.no_progress == 0`,`no_progress_at` 不变 | 命令 + 完整输出 + 退出码 |
| TC-07 | A | 紧接 TC-05,**把通知标记为已读**,再施加一次无增长心跳(round-01 R-02 的精确场景) | 再跑 reconcile | **仍不新增通知行**(去重不依赖通知已读状态,靠 `no_progress_at`);`stalled_at` 被心跳清空也不影响 | 命令 + 完整输出 + 退出码 |
| TC-08 | A | 空转在阈值内(**反例**) | 跑 reconcile | 不计数、不发通知 | 命令 + 完整输出 + 退出码 |
| TC-09 | A | **round-01 R-01 完整序列**:先有有效读数 → 持续 `log_bytes=None` 心跳直到超过 `sample_max_age` → 空转已超阈值 | 跑 reconcile(分别在 `auto_stop=False` 与 `True` 下) | **不计数、不发通知**(采样已失效,无权判定);`auto_stop=True` 时**也不产生 stop outbox**(不误杀) | 命令 + 完整输出 + 退出码 |
| TC-10 | A | 紧接 TC-09,**读数恢复**(带 `log_bytes` 且有增长的心跳),随后再次空转超阈值 | 跑 reconcile | 恢复后重新计时:先不告警;新的空转超阈值后再告警一次 | 命令 + 完整输出 + 退出码 |
| TC-11 | A | `no_progress_stall_seconds = 0` | 跑 reconcile(即使空转很久) | 不计数、不发通知 | 命令 + 完整输出 + 退出码 |
| TC-12 | A | `auto_stop_on_no_progress = False`(**默认值**) | reconcile 命中 | **不产生任何 stop outbox** | 命令 + 完整输出 + 退出码 |
| TC-13 | A | `auto_stop_on_no_progress = True` | reconcile 命中,再跑两次 reconcile,其间插入一次无增长心跳(清空 `stalled_at`) | 只产生 **1 条** `intent=cancel` 的 stop outbox(round-01 R-03);通知 payload `auto_stopped` 为真 | 命令 + 完整输出 + 退出码 |

### C. agent:日志采样与心跳载荷(回应 round-02 R-04)

| 编号 | 档位 | 前置条件 | 步骤 | 预期结果 | 证据形态 |
|---|---|---|---|---|---|
| TC-14 | A | `max_job_log_bytes > 0`(保护开启),job.log 可读 | 跑一次 tick | 发出的心跳事件 `log_bytes` == 文件实际大小 | 命令 + 完整输出 + 退出码 |
| TC-15 | A | **`max_job_log_bytes = 0`(保护关闭)**,job.log 可读 | 跑一次 tick | 心跳**仍带**正确的 `log_bytes`(证明采样与 flood 开关解耦);flood 逻辑未被触发 | 命令 + 完整输出 + 退出码 |
| TC-16 | A | job.log 不存在 / 读取抛错(**边界**) | 跑一次 tick | 心跳带 `log_bytes=None`,tick 不抛异常,其余流程照常 | 命令 + 完整输出 + 退出码 |

### D. agent:stop 状态机

| 编号 | 档位 | 前置条件 | 步骤 | 预期结果 | 证据形态 |
|---|---|---|---|---|---|
| TC-17 | A | 假 scrapyd:TERM 后仍列 running,KILL 后消失 | 下发 cancel,再连续跑 tick | `_handle_stop` **立即返回**且此时 job 仍在列表(未阻塞等待);`stop_requested_at` 已落盘;后续 tick 到期发一次 `signal=KILL`;确认消失后 emit `canceled` **恰一次** | 命令 + 完整输出 + 退出码 |
| TC-18 | A | TERM 后 job 立即消失(**不该升级**) | 下发 cancel + 跑 tick | **只有一次**不带 signal 的 cancel,**不发 KILL**;emit `canceled` | 命令 + 完整输出 + 退出码 |
| TC-19 | A | KILL 后仍不消失(**最坏路径**) | 跑 tick 直到超过 `stop_confirm_timeout_seconds` | 仍 emit `canceled`(权威语义不倒退),并记录 WARNING 说明 job 仍在列表 | 命令 + 完整输出 + 退出码 |
| TC-20 | A | **round-01 R-04**:N 条 stop 命令与若干正常执行同批 | 跑一次 `drain_once` + 一次 tick | 正常执行的心跳**仍在这一轮发出**、flood watchdog 仍被调用;`drain_once` 期间对 scrapyd 的 `listjobs` 调用次数**不随停止等待时长增长** | 命令 + 完整输出 + 退出码 |
| TC-21 | A | **round-02 R-03**:首次 TERM 返回 `cancel_failed` | 下发 cancel,跑若干 tick | `stop_requested_at` 仍已落盘(意图不丢),`stop_escalation` 保持 `None`;下一 tick 重试 TERM 并成功后才置 `"term"` | 命令 + 完整输出 + 退出码 |
| TC-22 | A | **round-02 R-03**:首次 TERM **抛异常** | 下发 cancel(handler 内异常被 `_process` 吞掉并 XACK),跑若干 tick | 停止请求**不丢失**:watchdog 据已落盘的意图继续推进直至收尾 | 命令 + 完整输出 + 退出码 |
| TC-23 | A | **round-02 R-03**:意图落盘后、TERM 发出前「重启」(丢弃内存态,用同一 state 目录重建 agent) | 重建后跑 tick | 状态机从 state 文件恢复并继续发 TERM→KILL→确认 | 命令 + 完整输出 + 退出码 |
| TC-24 | A | **round-02 R-02**:`intent=reclaim`,job 仍在运行;用真实 `ScrapyRunner`,TERM 发出后 `mark_canceled` 生效、job 随后离开列表(于是 `_resolve_status` 会报 `canceled`) | 下发 reclaim + 跑 tick 至确认 | 收尾为 `mark_done(result="lost")`,**不 emit 任何事件**,execution 保持 lost —— 不得把自己造的 `canceled` 当权威终态上报 | 命令 + 完整输出 + 退出码 |
| TC-25 | A | **round-02 R-02**:`intent=reclaim`,**发信号之前**就已存在真实终态 | 下发 reclaim | 直接走 `_finish_scrapy_attempt` 覆盖上报,**不发任何信号**、不进入状态机 | 命令 + 完整输出 + 退出码 |
| TC-26 | A | **round-02 R-01 plan-blocker**:reclaim 已入队,`cleanup_logs` 在停止确认完成**之前**到达 | 下发 reclaim → 下发 cleanup → 继续跑 tick | cleanup **不立即删除 state**(置 `cleanup_pending`),状态机仍能升级 KILL 并确认;收尾后才真正执行清理(job.log / workspace / state 均被删) | 命令 + 完整输出 + 退出码 |
| TC-27 | A | **round-03 R-01**:`cleanup_logs` 先到(state 已删),随后 `intent=cancel` 的 stop 到达;以及「尚未启动就被取消」的执行(从来没有 state) | 下发 cancel | **仍 emit 权威 `attempt.canceled`**(`docs/architecture/03-execution-and-logs.md:28` 的必达契约),不进入状态机、不抛异常 | 命令 + 完整输出 + 退出码 |
| TC-28 | A | 同上但 `intent=reclaim`,state 已删 | 下发 reclaim | 幂等忽略,**不 emit 任何事件** | 命令 + 完整输出 + 退出码 |
| TC-29 | A | **round-02 R-05**:stop 期间 scrapyd 短暂不可达(`status` 返回 `unknown`),随后恢复 | 跑若干 tick | `unknown` 既不被当作「已消失」收尾,也不推进 escalation;恢复后正常继续直至确认 | 命令 + 完整输出 + 退出码 |
| TC-30 | A | **round-03 R-02 + round-06 R-03**:scrapyd **持续** `unknown` 直到超过 `stop_confirm_timeout_seconds`,且此前已置 `cleanup_pending`;分别跑 `cancel` 与 `reclaim` | 跑 tick 直到超期限,再继续跑若干 tick 保持 `unknown`;最后让 scrapyd 恢复且 job 已退出 | 硬期限分支先于 `unknown` 生效:`cancel` emit `canceled`、`reclaim` 保持 lost 不 emit;**但两种 intent 下都保留 state、scrapyd job 映射与 `cleanup_pending`,`kill_pending` 置真,持续 `unknown` 期间绝不清理**;直到恢复并确认退出后,`kill_pending` 清除、延期清理这时才执行 | 命令 + 完整输出 + 退出码 |
| TC-31 | A | **round-03 R-03**:收尾 `mark_done` 之后、`_do_cleanup` 之前「重启」(丢内存态,用同一 state 目录重建 agent),残留 `phase=done` + `cleanup_pending=True` | 重建后跑 tick | 恢复入口对该 state 执行清理:job.log / workspace / state 全部删除;该入口幂等,重复跑不报错 | 命令 + 完整输出 + 退出码 |
| TC-32 | A | **round-03 R-03**:`_do_cleanup` 首次抛异常 | 跑 tick(第一次失败)→ 再跑 tick(第二次正常) | 第一次失败后 **`cleanup_pending` 保留**、不吞掉;第二次由恢复入口重试并成功清理 | 命令 + 完整输出 + 退出码 |
| TC-36 | A | **round-04 R-01**:`intent=reclaim`,TERM 已成功、job 已离开列表,但 watchdog **尚未收尾**;此时 run 命令重投(真实 `ScrapyRunner`,`mark_canceled` 已生效故 `status` 会返回 `canceled`) | 下发 run 重投,再继续跑 tick 至收尾 | 重投**不 emit 任何事件**(尤其不得 emit `canceled`),server 侧保持 lost;随后由状态机收尾为 `mark_done("lost")`,且挂起的延期清理仍正常完成 | 命令 + 完整输出 + 退出码 |
| TC-37 | A | **round-05 R-01 plan-blocker**:进程在 KILL 后**仍然存活**,一路撑过 `stop_confirm_timeout_seconds`(`intent=cancel`,且此前已置 `cleanup_pending`) | 跑 tick 至超期限,再继续跑若干 tick | 到点**照常 emit `canceled`**(契约不退化),但 `kill_pending` 被置真、**state 与 scrapyd job 映射都保留、延期清理不执行**;后续 tick 按 `kill_retry_interval_seconds` 重发 KILL 并记 WARNING | 命令 + 完整输出 + 退出码 |
| TC-38 | A | 紧接 TC-37:scrapyd 先返回 `unknown` 一段时间,之后恢复且 job 已退出 | 继续跑 tick | `unknown` 期间不误判、不清理;恢复后确认退出 → `kill_pending` 清除 → **挂起的延期清理这时才执行**(job.log / workspace / state 全删) | 命令 + 完整输出 + 退出码 |
| TC-39 | A | 同 TC-37 但 `intent=reclaim` | 跑 tick 至超期限并继续 | 保持 lost、**不 emit 任何事件**;`kill_pending` 同样置真并持续回收,确认退出后才清理 | 命令 + 完整输出 + 退出码 |
| TC-40 | A | **round-05 R-02**:执行本地自然结束、已被 `reconcile_started_attempts` 标为 `phase=done`,`cleanup_logs` 尚未到达,此时收到 `intent=cancel` 的 stop | 下发 cancel | **仍 emit 权威 `canceled`**(终态必达),且**不把 `phase` 改回 `started`**、不进入状态机、不重新激活执行 | 命令 + 完整输出 + 退出码 |
| TC-41 | A | 同上但 `intent=reclaim`,且 state 记录了真实终态 | 下发 reclaim | re-emit 该真实终态;无真实终态时忽略;两种情况都不重新激活执行 | 命令 + 完整输出 + 退出码 |
| TC-42 | A | **round-06 R-01**:先超时收尾(state = `done` + `kill_pending=True`,此前**没有**置过 `cleanup_pending`),**之后**才首次收到 `cleanup_logs` —— 即 cancel 的正常路径 | 下发 cleanup,继续跑 tick;最后让 job 真正退出 | cleanup **不立即执行**而是置 `cleanup_pending=True` 并返回(命令照常 ACK);`kill_pending` 期间始终不清理、不删映射;确认退出后才执行清理并删 state | 命令 + 完整输出 + 退出码 |
| TC-43 | A | **round-06 R-02 + round-07 R-01**:在硬期限收尾处注入故障,使 `mark_done` 写入之后、**进入 `emit` 之前**进程退出(此时 event outbox 为空、原 stop 命令已 ACK);随后用同一 state 目录重建 agent | 重建后跑 tick,**不重投任何命令** | 落盘 state 必须是 `done` + `result` + `kill_pending=True` + `terminal_pending=True` **同时存在**(证明一次原子写入);恢复后 4.7 第 0 步**补发 `canceled` 并最终送达 server**,再继续重试 KILL、确认退出、执行清理;全过程不会因 `kill_pending=False` 而误删映射 | 命令 + 完整输出 + 退出码 |
| TC-44 | A | **round-07 R-02**:真实 `ScrapyRunner` + 假 `ScrapydClient`,一个仍处 `pending`、**尚未生成 job.log** 的 job 被 cancel,随后从 listjobs 的两张表里消失(此时 `_resolve_status` 会返回 `unknown`) | 下发 cancel,跑 tick | `is_job_alive` 返回 `False`(listjobs 成功且两表皆无)→ **正常确认退出并收尾**,不因 `status()` 的 `unknown` 而空等到超时;延期清理正常完成 | 命令 + 完整输出 + 退出码 |
| TC-45 | A | 同上但 `listjobs` 抛 `ScrapydError`(**真正不可达**) | 跑 tick | `is_job_alive` 返回 `None` → 保留 state、映射与所有挂起标记,绝不当作已退出;scrapyd 恢复后才继续 | 命令 + 完整输出 + 退出码 |

### E. 前端与回归

| 编号 | 档位 | 前置条件 | 步骤 | 预期结果 | 证据形态 |
|---|---|---|---|---|---|
| TC-33 | A | web 单测 | 渲染一条 `attempt_no_progress` 通知 | 标题/正文按 i18n 渲染(含空转时长与阈值);点击落到 `/tasks/detail?id=<task_id>` | 命令 + 完整输出 + 退出码 |
| TC-34 | A | 迁移 | 对空库 `alembic upgrade head` 再 `downgrade -1` | 升级后三个新列存在,降级后消失,均无报错 | 命令 + 完整输出 + 退出码 |
| TC-35 | A | 仓库工作区 | `ruff check apps packages`、`pytest`、`pnpm -C apps/web test` | 全部通过,无新增告警 | 命令 + 完整输出 + 退出码 |

C 档 0 条(全部可由非交互命令判定)。异常/边界路径:TC-02、TC-03、TC-06~TC-12、
TC-15、TC-16、TC-18、TC-19、TC-21~TC-32、TC-36~TC-45。

## 风险与回滚

- **误报**:正常但长时间静默的任务会收到通知。默认 1800s 明显宽于已知最长的正常
  轮次;嫌吵可调大或设 0 关闭。默认不自动停止,误报代价上限是一条通知。
- **误杀**:本方案**不引入任何新的自动终止路径**(`auto_stop_on_no_progress` 默认
  False);`lost`/reclaim 链一行未改;采样失效时连告警都不发(TC-09 钉死)。
- **心跳语义连锁**:`last_event_at` 刷新逻辑不变,`heartbeat_timeout` /
  `event_stall` / `lost_after_stalled_seconds` 行为不变;TC-02 专门钉死。
- **stop 状态机的时延**:取消从「发一枪就走」变为最多
  `stop_confirm_timeout_seconds`(默认 120s)确认。取消本就是异步 outbox 命令,不阻塞
  API;且状态机跨 tick 推进,不占用命令消费者(TC-17 钉死)。代价是任务在 UI 上停留
  在 running 的时间可能多几十秒——这是「确认尸体」的必要成本。
- **日志清理被推迟**:停止确认期间到达的 `cleanup_logs` 会被挂起(`cleanup_pending`),
  要等到**进程确认退出**之后才真正删 job.log / workspace。正常路径下这最多是
  `stop_confirm_timeout_seconds`(默认 120s);**进程杀不掉时会推迟更久** —— 这是
  刻意的取舍:宁可晚点回收磁盘,也不能删掉 job 映射后留下无人追踪的残留进程
  (round-05 R-01)。回收本身不封顶、按 `kill_retry_interval_seconds` 持续重试并记
  WARNING,可检索、可人工介入(TC-37~TC-39 钉死)。agent 重启也能从 state 文件恢复
  继续推进(TC-23、TC-31)。
- **新增 state 字段的向后兼容**:`AttemptState` 的四个新字段都有默认值,旧 state 文件
  照常加载(与 `log_flood_*` 当初的加法一致)。
- **迁移**:三个 nullable 列,无回填、无索引,`downgrade` 直接 drop。
- **回滚**:`git revert` 单个提交;新列留着不影响旧代码(nullable)。
