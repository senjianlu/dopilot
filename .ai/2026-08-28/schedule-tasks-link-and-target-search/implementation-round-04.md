---
task: schedule-tasks-link-and-target-search
round: 04
date: 2026-08-28
---

# 实现记录:第 04 轮

修第 03 轮评审的 blocker R-01,并顺带修 minor R-02(一行 `aria-label`,
属本任务新写代码的可访问性缺口)。

## 本轮改动

| 文件 | 改动摘要 |
|---|---|
| `apps/web/app/(app)/tasks/__tests__/tasks.test.tsx` | R-01:重写 TC-11。过期响应 resolve 后,在 `act` 内 `await` 该 Promise 及其回调链再断言(消除"什么都还没发生就通过"的窗口);同时让过期响应的 `total` 与新响应不同(999 vs 7),使"被误用"在页码指示器上也可见,断言页码文本仍等于新响应对应的值 |
| `apps/web/app/(app)/tasks/page.tsx` | R-02:搜索框补 `aria-label={t("tasks.searchTarget")}`(此前只有 placeholder) |

被测源码除这一行 `aria-label` 外未作改动。

## 修复对照

| 评审问题编号 | 严重度 | 修复方式 |
|---|---|---|
| R-01 | blocker | 评审判定成立:原写法 `waitFor(() => expect(queryByTestId("task-old")).toBeNull())` 检查的是一个**本就不存在**的元素,可在旧 Promise 回调运行前通过。现改为:`await act(async () => { await first.promise; await Promise.resolve(); })` 确保过期响应确已被组件处理完毕,再做三项断言(过期行不存在 / 新行仍在 / 页码仍为新响应的值)。证据:`evidence/round04-tc-09-to-14-tasks-tap.txt`,锚点 `ok 4 - discards a stale response that lands after a newer one`,EXIT=0 |
| R-02 | minor | 已加 `aria-label`。证据:`apps/web/app/(app)/tasks/page.tsx:259-262`;`round04-tc-17-18-full.txt` 中 eslint / tsc / build 均 EXIT=0 |

### 断言有效性的自证(并附一处诚实的实现发现)

对重写后的 TC-11 做变异验证(完整命令与输出见
`evidence/round04-mutation-check.md`):

1. **只移除 `seq !== reqSeq.current` → 用例仍通过**。这暴露了一个实现事实:
   实际生效的防护是 `alive`,不是请求序号。请求只由那个以 `filters` 为依赖
   的 effect 发出,发新请求必然意味着 effect 重跑,而重跑前 cleanup 已把旧
   闭包的 `alive` 置 false——因此"序号过期"与"`alive` 为 false"在本设计中
   **逻辑等价**,`reqSeq` 是冗余的第二道守卫。
2. **两道守卫都移除 → 用例失败**(过期的 `task-old` 行渲染出来并被捕获)。
   说明 TC-11 对 plan 要求的行为确有约束力。

**关于是否删除 `reqSeq`**:它已被证明冗余。此处**选择保留**,原因是 plan
第 3 节明确写了"用单调递增的请求序号丢弃过期响应"(该写法是 plan 评审第 02
轮 R-01 的指定修法之一),删除它会构成与已确认方案的实现级偏离;而保留它
无行为影响。上述冗余事实在此如实记录,便于后续需要简化时直接依据。

## 测试结果

| 编号 | 档位 | 结果 | 证据 |
|---|---|---|---|
| TC-01 ~ TC-08 | A | pass | `evidence/round04-tc-17-backend-pytest.txt`(全量 790 passed, 1 skipped, EXIT=0);逐条锚点见 `round02-tc-01-08-backend.txt`(后端测试自第 02 轮起未改动) |
| TC-09 ~ TC-14 | A | pass | `evidence/round04-tc-09-to-14-tasks-tap.txt`,16 条 TAP 全 `ok`,`not ok` 为 0,act 警告为 0,EXIT=0。TC-11 锚点 `ok 4 - discards a stale response that lands after a newer one` |
| TC-15 | A | pass | `round04-tc-17-18-full.txt` 第一段全量 web(122 passed, EXIT=0);逐条锚点见 `tc-15-schedules-tap.txt` |
| TC-16 | A | pass | 同上;逐条锚点见 `tc-16-client-tap.txt` |
| TC-17 | A(回归) | pass | `round04-tc-17-backend-pytest.txt`(790 passed, 1 skipped, EXIT=0)+ `round04-tc-17-18-full.txt` 的 web / ruff / eslint / tsc 四段,EXIT 均为 0 |
| TC-18 | A(构建约束) | pass | `round04-tc-17-18-full.txt` 末段,`✓ Compiled successfully`,EXIT=0 |

## 与方案的偏差

沿用第 01–03 轮已记录的各项偏差(服务层也 strip;命令用
`.venv/bin/python -m`;证据文件按命令范围合并并逐条给锚点;PG 连接串;
第 03 轮对已 approved plan.md 的 ADR 描述作事实更正)。本轮无新增偏差。
