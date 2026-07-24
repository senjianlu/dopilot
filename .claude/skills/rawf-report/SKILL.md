---
name: rawf-report
description: rawf 工作流第 5 步(收尾):评审 pass 后向用户汇报改动、评审轮次与遗留 minor,经用户确认后提交并关闭任务;用户中止任务时的收尾也用本 skill。
---

# rawf-report:汇报与收尾

## 汇报

1. 回写检查:本任务是否改变了架构或关键决策?是 → 先把变化写回
   docs/(architecture/ 或 decisions/),该改动与代码同一提交;architecture/
   README.md 只做汇总和导航,详细主题下沉到同目录其他文件。
2. 汇总本任务:改动文件清单与摘要、评审结论与所用轮次、遗留 minor
   清单(取自最后一轮 review 的 minor 条目)。
3. 按 .ai-workflow/templates/summary.md 将汇总写入任务目录 summary.md。
4. 向用户汇报,并就两件事征求决定:
   - 每条遗留 minor:本次修 / 记入后续任务 / 放弃
   - 是否提交
5. 用户明确同意前,不执行任何 git 提交;"用户没有反对"不算同意。

## 提交与关闭

6. 用户同意后:git add 本任务的代码改动与 .ai/ 任务目录,单次提交。
   提交信息按 AGENTS.md「Git 提交规范」:header 为
   `<type>(<scope>): <subject>`,footer 附
   `Rawf: <yyyy-mm-dd>/<task-slug>`。代码与决策痕迹同一个 commit,
   回看历史时二者互为注解。
7. 只 commit,不 push;push 由用户自行执行或另行明确要求。
8. 提交完成后删除 .ai/.current-task,任务关闭。
9. 用户拒绝提交时:询问任务是保持打开(保留 .current-task,墙继续生效)
   还是放弃(删除 .current-task,工作区改动的去留由用户处置)。
