# 0006:FastAPI 后端 + Next.js 静态导出前端（由 server 托管）

- 日期:2026-06-17（前端选型于阶段 2.1 修订）
- 背景:dopilot 前后端整体重构为 greenfield：后端不继承 Flask/Jinja，前端
  不继承任何 scrapydweb 模板，需要一套前后端分离且部署最简（无独立 Web
  容器）的技术栈。
- 决定:后端 **FastAPI + Pydantic + ASGI**（`apps/server`，提供 `/api/v1/*`
  JSON/SSE API）。前端为 **greenfield SPA**：**Next.js 静态导出
  （`output: export` + `trailingSlash`）+ shadcn/ui + Recharts +
  react-i18next + TypeScript**（`apps/web`）。构建产物为纯静态 HTML/CSS/JS，
  由 `dopilot-server` 同容器托管（`DOPILOT_WEB_DIST=/app/web`），**无
  `next start`、无 Node 生产运行时、无独立 Web 容器**。i18n 默认中文，后端
  仅返回结构化 message code，文案映射在前端。不内置 nginx，反向代理是用户
  可选部署层（SSE 路径须关缓冲，FastAPI SSE 响应带 `X-Accel-Buffering: no`）。
- 影响:
  - dopilot 无任何继承的 Jinja 页面，不存在 Jinja/SPA 共存或 strangler 迁移。
  - `/api/*` 永不被静态托管改写为 HTML。
  - 前端测试为 vitest + Testing Library（e2e 为 Playwright），lint 为 ESLint
    flat config。

## 修订

- 阶段 2.1:前端技术栈由初始选型 **Vue 3 + Element Plus + Vite + vue-i18n**
  整体替换为上述 Next.js 栈（页面、组件、i18n、测试栈全部迁移）；决策的
  前后端分离、静态托管、无 Node 运行时等约束不变。
