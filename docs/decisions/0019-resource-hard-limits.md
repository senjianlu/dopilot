# 0019:资源硬上限——防日志/磁盘/内存膨胀

- 日期:2026-07-24
- 背景:dopilot 是长运行调度平台。生产环境曾因容器日志与应用产出文件无界
  增长把宿主机拖死;`docker system df -v` 观测到 `dopilot-redis` 卷 2.11GB
  (超过 PostgreSQL 与 server-data 本身),成因是日志 stream 仅按条目数裁剪
  (`stream_maxlen_logs=1000000`)+ AOF、`log_retention_seconds` 是死配置
  (无任何 XTRIM);`event_audit` 每条状态事件插一行且全库无删除路径;
  `/server-data/logs` 无单文件/总量上限、保留配置未消费;三份 compose 所有
  service 无 `logging:` 块;agent 侧 artifact/wheel 缓存永不淘汰、job.log
  无上限、`.logpos` 游标泄漏、event outbox 在 Redis 长停时无界。全仓库审计
  确认 15 处无界增长面(部署层 / server / agent)。

- 决定:每个增长面获得**可配置硬上限 + 安全默认值**,过期由后台**自动
  执行**(不依赖手动运维),并保持既有不变量([0009](0009-realtime-logs-redis-push-sse.md)
  日志 RPO≠0 可接受、缺口/截断是可见审计事实且永不阻塞状态收敛;
  [0010](0010-single-instance-server.md) 单实例 server)。分三层:

  - **部署层(compose)**:每个 service 设 json-file 日志轮转
    (`max-size=10m`/`max-file=3`);Redis 设 `--maxmemory`(默认 512mb)
    + `--maxmemory-policy noeviction`(到上限 XADD 响亮失败而非静默逐出流
    数据——两侧已容忍 XADD 失败)+ AOF 自动重写阈值。
  - **server**:单执行日志 `[logs].max_file_bytes`(默认 100MiB,超限继续
    消费/ACK、写一行截断标记、置粘滞 `log_integrity=truncated`);常驻
    `RetentionSweepLoop` 按 `[logs].retention_days` 自动清理终态数据
    (失败安全两阶段:先标 `expired` 提交、再删正文、再删行,崩溃后下轮
    幂等续作)、按 `[maintenance].event_audit_retention_days` 分批删
    `event_audit`、对日志/事件流 `XTRIM MINID` 实装 `log_retention_seconds`;
    `stream_maxlen_logs` 默认 1_000_000 → 100_000;上传分块读 + 单次
    `max_upload_bytes`(413)+ 聚合 `max_total_bytes`(507)配额;SSE 订阅
    队列有界(满则断开,客户端重连续传)。
  - **agent**:常驻 `AgentJanitor` 实装文档早已声称的 TTL 兜底 GC——终态
    workspace/日志/state/`.logpos` 超 `completed_log_ttl_days`、孤儿超
    `orphan_log_ttl_days` 即删,运行中永不删(三重安全判定:内存活跃集、
    `job.pgid` sidecar 进程存活、workspace 树静默期);job.log
    `max_job_log_bytes` 上限(PIPE + 持续 drain,越界丢弃但继续排空,子进程
    永不因背压阻塞);artifact/wheel 缓存 `artifact_cache_max_bytes` 按 LRU
    (`.ready` mtime,命中即 touch)淘汰,运行中引用的 sha 不淘汰;event
    outbox `event_outbox_max_files` 上限(超限丢最旧);stream `maxlen_*`
    接入 TOML/env。

- 关键取舍:
  - **Redis `noeviction` 而非 LRU 逐出**:流数据被逐出会造成日志缺口且
    不可见;`noeviction` 让 XADD 失败可观测(ERROR 日志 + 心跳 outbox
    计数),与 RPO≠0 决策一致。首要边界仍是 XADD MAXLEN + 定时 XTRIM,
    maxmemory 只是防宿主机 OOM 的兜底。
  - **artifact 正文不自动删除**:归档件仍可被已绑定模板运行
    (task-artifact-archive 决策),故聚合有界性由**拒绝新上传**(507)实现,
    不引入回收。
  - **保留清扫默认开启**(`[maintenance].enabled=true`):上限的意义就是
    无需运维介入即生效;保留手动 API 作兜底与 dry-run。
  - **孤儿删除的安全边界**:`StateStore.read()` 在缺失/损坏时都返回 None,
    故"无可读 state"不等于"已死";必须三条件齐备(不在内存活跃集、pgid
    判死、树静默期已满)才删,任一不满足本轮跳过——损坏 state 仍可回收
    (不永久滞留),运行中永不误删。

- 影响:
  - 新配置段/字段见 [04-configuration](../architecture/04-configuration.md);
    部署层上限与生产收缩 runbook 见 [05-deployment](../architecture/05-deployment.md);
    日志 `truncated` 完整性与自动/手动清理见
    [03-execution-and-logs](../architecture/03-execution-and-logs.md)。
  - `log_integrity` 枚举新增 `truncated`(String 列,零迁移;web 未引用)。
  - 无 Alembic 迁移、无协议破坏性变更;全部新配置有默认值,回滚 = 回退镜像
    + compose。
  - 验证:`pytest apps/server/tests apps/agent/tests packages/protocol/tests`、
    `ruff check apps packages`、
    `docker compose -f deploy/docker/docker-compose.yml config -q`。
