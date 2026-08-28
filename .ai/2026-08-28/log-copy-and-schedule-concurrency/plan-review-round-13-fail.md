# Plan 评审:第 13 轮

## 问题清单
- [major] R-01 HEAD 用例要求返回错误 envelope，与 HTTP 语义及现有测试传输层冲突
  - 详情:定位：A1 的 HEAD 契约与 TC-46。方案要求 HEAD 成功时 body 为空，却要求 404 时返回“完整 envelope”；但 HEAD 响应无论成功或失败都不应包含响应体，仓库使用的 httpx.ASGITransport 也会明确丢弃 HEAD 的所有 body，因此 TC-46 无法观察或解析该 envelope。应把 HEAD 的 404 预期改为状态码及必要响应头、body 为空；若前端确实需要错误 envelope，则应改用轻量 GET/元数据端点，并相应调整 TC-25/TC-46。
- [major] R-02 核心并发用例未准备健康节点，触发任务会立即成为 no_target，无法验证额度占用
  - 详情:定位：TC-13、TC-18。现有两个 executor 在没有健康且能力匹配的节点时，会把新 task 立即提交为终态 no_target；现有调度触发测试也都会先调用 seeder.healthy_node()。按当前前置条件，TC-13 的前三次触发都会因额度未被占用而成功，TC-18 的两个并发触发也可能都成功且最终 active task 为 0，无法得到预期的“一个成功、一个 409、active=1”。应在这两条用例中明确创建至少一个健康且能力匹配的节点，并断言获准任务保持 queued/active 后再验证上限和行锁。

## 总评
并发闸的事务设计、下载资源生命周期以及逐条证据档位总体已经自洽，44 个 A 档、2 个 B 档、0 个 C 档符合证据契约。当前仍有一个不可执行的 HEAD 测试契约，以及两个无法进入目标状态的核心并发用例，因此按 plan-review 规则判定 fail。

VERDICT: fail
