---
task: schedule-tasks-link-and-target-search
round: 02
date: 2026-08-28
---

# 实现记录:第 02 轮

## 本轮改动

本轮**只修第 01 轮评审的 blocker R-01**,不动其它代码。R-02 为 minor,
按 rawf-review 分流规则不在本轮处理,列入遗留 minor 交用户裁决。

| 文件 | 改动摘要 |
|---|---|
| `apps/server/tests/test_task_filters.py` | TC-05 补上 plan 要求的边缘空格断言:`target_query="  alpha  "` 与 `"alpha"` 的 total 与返回行 id 完全一致 |
| `apps/web/app/(app)/tasks/__tests__/tasks.test.tsx` | TC-10 改为确定性的 299/300ms 边界断言(不再是"等 150ms");TC-14 改为在防抖窗口内**同时**变更 status 与清除调度芯片,并断言最终请求含 `q`/`status`/`scheduleId` 三者的最新值 |

**被测源码未作任何改动**——本轮问题全部出在测试断言强度上。

## 修复对照

| 评审问题编号 | 严重度 | 修复方式 |
|---|---|---|
| R-01(TC-05 部分) | blocker | `test_blank_query_means_no_filter` 增加 `"  alpha  "` 与 `"alpha"` 的等价断言(总数相等 + 返回行 id 列表相等)。证据:`evidence/round02-tc-01-08-backend.txt`,锚点 `test_blank_query_means_no_filter PASSED` |
| R-01(TC-10 部分) | blocker | 放弃"真实计时器等 150ms"的弱断言。改为:真实计时器下挂载完成后切假时钟,用**同步** `act(() => vi.advanceTimersByTime(n))` 推进——同步 act 会同步 flush effect,因此无需在假时钟下 await(那正是第 01 轮死锁的原因)。断言:299ms 时调用数不变,再推进 1ms 后**恰好**多 1 次调用且带 `q:"alpha", page:1`。证据:`evidence/round02-tc-09-to-14-tasks-tap.txt`,锚点 `ok 1 - debounces typing and resets to page 1` |
| R-01(TC-14 部分) | blocker | 补上 status 变更。关键是**在打字之前**就装假时钟(装在其后的话,防抖计时器仍是真实的,推进假时钟无效),再用同步 `fireEvent` 驱动 Radix 下拉(user-event 会 await 真实宏任务,在假时钟下死锁)。窗口内依次:输入 `alpha` → status 改 `failed` → 清除调度芯片,累计仅推进 3ms;随后推进 400ms 让防抖触发,断言该次请求同时带 `q:"alpha"`、`status:"failed"`、`scheduleId:null`、`page:1`。另加两个维度**各自起点**的单调不回归断言。证据:同上,锚点 `ok 3 - uses the LATEST filters when the debounce fires, not the ones captured while typing` |

### 断言有效性的额外自证

R-01 的实质是"断言弱于契约却报 pass"。为避免改完仍然形同虚设,本轮对源码
注入两个 bug 做变异验证,确认用例会变红后完全还原源码:

- 防抖回调改为捕获快照(`setFilters({...filters, ...})`)→ TC-14 失败;
- 防抖窗口 300ms 改 150ms → TC-10 失败(299ms 处已发出请求,调用数 2 ≠ 1)。

完整命令与输出见 `evidence/round02-mutation-check.md`;还原后的全绿证据即
同目录 `round02-*.txt` 系列。

## 测试结果

| 编号 | 档位 | 结果 | 证据 |
|---|---|---|---|
| TC-01 | A | pass | `evidence/round02-tc-01-08-backend.txt`,锚点 `test_list_tasks_page_schedule_filter PASSED` |
| TC-02 | A | pass | 同上,锚点 `test_target_query_is_case_insensitive_substring PASSED` |
| TC-03 | A | pass | 同上,锚点 `test_filters_and_together PASSED` |
| TC-04 | A(异常/边界) | pass | 同上,锚点 `test_like_wildcards_are_escaped PASSED` |
| TC-05 | A(异常/边界) | pass | 同上,锚点 `test_blank_query_means_no_filter PASSED`(本轮已补边缘空格断言) |
| TC-06 | A | pass | 同上,锚点 `test_get_tasks_schedule_filter PASSED` |
| TC-07 | A | pass | 同上,锚点 `test_get_tasks_target_query_filter PASSED` |
| TC-08 | A(异常/边界) | pass | 同上,锚点 `test_get_tasks_rejects_overlong_query PASSED` |
| TC-09 | A | pass | `evidence/round02-tc-09-to-14-tasks-tap.txt`,`TasksPage schedule drill-down` 组下 3 条全 ok |
| TC-10 | A | pass | 同上,`ok 1 - debounces typing and resets to page 1`(299/300 确定性边界)、`ok 2 - searches immediately on Enter and does not fire again after the delay` |
| TC-11 | A(异常/边界) | pass | 同上,`ok 4 - discards a stale response that lands after a newer one` |
| TC-12 | A(异常/边界) | pass | 同上,`ok 5 - caps the search input ...`、`ok 6 - surfaces a toast instead of an unhandled rejection ...` |
| TC-13 | A | pass | 同上,`ok 7 - preserves the search term and schedule filter across paging and refresh` |
| TC-14 | A(异常/边界) | pass | 同上,`ok 3 - uses the LATEST filters when the debounce fires, not the ones captured while typing`(本轮已补 status 变更与三值断言) |
| TC-15 | A | pass | `evidence/tc-15-schedules-tap.txt`(本轮未改动 schedules 测试);第 02 轮全量回归 `round02-tc-17-web-vitest.txt` 一并覆盖 |
| TC-16 | A | pass | `evidence/tc-16-client-tap.txt`(本轮未改动);同上由全量回归覆盖 |
| TC-17 | A(回归) | pass | `evidence/round02-tc-17-backend-pytest.txt`(790 passed, 1 skipped, EXIT=0)、`round02-tc-17-web-vitest.txt`(122 passed, EXIT=0)、`round02-tc-17-static-checks.txt`(ruff / eslint / tsc 三段 EXIT 均为 0) |
| TC-18 | A(构建约束) | pass | `evidence/round02-tc-18-next-build.txt`,`✓ Compiled successfully`、`/tasks` 列于静态预渲染路由,EXIT=0 |

## 与方案的偏差

第 01 轮记录的偏差 1、3、4、5 依然成立(服务层也 strip;命令用
`.venv/bin/python -m pytest`;证据文件按命令范围合并并逐条给锚点;PG 连接串)。

第 01 轮的偏差 2 **本轮已收敛回 plan**:TC-10 / TC-14 恢复使用
`vi.useFakeTimers()`,与 plan 声明一致。第 01 轮放弃假时钟是因为遇到死锁,
本轮找到了正确用法,记录如下(这是与 plan 文字的实现细节差异,行为与预期
结果完全一致):

- **假时钟必须在触发防抖的输入之前安装**。装在其后,那个已排期的
  `setTimeout` 仍是真实计时器,推进假时钟对它无效(实测表现为推进 400ms
  后调用数不增)。
- **不得在假时钟下 await 需要真实宏任务的东西**。`vi.waitFor` 只推进假
  计时器,而 React 调度器要真实宏任务才 flush,于是死等到超时;且超时后
  用例自身的 `finally` 不执行,假时钟会泄漏污染后续用例。正确做法是用
  **同步** `act(() => vi.advanceTimersByTime(n))`,它同步 flush effect,
  全程不 await。
- **假时钟下用 `fireEvent` 而非 user-event 驱动 Radix 下拉**。user-event
  内部 await 真实宏任务,同样死锁;`fireEvent` 是同步的,配合每步 1ms 的
  假时钟推进即可让 Radix 内部计时器跑完(3 步共 3ms,仍远在 300ms 窗口内)。
- 保留第 01 轮加的全局 `afterEach(() => vi.useRealTimers())` 作为兜底。
