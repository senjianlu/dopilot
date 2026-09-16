---
status: approved
task: fix-console-horizontal-overflow
date: 2026-09-16
approved_at: 2026-09-16 15:13:42 +0900
plan_review_max_rounds: 8
impl_fix_max_rounds: 8
---

# 方案:修复控制台整页横向滚动,并收窄调度页列宽

> 轮次上限说明:用户于 2026-09-16 明确要求「plan 和改修的 review 都上升到
> 最大 8 轮」,故本任务 frontmatter 覆盖默认的 3 轮为 8 轮。

## 背景与目标

生产控制台 https://dopilot.cscheap.com 的**定时调度**页出现整页横向滚动条。
2026-09-15 起 steammarket-spider 新增了超长命名的调度与模板
(`steammarket-spider | JUSTONEAPI STEAM_GIFT_CARD_USD_100_TAOBAO_CNY`,
模板名再加 ` | template`),把问题暴露了出来。

### 根因(已用 Playwright 在生产实测坐实)

`apps/web/components/ui/sidebar.tsx:307-318` 的 `SidebarInset` 是
`sidebar-wrapper`(flex 行)的子项,写了 `flex-1 w-full` 但**缺 `min-w-0`**。
flex 子项默认 `min-width: auto`,其自动最小尺寸取 *specified size suggestion*
(`width:100%` 换算值)与 *content size suggestion*(内容 min-content)中的
**较小者**。表格内容一长,content suggestion 被撑大,最小尺寸就落在
`width:100%` = 整个视口宽;而 inset 左边缘在 x=256(侧边栏之后),右边缘
= 256 + 视口宽,于是**整页恒定溢出 256px(= 侧边栏宽度),与视口多宽无关**。

实测(`evidence/prod-overflow-measurements.txt`,视口 1280/1440/1920 三档):

| 页面 | 修复前整页溢出 | 注入 `min-width:0` 后 |
|---|---|---|
| /schedules | 256px | 0 |
| /templates | 256px | 0 |
| /tasks | 250px | 0 |
| /artifacts | 68px | 0 |
| /dashboard | 0(内容尚未够宽) | 0 |
| /nodes | 0(内容尚未够宽) | 0 |

即:**这是全局布局缺陷,调度页只是内容最宽、最先暴露的地方**;dashboard 与
nodes 只是暂时没踩到,同样带雷。

### 第二层问题

只补 `min-w-0` 后整页滚动消失,但调度表内容宽 1856px、可用仅 1102px,
**「操作」列(任务记录/立即触发/编辑/删除)被推出视野**,需在卡片内横向滚
才够得着。主因是名称列 534px + 模板列 603px,两列内容高度重复。实测把两列
截断到 22rem 仍剩 353px 要滚;操作列四个按钮合计约 280px,收进「⋯」下拉后
可省约 220px,名称/模板各留 18rem 即可让卡片内也不必滚动。

### 目标

1. 消除整页横向滚动(根因修复,惠及全部页面)。
2. 调度页在 1440 宽视口下,整页与卡片内**均无横向滚动条**,且操作入口完整可达。
3. 截断后仍能看到完整名称(tooltip)。

### 明确不做

- **不动** tasks / templates / artifacts / dashboard / nodes 页的列布局。
  它们的整页溢出由根因修复一并解决;列内滚动不在本次范围(用户已明确
  「不要偏移」)。
- 不改后端、不改调度数据模型、不改命名规则。
- 不处理 `.ai/2026-09-15/stuck-scrapy-job-holds-schedule-slot/` 的超时议题
  (用户已决定另开任务,走「无活动超时」路线)。

## 改动范围

| 文件 | 改动 |
|---|---|
| `apps/web/components/ui/sidebar.tsx` | `SidebarInset` 补 `min-w-0`(根因) |
| `apps/web/app/(app)/schedules/page.tsx` | 名称/模板列截断 + tooltip;操作列四按钮收进 `DropdownMenu` |
| `apps/web/app/(app)/schedules/__tests__/schedules.test.tsx` | 适配菜单交互,新增截断/菜单用例 |
| `apps/web/lib/i18n/locales/zh.ts` | 新增 `schedules.moreActions` |
| `apps/web/lib/i18n/locales/en.ts` | 同上 |
| `apps/web/e2e/specs/phase1-ui.spec.ts` | 第 313 行点击「立即触发」前先开菜单 |

共 6 个文件(≤10,按 CLAUDE.md 不强制 plan 评审闸;本任务仍主动跑一轮)。
`dropdown-menu.tsx` 与 `tooltip.tsx` 已在 `apps/web/components/ui/` 入库,
无需新增 shadcn 组件。

## 实现方案

### 1. 根因:`SidebarInset` 补 `min-w-0`

```
- "relative flex w-full flex-1 flex-col bg-background"
+ "relative flex w-full min-w-0 flex-1 flex-col bg-background"
```

`min-w-0` 使自动最小尺寸归零,flex 收缩生效,inset 宽度回到「视口宽 − 侧边栏宽」;
超宽表格改由 `Table` 自带的 `table-container`(`overflow-x-auto`)内部滚动 ——
这本就是 shadcn 的设计意图。注释说明为何必需,避免后续被当成冗余类删掉。

### 2. 名称列与模板列截断 + tooltip

两列改为「外层 flex(不截断) + 内层文本 span(截断)」结构:

```
<span className="flex items-center gap-2">          {/* 外层:不截断 */}
  <Tooltip>
    <TooltipTrigger asChild>
      <span tabIndex={0} title={fullName}
            className="block max-w-[18rem] truncate">{fullName}</span>
    </TooltipTrigger>
    <TooltipContent>{fullName}</TooltipContent>
  </Tooltip>
  {badge /* auto-disabled Badge 或 ArchivedIndicator */}
</span>
```

三条要点:

1. **截断的文本 span 本身就是 tooltip 触发器**,并带 `tabIndex={0}`,所以
   hover 与 Tab 聚焦两条路径都能唤出完整原文 —— 与本页「已自动禁用」徽标
   的既有做法一致(`page.tsx:466-476` 用真实 `<button>` 做可聚焦触发器,
   单测 `schedules.test.tsx:523-533` 已验证 hover 与聚焦两条路径)。这里
   文本节点用 `<span tabIndex={0}>` 而非 `<button>`,避免把纯文本标成按钮
   语义,可聚焦性由 `tabIndex` 保证。
2. 原生 `title` 只作**额外**兜底(无 JS / 无 hover 环境),**不作为验收
   依据** —— TC-02 断言的是 tooltip 真的可达,不是 `title` 存在。
3. 名称列右侧的「已自动禁用」Badge 与模板列的 `ArchivedIndicator` **留在
   截断区之外**(外层 flex 的兄弟节点,`shrink-0`),否则会被一起截掉。
   jsdom 不计算布局、验不出裁剪,故该边界由 TC-07 在真实浏览器里验证。

### 3. 操作列收进下拉菜单

四个 `Button` 换成 `DropdownMenu`:触发器是 `size="icon"` 的
`MoreHorizontal`(lucide-react,已在依赖内)ghost 按钮,
`data-testid={`schedule-actions-${schedule.name}`}`,
`aria-label={t("schedules.moreActions")}`。

菜单项保持原有四项与既有 `data-testid`(`schedule-tasks-*` /
`schedule-trigger-*` / `schedule-edit-*`,删除项补
`schedule-delete-*`),这样测试与 e2e 只需多一步「开菜单」,不必重写选择器。
「任务记录」用 `DropdownMenuItem asChild` 包 `Link` 保持可导航;「删除」用
`variant="destructive"`。触发中的 Spinner 移到菜单项内,`disabled` 语义不变。

### 4. i18n

`schedules.moreActions`:zh「更多操作」/ en「More actions」。仅此一个新 key。

### 5. 测试与 e2e 适配

现有单测直接 `click(getByTestId("schedule-trigger-demo-schedule"))`,菜单化后
需先点开 `schedule-actions-demo-schedule`。e2e `phase1-ui.spec.ts:313` 同理。

## 测试用例

| 编号 | 档位 | 前置条件 | 步骤 | 预期结果 | 证据形态 |
|---|---|---|---|---|---|
| TC-01 | A | web 单测环境 | 渲染 `SidebarInset`,读其 className | 含 `min-w-0`;`pnpm -C apps/web test` 通过 | 命令 + 完整输出 + 退出码 |
| TC-02 | A | 调度列表含超长名(`steammarket-spider \| JUSTONEAPI STEAM_GIFT_CARD_USD_100_TAOBAO_CNY`) | 渲染调度页,取名称/模板单元格的文本 span | 带 `truncate` 与 `max-w-[18rem]` | 命令 + 完整输出 + 退出码 |
| TC-02b | A | 同上 | 对**名称**与**模板**两个截断 span 分别:①`user.hover` ②`.focus()` 键盘聚焦(先断言 `tabIndex === 0`) | 两条路径都使 `TooltipContent` 出现且文本等于**完整原文**;`unhover`/`blur` 后消失。按 `schedules.test.tsx:523-533` 既有 tooltip 断言模式 | 命令 + 完整输出 + 退出码 |
| TC-03 | A | 同上 | 渲染后立即查询菜单四项 | 四项均不在文档中;点击 `schedule-actions-*` 后四项全部可见 | 命令 + 完整输出 + 退出码 |
| TC-04 | A | 同上 | 开菜单 → 点 `schedule-trigger-*` | `triggerSchedule` 被调用一次且入参为该调度 id | 命令 + 完整输出 + 退出码 |
| TC-05 | A | 同上(破坏性路径) | 开菜单 → 点 `schedule-delete-*` → 确认框取消 | `deleteSchedule` **未**被调用;再走一次并确认,则被调用一次 | 命令 + 完整输出 + 退出码 |
| TC-06 | A | 名称列带「已自动禁用」徽标、模板列带 ArchivedIndicator | 渲染后取徽标与 ArchivedIndicator,检查其**在 DOM 中的位置** | 二者在文档中,且**不是截断 span 的后代**(`truncateSpan.contains(badge) === false`)——结构上就不可能被裁掉;真实裁剪由 TC-07 验 | 命令 + 完整输出 + 退出码 |
| TC-07 | A | 本地 `next dev` + Playwright,`page.route` mock `/api/v1/*`。**数据须同时含**:超长调度名、超长模板名、`auto_disabled_at` 非空(渲染「已自动禁用」徽标)、模板已归档(渲染 ArchivedIndicator) | 在 1280/1440/1920 三档视口量测 | ①`documentElement.scrollWidth === clientWidth`(整页零溢出);②1440 档 `table-container` 的 `scrollWidth <= clientWidth`(卡片内亦无滚动);③徽标与 ArchivedIndicator 的 `getBoundingClientRect()` **完整落在其所属单元格的可视矩形内**(未被 `overflow:hidden` 裁掉),且 `checkVisibility()` 为真;④操作菜单触发器 `schedule-actions-*` 可见,点击后四个菜单项均可见 | 脚本 + 三档完整数值输出 + 退出码 |
| TC-08 | A | 仓库工作区 | `pnpm -C apps/web lint`、`pnpm -C apps/web typecheck`、`pnpm -C apps/web test` | 全部通过,无新增告警 | 命令 + 完整输出 + 退出码 |
| TC-09 | B | e2e spec 已改 | grep `phase1-ui.spec.ts` 中触发调度的片段 | 点击 `schedule-trigger-*` 前存在 `schedule-actions-*` 的点击(带文件:行号);e2e 实跑需 docker 全栈,不在本次执行 | 代码引用 `文件:行号` |

C 档 0 条(本任务无不可自动化的人工交互项)。

## 风险与回滚

- **`min-w-0` 波及全站**:它放宽约束(允许收缩),不会让任何页面变得更宽;
  TC-07 覆盖三档视口,TC-08 全量回归。若真有页面依赖旧的「被撑开」行为,
  回滚只需删掉这一个类。
- **菜单化降低操作可发现性**:四个操作从一眼可见变成两步。这是用户在本轮
  明确选定的取舍(「根因 + 截断 + 操作列收菜单」)。破坏性的「删除」仍保留
  既有确认框(TC-05 覆盖)。
- **截断可能藏掉关键信息**:截断 span 自身即 tooltip 触发器且 `tabIndex={0}`,
  hover 与键盘聚焦两条路径都能唤出完整原文(TC-02b 逐条断言),原生 `title`
  另作无 JS 环境的兜底。徽标类信息(已自动禁用、已归档)结构上就在截断区
  之外(TC-06),真实不被裁剪由浏览器用例 TC-07 ③ 验证。
- **e2e 未实跑**:`phase1-ui.spec.ts` 依赖 docker 全栈(server + 3 agents +
  PG + Redis),本轮不具备条件,以 TC-09 静态引用兜底,并在报告中明确声明。
- **回滚**:6 个文件均为前端改动,`git revert` 单个提交即可完整回退,无数据
  迁移、无后端行为变化。
