---
task: upgrade-ai-workflow-template-v1-2-1
round: 01
date: 2026-11-02
---

# 实现记录:第 01 轮

## 本轮改动

对照物:模板克隆 `/tmp/claude-1000/awt/tpl`,`v1.2.1` = `246db2af…96cc`、`v1.0.0` = `2aeab2ea…c61b68`(TC-01 现场核对)。

| 文件 | 改动摘要 |
|---|---|
| `.ai-workflow/TEMPLATE-VERSION` | 从 v1.2.1 拷入;第 3 行改为 `adopted: 2026-11-02` |
| `.ai-workflow/prompts/plan-review.md`、`prompts/review.md` | 从 v1.2.1 拷入覆盖 |
| `.ai-workflow/review-standards.md` | 从 v1.2.1 拷入覆盖,随后删去「技术栈评审关注点」中以 `- Scrapy:` 起头的 4 行(重新施加 D-1) |
| `.ai-workflow/schemas/plan-review.schema.json`、`schemas/review.schema.json` | 从 v1.2.1 拷入覆盖 |
| `.ai-workflow/scripts/evidence.sh`、`scripts/evidence-check.sh` | 新增(v1.2.1 原文,+x) |
| `.ai-workflow/scripts/plan-review.sh`、`scripts/review.sh` | 从 v1.2.1 拷入覆盖(可执行位保持) |
| `.ai-workflow/templates/{plan,implementation-round,summary}.md` | 从 v1.2.1 拷入覆盖 |
| `.claude/hooks/gate-review.sh` | 从 v1.2.1 拷入覆盖 |
| `.claude/skills/rawf-{plan,implement,review,report}/SKILL.md` | 从 v1.2.1 拷入覆盖 |
| `CLAUDE.md` | 1b 步改为默认 5 轮(前两轮穷尽、第 3 轮起收敛);轮次上限硬规则改为"plan 评审 5 轮、实现层修复 3 轮";新增两条硬规则(A 档证据经 evidence.sh;追加类偏差不得自行实现);模板决策引用按 D-6 写作"模板决策 0010/0011/0012",D-2 省略的 0003 尾注继续省略。结果与"模板 v1.2.1 原文经 D-2/D-6 规范化"逐字节相等(TC-02) |
| `AGENTS.md` | 通用硬规则 plan-review 默认最多 3 轮 → 5 轮 |
| `.gitignore` | rawf 块追加锁文件注释 + `.ai/**/.review-lock`、`.ai/**/.plan-review-lock`(注释按 D-6 写"模板决策 0009") |
| `docs/decisions/0020-ai-workflow-template-version-anchor.md` | 末尾追加「修订」小节:升级来源与做法、D-6 偏离行、可整体替换类文件中模板决策编号不改写的说明(既有正文未动,TC-07 前缀断言) |
| `docs/decisions/README.md` | 0020 索引行补"(2026-11-02 升至 v1.2.1)" |

v1.0.0→v1.2.1 未变的受管文件(`gate-plan.sh`、`.claude/settings.json`、`.githooks/commit-msg`、`.gitmessage`、`scripts/.gitkeep`)未动,TC-01 断言其与 v1.2.1 逐字节一致。

## plan 评审 minor 交接

`bash .ai-workflow/scripts/plan-review.sh __minors .ai/2026-11-02/upgrade-ai-workflow-template-v1-2-1` 输出"无"(rc=0):plan 评审仅 1 轮,结论 pass,问题清单为空。

| 来源 | 内容 | 处置 |
|---|---|---|
| plan-review-round-01-pass.md | 无 minor | — |

## 修复对照

第 1 轮,不适用。

## 测试结果

| 编号 | 档位 | 结果 | 证据 |
|---|---|---|---|
| TC-01 | A | pass | TC-01.log(IDENTICAL=21、EXPECTED-DIFF=2、EXPECTED-ABSENT=1、UNEXPECTED-*=0;两个 tag SHA 与钉死值一致) |
| TC-02 | A | pass | TC-02.log(逐 hunk 断言全部 PASS;CLAUDE.md 与规范化模板 sha256 相等) |
| TC-03 | A | pass | TC-03.log(4 个流程脚本、2 个 hook、commit-msg 均 `bash -n` 通过且可执行) |
| TC-04 | A | pass | TC-04.log(无锁 block / 锁被持有放行 / 锁存在未持有 block / 锁为目录 block / 已有评审放行) |
| TC-05 | A | pass | TC-05.log(evidence.sh 透传 exit 7、字段齐全、同名重跑与非法编号 exit 3;evidence-check 完整 exit 0、缺行报 MISSING-ROW、bytes 篡改报 TRUNCATED) |
| TC-06 | A | pass | TC-06.log(exit 0,输出"无")。说明:被测历史任务三轮 plan 评审共 5 条问题(round-01 3 条、round-02 2 条、round-03 0 条),无一为 minor(`grep -c '\[minor\]'` 三轮均为 0),故"无"即正确汇总;本用例验证的是新入口对历史任务目录只读可用、不报错 |
| TC-07 | A | pass | TC-07.log |
| TC-08 | A | pass | TC-08.log(变更集恰为 plan 列出的 23 个文件 + 本任务目录;应用路径零改动;建议目录 19 个文件清单哈希与基线一致且仍未跟踪) |

## 与方案的偏差

| 编号 | 类型 | 内容 | 原因 | 处置 |
|---|---|---|---|---|
| D-01 | 替代 | TC-04 断言脚本在 plan 所列三种情形之外,多覆盖"锁文件存在但未被持有→block"与"已有本轮评审文件→放行"两种 | 同一目标(验证新 hook 的锁判定)更完整的覆盖;不改变 plan 用例意图与预期 | 已在证据中如实体现 |
| D-02 | 替代 | TC-05 断言脚本在 plan 所列异常路径之外,多覆盖"非法 TC 编号 exit 3"与"bytes 被篡改报 TRUNCATED" | 同上 | 已在证据中如实体现 |

## 停车场

- 模板 `CLAUDE.md` / `.gitignore` 中以 `docs/decisions/00NN` 引用模板自身决策,consumer 侧必然串号(本仓库已累积 D-2、D-6 两条同类偏离)。可向模板上游建议改为显式写"模板决策"或带仓库 URL,从源头消除这类偏离。留待用户决定是否向模板提 issue。
- 本机记忆"后台评审卡 stdin"所述问题已由 v1.0.1(codex stdin 固定接 /dev/null)根治,收尾后更新该条记忆(仓库外,不入 diff)。
