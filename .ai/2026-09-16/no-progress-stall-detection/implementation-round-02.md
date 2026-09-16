---
task: no-progress-stall-detection
round: 02
date: 2026-09-16
---

# 实现记录:第 02 轮

修第 01 轮评审的 1 个 blocker + 2 个 major。两个 major 都是真缺陷(已改实现),
blocker 是我用较窄的测试声明了较宽的 plan 用例(已补齐)。

## 本轮改动

| 文件 | 改动摘要 |
|---|---|
| `apps/agent/dopilot_agent/redis/commands.py` | reclaim 分支在**读 status 之前**加 `stop_requested_at` 幂等检查(R-01) |
| `apps/server/dopilot_server/redis/reconcile.py` | 判 lost 的分支加 `continue`;`_check_no_progress` 另加 `status not in EXEC_ACTIVE` 的双保险(R-02) |
| `apps/server/tests/test_reconcile_no_progress.py` | 改为用**真实 `apply_event` 心跳**驱动全部时钟变化;TC-09 覆盖 `auto_stop` 两种取值;新增 R-02 的窗口重叠回归 |
| `apps/agent/tests/test_stop_state_machine.py` | 新增 `_write_log` / `_assert_cleaned` / `_assert_not_cleaned`,凡涉及清理的用例一律核验 **job.log 真的被删**;按评审逐条补齐场景(下表) |

## 修复对照

| 评审问题编号 | 严重度 | 修复方式 |
|---|---|---|
| R-01 | major | **确认是缺陷。** `_handle_stop` 的 reclaim 分支先 `status()` 再进 `_begin_stop`,而幂等检查在 `_begin_stop` 内部 —— 同批重投的 reclaim 会在 TERM 已生效、job 已离开列表时读到被 `mark_canceled` 污染的 `canceled`,经 `_finish_scrapy_attempt` 上报并覆盖 server 的 lost。已把 `if state.stop_requested_at: return` 提到 `status()` **之前**(`commands.py`,reclaim 分支),并注释写明为何这个顺序是契约的一部分。回归用例:`test_duplicate_reclaim_mid_flight_does_not_report_a_terminal`(同批第二条 reclaim 不发信号、不发事件,最终仍为 lost)。 |
| R-02 | major | **确认是缺陷。** 第 2 步 `mark_lost` 后没有 `continue`,第 3 步照跑。当 `lost_after_stalled_seconds` < 采样有效窗口(合法配置)且空转超阈值时,同一轮会先建 reclaim 再建 no-progress cancel,而 cancel 的终态会把 lost 覆盖成 canceled。已在 lost 分支末尾 `continue`,并在 `_check_no_progress` 入口补 `status not in EXEC_ACTIVE` 的双保险。回归用例:`test_lost_execution_never_also_gets_a_no_progress_cancel`(`lost_after=300` / `sample_max_age=3600` / `auto_stop=True`,断言只有 reclaim、无 cancel、无通知)。 |
| R-03 | blocker | **评审指出的每一条都成立**,逐条补齐见下。另按要求:凡涉及清理的用例现在都写入真实 job.log 并断言文件被删除(`_assert_cleaned`),不再只看 state 消失。 |

### R-03 逐条补齐

| 评审指出的缺口 | 现在的覆盖 |
|---|---|
| TC-07/09/10/13 应由**真实 `apply_event` 心跳**驱动,而非直接改 DB 字段 | `test_reconcile_no_progress.py` 新增 `_heartbeat()` helper 走 `apply_event`;去重(TC-07)、采样失效(TC-09)、恢复(TC-10)、自动停止幂等(TC-13)全部由真实心跳推动。采样失效由**连发 3 条不带 `log_bytes` 的心跳 + 推进 reconcile 的 `now`** 造成,不再手改 `last_progress_sample_at` |
| TC-09 缺 `auto_stop=False` 分支 | 该用例改为对 `(False, True)` 两种取值各跑一遍 |
| TC-23 缺重启后的 KILL 升级 | `test_intent_persisted_before_term_survives_a_restart` 现在:TERM 首次失败 → 重启 → 重试 TERM → 推进时钟 → **重启后的实例发出 KILL** → 确认收尾 |
| TC-26 测的是 cancel,缺 reclaim 交错 | `test_cleanup_during_stop_is_deferred_not_dropped` 改为 `@pytest.mark.parametrize` 覆盖 **cancel 与 reclaim 两种 intent**,并分别断言事件语义 |
| TC-30 缺两种 intent、缺超时后持续 unknown 的多个 tick | `test_persistent_unknown_still_hits_the_deadline` 参数化两种 intent;超时后**再跑 3 个 tick 保持 unknown**,每次断言未清理、`kill_pending` 与 `cleanup_pending` 都还在;恢复后才清理 |
| TC-31 没有重建 agent、缺重复执行 | `test_deferred_cleanup_survives_a_restart_and_a_failure`:清理首次抛 `OSError` → **用同一 state 目录新建 consumer**(重启)→ 恢复入口完成清理 → **再跑一次断言幂等** |
| TC-36 缺挂起清理请求后的重投与清理 | `test_run_redelivery_during_a_stop_stays_silent` 现在先挂起 `cleanup_logs`,再重投 run,断言重投**既不发事件也不触发清理**,最后由状态机在正确时机清理 |
| TC-37 缺「超时前已有 cleanup_pending」 | `test_deadline_reports_terminal_but_keeps_reclaiming` 在超时**之前**下发 cleanup,断言超时收尾后 `cleanup_pending` 仍为真、**日志文件仍在**;确认退出后才清理 |
| TC-38 缺「超时后 unknown 阶段不清理」 | 并入 TC-30 的多 tick 断言(每个 unknown tick 都 `_assert_not_cleaned`) |
| TC-39 缺 reclaim 超时后持续回收、无事件、确认后清理 | 新增 `test_reclaim_keeps_reclaiming_past_the_deadline_without_events`:超时后 `result=="lost"`、**全程无 canceled 事件**、KILL 按间隔重发、确认退出后才清理 |
| TC-43 补发终态后就结束了 | `test_terminal_persisted_but_unsent_is_republished_after_restart` 续到底:补发 → 挂起 cleanup → 继续按间隔 KILL → 确认退出 → 清理;并断言 **canceled 全程恰好发布一次** |
| TC-44 在 cancel 前已清空所有列表 | 改为**真正的 pending job**:把 job 移进 `pending` 列表、确认 `is_job_alive()` 为 `True`,再 cancel + 挂起 cleanup;之后清空 pending/finished 模拟排队作业被取消(不产生 finished 条目、不写日志),断言 `status()` 确实返回 `unknown` 而 `is_job_alive()` 返回 `False`,并在**同一个 tick 内**完成确认与清理 |
| 涉及清理的用例需核验实际日志删除 | 新增 `_write_log` / `_assert_cleaned` / `_assert_not_cleaned`,TC-26/30/31/32/36/37/38/39/42/43/44 全部改为核验 job.log 文件本身 |

`_do_cleanup` 是**尽力删除而非事务**:注入 `store.delete` 失败时 job.log 可能已被删。
故 TC-32 的失败态断言改为「**state 与 `cleanup_pending` 必须保留**」(这才是重试
可达性的依据),并在用例里写明理由;成功态仍断言文件真的没了。

## 测试结果

全部 A 档。python `evidence/python-tests.txt`(`pytest -v`,**846 passed** /
1 skipped / exit=0,含 PG 用例);web `evidence/web-tests.txt`(TAP `1..129`,
exit=0);回归 `evidence/lint-typecheck.txt`(ruff / eslint / tsc 三项 exit=0)。

| 编号 | 档位 | 结果 | 证据(用例名) |
|---|---|---|---|
| TC-01 | A | pass | `test_event_progress.py::test_growing_log_advances_both_clocks` |
| TC-02 | A | pass | `…::test_flat_log_keeps_liveness_but_not_progress` |
| TC-03 | A | pass | `…::test_missing_reading_freezes_nothing` |
| TC-04 | A | pass | `…::test_lifecycle_event_counts_as_progress` |
| TC-05 | A | pass | `test_reconcile_no_progress.py::test_alerts_once_without_touching_the_execution` |
| TC-06 | A | pass | `…::test_repeated_passes_do_not_re_alert` |
| TC-07 | A | pass | `…::test_reading_the_alert_does_not_unlatch_it`(真实心跳驱动) |
| TC-08 | A | pass | `…::test_idle_below_threshold_is_quiet` |
| TC-09 | A | pass | `…::test_stale_sample_is_never_judged`(`auto_stop` 两种取值各一遍) |
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
| TC-23 | A | pass | `…::test_intent_persisted_before_term_survives_a_restart`(含重启后的 KILL 升级) |
| TC-24 | A | pass | `…::test_reclaim_stays_lost_even_when_status_says_canceled` |
| TC-25 | A | pass | `…::test_reclaim_with_a_real_terminal_overrides_without_signalling` |
| TC-26 | A | pass | `…::test_cleanup_during_stop_is_deferred_not_dropped[cancel]` 与 `[reclaim]` |
| TC-27 | A | pass | `…::test_cancel_without_state_still_reports_canceled` |
| TC-28 | A | pass | `…::test_reclaim_without_state_is_ignored` |
| TC-29 | A | pass | `…::test_unreachable_scrapyd_neither_confirms_nor_escalates` |
| TC-30 | A | pass | `…::test_persistent_unknown_still_hits_the_deadline[cancel]` 与 `[reclaim]`(超时后 3 个 unknown tick 均不清理) |
| TC-31 | A | pass | `…::test_deferred_cleanup_survives_a_restart_and_a_failure`(含重启与幂等重跑) |
| TC-32 | A | pass | 同上(首次 `OSError` 后保留 `cleanup_pending` 并重试成功) |
| TC-33 | A | pass | `notification-bell.test.tsx::tells a stalled attempt apart from one it also stopped` + `maps notification types onto existing static routes` |
| TC-34 | A | pass | `test_migration_0015_pg.py::test_migration_0015_adds_and_drops_progress_columns` |
| TC-35 | A | pass | `evidence/lint-typecheck.txt` + `python-tests.txt` + `web-tests.txt` |
| TC-36 | A | pass | `…::test_run_redelivery_during_a_stop_stays_silent`(含挂起清理) |
| TC-37 | A | pass | `…::test_deadline_reports_terminal_but_keeps_reclaiming`(超时前已挂起 cleanup,断言文件仍在) |
| TC-38 | A | pass | `…::test_persistent_unknown_still_hits_the_deadline[*]`(unknown 阶段逐 tick 断言未清理) |
| TC-39 | A | pass | `…::test_reclaim_keeps_reclaiming_past_the_deadline_without_events` |
| TC-40 | A | pass | `…::test_cancel_on_a_finished_attempt_reports_without_reviving_it` |
| TC-41 | A | pass | `…::test_reclaim_on_a_finished_attempt_reemits_without_reviving_it` |
| TC-42 | A | pass | `…::test_cleanup_after_terminal_is_deferred_until_the_process_dies` |
| TC-43 | A | pass | `…::test_terminal_persisted_but_unsent_is_republished_after_restart`(续到回收与清理完成) |
| TC-44 | A | pass | `…::test_pending_job_without_a_log_is_confirmed_not_stranded`(真 pending job + 延期清理) |
| TC-45 | A | pass | `…::test_unreachable_scrapyd_neither_confirms_nor_escalates` |

C 档 0 条,blocked 0 条。

## 与方案的偏差

沿用第 01 轮记录的 5 条,本轮未新增偏差。其中第 4 条(`_cleanup_must_wait` 比
plan §4.5 多 `terminal_pending`)在本轮被 TC-43 的完整序列进一步印证:终态还没进
`emit` 时清理会把 `result` 一起删掉,那条 `canceled` 就再也补发不出来。
