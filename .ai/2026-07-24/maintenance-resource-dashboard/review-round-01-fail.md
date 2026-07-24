# 评审:第 01 轮

## 问题清单
- [blocker] R-01 A 档测试证据未覆盖 TC-10，且 TC-05/TC-07/TC-08 的原始输出所对应测试缺少方案要求的分支
  - 详情:`.ai/2026-07-24/maintenance-resource-dashboard/evidence/tc09-10-agent-disk.txt:1-16` 的命令使用 `-k tc09`，实际仅执行 3 个 `test_tc09_*`，没有执行 `apps/agent/tests/test_heartbeat_worker.py:129` 和 `:149` 的磁盘心跳测试，因此 TC-10 没有 A 档原始输出。另据 `.ai/2026-07-24/maintenance-resource-dashboard/evidence/tc01-11-server-resource-stats.txt:1-53` 的完整用例清单，TC-05 未执行 plan 要求的 prune 抛错隔离分支，TC-07 未执行 `stats_interval_seconds=0` 时 app 不启动 loop/端点空响应/零采样分支，TC-08 未执行 TOML 覆盖（且 plan 所列 server/agent 配置覆盖未完整体现）。按 A 档契约须补交：TC-10 的执行命令、完整 stdout/stderr、退出码；TC-05 prune 故障分支、TC-07 关闭采样 app 接线分支、TC-08 TOML/计划所列配置分支的对应测试及其执行命令、完整 stdout/stderr、退出码。
- [blocker] R-02 TC-17 的 A 档证据缺少脚本执行命令及脚本最终退出码
  - 详情:`.ai/2026-07-24/maintenance-resource-dashboard/evidence/tc17-postgres.txt:1-81` 记录了脚本内部输出和 pytest 的 `=== pytest exit: 0 ===`，但没有记录调用 `tc17-postgres.sh` 的外层命令，也没有脚本自身的最终退出码；这不满足 plan 对 TC-17 明定的“命令 + 完整输出 + 退出码”。须补交 TC-17：实际脚本执行命令、完整 stdout/stderr、脚本最终退出码（并保留现有脚本文件）。
- [major] R-03 TC-05 的实现测试漏掉 prune 失败隔离，无法证明三步骤级故障隔离契约
  - 详情:`apps/server/tests/test_resource_stats.py:607-626` 仅验证 cleanup 抛错后其他步骤继续，`:629-642` 验证单流 trim 失败；文件中不存在让 `prune_event_audit` 抛错并断言 trim 仍执行的测试，而 plan TC-05 明确要求该场景。新增 prune 抛错测试，断言 event_audit=failed、stream_trim 仍执行且为 ok，并核验 HTTP 200。
- [major] R-04 TC-07 未测试 stats_interval_seconds=0 的真实 lifespan 接线行为
  - 详情:`apps/server/tests/test_resource_stats.py:712-751` 只测 loop 异常恢复和 retention_days=0；没有覆盖 `apps/server/dopilot_server/app.py:176-182` 的关闭分支，也没有按 plan 断言关闭时端点返回 sampled_at:null/scopes:[] 且采样计数为 0。补充运行 lifespan 的 app 级测试，覆盖 sampler 不启动、空响应及零采样。

## 总评
实现主体与方案结构基本一致，B 档 TC-16 引用可定位，现有 A 档输出也未发现与其实际结果相矛盾之处。但多项 A 档契约证据不完整，且两个明确要求的故障/关闭分支测试缺失；依据权威判定规则本轮必须 fail。

VERDICT: fail
