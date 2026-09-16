# dopilot 侧与本次问题相关的代码事实

2026-09-15 在 steammarket-spider 会话里只读阅读 dopilot 源码(HEAD `139bd1e`)得出。标「亲核」的是我逐行读过原文的;标「子代理」的来自
同会话一个只读 Explore 子代理的报告,给了 file:line 但我未逐行复核 —— 讨论改修前请以源码为准再核一遍。

## 1. 没有单任务运行时长上限(亲核)

`apps/server/dopilot_server/config/settings.py:144-150`:

```python
heartbeat_timeout_seconds: int = 30
stalled_attempt_seconds: int = 300
# With per-attempt heartbeats (~60s while confirmed alive) a healthy attempt
# never idles anywhere near this; it now bounds "agent online but liveness
# unconfirmable" before reclaim, so it errs toward not killing healthy work
# (900 used to act as a hard task-runtime cap for pre-heartbeat agents).
lost_after_stalled_seconds: int = 3600
```

即:以前 900 秒曾充当事实上的运行上限;引入 attempt 心跳后,只有「心跳也确认不了存活」才会 reclaim,正常心跳的任务永不超时。
子代理补充:`ExecutionTemplate` / `Schedule` 模型没有超时字段(`apps/server/dopilot_server/models/scheduling.py:49-90, 113-170`);
`unreachable_lost_seconds=120`(settings.py:193)声明并加载但无人读取。

## 2. 心跳按 scrapyd 列表续命,卡死进程永远占着并发槽(子代理)

- agent 在 scrapyd `listjobs` 仍把 job 列为 running 时,约每 60 秒发一次 `attempt.heartbeat`
  (`apps/agent/dopilot_agent/redis/commands.py:323-329`,agent `config/settings.py:42` `attempt_heartbeat_interval_seconds = 60`,亲核);
  服务端每次心跳重置空闲计时(`apps/server/dopilot_server/services/events.py:198-207`)。
- 事件停滞判 lost 需要空闲 ≥ 3600 s(`apps/server/dopilot_server/redis/reconcile.py:175-198`)—— 有心跳就永远到不了。
- 心跳反映的是「scrapyd 列表里还有这个 job」,不是进程是否在干活:本次进程在 Scrapy 关闭阶段卡住、没有任何日志输出,仍被视为健康。

## 3. 按调度并发闸跳过后续触发(子代理;与 steammarket 侧记忆一致)

`apps/server/dopilot_server/services/schedules.py:420-438` `acquire_firing_slot` 统计该调度 queued / running / finalizing 的任务数
(`TASK_ACTIVE`,`services/states.py:44`),达上限时定时触发记「timer firing skipped: concurrency」并跳过(`schedules.py:506-514`),
手动 trigger-now 返回 409(`schedules.py:425-432`)。SWAPGG 730 的 max_concurrency 为 1 ⇒ 03:40 之后每次触发都被跳过。

## 4. 取消只发 TERM,并立即标 canceled、释放槽位(亲核)

`apps/agent/dopilot_agent/redis/commands.py:1000-1016`:

```python
if cmd.intent == StopIntent.cancel:
    if is_wheel:
        # SIGTERM -> 10s -> SIGKILL the process group, then authoritative
        # canceled regardless of the child's exit code.
        ...
    # scrapy (or missing state) -> authoritative canceled as before.
    await self._runner.stop(cmd.execution_id, cmd.task_id)
    self._store.mark_done(cmd.execution_id, result="canceled")
    await self._events.emit_terminal(cmd.task_id, cmd.execution_id, AgentEventType.canceled)
    return
```

`apps/agent/dopilot_agent/scrapyd/client.py:137-148`:`cancel()` 只在传了 `signal` 时才带 `signal` 字段,docstring 写明
「TERM by default on scrapyd's side; the log-flood watchdog escalates to KILL」—— 取消路径没传,所以是 TERM。

含义:scrapy 任务取消 = 一次 TERM + 立刻判 canceled + 槽位释放,**不确认进程是否退出、不升级 KILL**(wheel runner 才有 TERM→10s→SIGKILL)。
本次这种卡在关闭阶段的进程多半不响应 TERM(见 `twisted-threadpool-join.txt`),取消后会变成 dopilot 看不见的残留进程,需要人工 `kill -9`
或直接对 scrapyd `cancel.json` 发 `signal=KILL`。子代理补充:取消入口为 Web 任务详情页的 Cancel 按钮
(`apps/web/app/(app)/tasks/detail/page.tsx:112-129,188`)与 `POST /api/v1/tasks/{task_id}/cancel`(`api/v1/tasks.py:177-194`);另有
`POST /api/v1/tasks/{task_id}/mark-lost`(`tasks.py:197-213`),同样只触发一次默认 TERM 的 reclaim。

## 5. 已有的「会升级到 KILL」的机制只针对日志刷屏(子代理)

日志刷屏看门狗(`apps/agent/dopilot_agent/redis/commands.py:426-484`):job.log 达到 `max_job_log_bytes`(32 MiB)时 TERM,30 s 后
`signal=KILL`,60 s 后按 PID SIGKILL(agent `config/settings.py:62-66`)。本次进程**没有日志输出**,不会触发。
