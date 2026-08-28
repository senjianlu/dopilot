# 前端（apps/web）

> 决策依据:[0006 技术栈](../decisions/0006-fastapi-backend-nextjs-static-frontend.md)。

- **Next.js 静态导出**（`output: export` + `trailingSlash`）+ shadcn/ui
  （slate 基色、明暗主题 next-themes）+ Recharts + react-i18next +
  TypeScript;greenfield SPA，经 axios 直连 `/api/v1`，实时日志经 SSE
  （短期 `stream_token` 建连、`Last-Event-ID` 重连补洞）。
- 目录:`app/`（Next 路由，每路由一个 HTML）、`components/`（`ui/`
  shadcn 手写件 + 业务件）、`lib/`（api 客户端 / i18n 等）、`hooks/`、
  `e2e/`（Playwright）。
- **生产无 Node 运行时**:`pnpm --filter web build` 产出 `apps/web/out`
  （每路由 HTML + `_next/` + `404.html`），镜像构建期拷入 `/app/web`，由
  `dopilot-server` 同源托管（`DOPILOT_WEB_DIST=/app/web`）;`/api/*` 永不
  被改写为 HTML。无独立 Web 容器、无 `next start`。
- 开发:`next dev` 经 `NEXT_PUBLIC_API_BASE` 指向 server。
- **日志查看器(`components/features/log-viewer.tsx`)**:SSE 收流 + 一个
  **复制**按钮,把**当前视图缓冲**写进剪贴板(不发请求)。范围刻意不是"整个
  日志文件"——首屏只回放尾部(`logs.first_screen_max_lines` /
  `first_screen_max_bytes`),按钮的无障碍说明 `logs.copyHint` 明写这一点。
  非安全上下文(http://)下 `navigator.clipboard` 不存在,写入被拒亦然,两种
  情况都弹 error toast 而非静默失败。
- **调度并发上限(`/schedules`)**:新建/编辑对话框的 `max_concurrency` 数字项
  (默认 1,`min=0`),列表列把 `0` 渲染为"不限"。`0` 是
  [0022](../decisions/0022-schedule-concurrency-limit.md) 的逃生舱,解析时
  不得用 `Number(v) || 1` 一类写法把它吞成 1。手动触发命中上限时后端返回
  409 `schedule.concurrency_limit`,页面弹 toast 且**不跳转**。
- **任务下钻与目标名搜索(`/tasks`)**:`/schedules` 每行的「任务记录」链接跳到
  `/tasks?schedule_id=<id>&schedule_name=<name>`,任务页据此初始化筛选并渲染一个
  可清除的调度芯片(`schedule_name` 纯展示,不参与请求;清除时同时
  `router.replace("/tasks")` 抹掉 query,免得刷新后筛选复活)。搜索框对
  `tasks.target` 做大小写不敏感子串匹配(300ms 防抖,回车立即),`maxLength`
  与后端 `MAX_TARGET_QUERY_LEN=100` 对齐,使 UI 无法构造出会被 400 拒绝的请求;
  搜索取舍见 [0023](../decisions/0023-task-target-search-without-trigram-index.md)。
  **实现约束**:该页把 `page/pageSize/build/status/scheduleId/q` 收敛为**单一
  `filters` 对象**,全部变更走函数式 `setFilters(prev => ...)`,请求由**唯一一个**
  以 `filters` 为依赖的 effect 发出。这不是风格偏好——防抖回调若按老写法把当时
  的筛选值当实参快照传出去,用户在 300ms 内改了下拉就会发出**新旧混合**的请求,
  且它反而更晚返回从而覆盖正确结果。过期响应由 effect cleanup 的 `alive` 标志
  丢弃。因页面读 `useSearchParams`,组件须置于 `React.Suspense` 边界内,否则静态
  导出构建直接失败。
- **运维清理页(`/maintenance`)**:双职责——(1) 资源仪表盘,约 10s 轮询
  `GET /maintenance/resource-stats` 的内存快照,按 scope(server 磁盘 /
  PostgreSQL / Redis / 每 agent)分组展示当前值、上限、`Progress` 用量条与
  等级 `ToneBadge`(ok→green/warn→amber/critical→red/unknown→gray),scope 级
  `stale`/`unavailable` 有独立标注;首次采样前显示骨架。(2) 三个安全操作
  (立即保留清扫 / 终态清理 dry-run+确认 / Redis 重写 AOF),均经 `useConfirm`
  确认、内联 `Alert`/summary 呈现。配置面见
  [04-configuration](04-configuration.md)。
- **消息中心(顶栏铃铛,`components/layout/notification-bell.tsx`)**:每 30s
  轮询 `GET /notifications/unread-count` 显示未读徽标(>99 显示 `99+`);下拉时
  拉 `GET /notifications?limit=20`,每条按 `type` + `payload` 经 i18n
  `notifications.types.<type>.{title,body}` 渲染(server 不存自然语言),未读加粗、
  `count` 折叠显示 `×N`;点击条目 `POST /notifications/read` 并跳转
  (`schedule_auto_disabled` → `/schedules?highlight=<id>`,`log_flood` /
  `log_truncated` → 既有静态路由 `/tasks/detail?id=<task_id>`,资源类 →
  `/maintenance`);底部「全部已读」。调度页对 `auto_disabled_at` 非空的行显示
  「已自动禁用」`Badge`(tooltip 含连续出错次数与时间),重新打开走既有
  `PUT /schedules/{id}`。机制见 [03-execution-and-logs](03-execution-and-logs.md#任务结果记录与调度自动禁用)。
- i18n 默认中文;后端 API 只返回结构化 message code，文案映射在前端。
- 测试:vitest + @testing-library/react + jsdom（单测/组件），Playwright
  （e2e，选择器走 `data-tone`/`data-testid`）;lint 为 ESLint flat config;
  类型检查 `tsc --noEmit` 独立 script。
