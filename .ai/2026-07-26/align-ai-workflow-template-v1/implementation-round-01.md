---
task: align-ai-workflow-template-v1
round: 01
date: 2026-07-26
---

# 实现记录:第 01 轮

## 本轮改动

按 plan 实现。受管/文档改动 4 个文件,外加任务目录内的核验脚本、逐 hunk
台账与 8 条用例的原始输出。

| 文件 | 改动摘要 |
|---|---|
| `.ai-workflow/TEMPLATE-VERSION` | 新增。三字段严格沿用模板 v1.0.0 形态:`version: 1.0.0` / `source: https://github.com/senjianlu/ai-workflow-template` / `adopted: 2026-07-26`(取完成基线对齐之日,依据模板 README「存量项目迁移」第 3 步) |
| `docs/decisions/0020-ai-workflow-template-version-anchor.md` | 新增决策记录。四段体例;决定含①认领 v1.0.0 版本锚点、②按模板决策 0007 第 4 条三处联动不采用 Scrapy 标准栈、③后续升级流程(模板独立克隆取 `v$OLD..v$NEW` 增量,不加模板 remote)、④被否备选;影响段含 **D-1…D-5 有意偏离清单** |
| `docs/decisions/README.md` | 索引表追加 0020 一行 |
| `docs/decisions/0018-adopt-ai-workflow-template.md` | 「影响」段追加交叉引用,指向 0020;未加"已被 NNNN 取代"标记(0020 只补充版本维度,并未推翻 0018) |
| `.ai/2026-07-26/align-ai-workflow-template-v1/evidence/baseline-check.sh` | 新增。TC-01:受管路径集从模板 v1.0.0 现算 + 双向比对 + SHA 钉死 + 3 条例外表 |
| `…/evidence/manual-merge-check.sh` | 新增。TC-08:hunk 集合现算 vs 台账集合相等、disposition 逐条核实、CLAUDE.md 全文比对、AGENTS.md 章节骨架、`.agents`/`skills-lock.json` no-op 证实 |
| `…/evidence/manual-merge-ledger.tsv` | 新增。10 条 hunk 的逐条处置台账(AGENTS.md 1 + README.md 9) |
| `…/evidence/template-version-check.sh` | 新增。TC-02:6 项断言 + 错误 adopted 日期反向自检 |
| `…/evidence/scrapy-absence-check.sh` | 新增。TC-03:三处同时缺席 + 注入残留反向自检 |
| `…/evidence/decision-doc-check.sh` | 新增。TC-05:0020 四段结构、D-1…D-5 齐全、索引与交叉引用一致性 |
| `…/evidence/changeset-check.sh` | 新增。TC-07:改动集与 plan 声明清单集合相等 + 明确不动目录零改动 |
| `…/evidence/link-check.py` | 新增。TC-06:markdown 相对链接目标存在性 |
| `…/evidence/tc0{1..8}-*.txt` | 8 条用例的完整原始输出(命令 + stdout/stderr + 退出码) |

实现过程中的一处自修:`changeset-check.sh` 初版用 `git status --porcelain`,
GNU git 会把整个未跟踪目录折叠成一行(`.ai/2026-07-26/`),按任务目录前缀
过滤会漏掉全部产物、导致集合相等断言**误报 FAIL**。已改为
`--untracked-files=all` 并在脚本内加注释说明原因;该误报的原始输出与修复后
的通过输出差异,体现在 `tc07-changeset.txt` 的最终版本(修复后重跑)。

## 修复对照

不适用(第 1 轮,无上一轮评审问题)。

> 备注:plan 阶段经 3 轮 Codex 评审收敛(上限 15,用户授权),
> `plan-review-round-01-fail.md` / `-02-fail.md` / `-03-pass.md` 已入库;
> 前两轮的 5 条 major 均已在 plan 中就地修订(详见 plan「评审轮次授权」节
> 与步骤 2/2b 的设计说明)。

## 测试结果

| 编号 | 档位 | 结果 | 证据 |
|---|---|---|---|
| TC-01 | A | pass | `evidence/tc01-baseline-check.txt`(exit=0)。v1.0.0 解析为 `2aeab2eaca28b1364a46ec7cfc9195849cc61b68`,与钉死 SHA 一致;模板侧现算受管路径 22 个、dopilot 侧 21 个;判定汇总 IDENTICAL=19 / EXPECTED-DIFF=2 / EXPECTED-ABSENT=1 / UNEXPECTED-*=0;`review-standards.md` 差异为"新增 0 行、删除 4 行"且被删块含 Scrapy 关注点;`TEMPLATE-VERSION` 除 adopted 行外与 v1.0.0 全等 |
| TC-02 | A | pass | `evidence/tc02-template-version.txt`(exit=0)。6 项断言全 PASS(行数 3、字段序 version,source,adopted、version=1.0.0、source 匹配、adopted 整行 `adopted: 2026-07-26`、无占位文案);反向自检:副本改为 `adopted: 2026-07-24` 时 `[6a]` 判不匹配并被拒 |
| TC-03 | A | pass | `evidence/tc03-scrapy-absence.txt`(exit=0)。三处同时 ABSENT;反向自检两项均"被检出"(注入 `- Scrapy:` 关注点行、注入「### 爬虫」章节) |
| TC-04 | A | pass | `evidence/tc04-round-caps.txt`。① `plan-review.sh __resolve_max_rounds` 对本任务 plan.md 输出 `15`、exit=0(15 轮授权被脚本真实识别);② 三份仓库外伪造 plan(空值 / `abc` / `0`)均 exit=3 且 stderr 为"plan.md 的 plan_review_max_rounds 非法(须为正整数,实际为:…)" |
| TC-05 | A | pass | `evidence/tc05-decision-docs.txt`(exit=0)。0020 四段齐备;D-1…D-5 五行全部命中;索引行 `| [0020](0020-…md) | …|` 存在且链接目标存在;0018 第 31 行含指向 0020 的交叉引用;0018 未被标记"已被…取代" |
| TC-06 | A | pass | `evidence/tc06-link-check.txt`(exit=0)。检查 22 个相对链接,BROKEN=0 |
| TC-07 | A | pass | `evidence/tc07-changeset.txt`(exit=0)。受管/文档改动集与 plan 声明清单**集合相等**(恰好 4 个);无越界改动;`apps/`、`packages/`、`deploy/`、`configs/`、`scripts/`、`examples/`、`tests/`、`.github/`、`.githooks/`、`.agents/` 全部零改动;`AGENTS.md`、`CLAUDE.md`、`README.md`、`README.zh-CN.md`、`.gitignore`、`.gitmessage`、`skills-lock.json` 零改动 |
| TC-08 | A | pass | `evidence/tc08-manual-merge.txt`。正向 exit=0:现算 hunk 10 条与台账 10 条**集合相等**;10 条 disposition 全部核实(`divergence:D-3` 在 0020 中命中、3 条 `absorbed:` 锚点存在、5 条 `n/a-template-doc`);CLAUDE.md 全文比对为"新增 0 行、删除 1 行"且被删行含 `docs/decisions/0003`(D-2);模板 5 个 `##` 章节在 dopilot AGENTS.md 全在;`.agents`/`skills-lock.json` 在 v1.0.0 侧确为空。反向自检 exit=1:台账删一行后报 `MISSING-IN-LEDGER README.md @@ -79,0 +91,37 @@` |

无 `blocked` 项,无 `fail` 项;plan 声明的档位未做任何下调(8 条全 A 档,
C 档 0 条)。

## 与方案的偏差

无。

补充两点执行细节(均在 plan 授权范围内,不构成偏差):

1. **模板克隆路径**:`$TPL` 取
   `/tmp/claude-1000/-home-rabbir-Projects-dopilot/c710bc7e-e506-4ef8-a504-c70181b8a2f7/scratchpad/tpl`
   (会话 scratchpad 内的独立克隆),与 plan「不加模板 remote、不 fetch 模板
   tag」一致;该路径已随 `tc01`/`tc08` 的原始输出留证。
2. **TC-07 的执行时点**:改动集快照在本实现记录写入**之后**重跑,因此其
   `git status` 输出包含 `implementation-round-01.md` 与
   `tc07-changeset.txt` 自身,均属任务目录产物,不影响集合相等断言。
