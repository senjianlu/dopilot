# 评审:第 01 轮

## 问题清单
- [blocker] R-01 TC-25 的 A 档证据未提供完整可执行命令
  - 详情:.ai/2026-08-22/log-flood-guard-and-notifications/evidence/tc-25-alembic-upgrade-downgrade-upgrade.txt:1-2,25-32,43-46 仅以说明文字记录 schema 重置、升级前数据 seed、结构检查和结果记录器执行，无法还原实际命令。需为 TC-25 补交这些步骤的完整命令、完整 stdout/stderr 和各自退出码；现有三条 Alembic 命令证据可保留。
- [blocker] R-02 TC-31 的两条 A 档 compose 证据使用省略号代替命令
  - 详情:.ai/2026-08-22/log-flood-guard-and-notifications/evidence/tc-31-compose-config.txt:170,480 将组合版和 agent 版命令写成 `$ ... docker compose ...`，不符合 A 档完整命令要求。需为 TC-31 补交 `docker-compose.yml` 与实现记录所声称的 `docker-compose.agent.yml` 校验的完整环境变量、命令、完整 stdout/stderr 和退出码。
- [blocker] R-03 洪泛升级可能因 job ID 前缀碰撞而 SIGKILL 其他 crawler
  - 详情:apps/agent/dopilot_agent/redis/commands.py:547 使用子串判断 `f"_job={job_id}" in a`。例如目标 job `abc` 已退出、同一 scrapyd 下仅剩 `_job=abc2` 时，后者会成为唯一候选并在第 520 行被 SIGKILL。应精确解析 `_job` 参数并要求值完全相等，同时增加前缀碰撞且目标已消失的回归用例。
- [major] R-04 手工清理绕过共享 LogsDirGauge，破坏目录计数精确性
  - 详情:apps/server/dopilot_server/api/v1/maintenance.py:81-83,138-140 调用 `cleanup_terminal_data` 时未传入 `app.state.logs_gauge`。文件会在 gauge 锁外删除且计数不扣减，随后正常日志可能因虚高计数被错误拒收，直至下次周期校准。两个入口都应取得运行时 gauge 并传入服务；还需覆盖清理与写入/校准交错的测试。
- [major] R-05 watchdog 首次发现洪泛时没有立即截回日志
  - 详情:apps/agent/dopilot_agent/redis/commands.py:428-441 首次达到 cap 后只标记并 cancel，随即返回；截断仅从下一 tick 的第 443-444 行开始。绕过进程内 FileHandler 的自定义日志因此可在整个 tick 间隔内保持任意大，违反 plan 的“每 tick 截回”要求。apps/agent/tests/test_log_flood.py:268-276 也跳过了 t=0 的大小断言；应在首次标记后立即截断并补断言。
- [major] R-06 LogPublisher 实际发布量超过 TC-03 声明的每执行上限
  - 详情:apps/agent/dopilot_agent/redis/logs.py:189-193 会先发布完整 cap 字节，再额外发布截断标记，因此 Redis 内容总量为 cap+marker。apps/agent/tests/test_log_publisher.py:144-147 刻意排除 marker 后才断言 4096，未覆盖 plan 要求的“内容字节总和 ≤ 4096”。应在 cap 内为 marker 预留空间，或按已批准方案的准确语义调整实现，并让测试统计所有非 EOF 内容。
- [minor] R-07 持久配置文档仍同时宣称旧的 100MiB 默认值
  - 详情:docs/architecture/04-configuration.md:50,56 仍将 server `max_file_bytes` 和 agent `max_job_log_bytes` 写为 100MiB，而同文件第 88、92 行及代码默认值均为 32MiB。应统一为 32MiB，避免运维按错误上限估算资源。
- [minor] R-08 新增通知菜单违反项目 shadcn 语义颜色和组合约束
  - 详情:apps/web/components/layout/notification-bell.tsx:60-68 使用 `bg-amber-500`/`bg-sky-500` 原始色值；第 194-206 行手写加载/空状态，第 210 行起的 `DropdownMenuItem` 未置于 `DropdownMenuGroup`。应改用语义 token/现有反馈组件，并按 shadcn 组合结构包装菜单项。

## 总评
本轮判定 fail：A 档证据有两处不完整，且 PID 前缀匹配可能终止错误进程。另有共享 gauge、首次洪泛截断和发布上限三项正确性缺陷；评审未运行测试，仅进行了只读差异、证据和静态格式核验。

VERDICT: fail
