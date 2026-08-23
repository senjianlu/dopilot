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

- **容器内存上限(日志洪泛防护)**:redis `mem_limit`/`memswap_limit`
  `${DOPILOT_REDIS_MEM_LIMIT:-1g}`(必须高于 `--maxmemory`;Redis **加载**
  RDB/AOF 不受 `maxmemory` 约束,没有它一份膨胀的 AOF 会在重启时把宿主机
  拖死——有了它只会杀掉 redis 容器并重启,反复出现按下方事故恢复 runbook 清空
  卷)、server `${DOPILOT_SERVER_MEM_LIMIT:-2g}`、agent
  `${DOPILOT_AGENT_MEM_LIMIT:-4g}`。

### 事故恢复 runbook(Redis 被日志流撑爆 / 宿主机卡死后,2026-08-21 事故)

以 Compose project 名 `P`(= compose 所在目录名;生产 `/opt/dopilot` 即
`dopilot`)参数化,卷名为 `${P}_dopilot-redis` / `${P}_dopilot-db` /
`${P}_dopilot-server-data`。**事故现场 server 已停、容器已删时从第 ③ 步开始。**

1. server 仍在运行时:先在 Web「一键停用全部调度」,然后分别查询
   `GET /api/v1/tasks?status=queued`、`?status=running`、`?status=finalizing`
   (admin Bearer;`status` 只接受单值)直到三者响应的 `total` 都为 0(长期悬挂
   的任务用维护页「标记 lost」),使命令流不再有未接管命令。
2. 每台 agent 主机 `docker compose -f docker-compose.agent.yml down`,
   `docker compose ps` 确认无容器;然后 server 主机 `docker compose down`,
   `docker compose ps` 确认 server/redis/db 均已停止,
   `docker ps --filter volume=${P}_dopilot-redis` 为空。
3. 在同一静止点**成对备份**(0007:索引与正文缺一不可):
   `docker run --rm -v ${P}_dopilot-db:/src -v /opt/backup:/dst alpine tar czf /dst/dopilot-db-$(date +%F).tgz -C /src .`
   与
   `docker run --rm -v ${P}_dopilot-server-data:/src -v /opt/backup:/dst alpine tar czf /dst/dopilot-server-data-$(date +%F).tgz -C /src .`;
   保留旧 compose 为 `docker-compose.yml.bak` 并记下旧镜像 digest。
4. `docker volume rm ${P}_dopilot-redis`(流是瞬态总线,0008;未接管的 `sent`
   命令由新版 dispatcher 的 sent 对账自动回退重投,queued task 不会悬挂)。
5. 用仓库 `deploy/docker/docker-compose.server.yml` 覆盖
   `/opt/dopilot/docker-compose.yml`(.env 不动),`docker compose pull`。
6. `docker compose up -d`(migrate 先跑完 `alembic upgrade head`,server 依赖其
   `service_completed_successfully`);`docker compose ps` 三服务 healthy,
   `curl -f http://localhost:5000/api/v1/health`。server 启动即对日志流做一次
   字节预算裁剪、校准日志目录 gauge,再启动消费者。
7. agent 主机拉新镜像后 `up -d`;Web 节点页确认心跳(`detail.scrapyd.log_cap`
   为 `managed`)。
8. 维护页资源面板确认 `redis.stream_bytes:logs` / `logs.dir_bytes` 在限内,
   任务页确认无悬挂 queued。
9. 引发事故的爬虫调度(如 steammarket)在爬虫仓库修好前保持禁用。

**回滚**(顺序敏感;agent 主机同样先 `down`):

1. `docker compose down`。
2. **仍用新 compose / 新镜像**执行
   `docker compose run --rm migrate alembic downgrade 0012`(旧镜像不含 0013,
   无法自行降级)。
3. 恢复旧 compose 与旧镜像:`cp docker-compose.yml.bak docker-compose.yml`,
   镜像钉回记下的旧 digest。
4. **成对恢复**第 ③ 步的两份备份(新版本启动时已截断/淘汰过 server-data,
   只恢复 DB 会得到索引与正文不一致):
   ```bash
   docker volume rm ${P}_dopilot-db ${P}_dopilot-server-data
   docker compose create   # 按旧 compose 重建空卷(带 compose 标签)与容器,不启动
   docker run --rm -v ${P}_dopilot-db:/dst -v /opt/backup:/src alpine tar xzf /src/dopilot-db-<日期>.tgz -C /dst
   docker run --rm -v ${P}_dopilot-server-data:/dst -v /opt/backup:/src alpine tar xzf /src/dopilot-server-data-<日期>.tgz -C /dst
   ```
5. `docker compose up -d`,`curl -f http://localhost:5000/api/v1/health`。

整个升级窗口内 agent 全停、与 server 同版本一起起,不存在老 agent 收到
`stop_logs` 的毒消息问题。

### 已膨胀的部署升级到本版本

**不要**在线启动新版 server 再指望它裁剪:新 compose 给 redis 设了
`mem_limit`(默认 1g),一份已经膨胀的 AOF/RDB 在加载阶段就会被 cgroup
OOM-kill 并进入容器级重启循环,server 根本等不到 Redis。统一走上方
「事故恢复 runbook」:停机 → 成对备份 → `docker volume rm ${P}_dopilot-redis`
(流是瞬态总线)→ 新 compose/镜像 `up -d`。若 Redis 卷**未**膨胀(用量远低于
`maxmemory`),可直接 `docker compose pull && up -d` 滚动升级,server 启动时
会先把日志流裁到字节预算、校准日志目录 gauge,再启动消费者。

PostgreSQL:保留清扫删行后空间由 autovacuum 复用、文件不立即回缩;需要立即
回收磁盘可择机停机 `VACUUM FULL`。

## 反向代理（可选）

dopilot 不内置 nginx。用户自接反代时 SSE 路径必须关缓冲
（`proxy_buffering off` + 长 `proxy_read_timeout`）;FastAPI SSE 响应自带
`X-Accel-Buffering: no` + `Cache-Control: no-cache` 双保险。
