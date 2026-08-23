# Plan 评审:第 14 轮

## 问题清单
- [plan-blocker] R-01 新 notifications 表允许未读记录无限增长，违反既有资源硬上限决策。
  - 详情:定位：plan.md:104-105、268；docs/decisions/0019-resource-hard-limits.md:14-17。方案的 `prune_notifications` 只删除已读且超期的记录，TC-24 还固化了该行为；但 `log_flood`/`log_truncated` 按 execution 生成独立键，未读时会随执行数量永久累积，小时桶和日桶记录也不会过期，因此 `notification_retention_days` 不能形成任何总量边界。这与 0019“每个增长面均有可配置硬上限并自动执行”的已确认决策冲突。需在方案层明确未读通知的绝对年龄或条数上限及超限时的聚合/淘汰语义，并增加未读记录长期无人处理时仍保持有界的 A 档测试。
- [major] R-02 Redis 流告警的同桶去重会把未读 error 降级为 warning 并覆盖关键清空事实。
  - 详情:定位：plan.md:105、193-196、TC-12/TC-24。`redis_stream_over_budget` 的正常裁剪和不收敛清空共用“小时桶”去重键，但 upsert 总是用最新事件覆盖 `severity` 与 `payload`。若本小时先发生 `cleared=true` 的 error，随后又发生普通 warning 裁剪，同一未读通知将被降级且清空事实从 payload 消失，消息中心会掩盖更严重的资源事故；现有测试未覆盖该顺序。应让严重度和关键状态单调保留（如取最高 severity、sticky cleared），或为裁剪与清空使用不同去重键，并测试 warning→error 与 error→warning 两种顺序。

## 总评
方案的证据契约合规：所有用例均逐条声明为 A 档并约定完整命令输出与退出码，C 档为 0，异常和并发路径覆盖总体充分。但消息中心新增了与资源硬上限决策冲突的无界持久化面，并且告警折叠可能掩盖 error 事件，须先修订方案后重评。

VERDICT: fail
