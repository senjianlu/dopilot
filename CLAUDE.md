@AGENTS.md

# Claude Code 工作流

## 开发工作流(强制)

所有非琐碎改动必须走此流程,产物写入 `.ai/<yyyy-mm-dd>/<task-slug>/`:

1. `/rawf-plan` → 产出 plan.md(必须含测试用例),向用户呈现摘要
1b. 【plan 评审闸,仅 >10 文件】确认前先跑 `.ai-workflow/scripts/plan-review.sh`,
    plan-blocker/major 就地改 plan 再重评,默认最多 3 轮(用户明确指定时
    以其为准,见硬规则),不决转人工
2. 【人工闸】用户确认 plan 前,禁止改动源码(有 hook 拦截)
3. `/rawf-implement` → 实现 + 自测,写 implementation-round-<NN>.md
4. `/rawf-review` → 跑 Codex 评审,产出 review-round-<NN>-<pass|fail>.md
5. fail → 按 rawf-review skill 的分流规则处理,实现层修复默认最多 3 轮
   (用户明确指定时以其为准,见硬规则)
6. `/rawf-report` → 汇报;提交须用户确认

例外:纯文档、拼写级改动可跳过流程,但需先向用户声明。

## 硬规则(通用硬规则见 AGENTS.md,以下为 Claude Code 补充)

- 与用户沟通一律使用简体中文(对话、方案摘要、汇报等面向用户的自然语言);
  代码、标识符、注释与既有产物的语言不受此约束
- 评审只能通过 `.ai-workflow/scripts/review.sh` 触发,不得自行替代
- **预计触及文件 > 10 的改动,方案确认闸之前必须先经 plan 阶段 Codex 评审**
  (`.ai-workflow/scripts/plan-review.sh`):plan-blocker/major 就地改 plan.md
  后重评,脚本强制轮次上限,达上限仍不决则停下交用户。≤10 文件不强制。
  文件数为 plan 起草时的估计;实现中实际超阈,按 rawf-implement"偏差需停下
  问用户"处理
- **评审轮次上限默认均为 3 轮**(plan 评审与实现层修复各自计数),仅当
  **用户明确要求放宽**时,在当前任务 plan.md frontmatter 写
  `plan_review_max_rounds` / `impl_fix_max_rounds`(正整数)覆盖默认值,
  并在摘要或实现记录中声明;不得未经用户提出而自行写入或建议性写入
- **评审进行中(review.sh 运行至返回,含后台等待期)禁止改动本项目任何
  文件,`.claude/` 除外**。脚本比对评审前后主工作区指纹,任何被计入的
  写入都会使评审无效并返回 exit 3;`.claude/`(如权限记录 settings.local.json)
  已从指纹排除,不受此限。发起评审后,等待其完成再对项目做写入
- 开新任务前先检查 `.ai/` 下是否有同日同名任务目录,避免覆盖
- 禁止用 Bash 重定向、临时脚本等方式绕过 gate-plan 对源码与工作流
  控制文件的写入闸
- 任务改变架构或关键决策时,收尾(/rawf-report)前把变化回写 docs/
  (architecture/ 或 decisions/),与代码同一提交;architecture/README.md
  只做汇总和导航,详细主题下沉到同目录其他文件
