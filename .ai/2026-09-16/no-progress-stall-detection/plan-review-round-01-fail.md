# Plan 评审:第 01 轮

## 问题清单
- [major] R-01 历史日志大小不能证明当前仍有可用进度信号，日志读取失败后可能误触发自动取消。
  - 详情:定位：plan.md:115-143、TC-03/TC-08。方案保留历史 execution.log_bytes，而豁免只检查该字段是否 NULL。因此曾成功上报大小、随后持续上报 None 的执行仍会超时告警，开启自动停止后还会被取消，与“没有可用进度信号不能据此告警”的约定冲突。应独立记录当前采样有效性或最近有效采样时间，明确读取失败及恢复后的计时规则；补充“有效读数→持续 None→超过阈值→恢复”的 A 档测试，并覆盖自动停止开启时不误杀。
- [major] R-02 通知去重只覆盖未读通知，无法兑现同一执行一次性告警。
  - 详情:定位：plan.md:144-147、TC-06。services/notifications.py 的唯一索引及 notify 冲突目标均限定 read_at IS NULL；用户读过通知后，下一次 reconcile 会创建新通知。stalled_at 又按 TC-02 在每次心跳时清空，不能作为持久的一次性标记。应明确并实现独立于通知已读状态、普通心跳的告警记录，补充“告警→标为已读→心跳→再次 reconcile”仍不新增通知的测试。
- [major] R-03 自动停止缺少持久去重，会在终态到达前不断追加取消命令。
  - 详情:定位：plan.md:148-150、TC-11。services/outbox.py 的 create_stop_outbox 每次生成新 command_id，没有去重；通知 dedupe_key 也不约束 outbox。reconcile 每 5 秒运行，取消确认需要数十秒，Redis 不可用时更可能长期重复入队。应定义每执行的自动停止幂等规则和失败重试策略，并补充多次 reconcile、心跳清除 stalled_at、outbox 已 sent 但尚未收到终态等场景，断言不会重复投递。
- [major] R-04 在现有串行命令消费者中等待取消确认，会阻断其他执行的心跳和日志保护检查。
  - 详情:定位：plan.md:154-170。commands.py 的 _run 顺序执行 reconcile_started_attempts 与 drain_once，后者逐条 await _process，默认每批 16 条。将每条 stop 改为等待 10+30 秒，会使一批取消阻断所有执行的存活心跳和 flood watchdog 约 640 秒，超过默认事件停滞阈值 300 秒；自定义较短 lost 阈值时还可能导致无关执行被判 lost。这不是 asyncio.sleep 能避免的事件循环阻塞问题，而是同一协程的串行调度问题。方案应采用可持续推进的停止状态机或受管理的后台停止任务，并明确锁、恢复及关闭行为；增加批量取消期间其他执行仍按期心跳和执行 watchdog 的测试。
- [major] R-05 取消升级方案未定义查询失败与 reclaim 的终态边界，现有测试无法保护这两条关键路径。
  - 详情:定位：plan.md:156-170、TC-12～TC-14。当前 ScrapyRunner 将 listjobs 不可达映射为 unknown，stop 还可能返回 cancel_failed；方案只描述仍在列表和确认消失，没有规定 unknown、TERM/KILL 请求失败及单次请求超过剩余期限时如何处理。另称 reclaim 复用整条链，而该链包含 emit canceled；现有 _handle_stop 的 reclaim 对仍运行的执行回收后保持 lost，仅已有真实终态时才上报覆盖。应明确仅复用终止与确认机制，分别保留 cancel/reclaim 的结果语义，定义不可确认时的有界处理策略，并增加上述异常及 reclaim 保持 lost、真实终态覆盖的 A 档测试。

## 总评
方案的评审闸和轮次声明与 rawf 约定兼容；17 条测试均逐条声明 A 档和证据形态，证据契约合规。进度信号有效性、一次性副作用及取消执行模型仍存在正确性缺口，相关异常测试也需补齐，因此本轮 fail。

VERDICT: fail
