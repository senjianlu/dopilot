# 评审:第 01 轮

## 问题清单
- [major] R-01 closed 分支缺少代际守卫，旧代际结果仍可能重新触发熔断。
  - 详情:apps/server/dopilot_server/services/outcomes.py:381：跳闸判断发生在第 411 行的 is_current 检查之前。若较早完成的当前代际成功结果因日志排空而迟到，它可以关闭 open，但按 finished_at 排序的最新连错前缀仍可能达到阈值；此后任一旧代际结果入账就会再次跳闸，甚至将旧任务制品写入 breaker_artifact_id，违反“旧代际只入账、不驱动状态”的契约。建议将代际守卫移到所有状态分支之前，并通过真实记录器补充上述迟到顺序的回归用例。
- [major] R-02 TC-13 的双调度并发测试未确保模板更新发生在记录器持锁期间。
  - 详情:apps/server/tests/test_schedule_breaker_pg.py:257：asyncio.gather 同时启动记录器与模板更新，模板更新可能在记录器取得调度锁之前已经提交；记录完成后的 sleep 无法建立所需顺序。因此 TC-13.log 的通过结果不能确证方案要求的“同一事务依次记录两个调度，期间另一会话更新模板并提交”。建议使用同步屏障暂停记录器于持锁阶段，随后执行模板更新，并断言它在记录器提交前完成，再继续记录和提交。
- [major] R-03 TC-16 未覆盖方案要求的 half_open 徽标 tooltip 文案。
  - 详情:apps/web/app/(app)/schedules/__tests__/schedules.test.tsx:753：half_open 仅断言了 Probing 标签，后续只悬停并检查 open、held 的 tooltip。TC-16 明确要求三种状态的徽标与 tooltip 文案，因此当前通过证据仍缺一个验收场景。建议补充 half_open 的悬停及提示文案断言，并重新留证。
- [minor] R-04 升级通知将可配置的升级时长写死为 24 小时。
  - 详情:apps/web/lib/i18n/locales/zh.ts:228、apps/web/lib/i18n/locales/en.ts:232：服务端按 breaker_escalate_after_seconds 判断升级，但中英文正文固定声称已熔断超过 24 小时；用户修改配置后通知会陈述错误时长。建议改为“已超过配置的升级时限”，或由 payload 提供实际时长并插值显示。

## 范围核对
无

## 总评
实现主体与方案一致，未发现未声明的范围外改动；逐条核验了 TC-01 至 TC-20，未发现结果虚报，但存在两项验收覆盖缺口。另发现旧代际结果可重新触发熔断的正确性缺陷，判定 fail；本轮仅作只读检查，未运行测试。

VERDICT: fail
