# Plan 评审:第 09 轮

## 问题清单
- [plan-blocker] R-01 LogsDirGauge 校准会丢失校准开始前尚未落盘的预留，无法保证目录硬界。
  - 详情:定位：plan.md:65、89、145-148、TC-11b。`reserve()` 先增加 value/reserved_counter，随后文件写入在线程池中执行；若 `calibrate()` 在 reserve 返回后、写入完成前取得 mark，walk 看不到这些字节，而 `(reserved_counter-mark)` 也不包含该预留，重置后即永久低估；若写入再失败，`release()` 还会二次扣减。另有 size-cap 时预留 `len(raw)+len(marker)`、实际仅写剩余正文和标记的矛盾，TC-10 要求的“gauge 等于实际落盘字节”无法同时满足。应定义带 pending/commit/release 的预留协议或串行化校准与写入，按实际计划写入量预留，并补充“校准前已 reserve、写入暂停/失败”和部分写入的 barrier 测试。
- [plan-blocker] R-02 维护任务会修改已封口日志，破坏结果记录器所依赖的“记录后完整性不可变”不变量。
  - 详情:定位：plan.md:65、105、165-168、198-200、TC-13/TC-21/TC-32。`truncate_oversized_log_files` 专门截断 `status=complete` 的日志并把完整性改为 truncated，但 `record_task_outcomes` 对 `outcome_recorded_at` 非空永久跳过，并声称封口后完整性不再变化。启动时 reconcile 又先于异步 retention 启动，旧超大日志可能先被记为成功、随后才被截断；以后降低 max_file_bytes 也会重现。应让既有超限截断在结果记录器启动前完成，或让维护截断原子地失效并重算账本；增加“已记录成功后维护截断”和启动竞态的 PostgreSQL 测试。
- [plan-blocker] R-03 恢复 runbook 删除 Redis 卷会丢失已标 sent 但 agent 尚未接管的命令。
  - 详情:定位：plan.md:66、202-203、288。runbook 先停 agent 再删除 Redis 卷，却以“命令由 outbox 重投”作为安全依据；现有 dispatcher 对 `sent` 行直接返回，只有 pending/failed_retryable 会重投，因此命令流中尚未消费的 run/stop/cleanup 命令会永久丢失，queued task 甚至可能一直悬挂。这也破坏 docs/decisions/0008 的 at-least-once 契约。应在方案中加入可证明的 drain/consumer-lag 检查或安全地重置未接管 sent 行及任务对账步骤，并增加恢复语义测试；TC-31 的 compose config 无法覆盖该验收路径。
- [plan-blocker] R-04 回滚顺序要求旧镜像执行其并不包含的 0013 downgrade，实际无法回滚数据库。
  - 详情:定位：plan.md:66。步骤先恢复旧 compose/旧镜像 tag，再执行 `alembic downgrade 0012`；旧镜像只包含到 0012，面对数据库当前 revision 0013 会报无法定位 revision。应在切换旧镜像前用新镜像执行 downgrade，或显式保留并运行含 0013 的镜像完成降级，再恢复旧 compose/tag；同时为 runbook 的镜像/迁移顺序补充验证契约。
- [major] R-05 出错判定未把 Scrapy stats 限定于 finished，会把正常取消误计为连续错误。
  - 详情:定位：plan.md:24-27、104、TC-18。目标定义为 failed/lost，或 finished 且 error_count>0/finish_reason异常；但 `execution_is_erroneous` 对所有状态无条件检查 error_count 和 finish_reason。被用户取消的 Scrapyd 通常以 execution=canceled、finish_reason=shutdown 收敛，因此连续取消会错误增加计数并可能自动禁用 Schedule。应仅在 status=finished 时应用 stats 条件，并在 TC-18 增加 canceled+shutdown/error_count 的非错误分支（若同时 truncated/log_flood，则按明确口径测试为错误）。
- [major] R-06 日志通知跳转目标不存在，且现有前端测试没有点击该分支。
  - 详情:定位：plan.md:111、TC-28。仓库的静态任务详情路由是 `/tasks/detail?id=<task_id>`，不存在动态 `/tasks/<task_id>` 页面；按方案实现后点击 log_flood/log_truncated 通知会进入 404。TC-28 只点击列表第一条 schedule 通知，未验证日志通知。应改用现有详情路由或明确新增可静态导出的路由，并增加点击日志通知后 URL 与详情加载的断言。
- [major] R-07 迁移未定义既有 Schedule Task 的 outcome generation，升级边界上的结果会漏计。
  - 详情:定位：plan.md:101、107、259、迁移 0013。`Task.schedule_generation` 被设计为 nullable 且仅在新建 task 时固化；现有 scheduled task 升级后仍为 NULL，随后终态入账时不会匹配 Schedule 当前 generation=0（账本 generation 若非空则直接插入失败）。应在迁移中回填既有 schedule_timer/schedule_trigger_now task 的 generation=0，或定义等价的兼容映射，并增加“升级前创建、升级后终态”的测试；同时明确历史终态是否应在首次 recorder tick 回灌，避免意外批量自动禁用。

## 总评
证据契约本身合规：测试表逐条声明了 A 档和证据形态，C 档为 0。方案仍存在目录硬界、结果不可变性及生产恢复语义上的架构错误，并漏测取消、升级边界和日志通知跳转，因此必须修订后重评。

VERDICT: fail
