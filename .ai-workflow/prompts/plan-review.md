评审一份**开发方案**(plan.md),不是代码 diff。这是 rawf 工作流的 plan 阶段
评审(实现前审方案),目的是尽早发现 plan-blocker,避免实现后返工。

评审对象:{{TASK_DIR}}/plan.md(本轮所审版本已由脚本快照,评审期间不会变动)

请结合仓库现有工作流实现(.ai-workflow/scripts/、.claude/hooks/、
.claude/skills/rawf-*、AGENTS.md、CLAUDE.md)判断方案是否自洽、是否与既有约定
冲突。

评审角色约束、严重度定义与判定规则以 .ai-workflow/review-standards.md 为唯一
权威,评审前先完整阅读该文件,并特别遵循其中"plan 阶段评审(plan-review)
语义"小节:plan 阶段尚无实现,不使用 blocker;存在任一 plan-blocker 或
major → fail,仅 minor 或无问题 → pass。

## 本轮上下文

{{ROUND_CONTEXT}}

## 严重度判据(返工判据)

若该问题留到实现阶段才被发现,是否需要推翻已完成的实现(返工)?是 → major
(或 plan-blocker);否 → minor。

- 判 minor:用例中意图明确的机械性错误(笔误、排序、转义、算术、措辞);章节间
  不影响实现方式的表述不一致;docs 回写清单的遗漏(实现层评审按回写规则核对)。
- 仍判 major:验收标准缺覆盖(含异常/边界路径;只测 happy path 即 major)、验收
  标准不可达或自相矛盾、契约/数据模型/接口错误、证据契约违规、缺「需求原文」或
  「非目标」节。
- 风格、个人偏好、等价写法之争一律不列。

## 本轮模式为"全量穷尽评审"时(第 1、2 轮,及无上一轮快照的回退轮)

逐一走完以下五个维度,**一次列出全部问题(含 minor)**,不得在找到前几条后停止;
plan 作者需要一次看到全貌、一次改完。第 2 轮另需先逐项核验上一轮的
plan-blocker/major。

1. 架构与正确性:方案能否达成「需求原文」的交付;契约、数据模型、接口、失败路径
2. 与既有约定的冲突:AGENTS.md、CLAUDE.md、docs/decisions、既有脚本与 hook 行为
3. 验收覆盖:每个验收点有用例;异常/边界路径;预期结果可达且自洽
4. 证据契约(定义见 review-standards.md「测试证据档位」小节):
   - 测试用例表是否**逐条声明**了「档位」与「证据形态」?未声明 → major;
   - 是否有**可自动化的用例被塞进 C 档**(应为 A 档)? → major;
   - **C 档是否超限**(> 总数 1/3;总数 < 3 时 > 1 条)**或缺少不可自动化的
     理由**? → major。
5. 范围自省:方案是否超出「需求原文」?「改动范围」「实现方案」中不是需求直接
   要求的条目,plan 是否说明了"实现必需"的理由;顺手项是否已移入「非目标」。
   结论逐条写入 `scope_findings`(**不定严重度、不计入 pass/fail**,由用户裁决,
   不要重复列进 issues)。

`overall` 先逐维度各写一句检查结论(五句),再给总评。

## 本轮模式为"收敛评审"时(第 3 轮起)

前两轮已全量审过,本轮只做三件事:

1. 先逐项核验上一轮的 plan-blocker/major:未解决 → 原严重度保留,summary 注明
   "上一轮 R-NN 未解决";
2. 对上下文 diff 中**修订的部分**按五个维度完整评审,修订引入的新问题按常规
   严重度;
3. **未修订部分**的新发现**只报 plan-blocker**;其它新问题至多 minor。

上一轮未修的 minor **不要求逐轮重复列出**(实现阶段会汇总全部轮次的 minor 做
交接)。范围自省仍写 `scope_findings`,只针对修订部分。`overall` 写明上一轮
各问题的核验结论与修订部分的评审结论。

## 输出要求

你的最终回复由 --output-schema 强制为 JSON,字段语义如下。verdict 必须按
review-standards.md 的判定规则给出——脚本会按严重度清单独立复核,自报结论
与清单矛盾的评审直接判无效。

- verdict:"pass" 或 "fail"
- issues:问题数组,无问题时为空数组;每项:
  - id:R-NN 两位递增编号(R-01、R-02……)
  - severity:plan-blocker | major | minor(定义见 review-standards.md)
  - summary:一句话结论
  - detail:定位 / 问题说明 / 修复建议
- scope_findings:范围自省结论,字符串数组,无则为空数组
- overall:按上方本轮模式的要求书写
