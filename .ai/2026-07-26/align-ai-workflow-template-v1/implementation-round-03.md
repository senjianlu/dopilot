---
task: align-ai-workflow-template-v1
round: 03
date: 2026-07-26
---

# 实现记录:第 03 轮

## 本轮改动

只修 `review-round-02-fail.md` 的 1 个 blocker,落在
`evidence/manual-merge-check.sh`(TC-08 的核验脚本)内;**未触碰任何受管
文件、决策文档与其它用例脚本**。

| 文件 | 改动摘要 |
|---|---|
| `.ai/2026-07-26/align-ai-workflow-template-v1/evidence/manual-merge-check.sh` | ① 把集合相等断言抽成 `check_ledger_set <台账> [silent]` 函数,台账路径成为**入参**(原先硬编码在脚本头部,外部无法替换);② 新增第 8 节**内置反向自检**:脚本自己生成两份伪造台账到 scratchpad(缺 1 行 / 多 1 行)并各跑一次断言,两者都必须被拒;③ 新增 `softbad()`,使自检可复用同一断言函数而不污染全局 `fail`;④ 生成伪造台账的确切命令以注释写在脚本内,与执行体一一对应 |
| `evidence/tc08-manual-merge.txt` | 按修复后的脚本重新生成:一条 `bash …/manual-merge-check.sh "$TPL"` 即含正反两向完整输出 |
| `evidence/tc01…tc06-*.txt` | 重跑取一致快照(逻辑未变,结论与上一轮相同) |

## 修复对照

| 评审问题编号 | 严重度 | 修复方式 |
|---|---|---|
| R-01 | blocker | 评审指出两点:证据里 TC-08 反向自检写成占位命令 `$ bash <LEDGER 指向缺行副本的同一脚本>`,且 canonical 脚本硬编码台账路径、自身不含该自检,导致"缺行副本如何注入"无法核验。**根因是把自检搭在脚本外部**(`sed` 改写 `LEDGER=` 后另存副本),那条命令链既不在脚本里也没落进证据。修法不是补写命令文本,而是把自检**内置进脚本**:台账改为 `check_ledger_set` 的入参,第 8 节由脚本自己生成伪造台账并断言其被拒。现在 TC-08 的全部内容——正向 10 条 hunk 集合相等、伪造 A(缺行)报 `MISSING-IN-LEDGER`、伪造 B(多行)报 `NOT-IN-TEMPLATE`——都由**同一条可复现命令**产出,`tc08-manual-merge.txt` 中有完整 stdout/stderr 与退出码,无占位符。 |

## 测试结果

| 编号 | 档位 | 结果 | 证据 |
|---|---|---|---|
| TC-01 | A | pass | `evidence/tc01-baseline-check.txt`(exit=0)。逐路径完整 64 位 SHA-256;D-1 逐字节相等断言通过;§5 反向自检伪造 A/B 均被拒;汇总 IDENTICAL=19 / EXPECTED-DIFF=2 / EXPECTED-ABSENT=1 / UNEXPECTED-*=0 |
| TC-02 | A | pass | `evidence/tc02-template-version.txt`(exit=0)。6 项断言全 PASS;反向自检 `adopted: 2026-07-24` 被拒 |
| TC-03 | A | pass | `evidence/tc03-scrapy-absence.txt`(exit=0)。三处同时 ABSENT;注入残留两项均被检出 |
| TC-04 | A | pass | `evidence/tc04-round-caps.txt`。① 输出 `15`、exit=0;② 三份伪造 plan(空 / `abc` / `0`)均 exit=3,stderr 为"…非法(须为正整数,实际为:…)" |
| TC-05 | A | pass | `evidence/tc05-decision-docs.txt`(exit=0,无 FAIL 行)。四段齐备、D-1…D-5 全在、索引与交叉引用一致、0018 未被标记取代 |
| TC-06 | A | pass | `evidence/tc06-link-check.txt`(exit=0)。22 个相对链接,BROKEN=0 |
| TC-07 | A | pass | `evidence/tc07-changeset.txt`(exit=0)。受管/文档改动集与 plan 声明清单集合相等(恰好 4 个);无越界改动;十个"明确不动"目录与七个根文件零改动 |
| TC-08 | A | pass | `evidence/tc08-manual-merge.txt`(exit=0)。**单条命令**产出正反两向:正向 §3 集合相等(台账 10 条)、§4 disposition 全部核实、§5 CLAUDE.md 偏离恰为 D-2、§6 AGENTS.md 5 个章节全在、§7 `.agents`/`skills-lock.json` no-op 属实;§8 伪造 A 报 `MISSING-IN-LEDGER README.md @@ -79,0 +91,37 @@` 被拒,伪造 B 报 `NOT-IN-TEMPLATE README.md @@ -999 +999 @@` 被拒 |

无 `blocked` 项,无 `fail` 项;档位未做任何下调(8 条全 A 档,C 档 0 条)。

## 与方案的偏差

无。

一点说明(不构成偏差):本轮反向自检比 plan 的 TC-08 描述**多覆盖一个方向**。
plan 只要求"删掉台账任一行必须被检出"(缺行);实现中同时加了"多一条模板
中不存在的 hunk 行必须被检出"(台账造假)。两者对应 `check_ledger_set` 的
两个失败分支,补上后集合相等断言的双向性才算被证明,属于加强而非偏离。
