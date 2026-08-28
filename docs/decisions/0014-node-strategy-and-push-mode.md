# 0014:节点策略三态（指定/全部/随机）与推模式

> ⚠️ **coalesce 口径已被 [0022](0022-schedule-concurrency-limit.md) 部分取代**:
> 下方"影响"节所述的定时 coalesce 仍然存在,但它只负责"未下发积压";
> "同一调度是否太忙"改由 0022 的并发闸(默认上限 1,手动触发同池)判断。
> 本文的节点策略与推模式部分不受影响。

- 日期:2026-06-17
- 背景:任务下发需要回答"跑在哪些节点"：有时要指定节点、有时要全部节点
  并发执行、有时只要任意一个健康节点；另需支持绕过定时的立即下发。
- 决定:
  - **节点策略 `node_strategy` 三态**:`selected`（指定节点）/ `all`
    （指定集合全部执行，并发 fan-out，默认）/ `random`（触发时从健康节点
    中动态随机选一个）。触发时动态归约，叠加健康过滤
    （heartbeat `last_seen_at`，见 [0008](0008-redis-streams-agent-communication.md)）
    与 artifact 能力过滤（[0012](0012-domain-model-clean-cut.md)）。
  - **推模式**:主动下发任务到指定 worker **立即执行**（与定时触发相对），
    经统一的 `BaseExecutor` 分派与独立 API 端点实现。
- 影响:
  - 模板/定时/直接运行共用同一套节点策略语义；Schedule 可覆盖模板的策略与
    节点选择（不可覆盖构建产物）。
  - 定时触发做 coalesce 抑制：同一 schedule 存在未终结 execution/outbox 时
    跳过或合并，避免 Redis 不可用窗口内堆积同源命令。
