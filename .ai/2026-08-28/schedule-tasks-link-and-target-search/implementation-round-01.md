---
task: schedule-tasks-link-and-target-search
round: 01
date: 2026-08-28
---

# 实现记录:第 01 轮

## 本轮改动

| 文件 | 改动摘要 |
|---|---|
| `apps/server/dopilot_server/services/executions.py` | 新增 `_LIKE_ESCAPE` / `_like_contains()`(先转义转义符再转义 `%` `_`);`list_tasks_page()` 增加 `schedule_id`、`target_query` 两个 keyword-only 参数,两者均同时作用于 `base` 与 `count_q`;`target_query` 在服务层内 `strip()` |
| `apps/server/dopilot_server/api/v1/tasks.py` | 新增 `MAX_TARGET_QUERY_LEN = 100`;`GET /tasks` 增加 `schedule_id`、`q` 两个 query 参数;`q` strip 后超长返回 400 `task.invalid_query`;两参数透传给服务层 |
| `apps/server/tests/test_task_filters.py`(新) | 8 条用例:服务层 5 条(含通配符转义、空白查询两条边界)+ API 层 3 条(含未知 schedule_id 不 404、超长 q 返 400) |
| `apps/web/lib/api/types.ts` | `ListTasksParams` 增加 `scheduleId?`、`q?` |
| `apps/web/lib/api/tasks.ts` | `listTasks()` 把两者序列化为 `schedule_id` / `q`,falsy 时整个键不发送 |
| `apps/web/app/(app)/tasks/page.tsx` | 拆 `TasksPageInner` + `React.Suspense`;`page/pageSize/build/status/scheduleId/q` 收敛为单一 `TaskFilters` 对象,全部走函数式 `setFilters`;唯一请求 effect 以 `filters` 为依赖;`reqSeq` 请求序号丢弃过期响应(成功/失败两路都判);300ms 防抖只提交 `q` 不发请求;回车立即提交;搜索框 `maxLength=100`;调度筛选芯片 + ✕ 清除(并 `router.replace("/tasks")`);请求失败 toast 兜底;首屏页大小移入 `useState` 惰性初始化 |
| `apps/web/app/(app)/schedules/page.tsx` | 操作列新增「任务记录」链接(`Button asChild` + `Link`),href 为 `/tasks?schedule_id=<enc>&schedule_name=<enc>` |
| `apps/web/lib/i18n/locales/zh.ts`、`en.ts` | 新增 `tasks.searchTarget` / `scheduleFilter` / `clearFilter` / `loadFailed`、`schedules.viewTasks` |
| `apps/web/app/(app)/tasks/__tests__/tasks.test.tsx` | `next/navigation` mock 增加可切换的 `useSearchParams` 与被断言的 `router.replace`;新增 `sonner` mock;新增 10 条用例(下钻 3 + 搜索 7) |
| `apps/web/app/(app)/schedules/__tests__/schedules.test.tsx` | 新增 2 条:入口链接 href、名称需转义时的 URL 编码 |
| `apps/web/lib/api/__tests__/client.test.ts` | 新增 3 条:经真实 axios 实例(仅替换 adapter)断言出站 `params` 的键名与省略行为 |
| `docs/decisions/0023-task-target-search-without-trigram-index.md`(新) | ADR:模糊搜索走顺序扫、不引入 pg_trgm 的理由、长度上限与转义、复议阈值 |
| `docs/decisions/README.md` | 索引追加 0023 一行 |

## 修复对照

第 1 轮,无上一轮评审问题。(plan 阶段 3 轮评审的 5 条 major 已在 plan.md
中就地修订并于第 03 轮 pass,不属于实现层修复轮。)

## 测试结果

| 编号 | 档位 | 结果 | 证据 |
|---|---|---|---|
| TC-01 | A | pass | `evidence/tc-01-08-backend.txt`,锚点 `test_list_tasks_page_schedule_filter PASSED` |
| TC-02 | A | pass | 同上,锚点 `test_target_query_is_case_insensitive_substring PASSED` |
| TC-03 | A | pass | 同上,锚点 `test_filters_and_together PASSED` |
| TC-04 | A(异常/边界) | pass | 同上,锚点 `test_like_wildcards_are_escaped PASSED` |
| TC-05 | A(异常/边界) | pass | 同上,锚点 `test_blank_query_means_no_filter PASSED` |
| TC-06 | A | pass | 同上,锚点 `test_get_tasks_schedule_filter PASSED` |
| TC-07 | A | pass | 同上,锚点 `test_get_tasks_target_query_filter PASSED` |
| TC-08 | A(异常/边界) | pass | 同上,锚点 `test_get_tasks_rejects_overlong_query PASSED` |
| TC-09 | A | pass | `evidence/tc-09-to-14-tasks-tap.txt`,`TasksPage schedule drill-down` 组下 3 条全 ok |
| TC-10 | A | pass | 同上,`ok 1 - debounces typing and resets to page 1`、`ok 2 - searches immediately on Enter and does not fire again after the delay` |
| TC-11 | A(异常/边界) | pass | 同上,`ok 4 - discards a stale response that lands after a newer one` |
| TC-12 | A(异常/边界) | pass | 同上,`ok 5 - caps the search input ...`、`ok 6 - surfaces a toast instead of an unhandled rejection ...` |
| TC-13 | A | pass | 同上,`ok 7 - preserves the search term and schedule filter across paging and refresh` |
| TC-14 | A(异常/边界) | pass | 同上,`ok 3 - uses the LATEST filters when the debounce fires, not the ones captured while typing` |
| TC-15 | A | pass | `evidence/tc-15-schedules-tap.txt`,`SchedulesPage task drill-down` 组下 2 条全 ok |
| TC-16 | A | pass | `evidence/tc-16-client-tap.txt`,`listTasks query serialization` 组下 3 条全 ok |
| TC-17 | A(回归) | pass | `evidence/tc-17-backend-pytest.txt`(790 passed, 1 skipped, EXIT=0;基线 782 → +8)、`tc-17-web-vitest.txt`(122 passed, EXIT=0;基线 107 → +15)、`tc-17-ruff.txt`、`tc-17-eslint.txt`、`tc-17-tsc.txt`(均 EXIT=0) |
| TC-18 | A(构建约束) | pass | `evidence/tc-18-next-build.txt`,`/tasks` 列于 `○ (Static) prerendered as static content`,EXIT=0 |

## 与方案的偏差

1. **服务层也对 `target_query` 做 `strip()`**(plan 原写"调用方传入前须
   strip,服务层只把 falsy 当无筛选")。原因:按 plan 原样实现后 TC-05
   实测失败——`"   "` 在 Python 中是真值,服务层会拿它去匹配 `%   %` 并返回
   0 行。把 strip 下沉到服务层后 API 层的 strip 成为幂等的第二道,该边界
   彻底消失。影响仅限服务层内部,对外行为与 plan 预期一致(且正是 plan 的
   TC-05 所要求的)。

2. **TC-10 / TC-14 改用真实计时器 + `fireEvent`,不用 `vi.useFakeTimers()`**
   (plan 写的是 `vi.useFakeTimers()`)。原因:实测发现假时钟与 React 19 的
   act 环境在本组件上互相死锁——请求由**裸 `setTimeout` 回调**触发的状态
   更新发出,而 `vi.waitFor` 在假时钟下只推进假计时器、不让出真实宏任务
   队列,React 调度器因此永远不 flush,用例 5s 超时;超时后 `finally` 不
   执行,假时钟还会泄漏到后续用例(实测一次污染 6 条)。改法:TC-10 用真实
   计时器并真等 150ms 断言"窗口内不发请求";TC-14 用同步的 `fireEvent`
   在同一 tick 内制造"防抖待触发时清掉调度芯片",再等过 500ms 断言最终
   请求带 `scheduleId: null`,并追加"一旦清除,其后任何请求都不得再带该
   调度"的单调不回归断言。覆盖的行为与 plan 的预期结果完全一致,只是
   驱动方式从假时钟换成真实时间 + 同步事件,且比原方案更不易 flaky。
   另加了一条全局 `afterEach` 恢复真实时钟作为兜底。

3. **执行命令**:plan 写 `.venv/bin/pytest`,实际用
   `.venv/bin/python -m pytest`。原因:该 venv 是在旧路径
   (`/home/rabbir/dopilot/.venv`)创建的,console-script 的 shebang 指向已
   不存在的解释器,直接执行报 127;`.venv/bin/python` 本身可用。ruff 同理
   改为 `.venv/bin/python -m ruff`。不影响被执行的内容。

4. **证据文件命名按范围合并**:plan 写 `evidence/tc-01.txt` … 逐条一个文件,
   实际同一条命令覆盖多条用例时合并为一个文件
   (`tc-01-08-backend.txt`、`tc-09-to-14-tasks-tap.txt`、
   `tc-15-schedules-tap.txt`、`tc-16-client-tap.txt`)。每条用例在上表中给出
   该文件内的具体锚点(pytest 的 `PASSED` 行 / TAP 的 `ok N - <用例名>` 行),
   可逐条核验;完整原始输出(命令 + stdout/stderr + 退出码)一个不缺。

5. **PG 并发用例的连接串**:TC-17 需要
   `DOPILOT_TEST_DATABASE_URL=postgresql+psycopg://dopilot:dopilot@localhost:5432/dopilot`
   (docs/architecture/07-development-and-testing.md:40),对应本机
   `docker-db-1` 容器。首次用错库名导致 12 个 PG 用例 ERROR,更正后全绿。
   属执行环境问题,非代码问题。
