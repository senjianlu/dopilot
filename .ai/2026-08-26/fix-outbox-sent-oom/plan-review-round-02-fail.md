# Plan 评审:第 02 轮

## 问题清单
- [plan-blocker] R-01 清扫 resolved outbox 会删除 soft-lost 任务的持久 reclaim 标记，破坏既有 at-most-once 与日志清理门禁。
  - 详情:定位：plan.md:136-157、199-201；apps/server/dopilot_server/services/outbox.py:166-183；services/events.py:211-225；redis/reconcile.py:239-244；docs/architecture/03-execution-and-logs.md:56-61。方案把所有父任务非活跃的 sent/failed/canceled 行视为可删，但 TASK_LOST 是可被后到 agent 事件覆盖的软终态；现有 reclaim_ever_issued 明确把 sent 甚至 failed 的 stop(intent=reclaim) 行作为持久事实，用于保证每 execution 终生至多一次 reclaim，并作为 lost execution 定稿日志的安全门禁。默认 outbox 保留 7 天而任务保留 30 天，清扫后到达的 heartbeat 会再次创建 reclaim，finalize_drained_logs 也会把已 reclaim 的 execution 误判为未 reclaim。需在方案层重新定义安全删除边界，例如保留 lost execution 的 reclaim 行直到父任务删除，或把该事实迁移到独立持久字段；补充清扫后 heartbeat 不重复 reclaim及日志门禁不回退的 A 档测试，并同步更新 docs/architecture/03-execution-and-logs.md，而不应只改配置文档。
- [major] R-02 keyset 页尾取自处理后的可变 ORM 行，且满批回绕算法与 TC-09 的调用次数互相矛盾。
  - 详情:定位：plan.md:83-115、184、191。逐行处理会把缺失消息改为 pending，随后 notif.notify 会执行 flush；CommandOutbox.updated_at 具有 onupdate=func.now()，因此在处理结束后读取 rows[-1].updated_at 可能得到更新后的时间而非本页查询键，游标会越过尚未扫描的旧 sent 行，在持续有新行时可形成饥饿，并使 TC-02 第二次调用无法取得第 3 条。应在 SELECT 返回后、任何 await/修改/flush 前立即快照不可变 page_end。另按当前“len(rows)==batch 就推进”规则，TC-09 第二次处理 Y 后，第三次只会查到空页并复位，第四次才从头检查 X；若要求第三次检查 X，需采用 batch+1、空页同轮回绕重查等明确算法，否则修正用例，并通过 XRANGE 调用目标断言真实检查了 X，而不能只断言返回空列表。

## 总评
方案已补齐逐条 A 档及完整证据形态，C 档为 0，批界、未解决状态和故障隔离也有覆盖。但清扫方案违反现有持久 reclaim 不变量，keyset 伪代码亦无法满足自身测试与无饥饿承诺，必须修订后重评。

VERDICT: fail
