# New Chat Startup Prompt

Use this prompt when starting a new Codex chat for dopilot work that should
follow the Codex-Claude governance workflow.

```text
请按本项目的 AI Agent Governance 流程执行这个任务。

先读取：
- AGENTS.md
- CLAUDE.md
- docs/agent-governance/00-operating-model.md
- docs/agent-governance/01-codex-claude-loop.md
- docs/agent-governance/02-claude-invocation.md

流程要求：
1. 先和我讨论方案并确定版本。
2. brief 前调用 Claude 做可行性验证。
3. Codex 自行判断 Claude 反馈，只有产品/架构/风险接受问题再问我。
4. 确认后写 phase/task brief。
5. 用 claude -p 调 Claude 实现。
6. Codex review Claude 的代码和测试结果。
7. 必要时让 Claude 修复或解释。
8. 最后给我验收摘要。

我的目标是：<写你的目标>
```

Short version:

```text
按 AGENTS.md 和 docs/agent-governance/ 的 Codex-Claude 治理流程执行。
我的目标是：<写你的目标>
```

Use the long version for a fresh chat or high-risk task. Use the short version
only when Codex has already loaded the project instructions in the current chat.
