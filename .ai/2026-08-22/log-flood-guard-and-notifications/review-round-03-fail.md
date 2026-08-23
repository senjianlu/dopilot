# 评审:第 03 轮

## 问题清单
- [major] R-01 截断标记绕过全局令牌桶，可突破每 agent 推送速率硬上限
  - 详情:apps/agent/dopilot_agent/redis/logs.py:192-200,227-232；apps/agent/tests/test_log_publisher.py:168-196 / 普通正文成功推送后会调用 `_spend`，但 `_publish_marker` 只要求剩余 allowance 大于 0，既不要求额度足以容纳标记，也不扣减标记字节。若桶中只剩 1 byte，多个恰好达到 cap 的执行仍可各推送一条完整标记，实际流入 Redis 的总字节可超过 G2/TC-04 的两秒桶容量；现有测试仅统计 `publish_once()` 返回的正文字节，因而看不见该绕过。应将标记纳入 allowance、扣减和返回总数，并增加“低于单条标记的剩余额度 + 多个达到 cap 的执行”回归测试，按 Redis 中实际 entry 字节断言上限。
- [major] R-02 TC-32 要求的启动顺序未实现，测试通过弱化断言掩盖了偏差
  - 详情:.ai/2026-08-22/log-flood-guard-and-notifications/plan.md:274；apps/server/dopilot_server/app.py:188-203；apps/server/tests/test_maintenance_guard.py:305-310 / plan 明确要求 `retention.start` 位于 `stream_guard.start` 之前，但实现先在第 192 行启动 stream guard，随后才在第 203 行启动 retention；测试只核对前四个 start，并对后二者做无序 membership 判断，未执行 plan 声明的精确顺序断言。应调整接线顺序以符合已批准方案，并让测试断言包含 `retention.start, stream_guard.start` 的完整顺序前缀；若确需改变顺序，应先更新并重新确认方案。
- [major] R-03 回滚手册没有两个持久卷的可执行恢复命令，TC-31c 的校验存在漏检
  - 详情:.ai/2026-08-22/log-flood-guard-and-notifications/plan.md:277；docs/architecture/05-deployment.md:147-151；apps/server/tests/test_runbook.py:29-36 / 文档仅以文字写“tar xzf 回两个卷”，没有任何实际 `tar xzf` 命令、目标挂载点或卷重建步骤，未满足 TC-31c 要求的每个卷至少一条恢复命令。测试只统计卷名出现次数，且正则的 `volume:/src` 分支会被备份命令满足，因此错误放行。应为 DB 与 server-data 分别写出完整、可执行的卷删除/重建及 `tar xzf` 恢复命令，并让测试分别匹配两条恢复命令及其目标卷。
- [minor] R-04 通知未读徽标仍绕过 shadcn 组件和语义前景色约束
  - 详情:apps/web/components/layout/notification-bell.tsx:167-170 / 未读数使用手写 `<span>` 模拟 Badge，并硬编码 `text-white`；这仍不符合项目 shadcn 的组件复用和语义颜色约束。应复用现有 `Badge`，并以 `text-destructive-foreground` 等语义 token 表达前景色。

## 总评
上一轮 R-01～R-05 的修复均已逐项落实；plan 中全部 A 档用例也都有命令、完整输出和退出码证据，未发现缺证或虚报。当前仍有一项速率硬界缺陷及两项被弱化测试掩盖的方案偏差，因此判定 fail；遵照只读要求未运行测试。

VERDICT: fail
