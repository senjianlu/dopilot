---
task: resource-hard-limits
round: 02
date: 2026-07-24
---

# 实现记录:第 02 轮(修复轮)

修复 review-round-01-fail 的 2 个 blocker(证据契约)+ 2 个 major(资源清理
正确性)。仅针对评审问题,未做无关改动。

## 本轮改动

| 文件 | 改动摘要 |
|---|---|
| apps/server/dopilot_server/services/maintenance.py | **R-03**:STEP 2 区分"unlink 失败(文件仍在)"与"已缺失(幂等成功)";失败的 task_id 计入 `failed_task_ids`,STEP 3 只删 `deletable`(未失败)的行/task,失败者留 expired 待下 tick 重试;`summary.tasks` 改为实际删除数 |
| apps/server/dopilot_server/logs/files.py | **R-03**:新增 `aexists`(异步 os.path.exists),用于区分失败 unlink 与已缺失 |
| apps/agent/dopilot_agent/redis/commands.py | **R-04**:新增 `_processing` 在途集(围绕 `_process` 增删)、`active_execution_ids()`(= `_processing ∪ _inproc_wheel`)、公开 `lock_for` |
| apps/agent/dopilot_agent/janitor.py | **R-04**:workspace 扫描改两阶段——线程内按活跃集快照扫候选,再在事件循环上**持同一把 per-execution 锁**、以**新鲜活跃集** + 重新 stat 复核后才删;`active_ids`/`lock_for` 注入(缺省回退 runner-only);`_remove_execution`→`_remove_files`(release 移出锁外) |
| apps/agent/dopilot_agent/main.py | **R-04**:janitor 装配 `active_ids`(runner ∪ consumer 在途)+ `lock_for`(consumer 锁) |
| apps/server/tests/test_resource_limits.py | **R-03**:TC-03 故障用例改断言"失败 unlink → 行留 expired + 文件仍在 + task 未删;恢复后下 tick 删净"(重命名 `..._retries_next_sweep`) |
| apps/agent/tests/test_resource_limits.py | **R-04**:新增 `test_tc08_janitor_respects_inflight_and_lock_recheck`(在途集保护 + 锁内新鲜复核竞态) |
| evidence/*(全部重生成) | **R-01/R-02**:每份 A 档证据加"# Command / # Exit code"框(tc15-pytest / tc15-ruff / tc14-compose-check / tc01-18-verbose);TC-16 补全 `文件:行号` 锚点 |

## 修复对照

| 评审问题编号 | 严重度 | 修复方式 |
|---|---|---|
| R-01 | blocker | 全部 A 档证据文件重生成,顶部写执行命令、尾部写退出码;覆盖 TC-01～15、17、18 的命令/完整输出/退出码(共享文件已在测试结果表标注覆盖关系) |
| R-02 | blocker | TC-16 证据补全 `文件:行号`:死配置消费点(retention.py:71、maintenance.py:285、reconcile.py:240)与各文档回写锚点(04:28/30/37、03:80/82/89/93、05:48/60/66、0019:1、README:43) |
| R-03 | major | unlink 失败不再删对应 DB 行:失败 task 留 expired 行 + 文件在盘,下一 sweep 重试;`aexists` 区分失败与已缺失;TC-03 故障用例改为断言重试语义(首次失败保留、恢复后删净) |
| R-04 | major | janitor 活跃集纳入 consumer 在途 id(`_processing`);删除决策移到事件循环、持 `_handle_cleanup` 同一把 per-execution 锁,并在锁内用新鲜活跃集 + 重新 stat 复核后才删;新增竞态测试 |

## 测试结果

plan.md 全部 18 条 + 本轮新增竞态用例,档位照抄 plan(A 档,证据在
`evidence/`);全量 `554 passed`,`ruff` clean。

| 编号 | 档位 | 结果 | 证据 |
|---|---|---|---|
| TC-01 | A | pass | tc01-18-resource-limits-verbose.txt |
| TC-02 | A | pass | tc01-18-resource-limits-verbose.txt |
| TC-03 | A | pass | tc01-18-resource-limits-verbose.txt（`..._deletes_old_terminal_only` + `..._unlink_failure_retries_next_sweep`,故障重试语义) |
| TC-04 | A | pass | tc01-18-resource-limits-verbose.txt |
| TC-05 | A | pass | tc01-18-resource-limits-verbose.txt |
| TC-06 | A | pass | tc01-18-resource-limits-verbose.txt（413 + under-cap 两例) |
| TC-07 | A | pass | tc01-18-resource-limits-verbose.txt |
| TC-08 | A | pass | tc01-18-resource-limits-verbose.txt（`..._workspace_and_orphan_gc` + `..._respects_inflight_and_lock_recheck` 竞态) |
| TC-09 | A | pass | tc01-18-resource-limits-verbose.txt |
| TC-10 | A | pass | tc01-18-resource-limits-verbose.txt |
| TC-11 | A | pass | tc01-18-resource-limits-verbose.txt |
| TC-12 | A | pass | tc01-18-resource-limits-verbose.txt |
| TC-13 | A | pass | tc01-18-resource-limits-verbose.txt（server + agent 两例) |
| TC-14 | A | pass | tc14-compose-check.txt（命令 + 输出 + `# Exit code: 0`) |
| TC-15 | A | pass | tc15-pytest.txt（`554 passed` + `# Exit code: 0`)、tc15-ruff.txt（`All checks passed!` + `# Exit code: 0`） |
| TC-16 | B | pass | tc16-doc-config-refs.txt（含全部 `文件:行号`) |
| TC-17 | A | pass | tc01-18-resource-limits-verbose.txt |
| TC-18 | A | pass | tc01-18-resource-limits-verbose.txt |

## 与方案的偏差

- 与第 01 轮相同的 C6 集中释放说明(见 round-01),不影响语义。
- R-04 修复引入 janitor 的 `active_ids`/`lock_for` 注入点,属 plan「三重安全
  判定 + per-execution 锁」的落地细化,与方案一致(plan 风险与回滚节已列
  "janitor 必须在同一 per-execution 锁内重新核验活跃性后删除")。
- 其余无偏差。
