# 决策记录

一事一文，文件名 `NNNN-<slug>.md`（NNNN 自 0001 递增），轻量四段：

```markdown
# NNNN:<决定一句话>

- 日期:<yyyy-mm-dd>
- 背景:为什么面临选择
- 决定:选了什么(含被否掉的主要备选)
- 影响:约束了什么,谁要跟着改
```

已确认的决策不再复议；要推翻就新增一条记录声明取代旧决策，并在旧
文件顶部加"已被 NNNN 取代"——不删除历史。

> 本目录 0001–0017 迁移自迁移前的 CLAUDE.md「Confirmed decisions」与
> `docs/dopilot/00-requirements.md` §4 决策表（git 历史可查）。「日期」
> 为原决策拍板日；未逐条留档的阶段性修订以「修订」小节按阶段标注。

## 索引

| # | 决策 |
|---|------|
| [0001](0001-scrapydweb-behavior-reference-only.md) | scrapydweb 仅作外部行为参考，绝不进入本仓库 |
| [0002](0002-three-job-types-strict-order.md) | 三类被调度对象按 Scrapy → Python 脚本 → Docker 严格分期 |
| [0003](0003-single-admin.md) | 单管理员，无多用户/RBAC |
| [0004](0004-two-docker-roles-unified-image.md) | server/agent 两种 Docker 角色，统一镜像 `rabbir/dopilot` |
| [0005](0005-monorepo-apps-packages.md) | monorepo：`apps/` + `packages/` 布局 |
| [0006](0006-fastapi-backend-nextjs-static-frontend.md) | FastAPI 后端 + Next.js 静态导出前端（由 server 托管） |
| [0007](0007-postgresql-only-log-bodies-on-disk.md) | PostgreSQL 唯一数据库；日志正文落文件不入库 |
| [0008](0008-redis-streams-agent-communication.md) | server↔agent 通信 = Redis Streams + agent 主动 heartbeat |
| [0009](0009-realtime-logs-redis-push-sse.md) | 实时日志：agent 推 Redis log stream + server 落盘 + SSE，无 WebSocket |
| [0010](0010-single-instance-server.md) | 单实例硬约束：server 单副本 + uvicorn `workers=1` |
| [0011](0011-auth-boundaries.md) | 认证边界：Web 管理员 fail-closed + 单一 agent 机器令牌 |
| [0012](0012-domain-model-clean-cut.md) | 领域模型：BuildArtifact → ExecutionTemplate → Schedule → Task → Execution |
| [0013](0013-python-wheel-execution-model.md) | Python 脚本以 `.whl` 接入：无 venv、无依赖解析 |
| [0014](0014-node-strategy-and-push-mode.md) | 节点策略三态（指定/全部/随机）与推模式 |
| [0015](0015-toml-config-no-scrapydweb-quirks.md) | TOML 配置 + env 覆盖；不继承 scrapydweb 配置形态与清目录行为 |
| [0016](0016-glibc-base-image-apscheduler-310.md) | glibc 基础镜像（非 Alpine）；APScheduler 3.10.x |
| [0017](0017-testing-baseline-own-regression-net.md) | 测试基线：scrapydweb 测试仅为 oracle，dopilot 自有测试是回归网 |
| [0018](0018-adopt-ai-workflow-template.md) | 采用 ai-workflow-template 的 rawf 治理流程，退役旧 Codex/Claude 治理 |
| [0019](0019-resource-hard-limits.md) | 资源硬上限：部署层/server/agent 各增长面配置化上限 + 自动过期，防日志/磁盘/内存膨胀 |
