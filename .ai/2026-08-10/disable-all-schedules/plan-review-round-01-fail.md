# Plan 评审:第 01 轮

## 问题清单
- [major] R-01 未测试批量端点会恰好触发一次 runner reload，核心“停掉实际定时任务”的验收未覆盖。
  - 详情:定位：plan.md「server 批量端点」及 TC-01/TC-02。方案将“单次 runner reload”作为避免 N 次 APScheduler reload、使生效中 job 集同步的关键设计，但两条服务端用例只验证数据库行和 HTTP 返回；即使漏调用、调用多次或调用发生在错误时机，测试仍会通过。补充 A 档端点测试：给 app.state 注入可 await 的 fake runner，断言成功批量停用后 reload 恰调用一次，并结合已启用调度验证其同步后的 job 集为空，或至少由端点测试精确断言 reload 一次、由 runner 测试验证该 reload 会移除已禁用调度的 jobs。
- [major] R-02 按钮“请求在途禁用”的明确验收条件没有测试覆盖。
  - 详情:定位：plan.md「web 按钮与确认框」及 TC-03 至 TC-05。TC-05 仅覆盖初始时没有 enabled 调度；TC-03 的 mock 立即完成，无法验证确认后请求尚未完成期间按钮 disabled、Spinner 展示及重复点击不会再次发起批量请求。补充 A 档 Vitest 用例，用可控 pending Promise 挂起 disableAllSchedules，在请求期间断言按钮 disabled/Spinner，并尝试再次点击后断言 API 仍只调用一次；随后 resolve Promise 并断言恢复刷新。

## 总评
方案的批量 UPDATE、路由和证据档位契约均与现有约定相容，且已包含取消与空集合边界。两项关键的已声明行为尚未被测试表覆盖，需就地补齐后再评审。

VERDICT: fail
