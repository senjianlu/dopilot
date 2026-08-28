# 0022:定时调度并发上限,默认 1,手动触发同池

- 日期:2026-08-28
- 背景:在此之前,同一个 schedule 的重复运行是**允许叠加**的。定时触发只做
  一道"未下发积压"合并(`services/outbox.py` 的
  `has_undispatched_backlog_for_schedule`,针对 Redis 中断窗口),其注释明确写着
  "running 的任务不算——新的定时触发不应仅仅因为上一轮还在跑就被抑制";
  `trigger_now` 则完全不合并。结果是:一个跑得比触发间隔还慢的爬虫会不断
  自我叠加,几轮下来同一个 schedule 在所有节点上并行堆积同源任务,既放大
  日志与资源占用,也让"这个调度到底在跑第几轮"无法回答。用户要求给定时调度
  加并发限制,并明确**手动触发也要计入同一个指标**——否则限制形同虚设。

- 决定:
  1. **`schedules.max_concurrency`,默认 1**。取值 `>= 1` 为上限,`0` 表示
     不限(即 0022 之前的旧行为,作为逃生舱保留)。合法区间
     `0 .. 2147483647`,与列类型(有符号 32 位 `Integer`)对齐,越界由 service
     返回结构化 400 而不是留到 COMMIT 时炸成 500。
  2. **口径:按 task 计数,不按 execution**。计数 = 该 schedule 名下处于
     `TASK_ACTIVE`(`queued` / `running` / `finalizing`)的 task 行数。一个
     task 扇出到 N 个节点仍只占 1 个额度;终止态(含 `no_target`)自动释放。
  3. **定时与手动共用同一额度池**。计数查询只按 `schedule_id` + 状态过滤,
     **不带 `source` 条件**:`schedule_timer` 产生的活动任务会挡住
     `trigger-now`,反之亦然。这正是用户要的"手动触发也纳入并发指标"。
     模板直跑 / 直接产物运行的 task `schedule_id` 为 NULL,天然不计入。
  4. **超限的两种表现**:手动 `trigger-now` 返回 **409**
     `schedule.concurrency_limit`(detail 带 `active` / `limit`),**不创建
     任务、不提供强制入口**;定时触发**静默跳过**,只记一行服务端
     `logger.info`,不发消息中心通知、**不计入 `consecutive_error_count`**
     (跳过不是失败,不得喂给 [0021](0021-log-flood-guard-and-auto-disable.md)
     的自动禁用)。
  5. **准入闸是一个串行区**。`services.schedules.acquire_firing_slot` 先对
     schedule 行 `SELECT ... FOR UPDATE`(带 `populate_existing=True` 刷新
     陈旧副本),再在锁内依次判断 存在 → 启用 → 积压合并 → 并发。三点理由:
     调用方手上的 `Schedule` 可能早于锁读取,`max_concurrency` 可能刚被并发
     PUT 改小;积压查询只看得见已提交的行,放在锁外会漏看先行事务刚提交的
     未决 outbox;两个并发触发必须恰好一个通过。锁在执行器那次建单原子提交
     时释放,**该提交发生在 XADD 之前**,所以行锁不跨 Redis 网络调用。
     被否掉的备选:应用层信号量(单实例也扛不住进程重启)、乐观重试
     (重复建单已经产生副作用,无法回滚 XADD)。
  6. **存量行统一回填为 1**(迁移 `server_default="1"`)。这是刻意的行为
     变更,由用户确认。
  7. 本决策**部分取代** [0014](0014-node-strategy-and-push-mode.md) 中
     "定时触发做 coalesce 抑制"那一条的口径:coalesce 仍在,但它只负责
     "未下发积压";"是否太忙"由本决策的并发闸负责,两者在同一个锁内先后
     执行。0014 的节点策略与推模式部分不受影响。

- 影响:
  - **升级即生效的行为变化**:现网若有依赖重叠运行的调度,升级后定时触发会
    被静默跳过、手动触发会被拒。处置办法是把该 schedule 的并发上限改成 `0`
    (不限)或更大的值,**不需要回滚版本**;Web 的调度编辑对话框可直接改,
    列表里 `0` 显示为"不限"。
  - **已知取舍**:任务卡在 active(agent 失联等)会长期占用额度,后续触发
    一直被挡。依赖既有的心跳与手动 `mark-lost` 兜底;409 的 detail 会返回
    当前 `active` 计数,前端提示引导用户去任务页处理。
  - `tasks` 新增 `ix_tasks_schedule_id_status` 索引:每次触发都要按
    schedule 统计活动任务,而 `tasks.schedule_id` 此前**没有任何索引**。
  - 迁移 `0014`;回滚 `alembic downgrade 0013` 即撤销列与索引。
