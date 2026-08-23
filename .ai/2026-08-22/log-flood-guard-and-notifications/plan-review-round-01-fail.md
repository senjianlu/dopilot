# Plan 评审:第 01 轮

## 问题清单
- [plan-blocker] R-01 将 WP-C 作为第二个 implementation round 与 rawf 的轮次语义直接冲突。
  - 详情:定位：`改动范围`的“两轮各自写 implementation-round 并评审”。`.claude/skills/rawf-implement/SKILL.md`规定第 1 轮实现完整 plan；第 2 轮起只能修复上一轮 fail 中的 blocker/major。若 WP-A/B 通过后再以 implementation-round-02 实现 WP-C，会绕过已通过评审后的方案/实现闸。应改为同一 implementation round 完成已批准方案，或将可独立发布的 WP-C 拆为新的 rawf 任务、plan 与评审链。
- [plan-blocker] R-02 连续错误计数挂在 `events._update_task` 无法覆盖方案承诺的所有终态和日志截断时序。
  - 详情:定位：WP-C 的 `services/events.py` 方案及“出错口径与连续计数”。现有 `CommandDispatcher._fail_execution_dispatch_timeout` 会直接把 execution/task 标为 failed，不经过 `apply_event`；服务端 `apply_log_event` 又与事件流由不同 consumer 消费，finished 事件可先使任务计为成功，之后日志才被标为 truncated。按当前方案，这两类已定义为失败的情况均不会计入连续错误；手动/协调路径写入 lost 也没有统一接入点。需在方案中定义唯一、幂等的“任务最终结果已确定”提交点，覆盖所有任务终态写入路径，并在日志完整性已最终确定后再记录结果；补充 dispatch_timeout、终态后日志截断、重复投递及多 execution task 的测试。
- [plan-blocker] R-03 20GB server 日志目录预算只淘汰 terminal 任务，不能构成所声明的硬盘硬上限。
  - 详情:定位：WP-A `enforce_logs_dir_budget` 和 TC-12。该方案仅按最老 terminal task 调用 `cleanup_terminal_data`；当超额部分来自大量 active/finalizing 日志，或可删除终态日志不足时，目录仍会无限越过 20GB。单文件 32MiB 不限制并发执行数量，因而不能补足总量边界。需在方案中规定无法靠终态淘汰恢复预算时的动作（例如准入/调度背压、停止并截断活动日志、或明确另一受控配额机制），并增加“全部/大部分为活动日志且预算无法恢复”的自动化测试。
- [plan-blocker] R-04 agent 启动截断把缺失 state 当作非活动，违反既有运行中作业保护边界。
  - 详情:定位：WP-A `janitor.py` C8。条件“非 active set、state 非 started 或无 state”在 agent 重启、state 损坏/丢失而 scrapyd 作业仍存活时会截断正在写入的 job.log。现有 `apps/agent/dopilot_agent/janitor.py` 与决策 0019 对未知状态采用保守的多重存活判定，明确运行中数据不得处理；C8 未包含 scrapyd 作业存活确认、静默期及扫描到执行间的二次校验。应先在方案中确定安全判定和并发锁/复检策略；若不能证明作业已停止则不得截断。TC-14 还应覆盖“state 缺失或损坏但作业仍活跃”的场景。
- [major] R-05 StreamGuard 的近似条数裁剪无法保证 256MB 字节预算。
  - 详情:定位：WP-A `StreamGuardLoop` 与“洪泛防护的两道闸”。`MEMORY USAGE` 是字节/分配量，而按 `len × budget/usage` 推导的 `XTRIM MAXLEN ~` 是近似条数裁剪；条目大小不均时不线性，近似裁剪本身也不保证达到目标，固定最多五次后仍可能超限。TC-10 的 fakeredis“按 entry 字节估算”掩盖了该差异。应明确可兑现的预算度量与收敛策略（重测后的精确裁剪/保守目标，以及仍不能达标时的处理），并据此增加不均匀大条目和近似裁剪未收敛的测试。
- [major] R-06 自动禁用后的 ScheduleRunner reload 未规定在事务提交后执行，可能重新注册刚被禁用的调度。
  - 详情:定位：WP-C 的 `services/events.py`、`app.py`。当前 `EventConsumer._apply_one` 先调用 `apply_event`，之后才 `session.commit()`；而现有 schedules API 是先提交再 `runner.reload()`。方案将 reload 回调描述为由 events 服务在同一事务中触发，若按该路径实现，reload 使用的新 session 可读到旧的 `enabled=true` 并重新注册 job。应把回调契约改为 EventConsumer 成功 commit 后才调用，且失败不得 ACK；TC-16 应验证 reload 查询到 disabled 状态且后续 timer 不再触发。

## 总评
测试用例表逐条声明了 A 档及所需原始输出形态，且 C 档为 0，证据契约本身合规。方案仍存在与 rawf 轮次约定冲突，以及日志配额、运行态清理和连续错误计数无法兑现验收口径的关键设计缺口，需修订后重评。

VERDICT: fail
