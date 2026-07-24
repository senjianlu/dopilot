# 评审:第 01 轮

## 问题清单
- [blocker] R-01 全部 A 档证据均缺少契约要求的执行命令和退出码
  - 详情:.ai/2026-07-24/resource-hard-limits/evidence/: TC-01～TC-13、TC-17、TC-18 的 tc01-18-resource-limits-verbose.txt 只有 pytest 输出，缺执行命令与退出码；TC-14 的 tc14-compose-check.txt 缺执行命令与退出码；TC-15 的 tc15-pytest.txt、tc15-ruff.txt 均缺各自执行命令与退出码。须按用例编号补交：TC-01～TC-15、TC-17、TC-18 对应的命令、完整 stdout/stderr、退出码；可共享证据文件，但必须明确覆盖关系。
- [blocker] R-02 TC-16 的 B 档文档引用缺少行号，无法按证据契约核验
  - 详情:.ai/2026-07-24/resource-hard-limits/evidence/tc16-doc-config-refs.txt: 文档回写部分仅列出 docs/architecture/04-configuration.md、03-execution-and-logs.md、05-deployment.md 和 docs/decisions/0019-resource-hard-limits.md，没有 `文件:行号` 引用。须为 TC-16 补交每项预期内容的具体文件与行号；当前代码消费点引用及旧草稿删除锚点可核验。
- [major] R-03 日志正文删除失败后仍删除数据库记录，遗留无法重试清理的孤儿文件
  - 详情:apps/server/dopilot_server/services/maintenance.py:183 捕获 OSError 后仅记录日志，随后仍在 :194-207 删除日志索引、执行、任务等记录并提交。这与 plan 要求的“IO 失败留待下 tick 重试”相反，正文会永久脱离数据库索引。测试 apps/server/tests/test_resource_limits.py:214-233 还把该错误行为视为允许，并未验证下一 tick 重试 unlink。修复为任一正文删除失败时保留相应 expired 行及其父记录，下一轮重新删除；补充断言首次失败后行仍为 expired、文件仍存在，恢复 unlink 后下一 tick 文件和记录均被删除。
- [major] R-04 Agent janitor 未使用命令处理活跃集和 per-execution 锁，存在删除在途执行目录的竞态
  - 详情:apps/agent/dopilot_agent/janitor.py:125-159 在线程中直接依据 runner.active_execution_ids() 扫描并删除，:169-179 也直接删除 workspace/state 后才调用 release；未包含 plan 要求的 CommandConsumer 在途处理 id，且未持有 `_handle_cleanup` 使用的同一把 per-execution asyncio.Lock。命令已进入处理但尚未 spawn/登记 `_procs` 时，旧且满足 TTL 的目录可能被 janitor 删除。应向 janitor 提供完整活跃集，并将逐执行清理协调到事件循环中，在同一 per-execution 锁内重新核验活跃性后删除；增加竞态测试。

## 总评
评审失败：测试输出本身显示通过，但 A/B 档留证不满足已批准方案的证据契约。实现还存在两项资源清理正确性问题：server 会遗留不可重试的孤儿日志正文，agent janitor 未按方案与命令处理锁及活跃集协调。

VERDICT: fail
