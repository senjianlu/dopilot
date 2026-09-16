---
task: no-progress-stall-detection
round: 03
date: 2026-09-16
---

# 实现记录:第 03 轮

本轮**只补测试,未改生产代码**。第 02 轮评审的 blocker 指出我的实现记录有两处
与源码矛盾(声称 TC-10 由真实心跳驱动、TC-42 已核验文件删除,实际都没做到),
以及四处场景不完整。逐条闭合如下;`apps/agent/dopilot_agent/` 与
`apps/server/dopilot_server/` 下的生产代码与第 02 轮完全一致。

## 本轮改动

| 文件 | 改动摘要 |
|---|---|
| `apps/server/tests/test_reconcile_no_progress.py` | 新增 `clock` fixture:`monkeypatch` 掉 `services.events` 的 `datetime`,使 `apply_event` 与 `reconcile_once` 共用同一把受控时钟。TC-10 据此重写,**不再写任何进度列** |
| `apps/agent/tests/test_stop_state_machine.py` | `_write_log` 支持 `workspace=True`(真建目录并写进 state),`_assert_cleaned` / `_assert_not_cleaned` 一并核验 **workspace 删除**;TC-42 补齐真实产物;TC-31 改为「mark_done 后、清理前崩溃 → 重启恢复」并与 TC-32 拆开 |
| `apps/agent/tests/test_terminal_delivery_e2e.py` | **新增**:TC-43 的端到端 —— agent 补发的事件经 server 的 `apply_event` 消费,断言 execution/task 收敛为 canceled |

## 修复对照

| 评审问题编号 | 严重度 | 修复方式 |
|---|---|---|
| R-01 | blocker | 五个子项逐条闭合,见下表。原记录中「全部由真实心跳驱动」「TC-42 已核验实际日志删除」两处表述**确与源码矛盾**,本轮已使其成立(而不是改写措辞)。 |

### 逐条闭合

| 评审指出的缺口 | 本轮的处理 |
|---|---|
| TC-10 仍直接改写 `last_progress_at` / `last_progress_sample_at`(旧 :317) | 根因是 `apply_event` 自己取 `datetime.now(UTC)`,测试无从让采样「变旧」,只能伸手改列。新增 `clock` fixture 把 `services.events.datetime` 换成受控实现,于是**采样失效、读数恢复、再次超时全程由真实心跳推进**:3 条不带 `log_bytes` 的心跳 + 时钟推进 600s 造成失效;1 条带增长的心跳造成恢复;9 条持平心跳造成再次超时。该用例现在**一个进度列都不写** |
| TC-42 未创建日志,只断言 state 消失(旧 :503) | 改为 `_write_log(store, workspace=True)`,并在超时收尾后、cleanup 到达后、以及两个额外回收 tick 中**逐次断言 log 与 workspace 仍在**;确认退出后才断言两者被删 |
| TC-31 是在日志已删、`store.delete` 失败后才重启,未覆盖「mark_done 后、清理前重启」(旧 :868) | 拆成两个用例。`test_cleanup_deferred_past_a_crash_is_recovered_on_restart`(TC-31):把 `_run_deferred_cleanup` 换成 no-op 模拟「确认退出、mark_done 已写,但还没清理就死了」,断言此刻 `kill_pending=False` / `cleanup_pending=True` / **产物都还在**,再用同一 state 目录新建 consumer,断言恢复入口**真的删掉 log 与 workspace**,并再跑一次验证幂等。`test_failed_cleanup_keeps_its_flag_and_is_retried`(TC-32)保留失败重试路径 |
| TC-43 只核验事件进入 FakeRedis,未核验最终送达 server | 新增 `test_terminal_delivery_e2e.py`:先把补发前流上的全部事件喂给 server 的 `apply_event`,断言 execution **尚未** canceled(证明确实缺一条);重启后取出**新增**的那条事件(断言恰好是 `canceled` 一条),再喂给同一个 server session,断言 `execution.status == canceled` 且 `task.status == canceled`。跨应用是刻意的:这条不变量横跨 agent 的持久化latch 与 server 的状态机,只测一半就漏掉了接缝 |
| TC-26/31/38 缺 workspace 删除断言 | `_write_log(..., workspace=True)` 真建目录并写入 `state.workspace_path`;TC-26(两种 intent)、TC-30/38、TC-31、TC-32、TC-39、TC-42 全部改用它,`_assert_cleaned` 同时断言 `log_path` 与 `workspace_path` 都不存在 |

## 测试结果

全部 A 档。python `evidence/python-tests.txt`(`pytest -v`,**848 passed** /
1 skipped / exit=0,含 PG 用例);web `evidence/web-tests.txt`(TAP `1..129`,
exit=0);回归 `evidence/lint-typecheck.txt`(ruff / eslint / tsc 三项 exit=0)。

与第 02 轮相比,用例名变化的条目:

| 编号 | 档位 | 结果 | 证据(用例名) |
|---|---|---|---|
| TC-10 | A | pass | `test_reconcile_no_progress.py::test_recovered_sample_restarts_the_clock`(受控时钟 + 真实心跳,零进度列写入) |
| TC-26 | A | pass | `test_stop_state_machine.py::test_cleanup_during_stop_is_deferred_not_dropped[cancel]` 与 `[reclaim]`(含 workspace) |
| TC-30 | A | pass | `…::test_persistent_unknown_still_hits_the_deadline[cancel]` 与 `[reclaim]`(含 workspace) |
| TC-31 | A | pass | `…::test_cleanup_deferred_past_a_crash_is_recovered_on_restart` |
| TC-32 | A | pass | `…::test_failed_cleanup_keeps_its_flag_and_is_retried` |
| TC-38 | A | pass | `…::test_persistent_unknown_still_hits_the_deadline[*]`(逐 tick 断言 log 与 workspace 均未删) |
| TC-39 | A | pass | `…::test_reclaim_keeps_reclaiming_past_the_deadline_without_events`(含 workspace) |
| TC-42 | A | pass | `…::test_cleanup_after_terminal_is_deferred_until_the_process_dies`(真实产物) |
| TC-43 | A | pass | `test_terminal_delivery_e2e.py::test_republished_terminal_converges_the_server_to_canceled` + `test_stop_state_machine.py::test_terminal_persisted_but_unsent_is_republished_after_restart` |

其余条目(TC-01~09、11~25、27~29、33~37、40、41、44、45)与第 02 轮记录一致,
用例名未变,结果仍为 pass。

C 档 0 条,blocked 0 条。

## 与方案的偏差

沿用第 01 轮记录的 5 条,本轮未新增偏差。
