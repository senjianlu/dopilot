# 评审:第 01 轮

## 问题清单
- [blocker] R-03 若干 A 档用例被记录为通过，但引用测试没有执行方案要求的关键场景。
  - 详情:.ai/2026-09-16/no-progress-stall-detection/implementation-round-01.md:104、105、113、117 等：原始日志确实包含所引用测试的通过结果，但不足以证明这些方案用例通过。例如 apps/agent/tests/test_stop_state_machine.py:257 的 TC-39 引用测试在 TERM 后直接确认退出，完全没有超时、kill_pending 或持续回收；:704 的 TC-31 引用测试没有重建 agent；:628 的 TC-43 测试在补发终态后结束，未完成后续回收清理。按证据契约须补齐测试，并为下列缺失内容提交执行命令、完整 stdout/stderr 和退出码：TC-07/09/10/13 通过真实 apply_event 心跳驱动去重、采样失效及恢复（当前直接改数据库字段，TC-09 还缺 auto_stop=False 分支）；TC-23 重启后的 KILL 升级；TC-26 reclaim 与延期清理交错（当前测的是 cancel）；TC-30 cancel/reclaim 两种意图及超时后持续 unknown 的多个 tick；TC-31 重启恢复清理及重复执行；TC-36 挂起清理请求后的重投与清理；TC-37 超时前已有 cleanup_pending；TC-38 超时后 unknown 阶段不清理；TC-39 reclaim 超时后持续回收、无事件、确认退出后清理；TC-43 补发终态最终送达 server，随后继续 KILL、确认及清理；TC-44 真正 pending job 被取消后消失并完成延期清理（当前在 cancel 前已清空所有列表）。涉及清理的用例还需创建并核验实际日志/workspace 删除，不能只断言 state 消失。同步修正实现记录，不能用较窄测试的 PASSED 代替完整用例通过。
- [major] R-01 reclaim 重投会绕过停止幂等检查，将自行产生的 canceled 当作权威终态。
  - 详情:apps/agent/dopilot_agent/redis/commands.py:1095：已有 stop_requested_at 的检查直到 _begin_stop:1113 才执行。首次 reclaim 发出 TERM、job 离开列表后，若同批收到重复 reclaim，status() 会因 mark_canceled 返回 canceled，随后 _finish_scrapy_attempt 将其上报，覆盖 server 的 lost，违反 plan §4.2/4.4。应在查询 status 之前检查已持久化的停止意图，让已有状态机独占收尾；补充同批重复 reclaim 的回归测试。
- [major] R-02 事件超时判 lost 后仍继续无进度检测，可能同时下发 reclaim 与 cancel。
  - 详情:apps/server/dopilot_server/redis/reconcile.py:208：第 2 步 mark_lost 后没有 continue，第 3 步也不检查 execution 是否仍 active。当 lost_after_stalled_seconds 小于采样有效窗口，且进度超阈值时，同一轮可以先判 lost 并创建 reclaim，再创建无进度 cancel；cancel 最终可能把 lost 覆盖成 canceled。此配置是允许的，且违反 plan §3“会被判 lost 的执行走不到这里”的约束。应在 lost 分支结束本执行的处理，或在无进度入口显式排除终态，并测试两个阈值窗口重叠的情况。

## 总评
无进度时钟与存活时钟的分离、默认关闭自动停止等主体实现符合方案，但停止重投和 lost 分支隔离仍有正确性缺陷。按只读要求未运行任何测试；已核验提交的测试日志，部分 A 档验收场景仍缺完整覆盖证据，本轮不通过。

VERDICT: fail
