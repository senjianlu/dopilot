# Plan 评审:第 05 轮

## 问题清单
- [plan-blocker] R-01 确认超时后删除停止状态，会再次产生无法追踪和回收的存活进程。
  - 详情:定位：plan.md 第 209–211、231–234、249–265 行及 TC-19、TC-30。方案在进程仍 running、持续 unknown，甚至所有信号均发送失败时，仍强制 mark_done 并执行延期清理。此后 tick 跳过 done 状态，cleanup 又删除 scrapyd job 映射，进程一旦仍存活便再无人重试停止；这与目标“确认进程真的死了”和消除不可见残留进程直接冲突。建议将取消终态的有界确认期限与进程回收生命周期分开：可以按契约报告 canceled，但未确认退出时保留持久回收记录和重试入口，确认退出后再删除必要映射。增加超过期限仍存活、随后 scrapyd 恢复时最终完成回收的 A 档测试，不能只断言 canceled 和清理成功。
- [major] R-02 停止状态机未处理已有 done 状态，取消请求可能没有任何终态出口。
  - 详情:定位：plan.md §4.2 第 0–3 步、§4.5 第 4 条。现有 commands.py 的 reconcile_started_attempts 会在消费 stop 前先把自然完成的执行标为 done；_handle_stop 当前仍会对它上报权威 canceled。新方案只特判 state 不存在或已有 stop_requested_at，其余 cancel 都登记停止意图，并要求 phase 保持 started，但没有定义输入为 done 时的处理。若保留原 phase，后续 tick 永远跳过它，取消事件不再发出；若改回 started，则引入未声明的终态回退。建议明确非 started 状态的 cancel/reclaim 分支，对已结束执行直接按既有契约收尾，不进入等待状态机；补充“本地自然结束并 mark_done 后、cleanup 前收到 cancel”的 A 档测试，验证终态必达且不会重新激活执行。

## 总评
工作流闸门、轮次声明和测试证据契约符合现有约定，36 条测试均逐条声明了 A 档及证据形态，也覆盖了多种异常路径。但停止超时后的资源生命周期和已有终态的取消分支仍需修订，因此本轮不通过。

VERDICT: fail
