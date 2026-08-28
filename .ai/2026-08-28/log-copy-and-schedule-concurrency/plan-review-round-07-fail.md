# Plan 评审:第 07 轮

## 问题清单
- [major] R-01 既有重复手动触发用例与新的默认并发上限 1 直接冲突，TC-29 按方案执行必然失败
  - 详情:`apps/server/tests/test_schedules.py:258` 的 `test_repeated_trigger_now_not_coalesced` 创建未指定上限的 schedule，第一次触发留下 queued task 后仍断言第二次触发成功；新方案将默认上限设为 1，第二次必须返回 409。改动范围却只声明为该文件补默认值断言。应明确把该既有用例改为 `max_concurrency=0`（或至少 2），继续验证“trigger-now 不做 backlog coalesce”，由新增并发用例验证默认限制；否则全量回归证据 TC-29 不可能退出 0。
- [major] R-02 TC-37 在释放首次提交后未固定 outbox 的 unresolved 状态，无法确定性验证锁内 coalesce
  - 详情:TC-37 只让事务 A 在首次 commit 前停住；放行 commit 后，A 会继续执行 `try_dispatch`，可能在事务 B 获锁并查询 backlog 前将 outbox 提交为 `sent`。既有 coalesce 本就不统计 sent 行，此时 B 创建第二个任务是合法结果，测试会因调度时序偶发失败，不能可靠区分查询位于锁内还是锁外。应增加首次 commit 后、XADD/最终 sent 提交前的第二道屏障（例如阻塞 producer），待 B 完成锁下 backlog 判断后再放行 A，或采用等价的确定性协调方式。

## 总评
方案的行锁结构、下载快照语义及 A/B/C 证据契约总体已经自洽，37 个 A 档、2 个 B 档、0 个 C 档符合约束。当前仍有一个确定的存量回归冲突和一个关键 PostgreSQL 竞态用例的不确定性，均会阻止形成可信且全绿的实现证据，因此判定 fail。

VERDICT: fail
