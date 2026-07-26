---
task: fix-evidence-script-text-bugs
round: 02
date: 2026-07-26
---

# 实现记录:第 02 轮

## 本轮改动

只修 `review-round-01-pass.md` 的 minor R-01(用户 2026-07-26 明确要求本轮
修),改动全部落在本任务新建的 `evidence/scan-other-scripts.sh` 内;**未触碰
两个被修脚本、两个来源任务的任何文件、以及其它用例脚本**。

| 文件 | 改动摘要 |
|---|---|
| `.ai/2026-07-26/fix-evidence-script-text-bugs/evidence/scan-other-scripts.sh` | ① `report()` 改为**逐文件输出结论**:每个参与扫描的文件都打一行 `OK` 或 `HIT`(命中时另附行号与原文并标注命中行数);② 计数拆成**命中文件数**与**命中行数**两个维度并各自标明单位,替换原先按文件数累加却称"处"的写法;③ 每个模式末尾打小计,结论段打印"参与扫描 N 个文件 × 3 个模式" |
| `evidence/tc04-scan-other-scripts.txt` | 按修改后的脚本重新生成(82 行,含 18 文件 × 3 模式的逐条结论) |
| `evidence/tc01/tc02/tc03-*.txt` | 重跑取一致快照(逻辑未变,结论与第 01 轮相同) |

## 修复对照

| 评审问题编号 | 严重度 | 修复方式 |
|---|---|---|
| R-01 | minor | 评审指出两点:① `plan.md:107` 要求 TC-04「逐文件列出扫描结论」,而 `scan-other-scripts.sh:72-80` 只输出命中项或汇总"无命中",证据中无法确认实际扫的 18 个文件分别是哪些——**这是对已确认方案的偏离**,且"无命中"与"根本没扫到"在证据上不可区分;② `hits` 按命中**文件数**累加却在文案中称"处",单位不符。修法:`report()` 逐文件打 `OK`/`HIT`(命中附行号原文与行数),计数拆为 `hit_files` / `hit_lines` 两个变量并分别以"个文件"/"行"表述,结论段显式打印参与扫描的文件数与模式数。重跑后 `tc04-scan-other-scripts.txt` 由 22 行增至 82 行,18 个文件在每个模式下的结论均可逐条核对 |

## 测试结果

| 编号 | 档位 | 结果 | 证据 |
|---|---|---|---|
| TC-01 | A | pass | `evidence/tc01-utf8-check.txt`(exit=0)。`decision-doc-check.sh` 自身 exit=0;全部输出通过 iconv UTF-8 校验;D-1(123 字符)、D-2(121)、D-3(65)、D-4(104)、D-5(175)与 `0020` 源文件逐字符一致 |
| TC-02 | A | pass | `evidence/tc02-reverse-selfcheck-rerun.txt`(exit=0)。`SyntaxError`/`Traceback` 0 次;步骤顺序清单实际打印(base 9 步 + app 6 步);旧顺序副本 4 条违例、当前版本 PASS |
| TC-03 | A | pass | `evidence/tc03-regression-selfcheck.txt`(exit=0)。回退 A 重现坏字节(iconv 校验失败),回退 B 重现 `SyntaxError` |
| TC-04 | A | pass | `evidence/tc04-scan-other-scripts.txt`(exit=0)。**逐文件结论已补齐**:排除 2 个自指文件后扫描 18 个,3 个模式各列出 18 行 `OK`;每模式小计"命中 0 个文件 / 0 行(共扫描 18 个文件)";结论段"参与扫描:18 个文件 × 3 个模式,命中:0 个文件 / 0 行" |
| TC-05 | A | pass | `evidence/tc05-changeset.txt`(exit=0)。源文件改动集恰好 2 个脚本;**专项断言通过**:两份历史证据未被改动(status + diff 双保险);两个来源任务的 plan/轮次记录/summary 零改动;`apps/`、`docs/`、`.github/`、`.ai-workflow/`、`.claude/` 等零改动 |

无 `blocked` 项,无 `fail` 项;档位未做任何下调(5 条全 A 档,C 档 0 条)。

## 与方案的偏差

无。

说明:本轮修的是**第 01 轮对方案的偏离**(TC-04 未按 `plan.md:107` 逐文件
列出),修完后实现与已确认方案一致。改动仅限本任务新建的扫描器,未扩大范围。
