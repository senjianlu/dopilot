---
task: fix-console-horizontal-overflow
date: 2026-09-16
rounds: 3
verdict: pass
---

# 任务小结:修复控制台整页横向滚动,并收窄调度页列宽

## 背景一句话

生产控制台的定时调度页出现整页横向滚动条,由 steammarket-spider 2026-09-15
新增的超长命名(`steammarket-spider | JUSTONEAPI STEAM_GIFT_CARD_USD_100_TAOBAO_CNY`
及其 `| template` 模板)触发。Playwright 登录生产实测后定位为**全局布局缺陷**:
`SidebarInset` 缺 `min-w-0`,导致所有含宽表的页面恒定溢出一个侧边栏宽度(256px),
与视口多宽无关;调度页只是内容最宽、最先暴露的地方。

## 改动

| 文件 | 摘要 |
|---|---|
| `apps/web/components/ui/sidebar.tsx` | **根因**:`SidebarInset` 补 `min-w-0`,附注释说明它承重、不可当冗余类删除 |
| `apps/web/app/(app)/schedules/page.tsx` | 新增局部组件 `TruncatedLabel`(截断 span 自身即 tooltip 触发器 + `tabIndex={0}` + `title` 兜底);名称/模板列 `max-w-[15rem] truncate`,徽标 `shrink-0` 留在截断区外;操作列四按钮收进 `DropdownMenu` |
| `apps/web/app/(app)/schedules/__tests__/schedules.test.tsx` | 加 `openRowActions` helper 适配菜单;新增 5 条用例覆盖截断、tooltip 双路径可达、菜单收纳、删除取消分支、徽标不被截断 |
| `apps/web/components/ui/__tests__/sidebar.test.tsx` | 新增,`min-w-0` 回归断言 |
| `apps/web/lib/i18n/locales/{zh,en}.ts` | 新增 `schedules.moreActions`(更多操作 / More actions) |
| `apps/web/e2e/specs/phase1-ui.spec.ts` | 点「立即触发」前先点开 `schedule-actions-*` |
| `docs/architecture/06-web-frontend.md` | 回写两条:全局布局约束(`min-w-0` 为何承重)、调度页行操作与长名截断策略;并更正「任务记录」链接现位于「⋯」菜单内 |

## 效果(TC-07,生产静态导出产物 + Playwright,三档视口)

| 视口 | 整页溢出(修复前 → 后) | 卡片内滚动 |
|---|---|---|
| 1280 | 256px → **0px** | 142px(plan 未在此档断言) |
| 1440 | 256px → **0px** | 754px → **0px** |
| 1920 | 256px → **0px** | 0px |

根因修复同时消除了 `/templates`(256px)、`/tasks`(250px)、`/artifacts`(68px)
的整页溢出;`/dashboard` 与 `/nodes` 当时内容尚不够宽、未暴露,同样受益。
「已自动禁用」徽标与归档标在三档下均 `checkVisibility()=true` 且矩形完整落在
所属单元格内;操作菜单触发器与四个菜单项三档均可见。

## 评审历程

### plan 阶段(上限 8,用 2 轮)

| 轮次 | 结论 | 关键问题 |
|---|---|---|
| 01 | fail | R-01 major:完整名称只验 `title`,未验证 tooltip 实际可达(hover/键盘)。R-02 major:jsdom 不算布局,徽标裁剪的边界验收不真实 |
| 02 | pass | 无 |

### 实现阶段(上限 8,用 3 轮)

| 轮次 | 结论 | 关键问题 |
|---|---|---|
| 01 | fail | R-01 blocker:TC-08 的 test 日志被 `tail -14` 截断,不满足 A 档证据契约。R-02 blocker:TC-07 的徽标与菜单验收只在 1440 档做,plan 要求三档 |
| 02 | fail | R-01 blocker:实现记录称 16 处 act 告警全部来自 maintenance,与原始日志矛盾(实为 maintenance 4 处 + notification-bell 12 处)——我的归属统计正则漏掉了 `components/layout/` 路径 |
| 03 | pass | 无 |

两个阶段的轮次上限均按用户 2026-09-16 的明确要求放宽为 8(写在 plan.md
frontmatter 的 `plan_review_max_rounds` / `impl_fix_max_rounds`)。

## 与方案的偏差(详见 implementation-round-01.md)

1. 新增 plan 改动范围表外的 `apps/web/components/ui/__tests__/sidebar.test.tsx`(承载 TC-01)
2. 截断宽度 `18rem` → `15rem`:plan 估算时未计入 78px 宽的「已自动禁用」徽标,
   实测 18rem 在最坏叠加下卡片内仍溢出 78px
3. 抽出局部组件 `TruncatedLabel`,避免名称/模板两处重复(结构与 plan 一致)
4. TC-02b 的 tooltip 关闭断言补 `{Escape}` 做确定性 dismiss(预期结果与档位均未改),
   `focus()/blur()` 用 `act(...)` 包裹以免引入新告警
5. TC-07 承载环境由 `next dev` 改为**生产静态导出产物**:dev 下页面不 hydrate,
   数据加载 effect 不执行、表格恒空,无法承载布局断言;静态导出才是线上真实形态

## 遗留 minor 及处置

无。最后一轮评审问题清单为空。

## 未执行项

`apps/web/e2e/specs/phase1-ui.spec.ts` 的 e2e 实跑依赖 docker 全栈(server + 3 agents
+ PostgreSQL + Redis),本任务未具备条件执行,已按 plan 声明以 TC-09 的 B 档静态引用
(`phase1-ui.spec.ts:314-315`)兜底。下次跑 phase1 smoke 时会覆盖到。
