# Plan 评审:第 03 轮

## 问题清单
- [major] R-01 state 缺失时统一忽略 stop，会破坏既有 cancel 终态契约。
  - 详情:定位：plan.md §4.5 第 5 条及 TC-27。现有 commands.py 的 process_missing 忽略仅适用于 reclaim；cancel 即使 state 不存在，也会 emit_terminal(canceled)。docs/architecture/03-execution-and-logs.md:28 明确要求此行为，尚未启动便取消的执行也依赖该事件收敛。方案将所有 stop 都改成忽略，会使取消无法及时完成。请按 intent 分支：reclaim 可忽略，cancel 保留权威 canceled 上报；TC-27 分别验证两种意图，并补充取消尚未启动执行的用例。
- [major] R-02 unknown 分支提前结束 tick，与停止确认的硬期限及 TC-28 冲突。
  - 详情:定位：plan.md:202–211。方案规定 status 为 unknown 时“本 tick 到此为止”，但总期限检查排在该分支之后。scrapyd 持续不可达时，每次都会提前返回，无法在 120 秒后强制收尾，cleanup_pending 也无法按约定释放。请明确期限检查必须覆盖 unknown、信号失败和 running 路径，例如在提前返回前统一判断期限；TC-28 应包含持续 unknown 直至超过期限的独立场景，分别断言 cancel/reclaim 收尾及挂起清理完成。
- [major] R-03 延期清理在 mark_done 后发生中断时，缺少重启恢复入口。
  - 详情:定位：plan.md §4.4、§4.5 第 3–4 条。方案先 mark_done，再执行 cleanup_pending；若两步之间进程退出，或清理抛异常，磁盘留下 phase=done、cleanup_pending=True。现有 reconcile_started_attempts 跳过所有非 started 状态，recover 也没有恢复此类清理的分支，而 cleanup 命令此前已经 ACK。因此“无需额外恢复代码”“最长推迟 120 秒”的保证不成立。请增加对 done 且 cleanup_pending 状态的幂等恢复清理入口，并补充 mark_done 后、清理前重启，以及清理首次失败后重试的 A 档用例；TC-23 仅覆盖 TERM 前重启，不能覆盖该窗口。

## 总评
证据契约合规：31 条用例均逐条声明 A 档及证据形态，也覆盖了多项异常路径。停止状态机仍存在取消契约退化、期限分支冲突和延期清理恢复缺口，需修订方案及对应测试后重评。

VERDICT: fail
