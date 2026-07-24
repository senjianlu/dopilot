---
task: resource-hard-limits
round: 01
date: 2026-07-24
---

# 实现记录:第 01 轮

按已确认 plan(status: approved)实现 Phase A(部署层)+ B(server)+ C(agent)
+ 文档回写。约 43 个源码/配置/文档文件 + 2 个新测试文件。无 Alembic 迁移、
无协议破坏性变更。

## 本轮改动

| 文件 | 改动摘要 |
|---|---|
| deploy/docker/docker-compose.yml / .server.yml / .agent.yml | **A**:新增共享 `x-logging` anchor(json-file 10m×3)应用到每个 service;redis 命令追加 `--maxmemory ${DOPILOT_REDIS_MAXMEMORY:-512mb} --maxmemory-policy noeviction` + AOF 自动重写阈值 |
| apps/server/dopilot_server/config/settings.py | **B**:`stream_maxlen_logs` 默认 1M→100k;`log_retention_seconds` 注释;`[logs]` 加 `max_file_bytes`、`retention_days` 14→30;新增 `MaintenanceSettings`;`[artifacts]` 加 `max_upload_bytes`/`max_total_bytes` |
| apps/server/dopilot_server/config/loader.py | 新字段的 env 覆盖(`DOPILOT_LOG_MAX_FILE_BYTES`、`DOPILOT_MAINTENANCE_*`、`DOPILOT_ARTIFACTS_MAX_*`) |
| configs/server.example.toml / server.docker.toml | 同步新配置段/字段 |
| apps/server/dopilot_server/logs/files.py | **B1**:`append_increment_capped` + `aappend_increment_capped`(达上限写截断标记、返回 truncated_now) |
| apps/server/dopilot_server/services/logs.py | **B1**:apply 路径接入 cap;新增 `OUTCOME_TRUNCATED(_DROPPED)`、`INTEGRITY_TRUNCATED`;已截断则继续消费只推进 cursor;SSE 内容按实写字节 |
| apps/server/dopilot_server/models/execution.py | **B1**:`log_integrity` 注释新增 `truncated` 值语义 |
| apps/server/dopilot_server/redis/reconcile.py | **B2**:finalize 时写 `retained_until` |
| apps/server/dopilot_server/services/maintenance.py | **B2/B3/B4**:`cleanup_terminal_data` 重构为失败安全两阶段(标 expired 提交→unlink→删行提交);新增 `prune_event_audit`(分批)、`trim_log_streams`(XTRIM MINID) |
| apps/server/dopilot_server/redis/client.py | **B4**:`RedisStreams.xtrim` + Protocol |
| apps/server/dopilot_server/retention.py（新） | **B2/B3/B4**:`RetentionSweepLoop`(克隆 reconcile 模式,三步独立守护) |
| apps/server/dopilot_server/app.py | **B2**:lifespan 挂载/停止 RetentionSweepLoop(gated `[maintenance].enabled`) |
| apps/server/dopilot_server/api/v1/maintenance.py | **B2**:service 自持提交,handler 不再 commit |
| apps/server/dopilot_server/artifacts/upload.py（新） | **B5**:`stream_to_staging`(分块+413)、`reserve_quota`/`release_quota`(507+并发锁) |
| apps/server/dopilot_server/artifacts/{scrapy,wheel}_store.py | **B5**:`validate_*_path` + `save_from_path`(路径校验+原子发布) |
| apps/server/dopilot_server/services/artifacts.py | **B5**:`stored_total_bytes` |
| apps/server/dopilot_server/api/v1/artifacts.py | **B5**:两个上传端点改流式+配额+finally 清理 |
| apps/server/dopilot_server/logs/sse.py | **B6**:队列 `maxsize`;满则清空+CLOSE+unsubscribe,幂等 |
| apps/agent/dopilot_agent/config/settings.py | **C7**:`[agent]` 加 janitor/TTL/job.log/cache 字段;`[redis]` 加 maxlen_*/outbox 上限;`[scrapyd]` 加 jobs/finished_to_keep |
| apps/agent/dopilot_agent/config/loader.py | **C7**:maxlen env 覆盖 |
| configs/agent.example.toml | 同步新字段 |
| apps/agent/dopilot_agent/runners/python_wheel.py | **C2/C1/C6**:stdout=PIPE + drain(限额+标记+继续排空);spawn 写 `job.pgid` sidecar(失败即杀);reaper await drain;`active_execution_ids`;`forget` |
| apps/agent/dopilot_agent/janitor.py（新） | **C1/C4**:`AgentJanitor`——workspace/logpos/state TTL GC(三重安全判定)+ 缓存 LRU 淘汰 |
| apps/agent/dopilot_agent/redis/logs.py | **C1/C6**:`on_eof` 回调 + `forget`(删 .logpos + 清 _eof_sent) |
| apps/agent/dopilot_agent/redis/events.py | **C5**:`_enforce_outbox_cap`(drop-oldest) |
| apps/agent/dopilot_agent/redis/commands.py | **C6**:`on_execution_eof`、`set_log_publisher`、`_release_execution`;`_handle_cleanup` 补删 .logpos + 释放全部簿记 |
| apps/agent/dopilot_agent/scrapyd/process.py | **C3**:scrapyd.conf 写 jobs/finished_to_keep |
| apps/agent/dopilot_agent/artifacts/{cache,wheel_cache}.py | **C4**:缓存命中 touch `.ready` mtime |
| apps/agent/dopilot_agent/deps.py / main.py | 装配新参数 + 启停 janitor + on_eof/set_log_publisher 接线 |
| apps/server/tests/test_log_consumer.py | 既有测试跟随 B1 写路径更名(spy `aappend_increment_capped`) |
| apps/{server,agent}/tests/test_resource_limits.py（新） | 18 条 TC |
| docs/architecture/03/04/05 + docs/decisions/0019 + README | 回写 truncated/自动清理/配置面/部署上限/收缩 runbook + 新决策 |

## 修复对照

不适用(第 1 轮)。

## 测试结果

18 条用例全部 pass,档位照抄 plan(17 A + 1 B,C 档 0)。A 档原始输出见
`evidence/`。

| 编号 | 档位 | 结果 | 证据 |
|---|---|---|---|
| TC-01 | A | pass | tc01-18-resource-limits-verbose.txt（`test_tc01_log_file_size_cap_truncates_and_keeps_consuming`） |
| TC-02 | A | pass | 同上（`test_tc02_truncated_sticky_through_finalize`） |
| TC-03 | A | pass | 同上（`test_tc03_retention_sweep_deletes_old_terminal_only` + `..._unlink_failure_leaves_no_dangling_index`,含 unlink 故障注入) |
| TC-04 | A | pass | 同上（`test_tc04_event_audit_batch_prune`） |
| TC-05 | A | pass | 同上（`test_tc05_trim_log_streams_xtrim_minid`,stub 断言 minid 毫秒) |
| TC-06 | A | pass | 同上（`test_tc06_stream_upload_413_over_cap_no_residue` + `..._under_cap_ok`,fake UploadFile 强制分块) |
| TC-07 | A | pass | 同上（`test_tc07_sse_bounded_queue_force_closes_slow_subscriber`） |
| TC-08 | A | pass | 同上（`test_tc08_janitor_workspace_and_orphan_gc`,含损坏 state+pgid 存活/mtime 新鲜不删) |
| TC-09 | A | pass | 同上（`test_tc09_job_log_size_cap_no_block`,~2MiB 输出远超管道容量仍正常退出) |
| TC-10 | A | pass | 同上（`test_tc10_scrapyd_conf_retention_keys`） |
| TC-11 | A | pass | 同上（`test_tc11_cache_lru_eviction`,含被引用 sha 不淘汰、cap=0 不淘汰) |
| TC-12 | A | pass | 同上（`test_tc12_outbox_cap_drops_oldest`） |
| TC-13 | A | pass | 同上（server `test_tc13_server_defaults_and_env_overrides` + agent `test_tc13_agent_defaults_and_env_overrides`,含 retention_days=30、maxlen_logs=100000) |
| TC-14 | A | pass | tc14-compose-check.txt（3 份 compose `docker compose config` OK + 每 service max-size + redis maxmemory/noeviction/auto-aof-rewrite 断言,FAIL=0) |
| TC-15 | A | pass | tc15-pytest.txt（`553 passed`)、tc15-ruff.txt（`All checks passed!`） |
| TC-16 | B | pass | tc16-doc-config-refs.txt:`retention_days` 消费点 `retention.py:71`、`log_retention_seconds` 消费点 `maintenance.py:268`、`retained_until` 写入 `reconcile.py:240`;04/05/03 文档 + 0019 决策已回写;`docs/phases` 已删除 |
| TC-17 | A | pass | tc01-18-resource-limits-verbose.txt（`test_tc17_bookkeeping_lifetime_and_eof_idempotent`,含 EOF 后多 tick 只发一次、_eof_sent/_locks 保留至 cleanup) |
| TC-18 | A | pass | 同上（`test_tc18_quota_507_at_boundary_and_concurrency`,含并发预留互斥、dedup/配额=0) |

## 与方案的偏差

- **C6 簿记清理落点**:plan 写 `_locks` 随 state 清理移除;实现中 `_locks`
  与 `_eof_sent` 一并在 `_handle_cleanup`/janitor 的 `_release_execution` 中
  释放(而非分散),`_inproc_wheel` + runner dicts 仍在 EOF 时经
  `on_execution_eof` 释放。行为与 plan 的两档生命周期一致(EOF-safe 项
  EOF 释放、扫描源同生命周期项 cleanup 释放),仅把后者集中到一个
  `_release_execution` 方法,不影响语义。
- 其余无偏差。plan 声明的档位与预期结果均未改动。
