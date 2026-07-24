评审一份**开发方案**(plan.md),不是代码 diff。这是 rawf 工作流的 plan 阶段
评审(实现前审方案),目的是尽早发现 plan-blocker,避免实现后返工。

评审对象:{{TASK_DIR}}/plan.md

请结合仓库现有工作流实现(.ai-workflow/scripts/、.claude/hooks/、
.claude/skills/rawf-*、AGENTS.md、CLAUDE.md)判断方案是否自洽、是否与既有约定
冲突。

评审角色约束、严重度定义与判定规则以 .ai-workflow/review-standards.md 为唯一
权威,评审前先完整阅读该文件,并特别遵循其中"plan 阶段评审(plan-review)
语义"小节:plan 阶段尚无实现,不使用 blocker;存在任一 plan-blocker 或
major → fail,仅 minor 或无问题 → pass。

**硬约束(务必遵守)**:只列会导致返工或架构错误的 plan-blocker/major。风格、
个人偏好、等价写法之争一律不列或至多降为 minor。核心只问两件事:
1. 方案是否存在架构/正确性错误,或与既有工作流约定冲突?
2. 测试用例是否真实覆盖验收标准(含异常/边界路径;只测 happy path 即 major)?
3. 证据契约是否合规(定义见 review-standards.md「测试证据档位」小节):
   - 测试用例表是否**逐条声明**了「档位」与「证据形态」?未声明 → major;
   - 是否有**可自动化的用例被塞进 C 档**(应为 A 档)? → major;
   - **C 档是否超限**(> 总数 1/3;总数 < 3 时 > 1 条)**或缺少不可自动化的
     理由**? → major。

输出要求:你的最终回复由 --output-schema 强制为 JSON,字段语义如下。verdict
必须按 review-standards.md 的判定规则给出——脚本会按严重度清单独立复核,
自报结论与清单矛盾的评审直接判无效。

- verdict:"pass" 或 "fail"
- issues:问题数组,无问题时为空数组;每项:
  - id:R-NN 两位递增编号(R-01、R-02……)
  - severity:plan-blocker | major | minor(定义见 review-standards.md)
  - summary:一句话结论
  - detail:定位 / 问题说明 / 修复建议
- overall:两三句总评
