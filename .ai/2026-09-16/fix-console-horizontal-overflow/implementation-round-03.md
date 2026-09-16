---
task: fix-console-horizontal-overflow
round: 03
date: 2026-09-16
---

# 实现记录:第 03 轮

本轮**只更正上一轮实现记录里的一处失实描述,未改生产代码、未改测试、未重跑测试**
(第 02 轮评审 R-01 明确:「引用现有完整日志即可,无需仅为纠正文案重跑测试」)。
`apps/web/` 下七个文件与第 01 轮完全一致。

## 本轮改动

| 文件 | 改动摘要 |
|---|---|
| `evidence/act-warning-attribution.txt` | **新增**:按 vitest 的 `stderr \| <file> > …` 块逐处归属 `tc08-lint-typecheck-test.txt` 里的 16 处 act 告警,给出逐行行号,并附 `git diff --name-only` / `git ls-files --others` 证明两个告警来源文件都不在本任务改动范围内 |
| 本文件 | 据实更正第 02 轮记录第 27 行的告警归属结论 |

## 修复对照

| 评审问题编号 | 严重度 | 修复方式 |
|---|---|---|
| R-01 | blocker | **评审指出的事实成立,第 02 轮记录写错了。** 我当时用 `grep -B1 "not wrapped in act"` 配一条只匹配 `app/(app)/…/__tests__/…` 的正则做归属统计,`components/layout/__tests__/notification-bell.test.tsx` 不符合该正则被整体漏掉,于是把 16 处全部算给了 maintenance。据实更正:**16 处 = `maintenance.test.tsx` 4 处(日志 line 23/33/43/53)+ `notification-bell.test.tsx` 12 处(line 96/106/116/126/138/148/158/168/180/190/200/210)**。逐处归属与行号见新增的 `evidence/act-warning-attribution.txt`。 |

### 更正后关于「无新增告警」的结论

结论本身不变,但依据须重新陈述如下(不再依赖那句错误的归属):

1. 16 处 act 告警**全部**来自 `app/(app)/maintenance/__tests__/maintenance.test.tsx`
   与 `components/layout/__tests__/notification-bell.test.tsx`。
2. 这两个文件**都不在本任务的改动清单里** —— `git diff --name-only HEAD -- apps/web`
   列出 6 个文件、`git ls-files --others --exclude-standard -- apps/web` 列出 1 个新增
   文件,七个之中都没有它们(原始输出见 `evidence/act-warning-attribution.txt`)。
3. 本任务**修改**的 `schedules.test.tsx` 与**新增**的 `sidebar.test.tsx` 各 **0 处**告警
   —— 第 01 轮曾因 `focus()`/`blur()` 绕过 React 事件系统而在 `schedules.test.tsx` 引入过
   Tooltip 的 act 告警,当轮即用 `act(...)` 包裹消除(见 `implementation-round-01.md`
   偏差 4),此后历次运行均为 0。
4. 生产代码侧,`sidebar.tsx` 的 `min-w-0` 是纯样式类,`schedules/page.tsx` 的改动只涉及
   调度页;`NotificationBell` 与维护页都不渲染 `SidebarInset`,也不经过调度页,二者的
   告警与本次改动无因果关系。

据此:**本任务未引入新的测试告警**;该 16 处属于仓库既有的、与本任务无关的 act 告警。
本轮未对这两个既有文件做任何改动——修它们超出本任务范围(plan「明确不做」已界定
边界),如需清理应另开任务。

## 测试结果

本轮未重跑,沿用第 02 轮同一批次证据(评审已确认其完整可核验),结论不变:

| 编号 | 档位 | 结果 | 证据 |
|---|---|---|---|
| TC-01 | A | pass | `evidence/tc01-06-vitest.txt`(`ok 42 - components/ui/__tests__/sidebar.test.tsx > SidebarInset > keeps min-w-0 …`) |
| TC-02 | A | pass | `evidence/tc01-06-vitest.txt`(`ok 92`) |
| TC-02b | A | pass | `evidence/tc01-06-vitest.txt`(`ok 93`) |
| TC-03 | A | pass | `evidence/tc01-06-vitest.txt`(`ok 94`) |
| TC-04 | A | pass | `evidence/tc01-06-vitest.txt`(`ok 71`) |
| TC-05 | A | pass | `evidence/tc01-06-vitest.txt`(`ok 95`,另 `ok 79` 为既有确认分支) |
| TC-06 | A | pass | `evidence/tc01-06-vitest.txt`(`ok 96`) |
| TC-07 | A | pass | `evidence/tc07-layout-probe.txt`(三档共 25 PASS / 2 INFO,`ALL CHECKS PASSED`,exit=0) |
| TC-08 | A | pass | `evidence/tc08-lint-typecheck-test.txt`(lint exit=0、typecheck exit=0、test 完整输出 16 files / 128 tests passed exit=0);告警归属见 `evidence/act-warning-attribution.txt` |
| TC-09 | B | pass | `apps/web/e2e/specs/phase1-ui.spec.ts:314-315` |

## 与方案的偏差

沿用第 01 轮记录的 5 条,本轮未新增偏差。
