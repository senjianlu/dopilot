# Plan 评审:第 07 轮

## 问题清单
- [major] R-01 收尾落盘与终态投递之间的崩溃窗口没有恢复路径，违反 canceled 必达契约。
  - 详情:定位：plan.md §4.3、§4.7、TC-43。方案要求先原子写入 done/result/kill_pending，再 emit；TC-43 恰好在两者之间模拟退出。现有 redis/events.py:138-142 只有进入 emit 后才持久化事件，因此此时 event outbox 为空。重启后的 §4.7 只回收进程和清理，不补发 canceled；原 stop 已 ACK，也不能依赖命令再次投递。结果是进程得到回收但 server 缺少权威终态，最终可能误判 lost。建议持久化待投递终态并提供重启补发入口，确保清理不会删除尚未可靠接管的终态；扩展 TC-43，断言无命令重投时 canceled 仍最终送达 server。
- [major] R-02 现有 status 的 unknown 无法区分不可达与已消失，导致已成功取消的执行永久滞留回收队列。
  - 详情:定位：plan.md §4.3 第5步、§4.7；apps/agent/dopilot_agent/runners/scrapyd.py:190-216。现有 runner 在 listjobs 成功、job 已不在任何列表且日志不存在时，同样返回 unknown。例如尚处 pending、未创建日志的 job 被取消后，方案会一直等待，超时再进入 kill_pending；此后每 tick 仍得到 unknown，永不清除标记或执行延期清理。建议为停止确认提供独立的存活查询结果，区分“查询失败”与“查询成功且 running/pending 均不存在”，不必改变原有终态推断语义。补充真实 ScrapyRunner + 假客户端用例：pending job 无日志，取消后从列表消失，应正常确认退出并完成清理；不可达仍必须保留状态。

## 总评
方案与 rawf 的评审闸、轮次配置和证据契约一致，43 条用例均逐条声明 A 档及证据形态。停止状态机仍存在终态投递恢复缺口和存活查询语义不匹配，需修订方案并补足对应验收断言后重评。

VERDICT: fail
