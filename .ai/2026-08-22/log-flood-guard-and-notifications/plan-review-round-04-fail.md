# Plan 评审:第 04 轮

## 问题清单
- [plan-blocker] R-01 Scrapyd 洪泛升级路径的 `killpg` 可能杀死同一 agent 上的其他作业或 scrapyd 自身。
  - 详情:定位：plan.md:74、127-130、TC-01b。方案按 `_job` 找到单个 crawler PID 后对其进程组执行 `os.killpg`，但现有 Scrapyd 以 `reactor.spawnProcess` 启动作业，未为每个作业建立独立进程组；“同一 cgroup”也不等于独立进程组。该操作可连带杀掉共享进程组中的 scrapyd/其他 crawler，违反多执行隔离。应删除该兜底，或先在架构上建立可证明的每作业隔离与可定位 PID/进程树机制；TC-01b 应验证不会影响同 agent 的另一运行作业，而非仅断言调用了 killpg。
- [plan-blocker] R-03 生产恢复 runbook 未定义停止/隔离 Redis 后再清空卷的可执行顺序，按所述步骤不能可靠恢复。
  - 详情:定位：plan.md:67、177-183。当前步骤是在“覆盖 compose”后直接清空正在被 Redis 容器挂载的 named volume，再 `up -d`；既没有停止 Redis/相关 agent，也没有保证旧容器会重建。运行中的 Redis 可能继续写 AOF，且 `dopilot_dopilot-redis` 依赖 Compose project 名，不能作为通用卷名。应在方案中规定并验证明确的停服、确认容器停止、按实际 Compose project 删除/重建 Redis volume、启动与健康检查、agent 重连顺序及失败回滚步骤。
- [plan-blocker] R-04 将 plan 与实现评审上限直接设为 15，绕过了 rawf 默认三轮和“仅用户明确授权才放宽”的闸门。
  - 详情:定位：plan.md:6-7；已有 plan-review-round-01~03-fail.md。CLAUDE.md、plan-review.sh 与 rawf-plan/rawf-implement 均规定默认最多 3 轮，只有用户明确要求放宽时才可写入这两个 frontmatter 字段，并须在摘要/实现记录中声明授权。当前计划没有保留该授权说明，却以 15 继续第 4 轮评审。应删除两个字段并在三轮后交人工，或补入用户明确授权的可审计记录后再继续。
- [major] R-02 logs 目录“硬界”未为每个执行分别写入的截断标记预留全局预算，实际可被无限个标记突破。
  - 详情:定位：plan.md:81、133-135、TC-11。目录已满时，方案仍会对每个首次命中预算的 ExecutionLogFile 写一条 `reason=dir-budget` 标记；因此不是文中所称“+ 一次标记”，而是“+ 每个执行一次标记”。在大量新活动执行持续到来时，目录仍可随标记数增长，不能兑现 G2 的 20GB 写入准入硬界；TC-11 只覆盖一个执行。应将标记字节纳入原子准入/预留预算，或在无空间时不落盘标记而仅持久化数据库状态与通知，并增加满额后多个不同 execution 并发到达的测试。

## 总评
测试表逐条声明了 A 档与原始输出证据形态，C 档为 0，证据契约本身合规；多数终态、乱序与异常路径也已有覆盖。上述问题会破坏作业隔离、目录硬上限、生产恢复或 rawf 评审闸门，因此本轮必须失败。

VERDICT: fail
