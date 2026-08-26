---
task: fix-outbox-sent-oom
round: 01
date: 2026-08-26
---

# 实现记录:第 01 轮

按已批准 plan(plan-review 第 5 轮 pass)实现。**授权声明**:本任务经用户
2026-08-26 明确指示放宽评审轮次上限(plan/实现修复各 15 轮)、豁免 plan
人工确认闸、并授权做到 commit + push,原文见 plan.md「用户授权记录」。

## 本轮改动
| 文件 | 改动摘要 |
|---|---|
| `apps/server/dopilot_server/redis/dispatcher.py` | `reconcile_sent_once`:SQL 侧 JOIN tasks 过滤活跃任务 + keyset 游标分页(`(updated_at, command_id)` 排序、页尾处理前快照、sweep 边界冻结、空页同轮回绕一次);`_tick`:dispatchable 查询 `ORDER BY created_at` + `LIMIT dispatch_batch_limit`(构造参数,默认 1000);新增导入 `tuple_`、`Task` |
| `apps/server/dopilot_server/services/maintenance.py` | 新增 `OUTBOX_RESOLVED` 与 `prune_resolved_outbox()`:分批删除已解决且父任务硬终态/缺失的行;排除 `stop(intent=reclaim)` 行与活跃/lost 任务的行;每批 commit;retention=0 关闭 |
| `apps/server/dopilot_server/retention.py` | `sweep_once` 新增 Step 2b(独立 try/except 守护)调用 `prune_resolved_outbox`;模块 docstring 步骤清单同步 |
| `apps/server/dopilot_server/config/settings.py` | 新增 `RedisSettings.sent_reconcile_batch_limit=500`、`MaintenanceSettings.outbox_retention_days=7`、`outbox_delete_batch=5000`(带注释) |
| `apps/server/dopilot_server/config/loader.py` | 新增 `DOPILOT_REDIS_SENT_RECONCILE_BATCH_LIMIT`、`DOPILOT_MAINTENANCE_OUTBOX_RETENTION_DAYS`、`DOPILOT_MAINTENANCE_OUTBOX_DELETE_BATCH` env 映射 |
| `configs/server.example.toml`、`configs/server.docker.toml` | 三个新键示例与注释 |
| `apps/server/tests/test_log_guard.py` | 新增 `_SqlSpy`/`_reconcile_dispatcher`/`_sent_row` 助手与 TC-01/02/09 三条用例(SQL 捕获断言、游标快照断言、持续写入防饥饿) |
| `apps/server/tests/test_dispatcher.py` | 新增 TC-07 用例(限批 + ORDER BY/LIMIT 的 SQL 断言) |
| `apps/server/tests/test_maintenance.py` | 新增 `_outbox_row`/`_outbox_ids` 助手与 TC-03/04(参数化 3 态)/05/10/11/12 六组用例 |
| `apps/server/tests/test_config.py` | 新增 TC-06 三条用例(默认值 / TOML 覆盖 / env 覆盖) |
| `docs/architecture/04-configuration.md` | `[redis]`/`[maintenance]` 配置表补三个新键 |
| `docs/architecture/03-execution-and-logs.md` | reclaim 持久去重段落补"清扫永不删 reclaim 行,随任务删除" |

## 修复对照
(第 1 轮,不适用)

## 测试结果
| 编号 | 档位 | 结果 | 证据 |
|---|---|---|---|
| TC-01 | A | pass | evidence/tc-01.txt(命令+全量输出,exit=0) |
| TC-02 | A | pass | evidence/tc-02.txt(exit=0;含游标==seed 页尾元组断言) |
| TC-03 | A | pass | evidence/tc-03.txt(exit=0) |
| TC-04 | A | pass | evidence/tc-04.txt(exit=0;pending/dispatching/failed_retryable 参数化 + 活跃/新行/retention=0) |
| TC-05 | A | pass | evidence/tc-05.txt(exit=0) |
| TC-06 | A | pass | evidence/tc-06.txt(exit=0) |
| TC-07 | A | pass | evidence/tc-07.txt(exit=0) |
| TC-08 | A | pass | evidence/tc-08-ruff.txt(All checks passed,exit=0)、evidence/tc-08-pytest.txt(494 passed, 1 skipped,exit=0;含 `DOPILOT_TEST_DATABASE_URL` 指向 scripts/dev-db 的 PG 并发用例) |
| TC-09 | A | pass | evidence/tc-09.txt(exit=0;xrange 打点证明 X 在第 1、3 次调用被真实检查,第 3 次被重排) |
| TC-10 | A | pass | evidence/tc-10.txt(exit=0;双向故障注入) |
| TC-11 | A | pass | evidence/tc-11.txt(exit=0) |
| TC-12 | A | pass | evidence/tc-12.txt(exit=0;heartbeat at-most-once + finalize 门禁) |

全量回归:494 passed / 1 skipped / 0 failed(skip 为既有条件跳过,与本任务无关)。

## 与方案的偏差
1. **测试实现细节**:async 会话下 `expire_all()` 后不能再读 ORM 属性
   (MissingGreenlet),用例中改为先把 id 存入普通变量再 expire——纯测试
   写法调整,不影响 plan 声明的前置/步骤/预期。
2. **TC-06 TOML 用例**:最小 TOML 需带 `[auth]` 段(loader Web admin auth
   fail-closed 校验),按仓库既有 `_write_toml` 惯例补齐——预期结果不变。
3. 其余与 plan 一致:无接口、范围、架构层面的偏差。
