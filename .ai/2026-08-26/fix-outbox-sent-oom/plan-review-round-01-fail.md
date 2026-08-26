# Plan 评审:第 01 轮

## 问题清单
- [plan-blocker] R-01 固定选取最老一批 sent 行却没有推进游标，会使后续命令永久饿死。
  - 详情:plan.md:72-90 的查询每轮都按 updated_at 选取同一批最老 sent 行。如果这些消息仍存在于 Redis，其状态和 updated_at 不变，下个周期仍会占满 LIMIT，后续丢失消息永远得不到检查，违反“超出部分由下一个周期续作”和 decision 0008 的 at-least-once 语义。TC-02 因首批全部转为 pending，未暴露此问题。方案应改为具有稳定排序、跨周期推进和回绕语义的有界扫描，并增加“首批消息仍存在、后批消息已丢失，后续周期能够重排后批”的 A 档用例。
- [major] R-02 TC-01 至 TC-07 的 A 档证据形态未逐条满足完整原始证据契约。
  - 详情:review-standards.md:44-47 要求每条 A 档证据包含执行命令、完整 stdout/stderr、退出码并落入 evidence/。plan.md:138-144 仅写“pytest 输出 + 退出码”；TC-01 缺执行命令及完整 stdout/stderr 声明，TC-02 至 TC-07 还缺落盘声明。请逐条补齐四项，不能用 TC-08 的全量回归证据替代各用例证据。
- [major] R-03 方案未经记录的用户授权把两类评审轮次上限从默认 3 放宽到了 15。
  - 详情:plan.md:6-7 设置 plan_review_max_rounds 和 impl_fix_max_rounds 为 15；CLAUDE.md:32-35 及 rawf skills 明确规定只有用户明确要求时才能覆盖默认值，并须在摘要或实现记录中声明。当前方案没有记录相应授权或说明。应删除字段恢复默认 3；如确有用户授权，则须在方案中明确记录。
- [major] R-04 清扫测试没有覆盖全部不可删除的 unresolved 状态，存在误删在途命令的验收盲区。
  - 详情:plan.md:116-119 承诺 pending、dispatching、failed_retryable 永不删除，但 TC-04 只验证 pending。其中 failed_retryable 最容易被误当成 failed 清除并造成命令丢失。请将 TC-04 参数化或增加用例，逐一验证 OUTBOX_UNRESOLVED 的三个状态均被保留。
- [major] R-05 RetentionSweepLoop 新步骤只有成功接线测试，没有验证方案承诺的故障隔离。
  - 详情:plan.md:121-124 明确要求 outbox 清扫使用独立 try/except，失败不得跳过其他步骤；TC-05 仅覆盖成功路径。应增加 A 档故障注入用例，至少验证 prune_resolved_outbox 抛错后后续 retention 步骤仍执行；同时验证前置步骤失败不会阻止 outbox 清扫。

## 总评
方案正确识别了无界物化和历史数据清理问题，但当前限批算法会造成永久饥饿，必须先修订核心设计。证据契约、rawf 轮次设置以及数据安全和故障隔离测试也需补齐后再进入实现。

VERDICT: fail
