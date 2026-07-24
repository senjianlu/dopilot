# 0017:测试基线：scrapydweb 测试仅为 oracle，dopilot 自有测试是回归网

- 日期:2026-06-17
- 背景:上游 scrapydweb 自带 146 个集成测试（强依赖真实 Scrapyd、外网凭据、
  HTML 文案断言）。需要界定它们与 dopilot 回归体系的关系，避免把上游测试
  当门禁。
- 决定:scrapydweb 的测试套件是**仅针对上游的行为 oracle**——移植某个域时
  读它、提取"输入→输出语义"作对照清单；**不是 dopilot 的回归网、不进
  dopilot CI**。dopilot 从第一天起写**自己的测试**：`apps/server/tests/`、
  `apps/agent/tests/`、`packages/protocol/tests/`（pytest），`apps/web`
  （vitest + Testing Library / Playwright e2e），绑定 dopilot 自己的 CI
  （GitHub Actions）。
- 影响:
  - 测试原则：后端测 `/api/v1` JSON 契约不测文案；executor 层可 mock、不
    依赖外部 Scrapyd；**Redis 通信可靠性域（command outbox/幂等/offset
    gap/heartbeat/lost/reconcile）无任何上游 oracle**，用 Redis 容器或
    fakeredis + 注入式故障自构造，验收清单以
    [0008](0008-redis-streams-agent-communication.md)/[0009](0009-realtime-logs-redis-push-sse.md)
    的语义为准。
  - 常用验证命令：`pytest`、`ruff check apps packages`、
    `corepack pnpm --filter web test`、`corepack pnpm --filter web build`、
    `cd deploy/docker && docker compose config`；Scrapy 端到端
    `scripts/smoke-phase1.sh`。
