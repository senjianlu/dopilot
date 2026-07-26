---
task: fix-evidence-script-text-bugs
round: 01
date: 2026-07-26
---

# 实现记录:第 01 轮

## 本轮改动

按 plan 实现。源文件改动 2 个,均为文本处理写法调整。

| 文件 | 改动摘要 |
|---|---|
| `.ai/2026-07-26/align-ai-workflow-template-v1/evidence/decision-doc-check.sh` | 第 30 行去掉 `| cut -c1-100`,D-1…D-5 整行打印;上方加注释说明 `cut -c` 与 `mawk substr` 均按字节切、纯 bash 下无 locale 安全的截断手段 |
| `.ai/2026-07-26/ci-docker-login-before-buildx/evidence/reverse-selfcheck.sh` | 内联 python 的 `s.get(\"name\", s.get(\"uses\"))` 改为先 `label = s.get("name") or s.get("uses")` 再 `print(f"… {label}")`,消除 f-string 内反斜杠;加注释说明成因 |
| `.ai/2026-07-26/fix-evidence-script-text-bugs/evidence/utf8-check.sh` | 新增。TC-01:重跑 decision-doc-check.sh,iconv 校验全部输出 + D-1…D-5 逐行与 0020 源文件比对 |
| `…/evidence/regression-selfcheck.sh` | 新增。TC-03:自造两份"打回原样"的带 bug 副本,断言两个缺陷必然重现 |
| `…/evidence/scan-other-scripts.sh` | 新增。TC-04:扫描其余 evidence 脚本的同类模式,只报告不修 |
| `…/evidence/changeset-check.sh` | 新增。TC-05:改动集集合相等 + **历史证据未被重生成**的专项断言 |
| `…/evidence/tc0{1..5}-*.txt` | 5 条用例的完整原始输出 |

### 自测中发现并修掉的一个真问题(TC-04 扫描器)

`scan-other-scripts.sh` 初版用 `awk -v pat="$2"` 传动态正则,首次运行报出
**5 处命中**,逐条核对后**全部是误报**:命中的是注释行、扫描器自身的模式串、
以及回退脚本里刻意注入 bug 的字符串常量。做了两轮加固:

1. **降噪**:剔除注释行;显式排除两个"按设计必须包含这些模式串"的文件
   (扫描器自身、回退副本生成器),排除项逐个打印、不静默。
2. **修正则转义 bug**(更要紧):降噪后仍剩 1 处命中——
   `template-version-check.sh:19` 的 `[ -f "$f" ] || { echo "…" }`,那是
   **bash 行、不是 Python**。根因是 `awk -v` 赋值会对值做转义处理,
   `\\"` 被吃成 `"`,模式 3 实际退化为 `f"[^"]*{[^}]*"`,匹配的根本不是它
   声称要找的东西。改为三个**字面 awk 程序**(不走动态正则),模式 3 用
   `/f"/ && index($0, "\\\"") > 0`。

   修正后用阳阴两个样本实测:阳性(修复前那行真正的 f-string 反斜杠)命中;
   阴性(被误报的那行 bash)不再命中。最终扫描结果:其余 18 个脚本三种模式
   **均无命中**。

## 修复对照

不适用(第 1 轮,无上一轮评审问题)。

> 本任务触及源文件 2 个(≤10),按 CLAUDE.md 未触发 plan 阶段 Codex 评审闸;
> 用户未要求放宽轮次,两个上限字段均未写入 frontmatter,按默认 3 轮。

## 测试结果

| 编号 | 档位 | 结果 | 证据 |
|---|---|---|---|
| TC-01 | A | pass | `evidence/tc01-utf8-check.txt`(exit=0)。`decision-doc-check.sh` 自身仍 exit=0(断言逻辑未被改坏);全部输出通过 `iconv -f UTF-8 -t UTF-8` 校验;D-1(123 字符)、D-2(121)、D-3(65)、D-4(104)、D-5(175)五行均与 `0020` 源文件**逐字符一致**,证明未被任何形式截断 |
| TC-02 | A | pass | `evidence/tc02-reverse-selfcheck-rerun.txt`(exit=0)。完整重跑 `reverse-selfcheck.sh`:`SyntaxError`/`Traceback` 出现次数 **0**;第 1 节"副本中两个 job 的步骤顺序"清单**实际打印**(base 9 步 + app 6 步);核心断言仍成立——旧顺序副本给出 4 条顺序违例、当前版本 PASS |
| TC-03 | A | pass | `evidence/tc03-regression-selfcheck.txt`(exit=0)。回退 A(恢复 `cut -c1-100`)的输出 **iconv 校验失败**,坏字节重现;回退 B(恢复 f-string 反斜杠)**重现 SyntaxError**。两者证明 TC-01/TC-02 的检测确实在测这两个 bug,非恒真通过 |
| TC-04 | A | pass | `evidence/tc04-scan-other-scripts.txt`(exit=0)。发现 20 个 evidence 脚本,显式排除 2 个自指文件后扫描 18 个:模式 1(`cut -c/-b`)、模式 2(`substr(`)、模式 3(f-string 反斜杠)**均无命中**;已修的两个文件复核亦无命中。**无需交用户决定的后续项** |
| TC-05 | A | pass | `evidence/tc05-changeset.txt`(exit=0)。源文件改动集**恰好** = 2 个脚本;**专项断言通过**:`tc05-decision-docs.txt` 与 `tc03-reverse-selfcheck.txt` 均未被改动(`git status` 无该项 + `git diff` 为空双保险);两个来源任务的 plan/轮次记录/summary 零改动;`apps/`、`docs/`、`.github/`、`.ai-workflow/`、`.claude/` 等零改动 |

无 `blocked` 项,无 `fail` 项;档位未做任何下调(5 条全 A 档,C 档 0 条)。

## 与方案的偏差

无。

一点说明(不构成偏差):plan 的 TC-04 预期里写了"若扫出其它文件命中,记入
实现记录并交用户决定"。实测**无命中**,故无待决项——该分支未被触发,不是
被跳过。扫描器本身在自测中经历了两轮加固(见上),加固对象是本任务新建的
测试工具、不是被测的两个脚本,未扩大改动范围。
