---
task: fix-outbox-sent-oom
date: 2026-08-26
rounds: 1
verdict: pass
---

# 任务小结:修复 command_outbox sent 行无界加载导致的 server OOM 重启循环

生产事故驱动(2026-08-25 起 server 容器每 ~21 秒被 cgroup OOM 杀死,内核
日志 803 次):`reconcile_sent_once` 无界加载 424k 行 `sent` outbox 撑爆
2GiB 内存限额。生产止血(停容器 + 手工清表)在任务外完成;本任务为代码
根治。授权:用户明确放宽 plan/实现评审轮次上限至 15、豁免 plan 人工确认、
授权 commit + push(见 plan.md「用户授权记录」)。

## 改动
| 文件 | 摘要 |
|---|---|
| `apps/server/dopilot_server/redis/dispatcher.py` | sent reconcile 改为 SQL 侧活跃任务过滤 + keyset 游标分页(页尾处理前快照、sweep 边界冻结、空页同轮回绕);dispatch tick 加 FIFO 限批(默认 1000) |
| `apps/server/dopilot_server/services/maintenance.py` | 新增 `prune_resolved_outbox`:分批清理已解决且父任务硬终态/缺失的 outbox 行;排除 reclaim 行与活跃/lost 任务行 |
| `apps/server/dopilot_server/retention.py` | sweep 新增 Step 2b(独立守护)接线 outbox 清理 |
| `apps/server/dopilot_server/config/{settings,loader}.py` | 新键 `sent_reconcile_batch_limit=500`、`outbox_retention_days=7`、`outbox_delete_batch=5000` + env 映射 |
| `configs/server.{example,docker}.toml` | 新键样例 |
| `apps/server/tests/{test_log_guard,test_dispatcher,test_maintenance,test_config}.py` | TC-01~12 全 A 档:SQL 捕获断言、游标快照、持续写入防饥饿、unresolved 三态保留、故障隔离、reclaim 不变量回归 |
| `docs/architecture/{03-execution-and-logs,04-configuration}.md` | reclaim 行寿命说明 + 配置表新键 |

## 评审历程
| 轮次 | 结论 | 关键问题 |
|---|---|---|
| plan-01 | fail | 限批无游标会饿死后续行(plan-blocker);证据契约/授权记录/三态覆盖/故障隔离(major×4) |
| plan-02 | fail | 清扫会误删持久 reclaim 去重事实(plan-blocker);页尾快照与回绕语义矛盾(major) |
| plan-03 | fail | 测试未锁定 SQL 侧过滤/限批、无法检出游标污染(major×2) |
| plan-04 | fail | 持续写入使游标永不回绕、旧行永失复查(plan-blocker)→ 冻结 sweep 边界 |
| plan-05 | pass | 无问题 |
| impl-01 | pass | 无问题(blocker/major/minor 均为 0);TC-01~12 证据核验一致 |

## 遗留 minor 及处置
无(实现层评审零问题)。

## 验证
- 12 条用例全 A 档 pass,证据在 evidence/(每条:命令 + 全量输出 + exit=0)
- 全量回归:`ruff check apps packages` 通过;`pytest apps/server`(含
  DOPILOT_TEST_DATABASE_URL 指向 dev PG)494 passed / 1 skipped / 0 failed
