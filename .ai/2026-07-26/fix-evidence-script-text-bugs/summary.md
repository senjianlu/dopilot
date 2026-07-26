---
task: fix-evidence-script-text-bugs
date: 2026-07-26
rounds: 3
verdict: pass
---


# 任务小结:修复两个已关闭任务遗留的 evidence 脚本文本处理瑕疵

## 起因

前两个任务各遗留一个评审 minor,都属"脚本处理文本的方式不对",当时确认
不影响断言有效性、随任务提交未修。用户 2026-07-26 要求专门开任务修掉,并
裁决**只修脚本、不重新生成历史证据**。

## 改动

| 文件 | 摘要 |
|---|---|
| `.ai/2026-07-26/align-ai-workflow-template-v1/evidence/decision-doc-check.sh` | 去掉 `| cut -c1-100`,D-1…D-5 整行打印;加注释说明 `cut -c` 与 `mawk substr` 均按字节切 |
| `.ai/2026-07-26/ci-docker-login-before-buildx/evidence/reverse-selfcheck.sh` | 内联 python 的标签先赋 `label` 局部变量再进 f-string,消除表达式内反斜杠 |
| `.ai/2026-07-26/fix-evidence-script-text-bugs/evidence/` | 4 个核验脚本(`utf8-check.sh`、`regression-selfcheck.sh`、`scan-other-scripts.sh`、`changeset-check.sh`)+ 5 条用例原始输出 |

### 关键技术判断(均经实测,非推断)

- `cut -c` 在 GNU coreutils 下**按字节切**,与 locale 无关(本机
  `LANG=zh_CN.UTF-8` 仍复现);对 0020 的 D-1 行(127 字符 / 187 字节)输出
  非法 UTF-8。
- **`awk substr` 不是安全替代**:本机 `awk` 为 `mawk 1.3.4`,同样按字节切,
  实测输出同样非法。这是原本设想的"标准修法",被实测否掉。
- 故缺陷 1 选择**取消截断**而非替换截断实现:纯 bash 下唯一 locale 安全的
  截断需引入 `python3`,为观感加依赖不划算;证据文件不受宽度约束,整行打印
  更利复核,并消除整类 locale 不确定性。

## 历史证据未被触碰(用户裁决,已机器化)

`tc05-decision-docs.txt` 与 `tc03-reverse-selfcheck.txt` 保持原样——它们记录
的是当时评审实际看到的内容,重生成会让其不再对应已提交的评审结论(AGENTS.md:
`.ai/` 是过程痕迹)。TC-05 以 `git status` + `git diff` 双保险专项断言这两份
文件未被改动;两个来源任务的 plan / 轮次记录 / summary 亦零改动。

**因此旧证据中仍保留那段坏字节与那段 traceback,这是预期状态、不是遗漏。**

## 评审历程

| 轮次 | 结论 | 关键问题 |
|---|---|---|
| impl-01 | pass | 无 blocker / 无 major;1 minor:TC-04 未按 `plan.md:107` 逐文件列出扫描结论,且 `hits` 按文件数累加却称"处" |
| impl-02 | fail | 1 major:**本文件(summary.md)陈旧**——第 01 轮汇报时写就,用户随后要求"本轮修" minor 并已完成第 02 轮,但 summary 仍记 `rounds: 1`、只列 impl-01、把 R-01 标为"待用户裁决",与 `implementation-round-02.md` 直接矛盾 |
| impl-03 | **pass** | 修 impl-02 的 major(更新本文件)。评审问题清单**为空**——无 blocker / major / minor |

本任务触及源文件 2 个(≤10),未触发 plan 阶段 Codex 评审闸;用户未要求放宽
轮次,按默认上限 3,实际用满 3 轮。

第 02 轮的 major 值得记一笔:它暴露的不是脚本缺陷,而是**流程缺陷**——
汇报产物在"评审通过 → 用户追加要求 → 再开修复轮"这条路径上会变陈旧,而
summary.md 是任务的最终记录,陈旧即错误。此后凡在汇报后又开新轮,须同步
回改 summary.md。

## 测试

5 条用例全 A 档、C 档 0 条,全部 pass(exit=0)。

自测中发现并修掉一个**真问题**:TC-04 扫描器初版报 5 处命中,逐条核对全是
误报(注释行、扫描器自身模式串、回退脚本的注入字符串)。降噪后仍剩 1 处
`template-version-check.sh:19`——那是 **bash 行而非 Python**;根因是
`awk -v pat=` 赋值会对值做转义处理,`\\"` 被吃成 `"`,模式 3 退化为
`f"[^"]*{[^}]*"`,匹配的不是它声称要找的东西。改为三个**字面 awk 程序**后,
以阳性样本(修复前那行)与阴性样本(那行 bash)实测:该中的中、不该中的
不中。最终 18 个受扫文件三种模式**均无命中**。

## 各轮问题及处置

| 编号 | 内容 | 处置 |
|---|---|---|
| impl-01 R-01(minor) | plan(`plan.md:107`)要求 TC-04「逐文件列出扫描结论」,但 `scan-other-scripts.sh` 只输出命中项或汇总「无命中」,证据中无法确认实际扫的 18 个文件分别是哪些——**"扫了但没命中"与"根本没扫到"在证据上不可区分**;另 `hits` 按命中**文件数**累加却称「处」,单位不符 | **已修**(用户 2026-07-26 要求本轮修,第 02 轮完成):`report()` 逐文件打 `OK`/`HIT`(命中附行号原文与行数),计数拆为 `hit_files` / `hit_lines` 并分别标单位,结论段显式打印参与扫描的文件数 × 模式数。`tc04-scan-other-scripts.txt` 由 22 行增至 82 行 |
| impl-02 R-01(major) | 本 summary.md 陈旧,与第 02 轮事实矛盾(详见上方评审历程) | **已修**(第 03 轮完成):`rounds` 改为 3,评审历程补齐 impl-01/02/03 三行,R-01 由「待用户裁决」改为「已修」,并记录该流程缺陷的教训 |

**无遗留项**:impl-01 的 minor 与 impl-02 的 major 均已修复,第 03 轮评审
问题清单为空。
