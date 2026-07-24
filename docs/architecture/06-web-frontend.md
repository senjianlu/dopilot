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
- i18n 默认中文;后端 API 只返回结构化 message code，文案映射在前端。
- 测试:vitest + @testing-library/react + jsdom（单测/组件），Playwright
  （e2e，选择器走 `data-tone`/`data-testid`）;lint 为 ESLint flat config;
  类型检查 `tsc --noEmit` 独立 script。
