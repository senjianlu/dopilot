# 0018:采用 ai-workflow-template 的 rawf 治理流程，退役旧 Codex/Claude 治理

- 日期:2026-07-24
- 背景:仓库此前使用自研的 Codex（治理/评审）+ Claude Code（实现/测试）
  双代理流程（`docs/agent-governance/` + `docs/phases/` 阶段产物，均已随
  本决策移除，git 历史可查）。该流程有效但文档形态发散：设计真相、阶段
  过程、治理规则混在多个目录，且闸门靠约定无硬约束。
- 决定:整体切换到
  [senjianlu/ai-workflow-template](https://github.com/senjianlu/ai-workflow-template)
  的 **rawf 工作流**：Claude Code 开发、OpenAI Codex 交叉评审，产物落
  `.ai/<yyyy-mm-dd>/<task-slug>/`（plan / implementation-round /
  review-round / summary + evidence），关键闸门由 `.claude/hooks/`
  （gate-plan / gate-review）硬约束，评审经
  `.ai-workflow/scripts/review.sh`（plan 阶段评审 `plan-review.sh`），
  提交规范 Conventional Commits 由 `.githooks/commit-msg` 强制。文档收敛为
  两层：**`docs/` 存持久真相**（`architecture/` + `decisions/`），
  **`.ai/` 存过程痕迹**。按用户裁决（2026-07-24），与模板迁移指引不同的
  一点是：历史阶段产物 `docs/phases/` 不保留，连同旧
  `docs/agent-governance/`、`docs/dopilot/`、`docs/refactor/` 与 scrapydweb
  行为分析（旧 `docs/architecture/`）一并删除，长期有效的事实已吸收进本
  目录与 `../architecture/`。
- 影响:
  - CLAUDE.md 换为模板版（纯工作流），AGENTS.md 按模板重写为工具中立的
    项目事实（技术栈/目录约定/硬规则/提交规范/Skill 基线）。
  - 前置依赖：Codex CLI（须支持 `codex exec --output-schema`，已
    `codex login`）、jq；克隆后执行
    `git config core.hooksPath .githooks && git config commit.template .gitmessage`。
  - 此后任务改变架构或关键决策时，须在收尾前回写 `docs/`，与代码同一提交。
  - 采用时模板尚无版本机制，故本记录未锚定模板版本；采用的版本、有意偏离
    清单与后续升级流程见
    [`0020`](0020-ai-workflow-template-version-anchor.md)（本记录的结论不变，
    由 0020 补充版本维度）。
