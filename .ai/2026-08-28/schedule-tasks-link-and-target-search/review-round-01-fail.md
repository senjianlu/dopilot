# 评审:第 01 轮

## 问题清单
- [blocker] R-01 TC-05、TC-10、TC-14 的 A 档证据未覆盖方案中的完整断言，却被记录为通过
  - 详情:.ai/2026-08-28/schedule-tasks-link-and-target-search/plan.md:308、313、317 要求分别验证带边缘空格的查询、299/300ms 防抖边界，以及 q/status/scheduleId 同时保持最新值；但 apps/server/tests/test_task_filters.py:177-190 从未传入 `"  alpha  "`，apps/web/app/(app)/tasks/__tests__/tasks.test.tsx:271-292 只等待 150ms（若实际防抖为 151–299ms 仍会通过），同文件:316-357 未把 status 改为 failed，也未断言 `status: "failed"`。implementation-round-01.md:45、49、73-74 仍将这些用例记为 pass，并声称覆盖与方案完全一致，按证据契约属于虚报测试。需要补交：TC-05 增加带边缘空格与普通查询结果等价的断言，并提交对应后端命令、完整 stdout/stderr、退出码；TC-10 增加 299ms 不请求、跨过 300ms 请求的确定性断言；TC-14 同时变更 status、清除调度并断言最终请求含 `q: "alpha"`、`status: "failed"`、`scheduleId: null`，随后为 TC-10/14 提交任务页 Vitest 命令、完整 TAP/stdout/stderr、退出码。
- [minor] R-02 调度筛选芯片的清除动作绕过了项目的 shadcn Button 组合约定
  - 详情:apps/web/app/(app)/tasks/page.tsx:246-254 在 Badge 内手写 `<button>`，并直接给 X 图标添加 `size-3`。这绕过了 Button 的焦点、尺寸和图标样式约定；建议改用 `Button variant="ghost" size="icon-xs"`，保留 aria-label/data-testid，并移除图标尺寸类。

## 总评
后端过滤、前端状态收敛和主要证据文件整体与方案一致，原始命令输出及退出码也基本完整。但三个 A 档用例的实际断言低于方案契约且仍被报告为通过，因此本轮必须判定 fail；评审按要求未运行任何测试。

VERDICT: fail
