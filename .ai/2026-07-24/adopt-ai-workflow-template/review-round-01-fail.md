# 评审:第 01 轮

## 问题清单
- [plan-blocker] R-01 任务缺少指定的 plan.md，无法按权威方案核验实现忠实度与测试档位
  - 详情:.ai/2026-07-24/adopt-ai-workflow-template/plan.md:文件不存在；implementation-round-01.md:9-15 以实现记录自行替代方案，但评审输入和测试证据契约要求档位在 plan 阶段声明。补建并确认 plan.md（包含范围、验收标准、逐项测试档位及证据形态）后重新评审。
- [blocker] R-02 多项 A 档证据不完整，不满足完整原始输出契约
  - 详情:.ai/2026-07-24/adopt-ai-workflow-template/evidence/tc01-link-check.txt:1 使用 `<link-check script>` 占位，缺少实际完整命令/脚本；tc03-stale-refs-grep.txt:7 使用 `--include=...` 和“过滤白名单”占位，且未记录退出码；tc05-workflow-scripts.txt:1 使用“ls -l 可执行位”占位，未给出实际 ls 参数及该步骤退出码。按 A 档规则须补交：TC-01 的实际完整命令或脚本、完整 stdout/stderr、退出码；TC-03 的实际完整 grep/过滤命令、完整 stdout/stderr、退出码；TC-05 的实际完整 bash -n 与权限检查命令、完整 stdout/stderr、各命令或整体命令退出码。
- [major] R-03 plan 闸门可被 Bash 写文件绕过，且活动任务缺少 plan 时直接放行
  - 详情:.claude/settings.json:5 仅为 Write/Edit/NotebookEdit 注册 PreToolUse hook，Bash 可通过重定向、sed -i 等修改源码而不触发闸门；.claude/hooks/gate-plan.sh:54-55 在活动任务的 plan.md 缺失时也直接放行。当前任务正是缺少 plan 的实例，因此闸门不能兑现“plan 未获批时拦截写入”的约束。应覆盖可能写文件的 Bash 调用（或在权限层禁止其写入），并在存在 `.ai/.current-task` 但 plan 缺失时 fail-closed。
- [major] R-04 评审完整性指纹排除了整个 .claude 目录，可漏掉工作流控制文件的并发修改
  - 详情:.ai-workflow/scripts/review.sh:16-22、29-30 将整个 `.claude/` 同时从已跟踪 diff 和未跟踪文件指纹中排除；评审期间若 hooks、settings.json 或 rawf skills 被修改，pre/post hash 仍相同，可能发布针对旧内容的评审结论。应只排除确需忽略的 `.claude/settings.local.json`，继续对其余 `.claude/` 控制文件计算指纹。

## 总评
本轮不能通过：指定方案缺失，且 TC-01、TC-03、TC-05 的 A 档证据使用占位命令，未达到完整原始证据要求。工作流实现还存在 plan 闸门可绕过和完整性指纹漏检控制文件两项关键健壮性缺陷。

VERDICT: fail
