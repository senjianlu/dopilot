---
task: no-progress-stall-detection
round: 01
date: 2026-09-16
---

# 实现记录:第 01 轮

## 本轮改动

实际触及 **25 个文件**(19 改 + 6 新增),plan 预计约 22,多出的是三个测试文件
拆分(见「与方案的偏差」1)。

### 协议

| 文件 | 改动摘要 |
|---|---|
| `packages/protocol/dopilot_protocol/streams.py` | `AgentEventType.heartbeat` 的 docstring 写明它可携带 `log_bytes`:存活与进度是两个问题,「采不到」(`None`)不等于「没进度」。`AgentEvent.log_bytes` 字段本就存在,无需加字段 |

### agent

| 文件 | 改动摘要 |
|---|---|
| `state/store.py` | `AttemptState` 新增 `stop_intent` / `stop_requested_at` / `stop_escalation` / `cleanup_pending` / `kill_pending` / `kill_last_attempt_at` / `terminal_pending`(均有默认值,旧 state 文件照常加载);`mark_done` 增加 `kill_pending` / `terminal_pending` 参数使三者成为**一次原子写入**;新增 `mark_stop_requested` / `mark_stop_escalation` / `mark_cleanup_pending` / `mark_kill_attempt` / `clear_kill_pending` / `clear_terminal_pending` |
| `runners/scrapyd.py` | 新增 `is_job_alive()`:只答「还在不在跑」,`True`/`False`/`None`(不可达)三态,不推断终态种类 |
| `redis/events.py` | `emit_heartbeat(..., log_bytes=None)`;`republish_current` 在停止状态机激活期间(`phase=="started"` 且 `stop_requested_at`)**不发任何事件** |
| `redis/commands.py` | 新增 `_sample_log_size`(与 flood 开关解耦)并把读数同时喂给 `_flood_watchdog` 与心跳;`_handle_stop` 改为只落盘意图 + 一次尽力 TERM;新增 `_begin_stop` / `_send_stop_signal` / `_stop_watchdog` / `_finalize_stop` / `_reclaim_watchdog` / `_run_deferred_cleanup`;`_handle_cleanup` 拆出 `_do_cleanup` 并在停止/回收未完成时改置 `cleanup_pending`;tick 遍历改为把 `phase != "started"` 的 state 交给 `_reclaim_watchdog` |
| `config/settings.py` | `stop_kill_after_seconds`(10)、`stop_confirm_timeout_seconds`(120)、`kill_retry_interval_seconds`(60) |
| `main.py` | 把三个新配置接到 `CommandConsumer` |

### server

| 文件 | 改动摘要 |
|---|---|
| `models/execution.py` | 新增 `last_progress_at` / `last_progress_sample_at` / `no_progress_at` |
| `migrations/versions/0015_execution_progress_tracking.py` | **新增**,三个 nullable 列,无回填无索引 |
| `services/events.py` | 心跳分支:带读数则推进 `last_progress_sample_at`,读数**增长**才推进 `last_progress_at` 并清 `no_progress_at`;`log_bytes is None` 时三者全不动。非心跳事件经新的 `_mark_progress` 推进进度并清标记。`last_event_at` / `stalled_at` 的既有行为**一字未改** |
| `redis/reconcile.py` | `ReconcileReport` 加 `no_progress` 计数;`reconcile_once` 在既有两步之后加第 3 步,调用新的 `_check_no_progress` |
| `config/settings.py` | `no_progress_stall_seconds`(1800,0=关)、`no_progress_sample_max_age_seconds`(300)、`auto_stop_on_no_progress`(**False**) |
| `models/notification.py` | `TYPE_ATTEMPT_NO_PROGRESS` |

### 配置、前端、文档

| 文件 | 改动摘要 |
|---|---|
| `configs/server.example.toml` | 三个新键 + 风险注释(阈值调窄会误报;自动停止先用告警观察) |
| `apps/web/components/layout/notification-bell.tsx` | 新类型落到 `/tasks/detail?id=`;`render` 支持 payload 的 `auto_stopped` → i18next context |
| `apps/web/lib/i18n/locales/{zh,en}.ts` | `attempt_no_progress` 的 `title` / `body` / `body_stopped` |
| `docs/architecture/03-execution-and-logs.md` | 回写取消时序(`canceled` 仍必达但改为确认后上报)、心跳携带 `log_bytes`、无进度探测、停止状态机、「终态有界 / 回收不封顶」 |

### 测试

| 文件 | 改动摘要 |
|---|---|
| `apps/server/tests/test_event_progress.py` | **新增**,TC-01~04 |
| `apps/server/tests/test_reconcile_no_progress.py` | **新增**,TC-05~13 |
| `apps/server/tests/test_migration_0015_pg.py` | **新增**,TC-34 |
| `apps/agent/tests/test_heartbeat_progress.py` | **新增**,TC-14~16 |
| `apps/agent/tests/test_stop_state_machine.py` | **新增**,TC-17~32、36~45 |
| `apps/agent/tests/test_command_consumer.py` | 三条既有 stop 用例适配跨 tick 收尾(见偏差 3) |
| `apps/web/components/layout/__tests__/notification-bell.test.tsx` | TC-33 |

## 修复对照

不适用(第 1 轮)。

## 测试结果

全部 A 档。python 证据 `evidence/python-tests.txt`(`pytest -v`,841 passed /
1 skipped / exit=0,含 PG 用例);web 证据 `evidence/web-tests.txt`(TAP,
`1..129`,exit=0);回归证据 `evidence/lint-typecheck.txt`。

| 编号 | 档位 | 结果 | 证据(用例名,见 `evidence/python-tests.txt` / `web-tests.txt`) |
|---|---|---|---|
| TC-01 | A | pass | `test_event_progress.py::test_growing_log_advances_both_clocks` |
| TC-02 | A | pass | `test_event_progress.py::test_flat_log_keeps_liveness_but_not_progress` |
| TC-03 | A | pass | `test_event_progress.py::test_missing_reading_freezes_nothing` |
| TC-04 | A | pass | `test_event_progress.py::test_lifecycle_event_counts_as_progress` |
| TC-05 | A | pass | `test_reconcile_no_progress.py::test_alerts_once_without_touching_the_execution` |
| TC-06 | A | pass | `…::test_repeated_passes_do_not_re_alert` |
| TC-07 | A | pass | `…::test_reading_the_alert_does_not_unlatch_it` |
| TC-08 | A | pass | `…::test_idle_below_threshold_is_quiet` |
| TC-09 | A | pass | `…::test_stale_sample_is_never_judged`(同时断言 `auto_stop=True` 下无 stop outbox) |
| TC-10 | A | pass | `…::test_recovered_sample_restarts_the_clock` |
| TC-11 | A | pass | `…::test_zero_threshold_disables_the_feature` |
| TC-12 | A | pass | `…::test_auto_stop_off_by_default_only_notifies` |
| TC-13 | A | pass | `…::test_auto_stop_enqueues_exactly_one_cancel` |
| TC-14 | A | pass | `test_heartbeat_progress.py::test_heartbeat_reports_the_log_size` |
| TC-15 | A | pass | `…::test_sampling_survives_a_disabled_log_cap` |
| TC-16 | A | pass | `…::test_unreadable_log_reports_no_reading_at_all` |
| TC-17 | A | pass | `test_stop_state_machine.py::test_cancel_escalates_to_kill_then_confirms` |
| TC-18 | A | pass | `…::test_cancel_that_dies_on_term_never_sends_kill` |
| TC-19 | A | pass | `…::test_deadline_reports_terminal_but_keeps_reclaiming` |
| TC-20 | A | pass | `…::test_a_batch_of_stops_does_not_starve_other_executions` |
| TC-21 | A | pass | `…::test_first_term_failure_keeps_the_intent_and_retries` |
| TC-22 | A | pass | 同上(`fail_cancel_times` 令 TERM 抛 `httpx.ConnectError`,handler 内被吞并 XACK) |
| TC-23 | A | pass | `…::test_intent_persisted_before_term_survives_a_restart` |
| TC-24 | A | pass | `…::test_reclaim_stays_lost_even_when_status_says_canceled` |
| TC-25 | A | pass | `…::test_reclaim_with_a_real_terminal_overrides_without_signalling` |
| TC-26 | A | pass | `…::test_cleanup_during_stop_is_deferred_not_dropped` |
| TC-27 | A | pass | `…::test_cancel_without_state_still_reports_canceled` |
| TC-28 | A | pass | `…::test_reclaim_without_state_is_ignored` |
| TC-29 | A | pass | `…::test_unreachable_scrapyd_neither_confirms_nor_escalates` |
| TC-30 | A | pass | `…::test_persistent_unknown_still_hits_the_deadline` |
| TC-31 | A | pass | `…::test_deferred_cleanup_is_retried_until_it_succeeds`(恢复入口对「重启后」「上次失败」是同一条路径) |
| TC-32 | A | pass | 同上(`store.delete` 首次抛 `OSError`,`cleanup_pending` 保留并在下一 tick 重试成功) |
| TC-33 | A | pass | `notification-bell.test.tsx::tells a stalled attempt apart from one it also stopped` + `maps notification types onto existing static routes` |
| TC-34 | A | pass | `test_migration_0015_pg.py::test_migration_0015_adds_and_drops_progress_columns` |
| TC-35 | A | pass | `evidence/lint-typecheck.txt`(ruff / eslint / tsc 三项 exit=0)+ `python-tests.txt` + `web-tests.txt` |
| TC-36 | A | pass | `…::test_run_redelivery_during_a_stop_stays_silent` |
| TC-37 | A | pass | `…::test_deadline_reports_terminal_but_keeps_reclaiming`(断言 `kill_pending=True`、映射保留、KILL 按间隔重发) |
| TC-38 | A | pass | `…::test_persistent_unknown_still_hits_the_deadline`(后半段:恢复并确认退出后才执行延期清理) |
| TC-39 | A | pass | `…::test_reclaim_stays_lost_even_when_status_says_canceled` |
| TC-40 | A | pass | `…::test_cancel_on_a_finished_attempt_reports_without_reviving_it` |
| TC-41 | A | pass | `…::test_reclaim_on_a_finished_attempt_reemits_without_reviving_it` |
| TC-42 | A | pass | `…::test_cleanup_after_terminal_is_deferred_until_the_process_dies` |
| TC-43 | A | pass | `…::test_terminal_persisted_but_unsent_is_republished_after_restart` |
| TC-44 | A | pass | `…::test_pending_job_without_a_log_is_confirmed_not_stranded`(用真实 `ScrapyRunner`,并显式断言 `status()` 返回 `unknown` 而 `is_job_alive()` 返回 `False`) |
| TC-45 | A | pass | `…::test_unreachable_scrapyd_neither_confirms_nor_escalates` |

C 档 0 条,blocked 0 条。

## 与方案的偏差

1. **测试文件数比 plan 预计多**。plan 写 agent 2 个 / server 2 个;实际 agent 2 个
   (`test_heartbeat_progress.py`、`test_stop_state_machine.py`)、server 3 个
   (多出 `test_migration_0015_pg.py` 承载 TC-34 的真实 Alembic 升降级),外加既有
   `test_command_consumer.py` 的适配。总文件数 25 而非约 22。影响:仅测试。

2. **`_stop_watchdog` 的步骤顺序与 plan §4.3 相反:先探存活,再补发/升级信号。**
   plan 写的是「先补发或升级信号,再判是否已退出」。按那个顺序,一个 TERM 之后就已
   退出、但还没被观察到的 job,会在下一 tick 先挨一发多余的 KILL —— 而 plan 自己的
   TC-18 明确要求「TERM 后 job 立即消失时**只有一次**不带 signal 的 cancel,不发
   KILL」。两者不能同时成立,实现取了与验收一致、且语义更直观的那个:
   ```
   3. 硬期限(仍然最先判,覆盖 unknown / 信号失败 / 一直 running)
   4. is_job_alive():False -> 收尾;None -> 本 tick 到此为止;True -> 继续
   5. 补发 TERM 或升级 KILL
   ```
   硬期限仍在最前,round-03 R-02 要解决的问题不受影响。副作用:发出信号的那一 tick
   不会同时确认退出,确认落到下一 tick(测试已按此断言)。

3. **三条既有 agent 用例需要适配**(`test_stop_cancel_clears_heartbeat_stamp`、
   `test_stop_cancel_after_running_emits_canceled`、
   `test_stop_reclaim_running_kills_stays_lost`):它们原本在 `drain_once` 之后
   立刻断言终态,而停止已改为跨 tick,故各加一次
   `reconcile_started_attempts()`。这不是预期结果的改写——终态、事件类型、
   `result` 全部按原样断言,只是多推进一个 tick。

4. **`_cleanup_must_wait` 比 plan §4.5 第 2 条多一个条件 `terminal_pending`**。
   plan 那一条只列了「停止中」与 `kill_pending`;但 §4.7 的清理前置条件写了三条
   (进程已退出、终态已交付、有清理请求),二者不一致。实现按 §4.7 的三条为准:
   终态还没进 `emit` 时清理会把 `result` 一起删掉,那条 `canceled` 就再也补发不出来。

5. **未给三个新 server 配置加环境变量覆盖**。`loader.py` 有一张
   `DOPILOT_*` 白名单,同段的 `stalled_attempt_seconds` 等都在其中。plan 没要求,
   为守住范围没有顺手加;运维改 TOML 即可,`configs/server.example.toml` 已写明。

以上 5 条都是实现层细节,未触及方案的架构、接口或范围(进度与存活分离、lost/reclaim
链一行不改、自动停止默认关闭、终态有界而回收不封顶),故未中断实现向用户请示。
