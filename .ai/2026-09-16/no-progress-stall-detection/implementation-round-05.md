---
task: no-progress-stall-detection
round: 05
date: 2026-09-16
---

# 实现记录:第 05 轮

修第 04 轮评审的 blocker。本轮**只补一条测试,未改生产代码**。

## 本轮改动

| 文件 | 改动摘要 |
|---|---|
| `apps/agent/tests/test_stop_state_machine.py` | 新增 `test_term_raising_through_the_runner_still_retries_and_finishes`,独立覆盖 TC-22 |

## 修复对照

| 评审问题编号 | 严重度 | 修复方式 |
|---|---|---|
| R-01 | blocker | **评审说得对,TC-22 此前确实没被覆盖。** 我原本用 `fail_cancel_times` 注入 `httpx.ConnectError` 来同时声明 TC-21 与 TC-22,但那个异常在 `scrapyd/client.py:62` 被转成 `ScrapydError`,又在 `runners/scrapyd.py:130` 被捕获并返回 `detail.reason == "cancel_failed"` —— 走的是 `_send_stop_signal` 的**返回值**分支(TC-21),压根到不了它的 `except Exception`(TC-22)。现在直接把 `runner.stop` 换成第一次抛 `RuntimeError` 的实现,让异常真正穿过去,并断言四件事:①意图已落盘(`stop_requested_at` 非空、`stop_escalation` 仍为 `None`、未发出任何信号);②命令确实已 ACK —— 再 `drain_once(claim_pending=True)` 返回 0,证明没有任何重投可依赖,唯一能推动它的就是那条落盘的意图;③下一 tick 重试成功并置 `stop_escalation="term"`;④再一 tick 确认退出、`result == "canceled"`、`canceled` 事件恰好一条。 |

这条区分不是文字游戏:被 runner 转换过的失败是**预期内**的(网络抖动、scrapyd 拒绝),
而没被转换的异常意味着**代码路径出了意料之外的问题** —— 恰恰是这种时候,「意图先落盘」
才是停止不至于凭空消失的唯一依靠。

## 测试结果

全部 A 档。python `evidence/python-tests.txt`(`pytest -v`,**849 passed** /
1 skipped / exit=0,含 PG 用例);web `evidence/web-tests.txt`(TAP `1..129`,
exit=0);回归 `evidence/lint-typecheck.txt`(ruff / eslint / tsc 三项 exit=0)。

| 编号 | 档位 | 结果 | 证据(用例名) |
|---|---|---|---|
| TC-21 | A | pass | `test_stop_state_machine.py::test_first_term_failure_keeps_the_intent_and_retries`(`cancel_failed` **返回值**路径) |
| TC-22 | A | pass | `…::test_term_raising_through_the_runner_still_retries_and_finishes`(异常**穿过** `runner.stop` 的路径) |

其余条目与第 03 / 04 轮记录一致,用例名未变,结果仍为 pass。

C 档 0 条,blocked 0 条。

## 与方案的偏差

沿用第 01 轮记录的 5 条,本轮未新增偏差。
