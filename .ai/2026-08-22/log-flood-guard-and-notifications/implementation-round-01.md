---
task: log-flood-guard-and-notifications
round: 01
date: 2026-08-23
---

# 实现记录:第 01 轮

> 评审轮次授权:plan frontmatter 的 `plan_review_max_rounds: 25` /
> `impl_fix_max_rounds: 25` 由用户于 2026-08-22 两次明确指示放宽(15 → 25)
> 写入,见 plan.md 顶部的授权记录;非用户提出不得写入。

## 本轮改动

按 plan 一轮实现完整方案(WP-A 清理 / WP-B 防护 / WP-C 自动禁用 + 消息中心)。

### packages/protocol

| 文件 | 改动摘要 |
|---|---|
| `dopilot_protocol/streams.py` | `AgentCommandType.stop_logs`;`AgentEvent` 增可选 `error_count` / `finish_reason` / `log_bytes`(默认 None,旧事件可解析) |
| `tests/test_stream_schemas.py` | 枚举断言更新;TC-07 三个用例 |

### apps/agent

| 文件 | 改动摘要 |
|---|---|
| `dopilot_agent/logcap.py`(新)、`dopilot_logcap.pth`(新)、`pyproject.toml` | 进程内 crawler 日志上限钩子:只凭 argv(`crawl` + `_job=` + `-s DOPILOT_JOB_LOG_CAP_BYTES` + `-s LOG_FILE`)激活,只给写 `LOG_FILE` 的 `FileHandler` 实例加上限,达限写标记 + 丢弃 + SIGTERM 自身一次;`.pth` 经 hatch `force-include` 装到 site-packages 根;`dev` extra 加 `hatchling` |
| `dopilot_agent/scrapyd/stats.py`(新) | 从日志尾 64KB 解析 scrapy stats(`log_count/ERROR`、`finish_reason`) |
| `dopilot_agent/config/settings.py` / `config/loader.py` | `max_job_log_bytes` 100MiB → 32MiB(语义扩展到所有 runner);新增 `log_flood_kill_after_seconds`、`janitor_quiet_seconds`、`[redis].log_publish_rate_bytes_per_second` 与对应 env |
| `dopilot_agent/state/store.py` | `AttemptState` 增 `log_flood*`、`log_capped`、`error_count`、`finish_reason`、`log_bytes`;`mark_log_flood` / `mark_log_capped` / `mark_stats` |
| `dopilot_agent/runners/scrapyd.py`、`scrapyd/client.py` | `schedule()` 注入 `-s DOPILOT_JOB_LOG_CAP_BYTES`(cap>0);`stop(signal=)` 透传 scrapyd `cancel.json` 的 `signal` |
| `dopilot_agent/redis/logs.py` | 每执行推送上限(达限一条标记 entry + `log_capped`,仍发 eof)、agent 级令牌桶限速、扫描起点轮转、`cap()` 入口 |
| `dopilot_agent/redis/commands.py` | `_process` 解码移入 try(坏消息记 warning 并 ACK);`stop_logs` 处理;flood watchdog(每 tick 查大小、cancel、每 tick 截回 cap、TERM→KILL→单 PID SIGKILL 且 ppid 校验、绝不 killpg、外部模式禁用);终态统一经 `_finish_scrapy_attempt`(stats + flood 覆盖为 `failed/log_flood`) |
| `dopilot_agent/redis/events.py` | 事件携带 stats 字段;`republish_current` 回放 state 中的 stats |
| `dopilot_agent/janitor.py` | C8:非活动超大 job.log 截断,三重条件(不在活动集;state done 或 无 state + scrapyd 不列 + 静默期;锁内复检) |
| `dopilot_agent/main.py`、`deps.py`、`redis/heartbeat.py` | 启动先跑一次 janitor sweep 再启动 consumer/publisher;外部 scrapyd 模式 warning;watchdog/publisher 接线;心跳 `detail.scrapyd.log_cap` / `log_cap_bytes` |
| `tests/conftest.py` | `FakeScrapyd` 增 `cancels` 记录、`fail_cancel_times`、`sticky_running` |
| `tests/test_log_flood.py`(新)、`test_logcap.py`(新)、`test_logcap_install.py`(新)、`test_packaging.py`(新)、`test_scrapyd_stats.py`(新)、`test_janitor.py`(新) | 新用例 |
| `tests/test_log_publisher.py`、`test_main.py`、`test_heartbeat_worker.py`、`test_config.py`、`test_resource_limits.py` | 补用例;既有 100MiB 默认值断言改 32MiB |

### apps/server

| 文件 | 改动摘要 |
|---|---|
| `config/settings.py` / `config/loader.py` | `[redis] stream_max_bytes_logs`、`stream_guard_interval_seconds`、`sent_reconcile_*`;`[logs] max_file_bytes` 100MiB → 32MiB、`max_total_bytes`;`[scheduler] auto_disable_after_errors`、`lost_outcome_grace_seconds`;`[maintenance] stale_command_stream_days`、`notification_*`;对应 env(沿用既有 `DOPILOT_LOG_` 前缀) |
| `models/execution.py`、`models/scheduling.py`、`models/notification.py`(新)、`models/__init__.py` | `Execution` stats 列;`Task.schedule_generation` / `outcome_recorded_at` / `outcome_erroneous`;`ExecutionLogFile.truncation_reason`;`Schedule` 计数/禁用/代际列;新表 `ScheduleOutcomeLedger`、`Notification`(部分唯一索引 `(type, dedupe_key) WHERE read_at IS NULL`) |
| `migrations/versions/0013_log_guard_outcomes_notifications.py`(新) | 加列/建表/索引 + 回填 `tasks.schedule_generation=0`;`downgrade` 完整 |
| `services/notifications.py`(新)、`api/v1/notifications.py`(新)、`api/v1/router.py`、`api/v1/schemas.py` | `notify` 原子 upsert(计数 +1、严重度 SQL 端只升不降、`cleared` sticky)、列表/未读数/已读/全部已读、有界 prune;四个 admin 端点;`ScheduleView` 四个新字段 |
| `logs/dir_gauge.py`(新) | 精确目录 gauge:写入/截断/删除/校准共用一把 `asyncio.Lock`,校准持锁跨越 `os.walk` |
| `services/logs.py` | 行锁(`FOR UPDATE`)、非可写状态 `sealed` 拒收、单文件 cap + 目录预算准入(标记也放不下就不写)、写前/写后 `stat` 结算 gauge(异常路径同样结算)、截断 → `stop_logs` outbox + `log_truncated` 通知 |
| `services/outbox.py`、`redis/dispatcher.py`、`redis/commands.py` | `create_stop_logs_outbox`(按执行去重);dispatcher 超时路径锁 task→execution 并复核;`sent` 对账(`XRANGE id id`,过新不查,缺失回退 `pending` + 通知);`CommandProducer.redis` |
| `redis/client.py`、`redis/stream_guard.py`(新) | `memory_usage` / `scan_keys` / `delete` / `xrange`;`StreamGuardLoop` 精确 XTRIM 迭代收敛、不收敛清空、分键通知 |
| `services/states.py` | `execution_is_erroneous` / `task_is_erroneous`(stats 仅对 finished;`maintenance` 截断不算;`log_bytes ≥ cap`) |
| `services/outcomes.py`(新) | 结果记录器:候选轮询、固定锁序 `task → executions → log_files → schedule`(`populate_existing`)、定稿/兜底/soft-lost 门槛、封口、账本 upsert + 自修剪 + 代际重算、自动禁用 + 通知 |
| `services/events.py` | 终态落 stats;task 行锁;`lost` 被覆盖时清空 `outcome_recorded_at`;`log_flood` 终态 → 通知 |
| `redis/reconcile.py` | `mark_lost` 锁 task→execution 并复核;`_rollup` 锁 task;tick 增记录器,**提交后**回调 `on_schedules_disabled` |
| `services/schedules.py`、`services/dispatch.py`、`services/executions.py` | 启用时递增 `outcome_generation` 并清零;task 创建固化 `schedule_generation`;`get_task/get_execution/get_log_file(for_update=)`(`populate_existing`);`schedule_view` 新字段 |
| `services/maintenance.py` | `cleanup_terminal_data` eligibility 收紧为"全部日志已封口" + 行锁 + gauge 结算(`only_task_ids`);`truncate_oversized_log_files`(仅封口、`reason=maintenance`)、`evict_logs_dir_to_budget`(不可恢复 → error 通知)、`delete_stale_command_streams`(四条件);`mark_task_lost` 锁 task 复核 |
| `retention.py`、`resource_stats.py`、`app.py`、`redis/consumers.py` | sweep 新步骤 4–7;`logs.dir_bytes` / `redis.stream_bytes:logs` 指标;lifespan:`StreamGuardLoop.enforce_once()` → gauge 校准 → consumers;dispatcher 带 settings;reconcile 注入 runner reload;LogConsumer 带 gauge;不做迁移 |
| `tests/conftest.py` | fake Redis 增 `xinfo_stream`/`info`/`xtrim`/`memory_usage`(估算 + override)/`scan_keys`/`delete`/`xrange`;`pg_engine` / `pg_sessionmaker`(无 `DOPILOT_TEST_DATABASE_URL` 时 **fail** 而非 skip;先 dispose 再 drop_all) |
| 新测试:`test_notifications.py`、`test_log_guard.py`、`test_outcomes.py`、`test_outcomes_pg.py`、`test_reconcile_outcomes.py`、`test_maintenance_guard.py`、`test_log_locking_pg.py`、`test_runbook.py` | 新用例 |
| `tests/test_config.py`、`test_schedules.py`、`test_log_consumer.py`、`test_resource_limits.py`、`test_resource_stats.py` | 补用例;既有用例适配(见"偏差") |

### apps/web

| 文件 | 改动摘要 |
|---|---|
| `lib/api/notifications.ts`(新)、`lib/api/types.ts` | 客户端与类型;`Schedule` 增四字段 |
| `components/layout/notification-bell.tsx`(新)、`components/layout/top-controls.tsx` | 铃铛(30s 轮询未读数、`99+`、下拉 20 条、type+payload 经 i18n 渲染、点击标已读并跳转既有静态路由、全部已读) |
| `app/(app)/schedules/page.tsx` | `auto_disabled_at` 行显示「已自动禁用」Badge + tooltip(带 `TooltipProvider`) |
| `lib/i18n/locales/en.ts`、`zh.ts` | `notifications.*`(7 种 type)、`schedules.autoDisabled*` |
| `components/layout/__tests__/notification-bell.test.tsx`(新)、`app/(app)/schedules/__tests__/schedules.test.tsx` | TC-28 / TC-29 |

### deploy / configs / docs

| 文件 | 改动摘要 |
|---|---|
| `deploy/docker/docker-compose.server.yml`、`docker-compose.yml`、`docker-compose.agent.yml` | redis `mem_limit`/`memswap_limit` 1g、server 2g、agent 4g(均 env 可覆盖)+ 注释 |
| `configs/server.example.toml`、`configs/server.docker.toml`、`configs/agent.example.toml` | 新默认值与新键(生产镜像加载的 docker TOML 同步) |
| `docs/architecture/02/03/04/05/06/07`、`README.md`、`docs/decisions/0021-*.md`(新)、`decisions/README.md` | 回写机制、配置表、事故恢复 runbook(含回滚顺序、成对备份)、消息中心、PostgreSQL 测试要求、决策记录 |

## 修复对照

第 1 轮,不适用。

## 测试结果

全部 A 档,证据 = `evidence/` 下文件(命令 + 完整 stdout/stderr + 退出码)。
PostgreSQL 用例经 `scripts/dev-db.sh up` + `DOPILOT_TEST_DATABASE_URL` 真实运行。

| 编号 | 档位 | 结果 | 证据 |
|---|---|---|---|
| TC-01 | A | pass | `tc-01-01b-01c-01h-02-02b-06-08-09-01f-log-flood.txt`(`test_flood_cancels_then_reports_failed_log_flood`) |
| TC-01b | A | pass | 同上(`test_escalation_and_disk_bound_when_cancel_is_ignored`:TERM→KILL→仅目标 pid `os.kill`,`killpg` 从未调用,每 tick ≤ cap+标记) |
| TC-01c | A | pass | 同上(`test_ambiguous_crawler_candidates_are_never_killed`) |
| TC-01d | A | pass | `tc-01d-01e-01g-logcap.txt`(`test_caps_only_the_log_file_handler_and_sigterms_once`、`test_no_patch_for_daemon_argv_or_zero_cap`) |
| TC-01e | A | pass | 同上(`test_subprocess_is_capped_and_terminated`:真实命令行,returncode == -15,文件 ≤ cap+记录+标记,对照组写满 50MB) |
| TC-01f | A | pass | `tc-01f-packaging.txt`(b)+ `tc-01-...-log-flood.txt`(`test_schedule_injects_cap_setting_next_to_runtime_context`、`test_managed_scrapyd_daemon_gets_no_cap_env`)(a)(c) |
| TC-01g | A | pass | `tc-01d-01e-01g-logcap.txt`(`test_activation_requires_full_crawler_identity`:环境变量不是激活来源) |
| TC-01h | A | pass | `tc-01-...-log-flood.txt`(`test_external_mode_has_no_pid_kill`)+ `tc-33-01h-agent-main-heartbeat.txt`(`test_build_request_reports_log_cap_mode`、`test_startup_janitor_sweep_runs_before_workers_start` 的 warning 断言) |
| TC-01i | A | pass | `tc-01i-logcap-install.txt`(离线构建 wheel → 隔离 venv → `.pth` 在 site-packages 根;真实命令行子进程被 SIGTERM 封顶,对照组正常) |
| TC-02 | A | pass | `tc-01-...-log-flood.txt`(`test_below_cap_is_untouched_and_finishes_normally`) |
| TC-02b | A | pass | 同上(`test_cap_zero_disables_watchdog_publisher_and_injection`)+ `tc-18-...-outcomes.txt`(`test_execution_is_erroneous_matrix` 的 cap=0 分支)+ `tc-10-...-log-guard.txt`(`test_dir_budget_admission_hard_limit` (c)) |
| TC-03 | A | pass | `tc-03-04-log-publisher.txt`(`test_publish_cap_emits_marker_once_then_stops_tailing`) |
| TC-04 | A | pass | 同上(`test_rate_limit_bounds_bytes_per_tick_and_rotates`) |
| TC-05 | A | pass | `tc-05-scrapyd-stats.txt` |
| TC-06 | A | pass | `tc-01-...-log-flood.txt`(`test_terminal_event_carries_scrapy_stats`) |
| TC-06b | A | pass | `tc-18-...-outcomes.txt`(`test_log_flood_terminal_notifies_once`:重复投递仍一条,API 可列出) |
| TC-07 | A | pass | `tc-07-protocol.txt` |
| TC-08 | A | pass | `tc-01-...-log-flood.txt`(`test_stop_logs_caps_the_publisher`) |
| TC-09 | A | pass | 同上(`test_bogus_command_is_acked_and_logged`) |
| TC-10 | A | pass | `tc-10-11-11b-11c-12-20e-log-guard.txt`(`test_size_cap_truncates_once_with_backpressure`:marker、`stop_logs` 恰一条、通知、gauge == 实际落盘) |
| TC-11 | A | pass | 同上(`test_dir_budget_admission_hard_limit`:(a) 只写标记 (b) 五执行零字节、实测 == 2990 (c) 预算 0 正常) |
| TC-11b | A | pass | 同上(`test_gauge_serialises_write_truncate_and_calibrate`:写入与截断阻塞到校准完成,`value == 实测`,部分写入 700 字节后异常 → +700) |
| TC-11c | A | pass | 同上(同一用例第二段:截断完成、扣减前 barrier,校准阻塞到整段完成) |
| TC-12 | A | pass | 同上(`test_stream_guard_uniform_converges` (a)、`test_stream_guard_uneven_entries_converge` (b)、`test_stream_guard_clears_when_it_cannot_converge` (c)、`test_stream_guard_budget_zero_is_off`) |
| TC-13 | A | pass | `tc-13-14-15-16-27-32-maintenance-guard.txt`(`test_truncate_oversized_only_sealed`) |
| TC-13b | A | pass | `tc-13b-13c-log-locking-postgres.txt`(`test_maintenance_waits_for_consumer_then_skips_unsealed`:阶段 1 active 文件按 eligibility 跳过;阶段 2 已封口文件上消费者持锁时维护阻塞至其提交后再截断/淘汰,最终无孤儿) |
| TC-13c | A | pass | 同上(`test_expired_row_rejects_late_increment_no_orphan`) |
| TC-14 | A | pass | `tc-13-...-maintenance-guard.txt`(`test_evict_logs_dir_to_budget`) |
| TC-15 | A | pass | 同上(`test_evict_cannot_recover_when_only_active_logs`:error 通知,日桶 count=2) |
| TC-16 | A | pass | 同上(`test_delete_stale_command_streams`:仅 ghost/retired 被删) |
| TC-17 | A | pass | `tc-17-janitor.txt`(a/e 截断,b/c/d 不动,锁内复检) |
| TC-18 | A | pass | `tc-18-...-outcomes.txt`(`test_execution_is_erroneous_matrix`) |
| TC-19 | A | pass | 同上(`test_three_consecutive_failures_disable_schedule`) |
| TC-19b | A | pass | 同上(`test_trigger_now_tasks_count`) |
| TC-19c | A | pass | 同上(`test_stats_drive_auto_disable_end_to_end`:`apply_event` 落 stats → 记录器 → 账本 → 禁用;重启用后成功清零) |
| TC-20 | A | pass | 同上(`test_reset_ignore_and_threshold_zero`:(a)(b)(c)(d)) |
| TC-20b | A | pass | 同上(`test_ledger_is_order_independent`、`test_soft_lost_policy`:(a)(b)(c)(d)(e)) |
| TC-20c | A | pass | 同上(`test_ledger_independent_of_task_retention`:Task 删除后账本仍在、第 5 次禁用、自修剪到 100) |
| TC-20d | A | pass | `tc-20d-20f-outcomes-postgres.txt`(四个交错用例,barrier 控制,PostgreSQL) |
| TC-20e | A | pass | `tc-10-...-log-guard.txt`(`test_sent_reconcile_requeues_vanished_commands`:A/B/C/D 四行 + 周期接线) |
| TC-20f | A | pass | `tc-20d-20f-outcomes-postgres.txt`(`test_stale_mark_lost_and_dispatch_timeout_lose_to_finished`:三种陈旧写入者都输给已提交的 finished) |
| TC-21 | A | pass | `tc-18-...-outcomes.txt`(`test_terminal_paths_and_sealing`:(a)–(f) + `mark_lost` 路径) |
| TC-22 | A | pass | `tc-22-reconcile-reload-after-commit.txt`(回调在 commit 后、新 session 读到 disabled、runner job 集为空;commit 失败无回调且未记录) |
| TC-23 | A | pass | `tc-23-schedules-api.txt`(`test_put_enable_resets_auto_disable_state`:PUT 清零/清除/代际 +1、trigger-now 任务带代际 1)+ `tc-18-...-outcomes.txt`(`test_manual_reenable_starts_new_generation`:(a) 计数 1 (b) 旧代际行不跨越) |
| TC-24 | A | pass | `tc-24-notifications.txt`(去重/分 type/严重度只升/sticky/prune 三界/API 与 401/PostgreSQL 并发三 session → 1 行 count=3 + 直接插入违反索引) |
| TC-25 | A | pass | `tc-25-alembic-upgrade-downgrade-upgrade.txt`(upgrade head → downgrade -1 → upgrade head 三步退出码 0;新表/新列/部分索引存在;升级前 task 回填代际 0 且终态后正常入账计数 1) |
| TC-26 | A | pass | `tc-26-config-agent-server.txt`(agent 与 server:默认值、env 覆盖、生产 `server.docker.toml` 加载 32MiB、旧名 `DOPILOT_LOG_MAX_FILE_BYTES` 生效) |
| TC-27 | A | pass | `tc-13-...-maintenance-guard.txt`(`test_resource_stats_new_entries`) |
| TC-28 | A | pass | `tc-28-web-notification-bell.txt`(徽标 3、zh 文案、点击 schedule → `/schedules?highlight=`、点击 log_flood → `/tasks/detail?id=`、全部已读、`99+`、en 七种 type 无缺失 key、路由映射) |
| TC-29 | A | pass | `tc-29-web-schedules-badge.txt`(`SchedulesPage auto-disable badge (TC-29)`) |
| TC-30 | A | pass | `tc-30-ruff.txt`(All checks passed)、`tc-30-pytest-full.txt`(730 passed, 1 skipped — 该 skip 为既有 `test_resource_stats.py:1040` 依赖另一个变量 `DOPILOT_TEST_PG_URL`,本任务未触及)、`tc-30-web-lint.txt`、`tc-30-web-typecheck.txt`、`tc-30-web-test.txt`(98 passed) |
| TC-31 | A | pass | `tc-31-compose-config.txt`(三份 compose `config` 退出码 0;输出含 redis/server `mem_limit`/`memswap_limit` 与 `--maxmemory 512mb`) |
| TC-31b | A | pass | `tc-31b-31c-runbook.txt`(`test_runbook_task_status_queries_are_valid`:三单值查询 200 含 `total`,逗号多值 400 `task.invalid_status`,docs 与之一致) |
| TC-31c | A | pass | 同上(`test_runbook_backs_up_and_restores_both_volumes`:两卷各 ≥2 次出现、成对备份/恢复、降级先于换回旧镜像) |
| TC-32 | A | pass | `tc-13-...-maintenance-guard.txt`(`test_lifespan_runs_guard_and_gauge_before_consumers`:顺序与完成时间戳) |
| TC-33 | A | pass | `tc-33-01h-agent-main-heartbeat.txt`(`test_startup_janitor_sweep_runs_before_workers_start`) |

## 与方案的偏差

1. **TC-13b 的验收形态**:plan 写"B 在 A 提交前阻塞;A 提交后 B 重读状态:文件仍
   active → 不截断"。实现中维护路径只把**已封口**文件列为候选(eligibility 先于
   加锁),对 active 文件根本不尝试加锁,因此"阻塞"只会在候选(已封口)文件上
   发生。用例拆为两阶段:阶段 1 active 文件被 eligibility 直接跳过(无等待);
   阶段 2 同一文件封口后、消费者持锁时维护确实阻塞到其提交。不变量(单写者、
   无孤儿、DB 与物理大小一致)与 plan 一致,只是阻塞的触发条件更严格。
2. **`stop_logs` 去重范围**:plan 写"已存在未终结行则不重复";实现把 `sent` 行也
   计入去重(`OUTBOX_UNRESOLVED ∪ {sent}`),避免同一执行每次截断事件重复入队
   (agent 侧幂等,功能无差)。
3. **通知严重度单调**:plan 写在 upsert 的 `set_` 里取 max;实现用 SQL `CASE`
   在 `ON CONFLICT ... DO UPDATE` 内完成(并发安全),`cleared` sticky 在 Python
   侧合并。语义同 plan。
4. **`docker-compose.agent.yml`**:plan 只要求"核对已有限制并补注释";该文件
   原本没有内存上限,本轮补了 `mem_limit ${DOPILOT_AGENT_MEM_LIMIT:-4g}`
   (加性改动,可被 env 覆盖)。
5. **既有测试的适配**(非功能退化):agent/server 的 100MiB 默认值断言改为
   32MiB;`test_log_consumer.py` 的"异步落盘边界"回归用例从监视
   `files.aappend_increment_capped` 改为监视新的线程内 `_write_settled`(同一
   不变量:写盘不在事件循环);`test_resource_limits.py` 的保留清扫 fixture 把
   终态任务的日志置为已封口(与 `finalize_drained_logs` 后的真实状态一致,因为
   清扫 eligibility 已收紧为只删封口日志);`test_resource_stats.py` 的 lifespan
   用例增加对 `StreamGuardLoop` 的桩。
6. **测试基础设施**:PostgreSQL 用例放在独立文件(`test_outcomes_pg.py`、
   `test_log_locking_pg.py`)并用共享 fixture `pg_sessionmaker`(未设
   `DOPILOT_TEST_DATABASE_URL` 时 `pytest.fail`);`test_notifications.py` 的并发
   用例也改用该 fixture(plan 未限定位置)。fixture 在 teardown 先 `dispose`
   再用新引擎 `drop_all`,避免失败用例残留的行锁让清理挂死。
7. **`apply_log_event` 的写盘路径**:不再经 `files.aappend_increment_capped`,
   改为在 gauge 锁内由 `_write_settled` 完成 stat/write/stat(plan 第 3 闸的
   写法);`files.py` 中的旧函数保留未删(其他读者无变更),本轮无调用方。
8. 其余按 plan 实现。`python_wheel` 的日志语义未改(0019)。
