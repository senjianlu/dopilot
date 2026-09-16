# 评审:第 04 轮

## 问题清单
- [blocker] R-01 TC-22 的异常路径仍未覆盖，现有证据仅证明 TC-21 的 cancel_failed 返回路径。
  - 详情:apps/agent/tests/test_stop_state_machine.py:352、363：TC-21 与 TC-22 共用测试，通过 fail_cancel_times 注入 httpx.ConnectError。但该异常在 scrapyd/client.py:62 被转换为 ScrapydError，再由 runners/scrapyd.py:130 捕获并返回 cancel_failed，未触发停止状态机的异常处理路径。当前实现记录沿用的 TC-22 pass 结论因此缺少对应场景证据。请补充让异常实际穿过 runner.stop 的测试，核验意图已持久化、命令已 ACK、后续 tick 能重试并完成收尾；补交 TC-22 的执行命令、完整 stdout/stderr、退出码，并更新实现记录。

## 总评
前两轮指出的停止重投、lost 分支隔离及主要补测缺口已修复，本轮配置文档与实现一致。按方案逐项核验 A 档证据后，TC-22 仍缺独立异常场景，因此不通过；本次全程只读，未运行测试。

VERDICT: fail
