# 部署

> 决策依据:[0004 统一镜像](../decisions/0004-two-docker-roles-unified-image.md)、
> [0007 持久化边界](../decisions/0007-postgresql-only-log-bodies-on-disk.md)、
> [0016 glibc 基础镜像](../decisions/0016-glibc-base-image-apscheduler-310.md)。

## 镜像

- 统一应用镜像 **`rabbir/dopilot:latest`**（+ 不可变 git-sha tag），内含
  server、agent、protocol、scrapy/scrapyd 运行时、Alembic 迁移与 Web 静态
  产物;启动命令选角色（`dopilot-server` / `dopilot-agent` /
  `alembic upgrade head`）。基础镜像 glibc 系（`python:3.12-slim` /
  `node:22-slim` 构建段），禁 Alpine。
- 依赖基础镜像 `rabbir/dopilot-py-base` / `rabbir/dopilot-web-base` 由 CI
  按 deps-hash 构建复用（`deploy/docker/Dockerfile.base` +
  `scripts/docker-deps-hash.sh`）。
- CI:`.github/workflows/docker.yml`——push master / `v*` tag /
  手动触发;`:latest` 仅主干或 release tag 可覆盖。Secrets:
  `DOCKERHUB_USERNAME` / `DOCKERHUB_TOKEN`;可选 `DOCKER_PLATFORMS`。
- ⚠️ 镜像命名空间 `rabbir` ≠ git origin `senjianlu`，绝不混用。

## compose 拓扑（`deploy/docker/`）

| 文件 | 场景 | 令牌口径 |
|---|---|---|
| `docker-compose.yml` | 一体栈:db + redis + migrate + server + 三个对称 scrapy agent | server 与 agent 同时启动，须显式共享 `DOPILOT_AGENT_TOKEN` |
| `docker-compose.server.yml` | server-only(db + redis + migrate + server)，Redis 端口对外发布供远端 agent 接入 | `DOPILOT_AGENT_TOKEN` 可省——server 首启生成并持久化到 `/server-data/secrets/agent-token` |
| `docker-compose.agent.yml` | agent-only 接入栈 | `DOPILOT_AGENT_TOKEN` 与 `DOPILOT_SERVER_URL` 必填（`:?` 快速失败）;绝不注入 `DOPILOT_ADMIN_API_TOKEN` |
| `docker-compose.build.yml` | 本地源码构建覆盖层（smoke 用） | 叠加在 `docker-compose.yml` 上 |

默认路径拉取 CI 镜像（`docker compose pull && up -d`），无需本地构建;
镜像默认经 `DOPILOT_IMAGE` 覆盖。默认 TOML 已烤进镜像，compose 不需要
`DOPILOT_CONFIG`;定制时把自有 TOML 只读挂到 `/app/configs/*.toml`。

端口与网络:server 发布 `5000`（API/SSE + Web UI 同源）;agent **不发布
任何端口**（纯出站;scrapyd 内部端口 6801 永不发布）;server 容器
`init: true`、单实例。

## 持久化卷与备份

| 卷 | 内容 | 备份 |
|---|---|---|
| `dopilot-db` | PostgreSQL:业务表 + `execution_log_files` 索引 | **必须** |
| `dopilot-server-data` → `/server-data` | 日志正文 `/server-data/logs` + `secrets/agent-token` + 上传中转 | **必须**（与 PG 缺一不可） |
| `dopilot-agent{N}-data` → `/agent-data` | scrapyd `job.log`、attempt 状态文件、event/log outbox、wheel/egg 缓存 | 可不备份（server drain 完成前不得删 `job.log`） |
| `dopilot-redis` | AOF | 不是备份目标（瞬时传输;丢失只影响在途消息，日志 RPO≠0 已接受） |

## 反向代理（可选）

dopilot 不内置 nginx。用户自接反代时 SSE 路径必须关缓冲
（`proxy_buffering off` + 长 `proxy_read_timeout`）;FastAPI SSE 响应自带
`X-Accel-Buffering: no` + `Cache-Control: no-cache` 双保险。
