# Plan 评审:第 02 轮

## 问题清单
- [plan-blocker] R-01 方案把数据库迁移放入 server lifespan，与既有 Alembic 独占迁移架构冲突。
  - 详情:定位：WP-A `apps/server/dopilot_server/app.py`（“lifespan:migrate 后”）及启动顺序第 4 节。现有 `app.py` 明确 server 不创建表，`deploy/docker` 以独立的一次性 `migrate` 服务在 server 前执行 `alembic upgrade head`。在 lifespan 迁移会破坏该分工并引入多 server/手工启动时的迁移竞态。应改为保留外部 migrate 服务/运维前置条件；app lifespan 只在 schema 已就绪后执行 StreamGuard、Gauge 校准和消费者启动。
- [plan-blocker] R-02 结果记录器会在日志仍可被消费并改写为 truncated 后不可逆地把任务记为成功。
  - 详情:定位：WP-C `services/outcomes.py`、实现方案第 2 节、风险表“drain + 60s”。`outcome_recorded_at` 一旦写入即永久跳过；但现有 `finalize_drained_logs` 是超时定稿，现有 `apply_log_event` 不会因 log file 已 `complete` 而拒绝后到日志。特别是方案的“超过 drain + 60s 兜底”会先记录成功，随后到达的超限日志可将 `log_integrity` 改为 `truncated`，却不再计入连续错误，违反 G3。风险表承认“可能少算一次”不能替代验收行为。需先定义日志与 outcome 的原子封口/可纠正结果模型，保证后到日志不会使已记录结果失真；并增加该交错场景的自动化用例，而不只覆盖定稿前截断的 TC-21(b)。
- [major] R-03 scrapyd 日志达到上限后只请求一次 cancel，cancel 失败或作业继续运行时 agent 本地磁盘仍可无限增长。
  - 详情:定位：WP-B `commands.py` 的 `getsize ≥ cap → runner.stop() + mark_log_flood`，以及 TC-01。现有 `ScrapyRunner.stop()` 在 scrapyd cancel 异常或作业已无法确认时可返回未停止；而方案标记 `log_flood` 后没有规定重试、超时升级或其他强制终止路径，且 `started` 日志被 janitor 明确排除。因此持续写入的作业会绕过“进程退出后截断”，违背 G2 的 agent 侧硬盘防膨胀目标。应规定 cancel 失败/未停止后的持续探测与受控升级终止策略，并测试 cancel 失败及 cancel 后作业仍在 running 时日志不会继续无界增长。
- [major] R-04 方案声明了 log_flood 消息类型，却没有定义任何产生该通知的服务路径或覆盖测试。
  - 详情:定位：WP-C `notifications` 类型列表与消息中心第 3 节；WP-B 只将 `log_flood` 写入 agent state/终态 error_code，WP-C `services/events.py` 仅规定落 Execution 字段，`outcomes.py` 仅规定 `schedule_auto_disabled` 通知。因而洪泛终止不会生成其声明的 `log_flood` 告警，TC-28 仅以 mock 数据渲染前端也无法覆盖生产路径。应明确在处理该终态时创建按 execution 去重的通知，并增加从终态事件到通知/API 或持久化记录的自动化测试。

## 总评
测试用例表逐条声明了 A 档和证据形态，且 C 档为 0，证据契约合规；多数既有的启动清理、目录准入和计数覆盖缺口也已有针对性测试。仍有迁移边界、不可逆结果记录及 scrapyd 终止失败的关键设计缺口，须修订方案后重评。

VERDICT: fail
