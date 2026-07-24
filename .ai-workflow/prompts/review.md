评审当前工作区的未提交改动(git diff HEAD 及未跟踪的新文件)。

本轮任务上下文:
- 方案:{{TASK_DIR}}/plan.md
- 本轮实现记录:{{TASK_DIR}}/implementation-round-{{ROUND}}.md
- 若轮次大于 01,请对照上一轮 review-round-*-fail.md 逐项核验修复是否到位

评审角色约束、标准、严重度定义与可执行动作以 .ai-workflow/review-standards.md
为唯一权威,评审前先完整阅读该文件。
你运行在只读沙箱中,不要运行任何测试;可运行确无写入副作用的静态检查
(命令因写失败报错不算代码缺陷,转证据核验,单条命令默认 5 分钟超时)。
核验实现记录中报告的测试结果是否属实的方式是**证据核验**,且必须
**按 plan 声明的档位**逐条进行:先读 plan.md 测试用例表的「档位」列,
再按 review-standards.md「测试证据档位」小节的逐档规则核验,**不得对
全部用例统一套用最严标准**。要点:A 档缺失或不完整 → blocker,且必须在
detail 中列明需要补交的证据清单(具体到用例编号与所缺内容);B 档核验
引用的 `文件:行号` 是否存在且支持结论;C 档默认采信实现者的结果描述,
**不得仅以「无原始命令输出」为由判 blocker**,只在自相矛盾、plan 中并非
C 档(擅自降档)或关键锚点缺失时判问题。任一档位:证据与记录矛盾按虚报
测试处理(blocker)。

输出要求:你的最终回复由 --output-schema 强制为 JSON,字段语义如下。
verdict 必须按 review-standards.md 的判定规则给出——脚本会按严重度清单
独立复核,自报结论与清单矛盾的评审直接判无效。

- verdict:"pass" 或 "fail"
- issues:问题数组,无问题时为空数组;每项:
  - id:R-NN 两位递增编号(R-01、R-02……)
  - severity:plan-blocker | blocker | major | minor(定义见 review-standards.md)
  - summary:一句话结论
  - detail:文件:行号 / 问题说明 / 修复建议
- overall:两三句总评

plan-blocker 不计入 pass/fail 判定,但必须列出(渲染时置顶)。
