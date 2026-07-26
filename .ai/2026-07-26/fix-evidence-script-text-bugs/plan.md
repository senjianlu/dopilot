---
status: approved
task: fix-evidence-script-text-bugs
date: 2026-07-26
approved_at: 2026-07-26 18:25:46+0900
---

# 方案:修复两个已关闭任务遗留的 evidence 脚本文本处理瑕疵

## 背景与目标

前两个任务各遗留一个 minor,都属"脚本处理文本的方式不对",评审均确认
**不影响断言有效性**,故当时随任务提交、未修:

| 来源任务 | 位置 | 缺陷 |
|---|---|---|
| `align-ai-workflow-template-v1`(评审 impl-03 R-01) | `evidence/decision-doc-check.sh:30` | `cut -c1-100` 按**字节**截断中文,输出里留下不完整 UTF-8 字节 |
| `ci-docker-login-before-buildx`(评审 impl-01 R-01) | `evidence/reverse-selfcheck.sh:53` | `python3 -c '…'` 单引号串中的 `\"` 原样传入 Python,f-string 表达式内不允许反斜杠 → `SyntaxError`,辅助打印整段没输出 |

### 已实测确认的事实(非推断)

- `cut -c1-100` 对 `0020` 的 D-1 行(127 字符 / 187 字节)输出**非法 UTF-8**
  (`iconv -f UTF-8 -t UTF-8` 校验失败);GNU coreutils 的 `cut -c` 实际按
  字节切,与 locale 无关(本机 `LANG=zh_CN.UTF-8` 仍复现)。
- **`awk substr` 不是安全替代**:本机 `awk` 是 `mawk 1.3.4`,同样按字节切,
  实测输出同样非法 UTF-8(截出 81 "字符")。故不能用 awk 换掉 cut。
- 缺陷 2 的修法(把标签先赋给局部变量再放进 f-string)已实测跑通,正确
  打印两个 job 的全部步骤。

### 目标与边界

修好这两个脚本,使其可被后来者安全复用。

**明确不重新生成历史证据**(用户 2026-07-26 裁决):`tc05-decision-docs.txt`
与 `tc03-reverse-selfcheck.txt` 保持原样。理由——AGENTS.md 规定 `.ai/` 是
过程痕迹;这两份输出记录的是**当时评审实际看到的内容**,重生成会让它们不再
对应已提交的评审结论。脚本是工具,可向前修;输出是记录,不改。因此修完之后,
旧证据里仍会保留那段坏字节与那段 traceback,这是**预期状态,不是遗漏**。

## 改动范围

### 改动的文件(2 个)

| # | 文件 | 动作 |
|---|---|---|
| 1 | `.ai/2026-07-26/align-ai-workflow-template-v1/evidence/decision-doc-check.sh` | 第 30 行去掉 `| cut -c1-100`,整行打印;加注释说明为何不用 `cut -c` / `awk substr` |
| 2 | `.ai/2026-07-26/ci-docker-login-before-buildx/evidence/reverse-selfcheck.sh` | 第 45-54 行的内联 python:`s.get(\"name\", s.get(\"uses\"))` 改为先 `label = s.get("name") or s.get("uses")` 再 `print(f"… {label}")`,消除 f-string 内反斜杠 |

**缺陷 1 取消截断而非替换截断实现的理由**:该脚本是纯 bash,唯一 locale
安全的截断手段是引入 `python3`(`cut -c`/`mawk substr` 均按字节);为纯观感
给一个 bash 脚本加 python3 依赖不划算。而截断本身没有价值——证据文件不受
宽度约束,打印完整行反而更利于复核。取消截断同时消除了整类 locale 相关的
不确定性。

### 明确不动

- **不重新生成任何历史证据文件**(见上,用户裁决)。
- **不动两个来源任务的其它文件**:plan.md、implementation-round-*.md、
  review-round-*.md、summary.md 一律不碰——它们是轮次记录,受"只增不改"
  约束。
- **不动其余 evidence 脚本**:`baseline-check.sh`、`manual-merge-check.sh`、
  `template-version-check.sh`、`scrapy-absence-check.sh`、`changeset-check.sh`、
  `pure-reorder-check.sh`、`step-order-check.py`、`env-scope-check.sh`、
  `link-check.py` 均不在本次范围;若它们也有同类问题,由 TC-04 扫出来后
  另行决定,本次只报告不顺手改。
- **不动任何应用代码与工作流控制文件**:`apps/`、`packages/`、`deploy/`、
  `configs/`、`scripts/`、`examples/`、`tests/`、`docs/`、`.github/`、
  `.ai-workflow/`、`.claude/` 零改动。
- **不加 docs/decisions 记录**:两处均为脚本缺陷修复,未改变架构或推翻既有
  决策。

## 实现方案

### 缺陷 1:`decision-doc-check.sh`

```bash
# 改前
    grep -m1 "| $d |" "$D20" | cut -c1-100 | sed 's/^/    /'
# 改后(整行打印;上方加注释说明 cut -c 与 mawk substr 均按字节切)
    grep -m1 "| $d |" "$D20" | sed 's/^/    /'
```

### 缺陷 2:`reverse-selfcheck.sh`

```python
# 改前(f-string 表达式内有反斜杠 → SyntaxError)
        print(f"      [{i}] {s.get(\"name\", s.get(\"uses\"))}")
# 改后
        label = s.get("name") or s.get("uses")
        print(f"      [{i}] {label}")
```

两处改动均已在 scratchpad 实测:改后 `decision-doc-check.sh` 的 D 行输出通过
`iconv` UTF-8 校验;改后的内联 python 正确打印两个 job 共 15 个步骤。

## 测试用例

**执行环境**:所有用例 cwd 为仓库根 `/home/rabbir/Projects/dopilot`,路径均为
仓库根相对路径;留证命令统一为
`<命令> > <证据文件> 2>&1; echo "exit=$?" >> <证据文件>`。

| 编号 | 档位 | 前置条件 | 步骤(cwd=仓库根) | 预期结果 | 证据形态 |
|---|---|---|---|---|---|
| TC-01 | A | 缺陷 1 已修 | `bash .ai/2026-07-26/fix-evidence-script-text-bugs/evidence/utf8-check.sh` —— 重跑 `decision-doc-check.sh` 并把其**全部输出**喂给 `iconv -f UTF-8 -t UTF-8`,断言无非法字节;同时断言 D-1…D-5 五行均被完整打印(每行末尾字符与源文件该行末尾一致,证明没被截断) | 退出码 0;iconv 校验通过;5 行逐行比对与 `0020` 源文件一致;并打印 `decision-doc-check.sh` 自身退出码 0(功能未被改坏) | 命令 + 完整输出 + 退出码 → `evidence/tc01-utf8-check.txt`;脚本 `evidence/utf8-check.sh` |
| TC-02 | A | 缺陷 2 已修 | `bash .ai/2026-07-26/ci-docker-login-before-buildx/evidence/reverse-selfcheck.sh` —— 完整重跑该反向自检脚本 | 退出码 0;输出中**不再出现** `SyntaxError` / `Traceback`;第 1 节的"副本中两个 job 的步骤顺序"清单**实际打印出来**(base 9 步 + app 6 步);核心断言仍为:旧顺序副本给出 4 条顺序违例、当前版本 PASS | 命令 + 完整输出 + 退出码 → `evidence/tc02-reverse-selfcheck-rerun.txt` |
| TC-03 | A | 两处均已修 | **异常/反向路径**:`bash .ai/2026-07-26/fix-evidence-script-text-bugs/evidence/regression-selfcheck.sh` —— 脚本自己在 scratchpad 造两份**打回原样**的副本(一份恢复 `cut -c1-100`,一份恢复 f-string 反斜杠),分别运行并断言:前者输出**必然** iconv 校验失败,后者**必然**出现 `SyntaxError` | 退出码 0;两份回退副本都被检出对应缺陷(证明 TC-01/TC-02 的检测不是恒真通过,确实在测这两个 bug) | 命令 + 完整输出 + 退出码 → `evidence/tc03-regression-selfcheck.txt`;脚本 `evidence/regression-selfcheck.sh` |
| TC-04 | A | 两处均已修 | `bash .ai/2026-07-26/fix-evidence-script-text-bugs/evidence/scan-other-scripts.sh` —— 扫描 `.ai/**/evidence/` 下**其余全部**脚本,报告是否还有 `cut -c`、`cut -b`、`mawk`-不安全的 `substr`、或 f-string 内反斜杠(`\\"` 出现在 `f"` 行)等同类模式 | 退出码 0;逐文件列出扫描结论。**本用例只报告、不修**:若扫出其它文件命中,记入实现记录并交用户决定,不在本任务顺手改(避免污染 diff) | 命令 + 完整输出 + 退出码 → `evidence/tc04-scan-other-scripts.txt`;脚本 `evidence/scan-other-scripts.sh` |
| TC-05 | A | 全部改动已落地,尚未提交 | `bash .ai/2026-07-26/fix-evidence-script-text-bugs/evidence/changeset-check.sh` —— `git status --porcelain --untracked-files=all` 与本方案声明清单做**集合相等**断言 | 退出码 0;改动集**恰好** = 上述 2 个脚本 + 本任务 `.ai/` 目录产物;**两个来源任务的 `tc05-decision-docs.txt` 与 `tc03-reverse-selfcheck.txt` 必须仍为未修改状态**(专项断言,证明"不重生成历史证据"被遵守);`apps/`、`docs/`、`.github/`、`.ai-workflow/`、`.claude/` 等零改动 | 命令 + 完整输出 + 退出码 → `evidence/tc05-changeset.txt` |

档位说明:5 条全 A 档,C 档 0 条(无人工交互项)。非 happy-path 覆盖:
TC-03(回退副本必须重现缺陷)、TC-05(集合相等 + 历史证据未被动的专项断言)。

## 风险与回滚

| 风险 | 说明 | 对策 |
|---|---|---|
| **改脚本时改坏其断言逻辑** | `decision-doc-check.sh` 去掉 cut 可能误伤 grep 管道 | TC-01 断言该脚本自身仍 `exit=0`、5 行 D 记录仍被正确识别 |
| **"顺手"重生成了历史证据** | 与用户裁决相悖,且改写已提交记录 | TC-05 专项断言两份历史证据文件保持未修改状态;`git status` 里出现它们即判 FAIL |
| **同类缺陷在别处仍存在** | 只修两处,其它 evidence 脚本可能同病 | TC-04 全量扫描并报告;**只报不修**,交用户决定,避免本任务 diff 失控 |
| **修法本身不成立** | 例如换用的写法在本机 locale 下仍不安全 | 两处修法均已在 scratchpad 实测通过(iconv 校验 / 实际打印 15 个步骤),非纸面推断;TC-03 再以回退副本反证检测有效 |

**回滚**:两个文件、纯文本处理写法调整,无状态、无依赖变化。回滚 =
`git revert` 该提交。注意回滚后旧脚本的缺陷会一并回来,但由于历史证据从未
被重生成,回滚不会造成记录不一致。
