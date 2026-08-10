# Plan 评审:第 01 轮

## 问题清单
- [plan-blocker] R-01 心跳短路会绕过既有 lost 后重连时的 reclaim 保护，可能让已标 lost 的进程永久继续运行。
  - 详情:定位：plan.md 第121-135行将所有 heartbeat 在 dedupe/状态机之前短路，并称对 terminal execution 无副作用。现有 apply_event 对 EXEC_LOST 收到任一非终态事件时会调用 _request_reclaim（apps/server/dopilot_server/services/events.py:200-206）；这是 agent 曾失联、server 以 heartbeat_timeout 标 lost（reconcile.py:145-150，不发 stop）后恢复时防止本地进程继续运行的保护。按方案，新 agent 恢复后只发 heartbeat，会仅刷新 last_event_at/stalled_at，既不恢复状态也不投递 reclaim，且 reconcile 不再扫描 lost execution，导致该进程无法被回收。需在方案中明确 heartbeat 对 EXEC_LOST 的处理须保留/触发既有 reclaim 语义（并避免重复投递），仅对非 lost 的 execution 做纯刷新；相应补充自动化用例，覆盖 heartbeat 到达 server-lost execution 后状态保持 lost 且恰好产生 reclaim stop。

## 总评
方案的证据契约合规：10 条用例均逐条声明 A 档和完整原始输出形态，且没有 C 档；同时覆盖了多条异常路径。其心跳短路与既有 lost 恢复保护冲突，须修订方案后再评审。

VERDICT: fail
