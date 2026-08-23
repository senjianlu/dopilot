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
