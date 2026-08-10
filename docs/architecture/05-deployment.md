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

### 升级顺序:server 先于 agent（attempt.heartbeat 引入后）

新 agent 会周期发送 `attempt.heartbeat` 事件;**不带毒丸容错的旧 server**
（≤ 引入版本之前）的事件消费者对未知事件类型解析失败且不 XACK,会被这条
消息反复重投卡死整条事件流。统一镜像**不能**天然保证顺序:一体栈里 agent
只依赖 Redis、不依赖 server 健康,远端 agent 更是完全独立。因此:

- **一体栈**:`docker compose pull` 后先 `docker compose up -d server`,
  确认 server 已切到新版且健康,再整组 `up -d`;若整组直接 `up -d`,须
  确认 server 容器成功切新——server 启动失败而 agent 已是新版时,须回滚
  agent 或修复 server;
- **远端 agent**(compose / K8s):一律在中心 server 确认升级完成后再拉
  新镜像重建;
- **顺序颠倒的自愈**:完成 server 升级即恢复——新 server 可解析心跳,
  且对无法解析的条目 XACK 跳过（毒丸容错）,无需清理 Redis。

端口与网络:server 发布 `5000`（API/SSE + Web UI 同源）;agent **不发布
任何端口**（纯出站;scrapyd 内部端口 6801 永不发布）;server 容器
`init: true`、单实例。

## Kubernetes / k3s(参考清单)

`deploy/kubernetes/agent/` 是 **agent-only** 接入清单的通用参考版,与
`docker-compose.agent.yml` 同口径:纯出站 worker agent 接入单独部署的 server,
无入站 HTTP、不绑端口、无 Service。server 侧仍走 compose(或自有编排)。

- **必填项**(缺一无法入群,与 compose 接入栈一致):`DOPILOT_AGENT_TOKEN`
  与 `DOPILOT_REDIS_URL` 经 Secret `dopilot-agent` 注入(`secretKeyRef`,
  仓库只放 `secret.example.yaml` 占位,真值绝不入库)、`DOPILOT_SERVER_URL`
  改占位为可达地址。K8s 无 compose 的 `:?` 快速失败,且探针不测 server 连通性
  (healthcheck 只校验配置加载 + 本地 scrapyd),故占位 URL 忘改时 Pod 仍会
  Ready 而 agent 从未入群——须在 server 侧(`nodes.last_seen_at` / 运维仪表盘
  agent 板块)确认入群,不能凭 Pod Ready 判定。agent 永不注入
  `DOPILOT_ADMIN_API_TOKEN`。
- **PVC 即 agent 磁盘硬顶**:`volumeClaimTemplates` 的容量(样例 20Gi)就是该
  agent 本地磁盘上限,`/maintenance` 每-agent 板块显示的正是该卷用量/容量;
  设到 `artifact_cache_max_bytes` + 工作集余量之上。
- **容器日志轮转归 kubelet**:K8s 下容器 stdout/stderr 由 kubelet 管,不是
  docker `json-file`。对齐 compose 侧宿主机磁盘保护须在节点设 kubelet
  `container-log-max-size` / `container-log-max-files`(k3s 走
  `/etc/rancher/k3s/config.yaml` 的 `kubelet-arg`)。
- 通用清单不含任何 secrets 注入 sidecar(Vault 等);容器 resources /
  ephemeral-storage 限额亦为节点侧待办。细则与 yaml 片段见
  `deploy/kubernetes/agent/README.md`。

## 持久化卷与备份

| 卷 | 内容 | 备份 |
|---|---|---|
| `dopilot-db` | PostgreSQL:业务表 + `execution_log_files` 索引 | **必须** |
| `dopilot-server-data` → `/server-data` | 日志正文 `/server-data/logs` + `secrets/agent-token` + 上传中转 | **必须**（与 PG 缺一不可） |
| `dopilot-agent{N}-data` → `/agent-data` | scrapyd `job.log`、attempt 状态文件、event/log outbox、wheel/egg 缓存 | 可不备份（server drain 完成前不得删 `job.log`） |
| `dopilot-redis` | AOF | 不是备份目标（瞬时传输;丢失只影响在途消息，日志 RPO≠0 已接受） |

## 资源硬上限（防宿主机膨胀）

长运行部署曾因容器日志与应用文件无界增长把宿主机磁盘/内存耗尽。部署层
在三份 compose 里设了两道硬边界(应用层上限见
[04-configuration](04-configuration.md) 与
[0019 决策](../decisions/0019-resource-hard-limits.md)):

- **容器日志轮转**:每个 service(server / agent / redis / db / migrate)经
  共享 `x-logging` anchor 设 json-file `max-size=10m` + `max-file=3`。宿主机
  若用 journald 等其他 driver,需在 daemon 侧另设等价上限——该 anchor 只管
  json-file。
- **Redis 内存**:`--maxmemory ${DOPILOT_REDIS_MAXMEMORY:-512mb}` +
  `--maxmemory-policy noeviction` + `--auto-aof-rewrite-percentage 100`
  + `--auto-aof-rewrite-min-size 64mb`。`noeviction` 是刻意选择:到上限后
  XADD 响亮失败(两侧可容忍:agent 日志游标不前进、事件留在磁盘 outbox、
  server 派发重试),而非静默逐出流数据。首要边界仍是每条 stream 的
  XADD MAXLEN 与 server 保留清扫的 `XTRIM MINID`。

### 生产收缩 runbook（已膨胀的部署升级到本版本）

若 `dopilot-redis` 卷已远超新 `maxmemory`(如观测到的 2.11GB):

1. 先升级并启动新版 **server**——`RetentionSweepLoop` 首个 tick(≤60s)即对
   日志/事件流执行 `XTRIM MINID`,把数据集收缩到保留窗内;`stream_maxlen_logs`
   默认也由 1_000_000 降到 100_000。
2. 再对 redis 应用 `maxmemory`(或接受收缩生效前最初一分钟可能的 XADD 失败
   ——agent 侧可容忍,日志随后补传)。
3. AOF 文件靠 `auto-aof-rewrite-*` 收缩;需要立即回收可一次性
   `redis-cli BGREWRITEAOF`。
4. PostgreSQL:保留清扫删行后空间由 autovacuum 复用、文件不立即回缩;需要
   立即回收磁盘可择机停机 `VACUUM FULL`。

## 反向代理（可选）

dopilot 不内置 nginx。用户自接反代时 SSE 路径必须关缓冲
（`proxy_buffering off` + 长 `proxy_read_timeout`）;FastAPI SSE 响应自带
`X-Accel-Buffering: no` + `Cache-Control: no-cache` 双保险。
