# 评审:第 03 轮

## 问题清单
- [blocker] R-01 TC-12 的 A 档证据未覆盖方案明确要求的多项页面断言
  - 详情:apps/web/app/(app)/maintenance/__tests__/maintenance.test.tsx:105 / 当前测试只断言 critical→red、warn→amber，未断言 ok→green、unknown→gray；操作测试在 :144-193 仅覆盖 sweep 的接受/取消、AOF 的接受以及 cleanup dry-run，缺少 AOF 取消、terminal-cleanup 确认执行与取消，也未核验 stale 样本时间及 unavailable 的 last_seen_at。现有 tc12-14-web.txt 虽含命令、输出和退出码，但执行的测试不足以证明 plan TC-12 的完整预期。需补交：①补齐上述 TC-12 断言后的测试；②实际执行命令；③完整 stdout/stderr；④退出码。
- [major] R-02 采集失败会被静默伪装成正常零值或直接省略 agent，而非标记 unavailable
  - 详情:apps/server/dopilot_server/resource_stats.py:172-181 的 _du 对缺失或不可读目录返回 0，:210-232 仍将 server scope 标为 ok；:514-525 的 nodes 查询失败则返回空列表，:561-577 随后直接省略全部 agent scope，并让 Redis 命令流列表也看似正常为空。这违反 plan 的“板块失败仅降级对应板块为 unavailable”契约，会把配置错误、权限故障或数据库故障误报为无资源占用/无 agent。建议让采集器区分真实空目录与访问失败，并显式传播 nodes/agent 采集失败状态；补充对应故障测试。

## 总评
上一轮 R-01、R-02 的指定修复已落实：TC-10 已使用真实 node id 留证并加入零遍历断言，无快照响应也读取真实 sweep_enabled。其余 A/B 档证据形态基本完整，但 TC-12 仍未满足 A 档覆盖契约，且采集降级语义存在正确性缺陷，因此本轮判定 fail。

VERDICT: fail
