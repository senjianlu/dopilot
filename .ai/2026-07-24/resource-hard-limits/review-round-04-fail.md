# 评审:第 04 轮

## 问题清单
- [blocker] R-01 部分 A 档用例仍未按 plan 覆盖，却被记录为全部通过
  - 详情:apps/server/tests/test_resource_limits.py:291-316、715-749、755-773 / TC-03 仍只在 delete 构造处抛错，没有覆盖 plan 明定的 commit 故障；TC-07 只读取 CLOSE 哨兵，未真实驱动生成器并验证其在超时内结束及 finally 清理；TC-18 只顺序调用 reserve_quota，未按 plan 并发发起上传端点请求。implementation-round-04.md 将三项完整报告为 pass，与测试源码不符，按虚报测试处理。需补交：TC-03 的 commit 故障测试及包含命令、完整 stdout/stderr、退出码的证据；TC-07 的真实生成器结束/finally 清理测试及同类完整证据；TC-18 的并发端点上传测试及同类完整证据。
- [blocker] R-02 已存在 artifact 在 manifest 发布失败时会被删除
  - 详情:apps/server/dopilot_server/artifacts/scrapy_store.py:251-260、apps/server/dopilot_server/artifacts/wheel_store.py:225-234 / save_from_path 无论目标是否已经存在，都会先覆盖正文；随后 manifest replace 抛出 OSError 时，remove_stored 会删除目标正文和原有 manifest。因而对已提交 SHA 的重复上传遇到 manifest I/O 故障会损坏现有 artifact；当前测试 apps/server/tests/test_resource_limits.py:621-648 只覆盖空存储，未发现该路径。应让 store 明确区分本次新建与既有对象，失败时只回滚本次拥有的产物，并增加“既有同 SHA + manifest replace 失败后原正文、manifest 与 DB 行均保持可用”的故障测试。

## 总评
本轮补齐了多项上一轮覆盖缺口，B 档引用也均存在并支持结论；按 SHA 串行化方向正确。当前仍有三项 A 档与 plan 不一致且被报告为通过，并存在重复上传故障删除已提交 artifact 的数据损坏路径，因此必须判定 fail。

VERDICT: fail
