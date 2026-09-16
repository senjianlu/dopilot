---
task: fix-console-horizontal-overflow
round: 02
date: 2026-09-16
---

# 实现记录:第 02 轮

本轮**只补证据,未改任何生产代码**。第 01 轮评审的两个 blocker 都是 A 档证据
契约缺口(日志被截取、验收未覆盖全部视口),不涉及实现缺陷;`apps/web/` 下
七个文件与第 01 轮完全一致(`git diff` 可核)。

## 本轮改动

| 文件 | 改动摘要 |
|---|---|
| `evidence/layout-probe.mjs` | 把 [3] 徽标裁剪与 [4] 操作菜单两组检查从「仅 1440」移进 1280/1440/1920 三档循环;[2] 卡片内滚动在三档都量测,但按 plan 只在 1440 断言 pass/fail,其余两档以 `INFO` 打印实测值;更新文件头注释(承载环境是生产静态导出而非 `next dev`,并写全复现命令) |
| `evidence/tc07-layout-probe.txt` | 重新生成:含 build 命令与输出、静态服务器命令、探测脚本完整 stdout 与 exit=0 |
| `evidence/tc08-lint-typecheck-test.txt` | 重新生成:`pnpm test` 段改为**未经截取**的完整 stdout/stderr(238 行)与退出码 |
| `evidence/tc01-06-vitest.txt` | 与本轮同批次重跑,保持 TAP 编号与其余证据同源 |
| `evidence/schedules-after-fix.png` | 由本轮脚本在 1440 档重新截取 |

## 修复对照

| 评审问题编号 | 严重度 | 修复方式 |
|---|---|---|
| R-01 | blocker | `tc08-lint-typecheck-test.txt` 的 test 段此前被 `tail -14` 截断,只剩 8 个文件的结果。已改为原样落盘 `corepack pnpm -C apps/web test` 的完整 stdout/stderr(238 行,含全部 16 个测试文件与运行开头)与 `exit=0`。据此可核验「无新增告警」:全文 16 处 `not wrapped in act` 告警**全部来自既有的 `app/(app)/maintenance/__tests__/maintenance.test.tsx`**,本任务触及的 `schedules.test.tsx` 与新增的 `sidebar.test.tsx` 一处告警都没有。lint / typecheck 段按评审意见未重复改动,仍为完整输出。 |
| R-02 | blocker | `layout-probe.mjs` 原先三档循环只测整页宽度(旧 132 行),测完固定回到 1440 才做徽标与菜单检查(旧 147 行起)。已重构为单层三档循环,每档都执行 [1][3][4];[2] 三档都量测,pass/fail 判定按 plan 原文只落在 1440。新证据 `tc07-layout-probe.txt` 含 1280 / 1440 / 1920 各自的两种徽标矩形、所属单元格边界、`checkVisibility()`,以及操作触发器与展开后四项菜单的可见性,共 25 项 PASS + 2 项 INFO,`ALL CHECKS PASSED`、exit=0。 |

## 测试结果

| 编号 | 档位 | 结果 | 证据 |
|---|---|---|---|
| TC-01 | A | pass | `evidence/tc01-06-vitest.txt`(`ok 42 - components/ui/__tests__/sidebar.test.tsx > SidebarInset > keeps min-w-0 …`) |
| TC-02 | A | pass | `evidence/tc01-06-vitest.txt`(`ok 92 - … > truncates the long schedule and template names`) |
| TC-02b | A | pass | `evidence/tc01-06-vitest.txt`(`ok 93 - … > surfaces the full name by hover and by keyboard focus`) |
| TC-03 | A | pass | `evidence/tc01-06-vitest.txt`(`ok 94 - … > keeps the four row actions behind the menu`) |
| TC-04 | A | pass | `evidence/tc01-06-vitest.txt`(`ok 71 - … > SchedulesPage > triggers a schedule and navigates to the created task`) |
| TC-05 | A | pass | `evidence/tc01-06-vitest.txt`(`ok 95 - … > does not delete from the menu when the confirm is cancelled`;另 `ok 79 - … > deletes a schedule only after confirmation` 为既有确认分支) |
| TC-06 | A | pass | `evidence/tc01-06-vitest.txt`(`ok 96 - … > keeps the auto-disabled badge and archived mark outside the truncation`) |
| TC-07 | A | pass | `evidence/tc07-layout-probe.txt`(三档共 25 PASS / 2 INFO,`ALL CHECKS PASSED`,exit=0);脚本 `evidence/layout-probe.mjs`;截图 `evidence/schedules-after-fix.png` |
| TC-08 | A | pass | `evidence/tc08-lint-typecheck-test.txt`(lint exit=0、typecheck exit=0、test 完整输出 16 files / 128 tests passed exit=0;无本任务引入的新增告警) |
| TC-09 | B | pass | `apps/web/e2e/specs/phase1-ui.spec.ts:314-315`:`schedule-actions-${SCHEDULE_NAME}` 的 click 紧邻在 `schedule-trigger-${SCHEDULE_NAME}` 之前。e2e 实跑依赖 docker 全栈,本轮未执行(plan 已声明) |

TC-07 三档关键数值:

| 视口 | 整页溢出 | 卡片内滚动 | 「已自动禁用」徽标 | 归档标 | 操作菜单 |
|---|---|---|---|---|---|
| 1280 | 0px | 142px(plan 未在此档断言) | w=78,[553,631] ⊂ 单元格 [297,639] | w=16,[1007,1023] ⊂ [755,1031] | 触发器 + 四项均可见 |
| 1440 | 0px | **0px**(plan 断言档) | w=78,[553,631] ⊂ [297,645] | w=16,[1015,1031] ⊂ [763,1043] | 触发器 + 四项均可见 |
| 1920 | 0px | 0px | w=78,[553,631] ⊂ [297,796] | w=16,[1218,1234] ⊂ [966,1368] | 触发器 + 四项均可见 |

两种徽标在三档下 `checkVisibility()` 均为 `true`、矩形均完整落在所属单元格内。
修复前同页面整页溢出为 1280/1440/1920 各 256px(`evidence/prod-overflow-measurements.txt`)。

## 与方案的偏差

沿用第 01 轮记录的 5 条(新增 `sidebar.test.tsx`、截断宽度 18rem→15rem、抽出
`TruncatedLabel`、TC-02b 用 `{Escape}` 做确定性 dismiss、TC-07 承载环境改为生产
静态导出),本轮未新增偏差。

其中第 5 条在本轮被评审 R-02 间接印证并已写进脚本头注释:`next dev` 下页面不
hydrate,数据加载的 `useEffect` 不执行,表格恒为空,无法承载布局断言;生产静态
导出才是线上真实形态(由 dopilot-server 托管)。
