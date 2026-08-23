# Plan 评审:第 06 轮

## 问题清单
- [plan-blocker] R-01 洪泛硬界仅适用于受 agent 管理的 scrapyd，未覆盖既有的外部 scrapyd 模式。
  - 详情:定位：plan.md:79-81、134-139；现有 `ScrapydSettings.start=False` 明确支持外部管理的 scrapyd，且已有测试使用该模式。方案的受控 sink 依赖给 `ScrapydProcess.start()` 注入环境变量，PID 升级又依赖受 agent 管理的 scrapyd 父 PID；在 `start=False` 下两者均不存在，只剩轮询后的截断/cancel，无法兑现 G2 声称的本地日志硬界。应在方案中明确并设计兼容路径：要么禁止/启动时拒绝该模式，要么规定由外部 scrapyd 注入 cap 并提供安全的终止策略；同时增加 `scrapyd.start=False` 下的自动化覆盖。
- [major] R-02 连续错误计数缺少 `schedule_trigger_now` 来源应计入的测试覆盖。
  - 详情:定位：plan.md:44-47、104、238-240。验收口径明确 `schedule_timer` 与 `schedule_trigger_now` 都必须计入，但 TC-19 只构造 `schedule_timer`，TC-20 只验证 `direct_artifact` 不计入；实现若误把条件写成仅 timer，全部现有测试仍会通过。应增加自动化用例，验证 `schedule_trigger_now` 的失败被写入账本、参与连续计数并可触发自动禁用。

## 总评
测试证据契约合规：所有用例逐条为 A 档，且声明了完整原始输出的证据形态，C 档为零。方案其余关键异常与时序路径覆盖较充分，但上述兼容性架构缺口和验收分支漏测须先修订。

VERDICT: fail
