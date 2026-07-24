---
task: adopt-ai-workflow-template
round: 01
date: 2026-07-24
---

# 实现记录:第 01 轮

> **⚠️ 本任务无 plan.md(用户明确知晓并批准)**:本任务的交付物就是把
> 仓库从旧 Codex/Claude 双代理治理迁移到 ai-workflow-template 的 rawf
> 工作流本身。在治理流程改修完成之前,不存在可依循的 rawf plan 流程,
> 因此无法先产出合规 plan 再实现。该风险点已由用户在会话中明确知晓并
> 指示直接进入评审。评审请以本记录「本轮改动」+「验证目标」两节作为
> 对照基准;测试用例档位在下方表格逐条声明(均为 A 档,证据在
> `evidence/`)。迁移决策本身已固化为 `docs/decisions/0018`。

## 本轮改动

依据:https://github.com/senjianlu/ai-workflow-template 的「存量项目迁移」
指引;用户三项裁决——docs/phases/ 删除(不按模板"原样保留")、scrapydweb
行为参考文档删除(结论性约束吸收进 decisions)、历史规划文档吸收后删除。

| 文件 | 改动摘要 |
|---|---|
| `.ai-workflow/`(新增,整目录) | 模板工作流层:评审脚本(review.sh / plan-review.sh)、prompts、schemas、review-standards.md、templates |
| `.claude/`(新增,整目录) | gate-plan / gate-review hooks、settings.json、rawf-plan/implement/review/report 四个 skills |
| `.ai/`(新增) | 任务产物目录(.gitkeep;本任务目录即首个产物) |
| `.githooks/commit-msg`、`.gitmessage` | 换为模板版(Conventional Commits 强制) |
| `.gitignore` | 重写:清 scrapydweb 遗留条目、取消忽略 `.claude/`(改为仅忽略 settings.local.json)、加 rawf 运行时排除项 |
| `CLAUDE.md` | 换为模板版(纯 rawf 工作流,@AGENTS.md 引入项目事实) |
| `AGENTS.md` | 按模板结构重写为工具中立项目事实:技术栈(前端栈 A + 后端)按 dopilot 实际裁剪、目录约定、通用硬规则、提交规范(scope 表)、Skill 基线(shadcn) |
| `docs/README.md` | 换为模板版分工说明(docs=持久真相 / .ai=过程痕迹)+ 历史小节 |
| `docs/decisions/`(新增 19 文件) | 18 条决策记录 + README 索引:逐条搬自旧 CLAUDE.md 决策表与 docs/dopilot/00-requirements.md §4;0018 记录本次治理切换与用户裁决 |
| `docs/architecture/`(新增 8 文件) | dopilot 当前架构真相:README(目录地图+系统形态)+ 运行拓扑 / 领域模型 / 执行与日志链路 / 配置与认证 / 部署 / 前端 / 开发与测试;写作时对照实际代码修正旧文档出入(如调度器为 AsyncIOScheduler 与 DB 同步、packages/client 不存在) |
| `docs/agent-governance/`、`docs/phases/`、`docs/dopilot/`、`docs/refactor/`、旧 `docs/architecture/`(删除,322 文件) | 旧治理与历史文档整体退役,长期有效事实已吸收进新 docs;git 历史可查 |
| `README.md`、`README.zh-CN.md`、`CONTRIBUTING.md` | Documentation/前置阅读/提交规范引用改指 docs/architecture、docs/decisions、AGENTS.md;补 hooks 启用命令 |
| `apps/server/dopilot_server/services/states.py`、`apps/server/migrations/versions/0003–0012(9 个文件)` | 仅 docstring:指向已删 docs/phases、docs/refactor 的历史引用标注为 `git history:` 前缀(无任何代码/schema 变更) |
| `packages/protocol/dopilot_protocol/agent.py`、`streams.py` | 仅 docstring:现行协议权威引用改指 docs/decisions/0008 与 docs/architecture/03 |
| `configs/server.docker.toml` | 仅注释:文档引用改指 docs/architecture/05-deployment.md |

## 修复对照

无(第 1 轮)。

## 验证目标(代替缺失的 plan 用例来源)

1. 新 docs 树内与根级 md 的全部相对链接可达。
2. 被编辑的 Python 文件(均为 docstring/注释级改动)语法完好。
3. 全仓不存在指向已删除文档目录的"现行"引用(有意的历史陈述白名单除外)。
4. 改动集与 rawf 前置就绪:git hooks/commit template 已配置,jq 与 codex CLI 可用。
5. 拷入的工作流脚本与 hooks 语法合法且保留可执行位。

## 测试结果

| 编号 | 档位 | 结果 | 证据 |
|---|---|---|---|
| TC-01 相对链接全通 | A | pass | evidence/tc01-link-check.txt |
| TC-02 py_compile 全通 | A | pass | evidence/tc02-py-compile.txt |
| TC-03 无现行死引用(白名单外) | A | pass | evidence/tc03-stale-refs-grep.txt |
| TC-04 改动集清单 + hooks/CLI 就绪 | A | pass | evidence/tc04-changeset-and-hooks.txt |
| TC-05 工作流脚本 bash -n + 可执行位 | A | pass | evidence/tc05-workflow-scripts.txt |

## 与方案的偏差

- **无 plan.md**(见顶部声明):治理流程自举任务,用户明确知晓并批准直接
  评审。
- **pytest / ruff 未运行**:当前 Codespace 环境无 `.venv`、未安装
  pytest/ruff(evidence/tc04 可见环境状态)。本轮对 Python 文件的改动
  **仅限 docstring/注释**(见「本轮改动」表),不触及任何运行时代码路径,
  以 TC-02 的 `py_compile` 作为语法层证据。如评审认为必须补跑完整测试,
  需先在环境中安装依赖后由后续轮次补交。
- 与模板迁移指引的一处有意偏差:模板建议"历史阶段产物(docs/phases/)
  原样保留",用户裁决改为删除(git 历史可查),已记录于
  docs/decisions/0018。
