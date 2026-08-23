# 评审:第 04 轮

## 问题清单
- [major] R-01 上一轮的标记限速修复在低速合法配置下仍会主动突破令牌桶硬上限
  - 详情:apps/agent/dopilot_agent/redis/logs.py:156-163,213-216；apps/agent/dopilot_agent/config/settings.py:97-100 / `_marker_allowed()` 在 `bucket_capacity < marker_len` 时允许满桶发送整条标记，随后 `_spend()` 又把负余额钳为 0；例如速率为 1 B/s、两秒桶容量为 2 B 时仍会一次写入约 60 B 标记，违背 G2 和模块自身“实际落入 Redis 的字节不超过桶容量”的硬保证。本轮新增测试只使用 1024 B/s，未覆盖该退化分支，而实现记录还将其列为方案偏差。应拒绝低于可承载单条标记的配置，或设计不会突破已批准桶容量的发送方式，并补充 `rate * 2 < marker_len` 的 Redis 实际落地字节回归用例。
- [major] R-02 消失的 sent 命令超过原 give-up 截止时间后不会重投，恢复对账会立即把它判失败
  - 详情:apps/server/dopilot_server/redis/dispatcher.py:223-226,254-271；apps/server/dopilot_server/services/outbox.py:46-49 / `reconcile_sent_once()` 只把旧行改回 `pending`，没有刷新或豁免创建时写入的 `give_up_at`；同一 `_tick()` 随后进入 `_process_row()`，对已超过 15 分钟截止时间的行直接置 `failed`，run 命令还会把 task/execution 标成 `dispatch_timeout`，根本不会执行方案承诺的重新 XADD。现有 TC-20e fixture 仅把 `updated_at` 回拨 120 秒，保留了仍在有效期内的 `give_up_at`，因此漏掉生产停机或 Redis 卷恢复超过 15 分钟的核心场景。应为恢复重投建立新的截止窗口或明确绕过旧截止时间，并增加过期 sent 行的重投测试。
- [major] R-03 启动清理把 cap 加标记长度误作超限检测阈值，略超 cap 且没有标记的既有日志会被永久漏过
  - 详情:apps/agent/dopilot_agent/janitor.py:286-311,414-428；apps/server/dopilot_server/services/maintenance.py:308-318,341-370 / 两条清理路径都只处理 `size > cap + len(marker)`；因此一个原始大小为 `cap + 1`、末尾没有 dopilot 标记的已停止/已封口日志既不会截回，也不会写截断标记或更新 server 的 `log_integrity/truncation_reason`，不符合 G1 对既有超限日志的清理语义。TC-13/TC-17 都只构造远大于 cap 的文件，未覆盖边界。应以 `size > cap` 作为候选条件，同时读取 cap 后的尾部来区分“已经精确是 cap+合法标记”的幂等状态与未处理的原始文件，并为两端补 `cap+1` 用例。
- [minor] R-04 自动禁用提示的 Tooltip 触发器是不可聚焦的 Badge span，键盘用户无法读取原因
  - 详情:apps/web/app/(app)/schedules/page.tsx:429-451 / `TooltipTrigger asChild` 最终落在 `Badge` 的默认 `<span>` 上；该元素没有按钮语义或焦点入口，提示中的次数和时间只能通过指针悬停获得。应使用可聚焦的按钮/链接作为 TooltipTrigger（可在其中组合 Badge），并补键盘聚焦断言。

## 总评
上一轮的启动顺序、runbook 恢复命令和通知未读 Badge 修复已落实；全部 plan 用例均为 A 档，现有证据具备命令、原始输出与退出码，未发现证据虚报。仍有三项资源硬界或恢复正确性缺陷，因此本轮判定 fail；遵照只读约束未运行测试，仅完成差异、静态格式与证据核验。

VERDICT: fail
