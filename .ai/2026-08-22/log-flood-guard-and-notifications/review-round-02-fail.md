# 评审:第 02 轮

## 问题清单
- [major] R-01 保留清理可能删除尚未写入调度结果账本的终态任务
  - 详情:apps/server/dopilot_server/services/maintenance.py:120,175-176,252-268；apps/server/dopilot_server/services/outcomes.py:68-75,282-313；apps/server/dopilot_server/app.py:188-203 / 清理条件未排除 outcome_recorded_at 为空的调度任务，而记录器每轮仅处理 200 条且与启动时 retention 并发运行；升级后旧任务可能先被删除，导致连续错误计数永久缺失。应在删除前可靠完成结果记录，或排除所有尚未记账的调度任务，并增加启动/超过 200 条旧任务的回归测试。
- [major] R-02 最老日志删除失败会永久阻塞其余候选的预算回收
  - 详情:apps/server/dopilot_server/services/maintenance.py:377-387 / 每轮只选择最老一条；该任务 unlink 失败后 summary.tasks 为 0，循环立即退出，下次仍会选中同一任务，后续可删除日志永远不会被尝试。应记录并跳过本轮失败的任务，在有界范围内继续后续候选，并测试“首个失败、第二个成功”的场景。
- [major] R-03 上一轮首次洪泛截断修复在 cap+1 场景仍然不执行截断或写标记
  - 详情:apps/agent/dopilot_agent/redis/commands.py:395-415；apps/agent/tests/test_log_flood.py:151-169 / _truncate_local_log 在 size <= cap+marker 长度时直接返回，因此 TC-01 的 cap+1 输入只会被取消，文件既未截回 cap 也没有截断标记；测试仅断言 <= 上界，弱于 plan 的“截断为 cap+标记”。应区分已含标记与尚未标记的文件，首次达到 cap 时截至 cap 并追加且仅追加一次标记，同时断言文件内容和精确长度。
- [major] R-04 部署文档保留了与新 Redis 容器限制互相冲突的升级流程
  - 详情:docs/architecture/05-deployment.md:107-110,133-140,155-165；deploy/docker/docker-compose.server.yml:102-118 / 新流程明确要求膨胀 AOF 必须先删除 Redis volume，但旧“生产收缩 runbook”仍要求先启动新版 server 再裁剪；默认 1GiB mem_limit 下，超大 AOF 会让 Redis 重启循环，server 无法启动执行裁剪。应删除或重写旧流程，统一指向停机备份并清空瞬态 Redis volume 的恢复路径。
- [minor] R-05 服务日志模块文件尾存在多余空行
  - 详情:apps/server/dopilot_server/services/logs.py:274 / git diff --check 报告 new blank line at EOF。删除多余文件尾空行即可。

## 总评
plan 中 TC-01～TC-33 均为 A 档，证据逐项具备完整命令、输出和退出码，未发现缺证或虚报；上一轮问题除 R-05 的修复不完整外，其余均已落实。当前仍有四项正确性或健壮性缺陷，故判定 fail；按约束未运行测试，只读 Ruff 检查通过。

VERDICT: fail
