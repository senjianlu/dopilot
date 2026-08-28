# 评审:第 02 轮

## 问题清单
- [plan-blocker] R-01 暂缓 pg_trgm 的方案依据包含错误的 PostgreSQL 权限前提
  - 详情:.ai/2026-08-28/schedule-tasks-link-and-target-search/plan.md:289、docs/decisions/0023-task-target-search-without-trigram-index.md:25 / 项目使用 PostgreSQL 16，而该版本的 pg_trgm 属于 trusted extension；拥有当前数据库 CREATE 权限的非超级用户即可安装，并非必然需要 DBA/超级用户。该错误前提直接支撑“不引入扩展”的架构取舍，需退回方案阶段按真实权限条件重新评估；若仍决定暂缓，应改写 plan 与 ADR 的理由。
- [minor] R-02 调度筛选芯片的清除动作仍绕过 shadcn Button 组合约定
  - 详情:apps/web/app/(app)/tasks/page.tsx:246 / Badge 内仍使用手写 button，并在 X 图标上直接设置 size-3；上一轮遗留问题尚未处理。建议改用 Button 的 ghost/icon-xs 组合，保留 aria-label 与 data-testid，并移除图标尺寸类。
- [minor] R-03 ADR 0023 对部署形态的决策编号引用错误
  - 详情:docs/decisions/0023-task-target-search-without-trigram-index.md:26、42 / 文档将 0002 和 0009 标注为部署形态依据，但它们分别讨论任务类型分期与实时日志；单管理员、镜像角色及静态前端分别见 0003、0004、0006。建议替换为真实支持结论的决策编号或删除错误引用。
- [minor] R-04 TC-14 全量回归仍产生未包裹 act 的 React 状态更新警告
  - 详情:apps/web/app/(app)/tasks/__tests__/tasks.test.tsx:356、.ai/2026-08-28/schedule-tasks-link-and-target-search/evidence/round02-tc-17-web-vitest.txt:11 / 用例虽通过且核心断言有效，但证据明确记录 TasksPageInner 更新未包裹 act，说明假时钟交互仍有未完整收敛的异步更新。建议把相关交互和计时器推进纳入 act，并在恢复真实计时器前等待请求状态完全结算。

## 总评
上一轮 blocker 涉及的 TC-05、TC-10、TC-14 已逐项补强，18 条 A 档用例均具备命令、完整输出和退出码，证据与通过结论一致。当前没有 blocker 或 major，因此实现评审按规则为 pass；但架构理由中的 PostgreSQL 权限事实仍需回到方案层修正。

VERDICT: pass
