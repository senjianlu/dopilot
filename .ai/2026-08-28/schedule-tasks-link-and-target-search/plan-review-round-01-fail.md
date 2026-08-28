# Plan 评审:第 01 轮

## 问题清单
- [major] R-01 异步筛选请求缺少“仅最新响应生效”机制，旧结果可能覆盖新搜索结果
  - 详情:定位：plan.md:172-183。方案仅对输入定时器做防抖；`load()` 仍是并发异步请求并在完成后直接写入页面状态。若旧查询响应晚于新查询，页面会在显示新搜索词时呈现旧结果。应通过 AbortController、请求序号或等价机制丢弃过期响应，并增加受控 Promise 乱序完成的测试；回车立即搜索时也应取消待触发的防抖请求。
- [major] R-02 前端未处理后端规定的 100 字符搜索上限，合法 UI 操作可产生未处理的 400
  - 详情:定位：plan.md:131-145、169-175、TC-07。搜索框允许任意长度，但后端会拒绝超过 100 字符的 `q`；现有 `load()` 模式没有错误处理，因此粘贴长文本会留下旧结果并产生 rejected Promise。TC-07 只验证后端拒绝，未覆盖页面行为。应给输入设置一致的 `maxLength`，或提供明确错误反馈，并增加对应前端边界测试。
- [major] R-03 测试在关键适配层两侧均使用 mock，无法证明新筛选参数真正贯通前后端
  - 详情:定位：plan.md:224-234。TC-02/03 直接测试服务层，TC-07 只测试 API 的超长分支，没有成功的 `GET /api/v1/tasks?q=...` 用例；TC-08/09/10 又 mock 了 `listTasks`，不会执行 `lib/api/tasks.ts` 中 camelCase 到 `schedule_id`/`q` 的序列化。遗漏 API 透传或 axios 参数映射时现有用例仍可全绿。应增加成功的 HTTP `q` 过滤用例，并直接验证 `listTasks()` 发出的 `schedule_id`、`q` 参数。
- [major] R-04 TC-12 既未验证静态导出构建，所列前端命令在仓库根目录也不可执行
  - 详情:定位：plan.md:235、245；pnpm-workspace.yaml:1-2；apps/web/package.json:6-14；apps/web/next.config.js:3-12。仓库根没有 package.json，根目录执行 `corepack pnpm exec vitest`、`pnpm lint`、`pnpm exec tsc` 会报无 workspace package；应明确 `cwd=apps/web` 或使用 `--filter web`。此外 tsc、lint、Vitest 无法验证 Next 静态导出对 `useSearchParams`/Suspense 的构建约束，风险表称其可兜底并不成立；TC-12 应加入 `corepack pnpm --filter web build` 的 A 档完整证据。

## 总评
方案的后端过滤思路、工作流轮次设置及逐条 A 档证据声明基本自洽，C 档数量也合规。但请求竞态、前端长度边界及关键透传和静态导出验证仍存在必须在实现前修订的 major，因此本轮判定 fail。

VERDICT: fail
