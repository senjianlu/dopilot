---
task: align-ai-workflow-template-v1
round: 02
date: 2026-07-26
---

# 实现记录:第 02 轮

## 本轮改动

只修 `review-round-01-fail.md` 的两个 major,均落在
`evidence/baseline-check.sh`(TC-01 的核验脚本)内;**未触碰任何受管文件、
决策文档与其它用例脚本**。

| 文件 | 改动摘要 |
|---|---|
| `.ai/2026-07-26/align-ai-workflow-template-v1/evidence/baseline-check.sh` | ① 逐路径输出改为**完整 64 位 SHA-256**(原为 `${sha:0:16}` 截断),模板侧与 dopilot 侧各占一行;② 新增 `check_review_standards()` 函数,把 D-1 的弱断言换成**逐字节相等**断言,预期块从模板 diff 现算;③ 新增 `softbad()` 与 `CRS_SILENT` 开关,使反向自检可复用同一检测函数而不污染全局 `fail`;④ 新增第 5 节反向自检(两份伪造样本),原「计数汇总」顺延为第 6 节 |
| `evidence/tc01-baseline-check.txt` | 按修复后的脚本重新生成 |
| `evidence/tc02/03/04/05/06/08-*.txt` | 重跑取一致快照(逻辑未变,结论与上一轮相同) |

## 修复对照

| 评审问题编号 | 严重度 | 修复方式 |
|---|---|---|
| R-01 | major | `baseline-check.sh` 第 3 节的打印从 `printf '%-46s tpl=%s loc=%s' "$p" "${tsha:0:16}" "${lsha:0:16}"` 改为分行输出 `tpl-sha256=<64 位>` / `loc-sha256=<64 位>`。内部比较本就用完整哈希,本次兑现的是**落盘证据的可审计性**:`tc01-baseline-check.txt` 现逐路径内联双方完整 SHA-256,评审可离线对照公开 tag 复核。已重新生成 TC-01 原始证据。 |
| R-02 | major | 旧逻辑只校验"删除 4 行 + 其中任一行含 Scrapy",删 1 行 Scrapy 加 3 行其它标准会误通过。新增 `check_review_standards()`:预期块**从模板现算**(`git diff 48a435a v1.0.0 -- review-standards.md` 的新增行),与 dopilot 侧实际被删块用 `cmp` 做**逐字节相等**断言,并保留"不得有新增行"。预期块不写死在脚本里——写死等于期望与事实都由实现者掌握,现算才能证明删掉的确实是模板加的那一块。同时按评审要求补第 5 节**反向自检**:伪造 A(删 1 行 Scrapy + 3 行其它标准)、伪造 B(删掉整块 4 行但把其中 1 行改写后留在原处)均必须被拒,实测两者都被拒。 |

## 测试结果

| 编号 | 档位 | 结果 | 证据 |
|---|---|---|---|
| TC-01 | A | pass | `evidence/tc01-baseline-check.txt`(exit=0)。逐路径**完整 SHA-256** 双行输出(如 `review-standards.md`:tpl=`5090431c…7e1c` / loc=`c2c094e7…c80a5`);D-1 断言显示"新增行=0 删除行=4 模板新增块行数=4",并逐行打印预期块与实际被删块后判定**逐字节相等**;第 5 节反向自检伪造 A、伪造 B 均被拒;汇总 IDENTICAL=19 / EXPECTED-DIFF=2 / EXPECTED-ABSENT=1 / UNEXPECTED-*=0 |
| TC-02 | A | pass | `evidence/tc02-template-version.txt`(exit=0)。6 项断言全 PASS;反向自检 `adopted: 2026-07-24` 被拒 |
| TC-03 | A | pass | `evidence/tc03-scrapy-absence.txt`(exit=0)。三处同时 ABSENT;注入残留两项均被检出 |
| TC-04 | A | pass | `evidence/tc04-round-caps.txt`。① 输出 `15`、exit=0;② 三份伪造 plan(空 / `abc` / `0`)均 exit=3 且 stderr 为"…非法(须为正整数,实际为:…)" |
| TC-05 | A | pass | `evidence/tc05-decision-docs.txt`(exit=0)。四段齐备、D-1…D-5 全在、索引与交叉引用一致、0018 未被标记取代 |
| TC-06 | A | pass | `evidence/tc06-link-check.txt`(exit=0)。22 个相对链接,BROKEN=0 |
| TC-07 | A | pass | `evidence/tc07-changeset.txt`(exit=0)。受管/文档改动集与 plan 声明清单集合相等(恰好 4 个);无越界改动;十个"明确不动"目录与七个根文件零改动 |
| TC-08 | A | pass | `evidence/tc08-manual-merge.txt`。正向 exit=0(10 条 hunk 集合相等、disposition 全部核实、CLAUDE.md 偏离恰为 D-2、AGENTS.md 5 个章节全在、`.agents`/`skills-lock.json` no-op 属实);反向自检 exit=1(台账删一行后报 `MISSING-IN-LEDGER`) |

无 `blocked` 项,无 `fail` 项;档位未做任何下调(8 条全 A 档,C 档 0 条)。

## 与方案的偏差

无。

两点说明(不构成偏差):

1. **反向自检伪造 B 的失败原因已按实测校正**:初稿标签写作"被删块中 1 行
   被改写",实测该构造会同时触发"有新增行"与"逐字节不等"两条断言
   (`diff` 显示 `112,115c112`,即 4 删 1 增),标签已改为
   "删掉整块 4 行,但把其中 1 行改写后留在原处 —— 应同时触发有新增行与
   逐字节不等",与证据输出一致,不做美化。
2. **本轮重跑了 TC-02…TC-06、TC-08**:这些用例的输入与逻辑均未改动,重跑
   只为让 8 份证据同属一次一致快照,结论与第 01 轮相同。TC-07 在本记录
   写入后最后执行,故其 `git status` 快照包含本文件。
