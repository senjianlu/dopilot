---
task: fix-console-horizontal-overflow
round: 01
date: 2026-09-16
---

# 实现记录:第 01 轮

## 本轮改动

| 文件 | 改动摘要 |
|---|---|
| `apps/web/components/ui/sidebar.tsx` | `SidebarInset` 补 `min-w-0`(根因),附注释说明它承重、不是冗余类 |
| `apps/web/app/(app)/schedules/page.tsx` | 新增页面内局部组件 `TruncatedLabel`(截断 span 自身即 tooltip 触发器,`tabIndex={0}` + `title` 兜底);名称/模板列改「外层 flex 不截断 + 内层文本截断」,徽标 `shrink-0` 留在截断区外;操作列四个按钮收进 `DropdownMenu`(触发器 `schedule-actions-*`,菜单项沿用既有 testid 并补 `schedule-delete-*`) |
| `apps/web/app/(app)/schedules/__tests__/schedules.test.tsx` | 加 `openRowActions` helper 适配菜单;新增 describe 覆盖 TC-02/02b/03/05/06 |
| `apps/web/components/ui/__tests__/sidebar.test.tsx` | **新增**,承载 TC-01 的 `min-w-0` 回归断言 |
| `apps/web/lib/i18n/locales/zh.ts` | 新增 `schedules.moreActions: "更多操作"` |
| `apps/web/lib/i18n/locales/en.ts` | 新增 `schedules.moreActions: "More actions"` |
| `apps/web/e2e/specs/phase1-ui.spec.ts` | 点「立即触发」前先点开 `schedule-actions-*` |

实际 7 个文件(plan 预计 6,多出的是 TC-01 的新测试文件,见「与方案的偏差」1)。

## 修复对照

不适用(第 1 轮)。

## 测试结果

| 编号 | 档位 | 结果 | 证据 |
|---|---|---|---|
| TC-01 | A | pass | `evidence/tc01-06-vitest.txt`(TAP `ok 42 - components/ui/__tests__/sidebar.test.tsx > SidebarInset > keeps min-w-0 …`) |
| TC-02 | A | pass | `evidence/tc01-06-vitest.txt`(`ok 92 - … > truncates the long schedule and template names`) |
| TC-02b | A | pass | `evidence/tc01-06-vitest.txt`(`ok 93 - … > surfaces the full name by hover and by keyboard focus`) |
| TC-03 | A | pass | `evidence/tc01-06-vitest.txt`(`ok 94 - … > keeps the four row actions behind the menu`) |
| TC-04 | A | pass | `evidence/tc01-06-vitest.txt`(`ok 71 - … > SchedulesPage > triggers a schedule and navigates to the created task`,经 `openRowActions` 开菜单后断言 `triggerSchedule("sch-1")`) |
| TC-05 | A | pass | `evidence/tc01-06-vitest.txt`(`ok 95 - … > does not delete from the menu when the confirm is cancelled`:取消分支 `deleteSchedule` 未调用、确认分支调用一次;另 `ok 79 - … > deletes a schedule only after confirmation` 是既有的确认分支用例,已适配菜单) |
| TC-06 | A | pass | `evidence/tc01-06-vitest.txt`(`ok 96 - … > keeps the auto-disabled badge and archived mark outside the truncation`) |
| TC-07 | A | pass | `evidence/tc07-layout-probe.txt`(12 项 PASS / `ALL CHECKS PASSED` / exit=0);脚本 `evidence/layout-probe.mjs`;截图 `evidence/schedules-after-fix.png` |
| TC-08 | A | pass | `evidence/tc08-lint-typecheck-test.txt`(lint exit=0、typecheck exit=0、test 128 passed exit=0,无新增告警) |
| TC-09 | B | pass | `apps/web/e2e/specs/phase1-ui.spec.ts:314-315`:`schedule-actions-${SCHEDULE_NAME}` 的 click 紧邻在 `schedule-trigger-${SCHEDULE_NAME}` 之前。e2e 实跑依赖 docker 全栈,本轮未执行(plan 已声明) |

TC-07 关键数值(`evidence/tc07-layout-probe.txt`):

- 整页溢出:1280 档 0px、1440 档 0px、1920 档 0px(修复前分别为 256 / 256 / 256px,见
  `evidence/prod-overflow-measurements.txt`)
- 1440 档卡片内:`table-container` scrollWidth=1102 clientWidth=1102,溢出 0px
- 「已自动禁用」徽标 width=78 落在单元格 [297,645] 内的 [553,631];归档标 width=16 落在
  单元格 [763,1043] 内的 [1015,1031];两者 `checkVisibility()` 均为真
- 操作菜单触发器可见,展开后 tasks / trigger / edit / delete 四项均可见

## 与方案的偏差

1. **新增了 plan 改动范围表之外的一个文件**:`apps/web/components/ui/__tests__/sidebar.test.tsx`。
   plan 的 TC-01 要求以 A 档断言 `SidebarInset` 带 `min-w-0`,而 `components/ui/` 下原本没有
   测试目录,必须新建文件承载。影响:仅新增测试,不触碰生产代码。

2. **截断宽度 `max-w-[18rem]` → `max-w-[15rem]`**。plan 基于生产量测估算 18rem 足够,但 TC-07
   的夹具按 plan 要求把四个恶化因素叠加(超长调度名 + 更长模板名 + 自动禁用徽标 + 归档标),
   首次运行 TC-07 ② 实测卡片内仍溢出 78px(scrollWidth=1180 / clientWidth=1102)——
   plan 估算时没把 78px 宽的徽标算进去。收窄到 15rem(240px)后归零。
   影响:名称/模板可见字符数减少约 3 个字,完整原文仍可由 tooltip(hover 与键盘聚焦两条
   路径)与 `title` 取得。单元测试断言同步改为 `max-w-[15rem]`。

3. **抽出页面内局部组件 `TruncatedLabel`**。plan 给的是内联 JSX 结构;名称列与模板列两处
   完全同构,内联会重复一遍 Tooltip/Provider 包装。结构、类名、`tabIndex`、`title` 与 plan
   所写一致,仅做了函数化。影响:无行为差异。

4. **TC-02b 的「消失」断言需要显式 `{Escape}` 才能确定性成立**。Radix 的 tooltip 默认 content
   可悬停,jsdom 里没有真实指针几何,单靠 `unhover` / `blur` 不足以触发关闭。**预期结果未
   改写、档位未下调**——仍然断言 tooltip 消失,只是补了一个确定性的 dismiss 动作,与本页既有
   auto-disabled 徽标测试(`schedules.test.tsx:531` 的 `user.keyboard("{Escape}")`)同一手法。
   同理 `focus()` / `blur()` 用 `act(...)` 包裹,以免引入新的 act 告警(TC-08 要求无新增告警)。

5. **TC-07 的承载环境从 `next dev` 换成生产静态导出产物**。plan 写「本地 `next dev` +
   Playwright」,实测 `next dev` 下页面不 hydrate:`useEffect` 不执行,整个页面加载期零
   `/api/v1` 请求(已单独验证 Playwright 的 route 拦截本身正常——页内手动 `fetch` 能被拦到),
   表格恒为「暂无调度」,无法承载布局断言。改为 `pnpm -C apps/web build` 产出 `apps/web/out`,
   用 `python3 -m http.server` 伺服,Playwright 照旧 `page.route` mock `/api/v1/**`。
   这比 dev server **更贴近生产**(线上就是静态导出由 FastAPI 托管)。
   TC-07 的数据条件与四项断言完全按 plan 执行,未增删。

以上 5 条均为实现层细节,未触及方案的架构、接口或范围(根因修复 + 调度页截断 + 操作列菜单化,
以及「不动其它页面列布局」的边界),故未中断实现向用户请示。
