---
status: approved
task: adopt-ai-workflow-template
date: 2026-07-24
approved_at: 2026-07-24
retroactive: true
---

# 方案:引入 ai-workflow-template 治理流程并收敛 docs 为架构+决策(追认性)

> **⚠️ 追认性 plan(第 01 轮评审 R-01 的处置)**:本任务是治理流程的
> 自举——在 rawf 流程落地之前不存在可依循的 plan 流程,故第 01 轮无
> plan 先行实现,该风险当时已由用户明确知晓。第 01 轮评审(R-01,
> plan-blocker)要求补建 plan;用户裁决**补追认性 plan 后重评**。本文
> 如实追认已实施的方案与验收契约,不伪称先于实现存在;`approved` 状态
> 对应用户对"补追认性 plan"处置的明确确认(2026-07-24)。

## 背景与目标

仓库原用自研 Codex+Claude 双代理治理(docs/agent-governance/ +
docs/phases/ 阶段产物),文档形态发散。目标:

1. 整体切换到 https://github.com/senjianlu/ai-workflow-template 的 rawf
   工作流(按其「存量项目迁移」指引分层迁移);
2. 全部文档收敛为 `docs/architecture/`(现状真相)+ `docs/decisions/`
   (决策记录),`docs/README.md` 说明分工;
3. 修正 README 等处与现状的出入。

用户三项前置裁决:docs/phases/ 删除(偏离模板"原样保留"指引,git 历史
可查)、scrapydweb 行为参考文档删除(结论性约束吸收进 decisions)、历史
规划文档吸收后删除。

## 改动范围

- **新增(工作流层,整体拷入模板)**:`.ai-workflow/`、`.claude/`
  (hooks/settings/rawf skills)、`.ai/`、`.githooks/commit-msg`、
  `.gitmessage`;`.gitignore` 重写(取消忽略 `.claude/`,加 rawf 排除项)。
- **替换**:`CLAUDE.md`(模板版)、`AGENTS.md`(模板结构,技术栈按
  dopilot 裁剪)。
- **新增(知识层)**:`docs/README.md`、`docs/architecture/`(README+7 篇)、
  `docs/decisions/`(README+18 条,其中 0018 记录本次迁移)。
- **删除**:`docs/agent-governance/`、`docs/phases/`、`docs/dopilot/`、
  `docs/refactor/`、旧 `docs/architecture/`(共 322 文件)。
- **引用同步(仅文档/注释级)**:`README.md`、`README.zh-CN.md`、
  `CONTRIBUTING.md`;`apps/server`(states.py + 迁移文件 0003–0012 的
  docstring)、`packages/protocol`(agent.py/streams.py docstring)、
  `configs/server.docker.toml`(注释)。
- **明确不动**:任何运行时代码路径、schema、依赖、CI 语义;模板工作流
  脚本内容(见「风险」第 3 条用户裁决)。

## 实现方案

按模板「存量项目迁移」顺序:①知识层——老 CLAUDE.md/00-requirements
决策表逐条搬入 decisions/,现状描述写入 architecture/(对照实际代码修正
出入);②工作流层——模板目录整体拷入,CLAUDE.md 换模板版,AGENTS.md
按模板结构重写;③引用同步——指向已删文档的现行引用改指新文档,历史
引用加 `git history:` 标注;④启用 git hooks 配置,确认 jq/codex 就绪。

## 测试用例

| 编号 | 档位 | 前置条件 | 步骤 | 预期结果 | 证据形态 |
|---|---|---|---|---|---|
| TC-01 | A | 新 docs 树已写入 | 运行 evidence/link-check-round02.py 遍历 docs/**/*.md + 根级 md 的相对链接 | 输出 `ALL LINKS OK`,退出码 0 | 脚本文件 + 完整命令/输出/退出码(evidence/tc01-link-check-round02.txt) |
| TC-02 | A | Python 文件已完成注释级编辑 | `python3 -m py_compile` 全部被编辑的 .py 文件 | 无输出,退出码 0 | 完整命令/输出/退出码(evidence/tc02-py-compile-round02.txt) |
| TC-03 | A(非 happy-path:验证"不存在"死引用) | 旧 docs 已删除、引用已同步 | 运行 evidence/stale-refs-check-round02.sh:全仓 grep 指向已删目录的引用,过滤白名单(有意历史陈述) | 输出 `RESULT: NO UNEXPECTED REFS (pass)`,退出码 0 | 脚本文件 + 完整命令/输出/退出码(evidence/tc03-stale-refs-round02.txt) |
| TC-04 | A | 迁移完成 | `git status --short` 全量改动集;`git config core.hooksPath`/`commit.template`;`command -v jq codex` | 改动集与「改动范围」一致;hooks/模板已配置;jq 与 codex 在 PATH | 完整命令/输出/退出码(evidence/tc04-changeset-hooks-round02.txt) |
| TC-05 | A | 模板脚本已拷入 | `bash -n` 逐个校验 5 个工作流脚本;`ls -l` 确认可执行位 | 语法全通(退出码 0);gate-plan/gate-review/review/plan-review/commit-msg 均带 x 位 | 完整命令/输出/退出码(evidence/tc05-workflow-scripts-round02.txt) |
| TC-06 | A | 项目包已 editable 安装(第 02 轮补装,见 TC-04 证据 pip list) | `pytest -q`(server/agent/protocol 全量) | 全部通过,退出码 0 | 完整命令/输出/退出码(evidence/tc06-pytest-round02.txt) |
| TC-07 | A | ruff 已安装(第 02 轮补装) | `ruff check apps packages` | `All checks passed!`,退出码 0 | 完整命令/输出/退出码(evidence/tc07-ruff-round02.txt) |

> 说明:web vitest/build 不在本 plan 用例内——本任务未触及 `apps/web`
> 任何文件(见「改动范围」)。第 01 轮曾以"环境未装 pytest/ruff"为由
> 未跑二者;第 02 轮补装依赖后已全量执行(TC-06/TC-07),该环境限制
> 表述随之作废。

## 风险与回滚

1. **自举无先行 plan**(已发生,用户知晓;本文即追认处置):第 01 轮
   实现先于 plan,由本追认性 plan + 第 01/02 轮实现记录留痕。
2. **删除 322 个历史文档**:回滚 = `git checkout` 恢复(未提交前)或
   git 历史找回(提交后);长期有效事实已吸收进新 docs。
3. **模板已知限制不修(用户裁决,2026-07-24)**:第 01 轮评审 R-03
   (gate-plan 不拦 Bash 写入、缺 plan 时放行)与 R-04(评审指纹排除
   整个 `.claude/`)均为模板自身明文设计——前者见模板 README「已知
   限制」,后者见 review.sh 头部注释。用户裁决**按模板保持现状、不做
   本地偏离**,残留风险接受并在实现记录注明;若后续要加固,另起任务
   并新增 docs/decisions/ 记录。
4. 提交前工作区可整体回滚;提交须用户确认。
