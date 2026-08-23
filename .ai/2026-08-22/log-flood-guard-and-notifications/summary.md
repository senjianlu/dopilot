---
task: log-flood-guard-and-notifications
date: 2026-08-23
rounds: 6
verdict: pass
---

# 任务小结:日志洪泛防护、资源硬顶、连续失败自动禁用与消息中心

源于 2026-08-21 生产事故(steammarket 爬虫 schema 变更 → 每条错误打印 1.15MB
INSERT → agent 无上限推送 → Redis 日志流 35GB → 宿主机 OOM;调查见
`.ai/2026-08-22/redis-log-stream-oom-investigation/`)。三条需求线:
启动清理既有超大日志;内存/磁盘双向硬顶;连续 5 次出错自动禁用调度 + 消息中心。

## 改动

| 文件 | 摘要 |
|---|---|
| `packages/protocol/dopilot_protocol/streams.py` | `AgentCommandType.stop_logs`;`AgentEvent.error_count / finish_reason / log_bytes` |
| `apps/agent/dopilot_agent/logcap.py`、`apps/agent/dopilot_logcap.pth`、`pyproject.toml` | 进程内 `.pth` 钩子:仅在 crawler argv 带 `-s DOPILOT_JOB_LOG_CAP_BYTES` 时激活,达 cap 停写 + SIGTERM 自身 |
| `apps/agent/dopilot_agent/scrapyd/stats.py` | 终态解析日志尾 64KB 最后一个 `Dumping Scrapy stats` 块(`log_count/ERROR`、`finish_reason`) |
| `apps/agent/dopilot_agent/config/settings.py`、`loader.py`、`configs/agent.example.toml` | `max_job_log_bytes=32MiB`、`log_flood_kill_after_seconds=30`、`janitor_quiet_seconds=3600`、`[redis].log_publish_rate_bytes_per_second=2MiB/s`(0 或 ≥128) |
| `apps/agent/dopilot_agent/state/store.py` | `log_flood*`、`log_capped`、stats 字段;`mark_log_flood / mark_log_capped / mark_stats / mark_canceled`(全部重读合并) |
| `apps/agent/dopilot_agent/runners/scrapyd.py`、`scrapyd/client.py` | 注入 `-s DOPILOT_JOB_LOG_CAP_BYTES`;`cancel(signal=)`;`stop()` 经 `mark_canceled` |
| `apps/agent/dopilot_agent/redis/logs.py` | 每执行推送上限(标记预留在 cap 内)+ agent 级令牌桶(正文与标记一律记账、永不超桶)+ 轮转 |
| `apps/agent/dopilot_agent/redis/commands.py` | `stop_logs` 处理;洪泛 watchdog(TERM→KILL→单 PID SIGKILL,argv token 精确匹配,绝不 killpg);立即截回到恰 cap+标记 |
| `apps/agent/dopilot_agent/janitor.py`、`main.py`、`redis/events.py`、`redis/heartbeat.py` | C8 启动/周期清扫超 cap 日志(`> cap` 且非 cap+标记态);启动先清扫再起 worker;事件带 stats;心跳 `detail.scrapyd.log_cap` |
| `apps/server/dopilot_server/config/*`、`configs/server.*.toml` | `logs.max_file_bytes=32MiB`、`max_total_bytes=20GB`、`redis.stream_max_bytes_logs=256MB`、记录器/通知保留等新键 |
| `apps/server/dopilot_server/models/*`、`migrations/versions/0013_*.py` | Execution stats 列;Task `schedule_generation/outcome_recorded_at/outcome_erroneous`;ExecutionLogFile `truncation_reason`;Schedule 连续计数/自动禁用列;`schedule_outcome_ledger`;`notifications`(部分唯一索引) |
| `apps/server/dopilot_server/logs/dir_gauge.py`、`services/logs.py` | 进程内精确目录 gauge(单锁);`apply_log_event` 行锁 + 封口拒收 + 目录预算准入硬限 + 截断后反压 `stop_logs` |
| `apps/server/dopilot_server/redis/stream_guard.py`、`redis/client.py`、`app.py` | `MEMORY USAGE` 字节预算、精确 XTRIM 迭代、不收敛清空;启动顺序 enforce_once → calibrate → 消费者 → retention → stream_guard |
| `apps/server/dopilot_server/redis/dispatcher.py`、`services/outbox.py` | `sent` 对账(XRANGE)回退重投并重开 give-up 窗口;`create_stop_logs_outbox` |
| `apps/server/dopilot_server/services/outcomes.py`、`states.py`、`events.py`、`redis/reconcile.py`、`services/schedules.py`、`dispatch.py`、`executions.py` | 唯一提交点记录器(锁序 task→executions→log_files→schedule,封口日志,账本,代际重置,soft-lost 策略);连续 5 次出错自动禁用;禁用后 commit 再 reload 调度器 |
| `apps/server/dopilot_server/services/notifications.py`、`models/notification.py`、`api/v1/notifications.py`、`router.py`、`schemas.py` | 通知原子 upsert(同 type+key 去重计数、严重度只升、`cleared` sticky)、列表/未读数/已读 API |
| `apps/server/dopilot_server/services/maintenance.py`、`retention.py`、`resource_stats.py`、`api/v1/maintenance.py` | 保留步骤 4–7:封口超限截断、目录预算淘汰(跳过失败候选)、陈旧命令流删除、通知裁剪;未入账调度任务不清扫;资源面板新指标;手工入口传 gauge |
| `apps/web/components/layout/notification-bell.tsx`、`top-controls.tsx`、`lib/api/notifications.ts`、`lib/api/types.ts`、`app/(app)/schedules/page.tsx`、locales | 顶栏铃铛(未读 Badge、下拉、全部已读、点击跳转);调度页「已自动禁用」Badge(可聚焦 Tooltip) |
| `deploy/docker/*.yml` | redis `mem_limit 1g` + `maxmemory 512mb`,server 2g,agent 4g |
| `docs/architecture/02–07、README.md`、`docs/decisions/0021-*.md`、`decisions/README.md` | 四级闸门、结果记录与自动禁用、配置表、事故恢复 runbook(成对备份/恢复命令)、前端消息中心;决策 0021 |
| 测试 | agent 13 个文件、server 15 个文件、protocol 1 个、web 2 个(含 PostgreSQL 行锁并发用例) |

## 评审历程

plan 评审 15 轮(14 fail → 第 15 轮 pass;用户授权上限 25)。实现评审 6 轮
(用户授权上限 25):

| 轮次 | 结论 | 关键问题 |
|---|---|---|
| 01 | fail | TC-25/TC-31 证据缺完整命令(blocker);job id 前缀碰撞误杀(blocker);手工清理绕过 gauge;首次洪泛未立即截回;发布端超每执行上限;文档 100MiB 残留;shadcn 语义色 |
| 02 | fail | 未入账调度任务被清扫;淘汰失败阻塞后续候选;cap+1 不截断;旧收缩 runbook 与 `mem_limit` 冲突;文件尾空行 |
| 03 | fail | 截断标记绕过令牌桶;启动顺序与 TC-32 不符;回滚缺两卷恢复命令;未读徽标未复用 Badge |
| 04 | fail | 低速配置标记仍可超桶;sent 回退后 `give_up_at` 已过期即判失败;清理阈值 `cap+标记` 漏掉 `cap+1`;Tooltip 触发器不可聚焦 |
| 05 | fail | stats 解析未限定在块内(业务日志伪造 stats);`stop()` 陈旧状态写回清掉 `log_capped` |
| 06 | pass | 无 |

## 遗留 minor 及处置

最后一轮(06)无 minor,无遗留。

## 部署与后续提醒(非本仓库范围)

- steammarket 爬虫的 `ON CONFLICT` 修复属于爬虫仓库;修好前其调度保持禁用。
- 生产(`/opt/dopilot`,Redis 卷已膨胀)按 docs/architecture/05「事故恢复
  runbook」升级:停机 → 成对备份 → `docker volume rm dopilot_dopilot-redis` →
  新 compose `up -d`;勿直接在线起新 server。
