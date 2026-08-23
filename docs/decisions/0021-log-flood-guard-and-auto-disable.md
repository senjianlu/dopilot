# 0021:日志洪泛防护与调度自动禁用

- 日期:2026-08-22
- 背景:2026-08-21 12:10 UTC 生产 console 被 Redis OOM 拖死(调查见
  `.ai/2026-08-22/redis-log-stream-oom-investigation/investigation.md`)。
  根因链:steammarket-spider 因 `prices` 表唯一约束变更,每批 flush 抛
  `InvalidColumnReference`,SQLAlchemy 把带上千行 VALUES 的 INSERT 原文
  (单行 1.15MB)写进 scrapy 日志,一个执行 40 分钟写 3GB;agent
  `LogPublisher` 对 scrapyd 运行无字节上限、无限速,按 256KB/条推进
  `dopilot:server:logs`;[0019](0019-resource-hard-limits.md) 的 `MAXLEN=100000`
  按条数计,在 256KB/条时等效 ≈35GB;server 100MiB 落盘上限是"消费后丢弃",
  字节已在 Redis 内存;生产 compose 落后仓库、无 `maxmemory`/容器内存上限,
  AOF + `restart: unless-stopped` 让 Redis 每次重启重放 7GB 再被杀(15 小时
  399 次)。此外 scrapyd 1.x 不暴露退出码,pipeline 全部报错的爬虫终态仍是
  `finished`,既有状态机把事故爬虫记为成功。

- 决定:
  1. **洪泛 = 失败**。agent 每执行日志硬上限 `max_job_log_bytes`(默认 32MiB)
     对所有 runner 生效;scrapyd 运行由**进程内** `logcap` 钩子(随 wheel 安装的
     `.pth`,只凭 crawler argv 激活,cap 经 scrapyd `-s` 设置注入)在写入端封顶
     并 SIGTERM 自身——可证明上限 = cap + 一条记录 + 标记,与轮询无关;agent
     watchdog 是第二道防线(cancel TERM→KILL→对受管 scrapyd 的唯一 crawler PID
     SIGKILL,绝不 killpg;每 tick 截回 cap 保磁盘有界),被 flood 终止的执行
     上报 `failed/log_flood`。
  2. **日志流按字节约束,不收敛则清空**。保留 MAXLEN 为次级约束,新增
     `StreamGuardLoop` 按 `MEMORY USAGE` 精确 `XTRIM` 迭代到
     `stream_max_bytes_logs`(默认 256MB),8 轮或降幅 <5% 仍超限即清空(流是
     瞬态总线,[0008](0008-redis-streams-agent-communication.md);日志 RPO≠0
     已接受)。agent 发布端另有每执行推送上限与 agent 级令牌桶限速;server
     截断后向 agent 发 `stop_logs` 反压。
  3. **logs 目录预算是写入准入硬界**(`max_total_bytes`,默认 20GB),由单进程
     精确 `LogsDirGauge`(写入/截断/删除/校准共用一把锁)在落盘前判定;放不下
     就一个字节不写;事后淘汰只负责腾空间。退役 agent 的命令流由 sweep 清理;
     `sent` 命令对账保证流被清空后的 at-least-once。
  4. **出错口径含 scrapy stats**。agent 终态解析日志尾的 `log_count/ERROR` /
     `finish_reason` 与本地日志大小随事件上报;server 判定 = failed/lost、
     `log_flood`、(仅 finished)`error_count>0` 或 `finish_reason≠finished`、
     `size-cap`/`dir-budget` 截断、上报 `log_bytes ≥ max_file_bytes`;维护截断
     (`maintenance`)不算。
  5. **任务结果由单一记录器在日志定稿后幂等判定**。`record_task_outcomes`
     在 reconcile 循环轮询所有终态路径,按固定锁序 `task → executions →
     execution_log_files → schedule`(`FOR UPDATE`、锁内重读)封口日志后记录;
     所有终态写入者遵循同一锁序并在锁内复核,陈旧对象不能覆盖权威终态;
     `lost` 只在 reclaim+drain 或宽限后记录,被覆盖时清戳重评。
  6. **按 Schedule 连续计数,账本独立、代际重置**。`schedule_timer` 与
     `schedule_trigger_now` 的结果写入 `schedule_outcome_ledger`(不随 Task
     保留期清理,按条数自修剪),`consecutive_error_count` 每次从当前代际重算;
     达 `auto_disable_after_errors`(默认 5)自动 `enabled=false` 并通知,tick
     提交后再 reload 调度器;手动重启用递增 `outcome_generation`,task 创建时
     固化代际,旧任务的迟到纠正永不跨越重置边界。
  7. **消息中心单表 + 去重键**。`notifications` 以部分唯一索引
     `(type, dedupe_key) WHERE read_at IS NULL` 做原子 upsert,严重度只升不降、
     `cleared` 等标志 sticky;表有已读/未读年龄与总行数硬上限(0019)。Web 顶栏
     铃铛徽标 + 下拉,文案在前端按 type 渲染。
  8. **部署层**:redis/server/agent 容器 `mem_limit`(Redis 加载 RDB/AOF 不受
     `maxmemory` 约束,容器上限保证只杀容器不杀宿主);`configs/server.docker.toml`
     与 example 同步新默认值;恢复 runbook 规定停机、成对备份、删 Redis 卷、先用
     新镜像降级再回滚镜像。

- 后果:
  - 话痨但正常的爬虫可能被 32MiB 上限终止(可配,终止前日志已含上下文);
    "有 ERROR 即出错"对偶发错误敏感(5 次连续 + 一次成功清零 + 可关)。
  - 行锁与锁序引入少量延迟;PostgreSQL 死锁检测回滚一方,消费者按既有
    "失败不 ACK、下次重试"重放。
  - 外部 scrapyd 模式(`start=false`)的进程内硬界要求该环境安装 `dopilot-agent`
    包;agent 启动 warning + 心跳 `log_cap=external` 标示。
  - python_wheel 的日志语义维持 0019(超限截断、进程继续)。
  - 相关:[0007](0007-postgresql-only-log-bodies-on-disk.md)(备份成对)、
    [0009](0009-realtime-logs-redis-push-sse.md)(RPO≠0)、
    [0019](0019-resource-hard-limits.md)(硬上限基线)。
