# Plan 评审:第 03 轮

## 问题清单
- [major] R-01 LOST execution 的心跳 reclaim 去重只检查未决 outbox，首次 stop 已 sent 后仍会每 60 秒重复投递 reclaim。
  - 详情:定位：plan.md:146-166、TC-11；现有 apps/server/dopilot_server/services/events.py:99-116 的 `_has_unresolved_reclaim` 仅匹配 pending/dispatching/failed_retryable，而 sent 不在该集合（models/command_outbox.py:26-40）。新心跳是周期性事件：首次 reclaim 被 dispatcher 标为 sent、但进程尚未产生终态时，下一次 heartbeat 会再次创建 stop，违背方案的“幂等去重/恰好一条”承诺，可能造成持续重复回收命令和审计记录。方案应改为对该 execution 是否已曾投递 reclaim 做持久去重（或等价唯一性约束），并把 TC-11 扩展为：将首条 reclaim 模拟为 sent 后再处理下一次 heartbeat，仍断言仅一条 reclaim outbox 且不新增审计。

## 总评
方案的测试证据契约合规：12 条用例均逐条声明 A 档及完整原始输出，且包含异常和边界路径。除 reclaim 的 sent 后重复投递缺口外，协议、状态机隔离和升级顺序与现有工作流约定一致。

VERDICT: fail
