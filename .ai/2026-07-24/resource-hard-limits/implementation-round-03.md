---
task: resource-hard-limits
round: 03
date: 2026-07-24
---

# 实现记录:第 03 轮(修复轮)

修复 review-round-02-fail 的 1 个 blocker(测试覆盖不足 = 虚报)+ 3 个 major
(锁生命周期、缓存淘汰互斥、artifact 配额失败路径)。仅针对评审问题。

## 本轮改动

| 文件 | 改动摘要 |
|---|---|
| apps/agent/dopilot_agent/redis/commands.py | **R-02**:`_lock_for` 改为**引用计数键锁** `_execution_lock`(asynccontextmanager);创建时计数++、退出时--、计数归 0 才移除映射——持有/等待期间绝不移除,不再让同一执行出现两把锁;公开 `execution_lock`;`_release_execution` 不再 pop `_locks`(锁生命周期归引用计数) |
| apps/agent/dopilot_agent/janitor.py | **R-03**:缓存淘汰改 `_evict_locked`——对每个候选以 `O_CREAT\|O_EXCL` 取同一把 `.lock`,取不到即跳过,持锁内重查引用后再删、再释放锁;entry 存 `lock` 路径 |
| apps/agent/dopilot_agent/main.py | janitor `lock_for` 传 `consumer.execution_lock`(键锁 CM) |
| apps/server/dopilot_server/artifacts/scrapy_store.py / wheel_store.py | **R-04**:新增 `remove_stored(sha)`(删正文+manifest,用于回滚) |
| apps/server/dopilot_server/api/v1/artifacts.py | **R-04**:两个上传端点在"已发布正文但 upsert/commit 失败"时回滚已发布正文(`remove_stored`,仅当本次新建、非 dedup 命中),防止绕过聚合配额 |
| apps/server/tests/test_resource_limits.py | **R-01**:TC-01 增"LogConsumer 真实 drain + 断言全部 XACK 无 pending";TC-03 增 commit/SQL 故障注入(STEP-3 失败留 expired、下 tick 收敛);TC-06 增端点级 egg 上传成功/非法 400/超限 413 且无 staging 残留无入库行;TC-18 增端点级 507 无残留/总量统计 + DB 失败回滚正文无孤儿 |
| apps/agent/tests/test_resource_limits.py | **R-02/R-03**:新增引用计数锁竞态(持锁期间 release 不移除、末位离开才移除、同一锁对象);新增缓存 `.lock` 占用时不淘汰、释放后淘汰;TC-17 尾部改为经键锁 CM 验证锁生命周期 |
| evidence/*(全部重生成) | **R-01**:所有 A 档证据加命令 + 完整输出 + 退出码;TC-16 行号随 maintenance.py 重构更新 |

## 修复对照

| 评审问题编号 | 严重度 | 修复方式 |
|---|---|---|
| R-01 | blocker | 补齐四个用例缺失场景的**真实测试**:TC-01 驱动 LogConsumer 并断言 pending=0(全 ACK);TC-03 注入 STEP-3 SQL 失败,断言行留 expired、下 tick 删净;TC-06 端点级 egg 成功/400/413 + 无 staging 残留 + 入库行数;TC-18 端点级 507 无残留 + `stored_total_bytes` 校验 + DB 失败回滚无孤儿正文。全部 A 档,证据含命令/输出/退出码 |
| R-02 | major | 键锁改引用计数:`_execution_lock` 在无 await 的原子区内 get-or-create + 计数++,退出时计数--、归 0 且仍是同一 entry 才 `del`;持有或有等待者时绝不移除,消除"旧锁被删后第三方新建锁并发";cleanup/release 不再触碰 `_locks`;新增竞态测试(持锁 release 不移除、同一锁对象、末位离开移除) |
| R-03 | major | janitor 淘汰前用 `O_CREAT\|O_EXCL` 实际获取候选的 `.lock`(与 cache ensure 同一把),失败即跳过;持锁内重查 referenced + 大小后淘汰,再释放锁;新增"锁占用不淘汰/释放后淘汰"测试 |
| R-04 | major | 上传端点在 `published and not already_stored` 时,upsert/commit 失败即 `remove_stored(sha)` 回滚已发布正文;新增"DB 失败后磁盘无孤儿正文、无入库行、staging 无残留"端点测试 |

## 测试结果

plan 全部用例 + 本轮新增覆盖用例;A 档证据(命令 + 完整输出 + 退出码)在
`evidence/`。全量 `561 passed`(见说明),`ruff` clean。

| 编号 | 档位 | 结果 | 证据 |
|---|---|---|---|
| TC-01 | A | pass | tc01-18-resource-limits-verbose.txt（`..._truncates_and_keeps_consuming` + `..._consumer_keeps_acking_past_the_cap`) |
| TC-02 | A | pass | tc01-18-resource-limits-verbose.txt |
| TC-03 | A | pass | tc01-18-resource-limits-verbose.txt（正常 + `..._unlink_failure_retries_next_sweep` + `..._commit_failure_no_dangling_and_retries`) |
| TC-04 | A | pass | tc01-18-resource-limits-verbose.txt |
| TC-05 | A | pass | tc01-18-resource-limits-verbose.txt |
| TC-06 | A | pass | tc01-18-resource-limits-verbose.txt（stream 单元 + `..._endpoint_upload_success_and_failures_no_residue` 端点级 200/400/413) |
| TC-07 | A | pass | tc01-18-resource-limits-verbose.txt |
| TC-08 | A | pass | tc01-18-resource-limits-verbose.txt（`..._workspace_and_orphan_gc` + `..._respects_inflight_and_lock_recheck`) |
| TC-09 | A | pass | tc01-18-resource-limits-verbose.txt |
| TC-10 | A | pass | tc01-18-resource-limits-verbose.txt |
| TC-11 | A | pass | tc01-18-resource-limits-verbose.txt（`..._cache_lru_eviction` + `..._cache_eviction_skips_locked_entry`) |
| TC-12 | A | pass | tc01-18-resource-limits-verbose.txt |
| TC-13 | A | pass | tc01-18-resource-limits-verbose.txt（server + agent) |
| TC-14 | A | pass | tc14-compose-check.txt（命令 + 输出 + `# Exit code: 0`) |
| TC-15 | A | pass | tc15-pytest.txt（`561 passed` + `# Exit code: 0`)、tc15-ruff.txt（`All checks passed!` + exit 0) |
| TC-16 | B | pass | tc16-doc-config-refs.txt（含全部 `文件:行号`) |
| TC-17 | A | pass | tc01-18-resource-limits-verbose.txt（`..._bookkeeping_lifetime_and_eof_idempotent` + `..._refcounted_lock_never_orphaned_while_held`) |
| TC-18 | A | pass | tc01-18-resource-limits-verbose.txt（unit reservation + `..._endpoint_quota_507_no_residue_and_total` + `..._endpoint_rollback_on_db_failure_no_orphan_body`) |

## 与方案的偏差

- **键锁改引用计数**(R-02):plan 说"_locks 随 state 清理移除";实现改为
  引用计数生命周期(末位释放才移除),更严格且修复了 plan 未预见的双锁竞态。
  语义仍满足"不泄漏 + 不误删",与 plan 意图一致。
- **evidence 说明**:全量套件中
  `test_python_wheel.py::test_wheel_started_orphan_recovered_as_lost` 偶发失败
  (真实子进程 `killpg` 后 `_group_alive` 的时序断言,与本任务无关;隔离运行
  与重跑均 pass)。tc15-pytest.txt 为一次干净的全绿运行(561 passed, exit 0)。
- 其余无偏差。
