# 架构总览

dopilot 是**自托管、单管理员**的调度平台（MIT 开源），在远端 worker 节点上
运行 Scrapy 爬虫与 Python 脚本，实时回流日志并留存每次运行记录。行为语义
参考上游 scrapydweb，但代码为 greenfield 全新编写——上游仅作外部行为参考，
绝不进入本仓库（[decisions/0001](../decisions/0001-scrapydweb-behavior-reference-only.md)）。

本目录组织:

| 文档 | 内容 |
|---|---|
| `README.md`(本文) | 目录地图 + 系统形态 |
| [`01-runtime-topology.md`](01-runtime-topology.md) | 运行拓扑:server / agent / Redis / PostgreSQL,三条 stream 与 heartbeat |
| [`02-domain-model.md`](02-domain-model.md) | 领域模型:BuildArtifact → … → Execution,快照与能力过滤 |
| [`03-execution-and-logs.md`](03-execution-and-logs.md) | 执行与日志链路:command outbox、幂等、lost/reconcile、日志完整性、日志洪泛防护、结果记录与自动禁用 |
| [`04-configuration.md`](04-configuration.md) | 配置与认证:TOML + env 覆盖,令牌体系 |
| [`05-deployment.md`](05-deployment.md) | 部署:统一镜像、三份 compose、持久化卷、CI、事故恢复 runbook |
| [`06-web-frontend.md`](06-web-frontend.md) | 前端:Next.js 静态导出 SPA、SSE、i18n、消息中心 |
| [`07-development-and-testing.md`](07-development-and-testing.md) | 开发环境与测试基线 |

> `README.md` 只做汇总和导航;某一主题超过本页简述体量时,下沉到同目录
> 文件并把入口写回上表。影响原因与取舍的长期决策在
> [`../decisions/`](../decisions/README.md)。

## 系统形态

monorepo（`apps/` + `packages/`,[decisions/0005](../decisions/0005-monorepo-apps-packages.md)）,
三个可部署单元 + 一个共享协议包:

```text
dopilot/                        # 仓库根 = Docker 构建上下文
├── apps/
│   ├── server/dopilot_server/  # FastAPI 调度中枢:api/v1、scheduler、executors、
│   │                           # redis(outbox/dispatcher/consumers)、auth、nodes、
│   │                           # logs、models、db、artifacts、agent_token
│   │   └── migrations/         # Alembic(server 独占 schema 演进)
│   ├── agent/dopilot_agent/    # worker 纯出站守护进程:redis(consumer/publisher)、
│   │                           # runners、scrapyd、artifacts、logs、state、healthcheck
│   └── web/                    # Next.js 静态导出 SPA(app/ components/ lib/ e2e/)
├── packages/protocol/          # server↔agent 共享 Pydantic 协议(streams.py 等)
├── deploy/docker/              # Dockerfile(.base) + 三份 docker-compose
├── configs/                    # server/agent TOML 配置样例
├── scripts/                    # dev-db / smoke / deps-hash 辅助脚本
├── examples/                   # 示例被调度对象(scrapy_clock)
└── docs/  .ai/                 # 持久真相 / 任务过程痕迹
```

部署单元与角色（[decisions/0004](../decisions/0004-two-docker-roles-unified-image.md)）:

| 角色 | 启动命令 | 职责 |
|---|---|---|
| **server** | `dopilot-server -b 0.0.0.0 -p 5000` | `/api/v1/*` JSON/SSE API + 同源托管 Web 静态产物;定时调度;唯一的 PostgreSQL 连接持有者;日志落盘 `/server-data/logs` |
| **agent** | `dopilot-agent`(无监听端口) | 纯出站 worker:消费 Redis 命令、运行 Scrapy/脚本、推状态与日志、POST heartbeat |
| **migrate** | `alembic upgrade head` | 一次性 schema 迁移 |

三者共用统一镜像 `rabbir/dopilot:latest`（镜像命名空间 `rabbir` ≠ git
origin `senjianlu`，两者无关）。server 单实例硬约束（uvicorn `workers=1`，
[decisions/0010](../decisions/0010-single-instance-server.md)）;横向扩展的
单位是 agent 节点数。

当前实现状态:**Scrapy `.egg` 与 Python `.whl` 两类任务可运行;Docker
长连接爬虫是未实现的未来阶段**（[decisions/0002](../decisions/0002-three-job-types-strict-order.md)）。

## 回写规则

- 本 README 只维护目录地图、系统形态和跨主题入口。
- 当前形态与运行规则写入本目录;原因与取舍写入 `../decisions/`。
