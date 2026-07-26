---
task: align-ai-workflow-template-v1
date: 2026-07-26
rounds: 3
verdict: pass
---

# 任务小结:对齐 AI 工作流到 ai-workflow-template v1.0.0 并认领版本锚点

## 版本判定结论

本仓库此前采用的是模板 commit `48a435a`(2026-07-20,v1.0.0 之前的未发版
状态)。双证据交叉:① 时间线——dopilot 于 2026-07-24 采用模板(`85f182b`),
该日之前模板的最后一个 commit 即 `48a435a`;② 内容指纹——模板该快照的受管
路径全集 20 个文件,dopilot 侧同名路径不多不少,19 个有内容的文件逐字节
一致。本任务完成对 v1.0.0(`2aeab2eaca28b1364a46ec7cfc9195849cc61b68`)的
全量基线对齐后,正式认领 `version: 1.0.0`。

## 改动

| 文件 | 摘要 |
|---|---|
| `.ai-workflow/TEMPLATE-VERSION` | 新增。版本锚点三字段:`version: 1.0.0` / `source: https://github.com/senjianlu/ai-workflow-template` / `adopted: 2026-07-26`(取完成基线对齐之日,依据模板 README「存量项目迁移」第 3 步) |
| `docs/decisions/0020-ai-workflow-template-version-anchor.md` | 新增决策。含①认领版本锚点、②按模板决策 0007 第 4 条三处联动不采用 Scrapy 标准栈、③后续升级流程(模板独立克隆取 `v$OLD..v$NEW`,不加模板 remote)、④被否备选;影响段含 **D-1…D-5 有意偏离清单** |
| `docs/decisions/README.md` | 索引表追加 0020 一行 |
| `docs/decisions/0018-adopt-ai-workflow-template.md` | 「影响」段追加指向 0020 的交叉引用;未加"已被取代"标记(0020 补充版本维度,未推翻 0018) |
| `.ai/2026-07-26/align-ai-workflow-template-v1/evidence/` | 6 个 bash 核验脚本 + `link-check.py` + 逐 hunk 处置台账 `manual-merge-ledger.tsv` + 8 条用例原始输出 |

**明确未动**:`apps/`、`packages/`、`deploy/`、`configs/`、`scripts/`、
`examples/`、`tests/`、`.github/`、`.githooks/`、`.agents/` 零改动;
`AGENTS.md`、`CLAUDE.md`、`README.md`、`README.zh-CN.md`、`.gitignore`、
`.gitmessage`、`skills-lock.json` 零改动(TC-07 以集合相等断言反向证明)。
本任务零运行时影响。

## 对齐结果

- **可整体替换类**:模板 v1.0.0 侧现算 22 个受管路径 → 19 `IDENTICAL`、
  2 `EXPECTED-DIFF`(`TEMPLATE-VERSION` 的 adopted 行、`review-standards.md`
  的 Scrapy 4 行)、1 `EXPECTED-ABSENT`(`rawf-stack-scrapy/SKILL.md`)、
  0 `UNEXPECTED-*`;双向比对确认 dopilot 侧无多余受管文件。
- **需人工合并类**:模板 `48a435a..v1.0.0` 落在该类路径上的增量共 **10 个
  hunk**(`AGENTS.md` 1 + `README.md` 9),逐条登记处置——1 条
  `divergence:D-3`、3 条 `absorbed:`(锚点已核实存在)、5 条
  `n/a-template-doc`;`CLAUDE.md` 全文比对偏离恰为 D-2;`.agents/skills`
  与 `skills-lock.json` 在 v1.0.0 侧不存在,`no-op` 属实。
- **不采用 Scrapy 标准栈**(用户 2026-07-26 裁决):dopilot 是调度 Scrapy
  项目的平台而非 Scrapy 应用,三处联动删除,登记为 D-1/D-3/D-4。

## 评审历程

| 轮次 | 结论 | 关键问题 |
|---|---|---|
| plan-01 | fail | 3 major:①15 轮上限未记录用户授权来源;②人工合并类只"登记处置"、脚本可在未核对时仍绿;③`adopted` 只校验日期格式,写错日期仍全绿 |
| plan-02 | fail | 2 major:①受管路径计数写错(漏 `.ai-workflow/scripts/.gitkeep`)、`rawf-stack-scrapy` 未归位;②测试命令 cwd 不自洽,6 条 `evidence/…` 命令从仓库根执行会找不到文件 |
| plan-03 | **pass** | 无问题 |
| impl-01 | fail | 2 major:①TC-01 只落盘 16 位 SHA 前缀,未兑现完整 SHA-256 审计契约;②Scrapy 删除块断言过弱("删 4 行 + 任一行含 Scrapy"),删 1 行 Scrapy 加 3 行其它标准会误通过 |
| impl-02 | fail | 1 blocker:TC-08 反向自检搭在脚本外部,证据里是占位命令、canonical 脚本硬编码台账路径且不含自检,无法核验缺行副本如何注入 |
| impl-03 | **pass** | 1 minor(见下) |

plan 阶段评审 3 轮 / 实现层评审 3 轮,两者上限均为 **15**(用户 2026-07-26
明确要求放宽,已写入 plan.md frontmatter 的 `plan_review_max_rounds` /
`impl_fix_max_rounds` 并在 plan「评审轮次授权」节声明)。

## 测试

8 条用例全 A 档、C 档 0 条,全部 pass(exit=0),原始输出落 `evidence/`。
含 5 处反向自检:错误 `adopted` 日期必须被拒、注入 Scrapy 残留必须被检出、
Scrapy 删除块伪造 A/B 必须被拒、台账缺行/多行必须被检出、非法轮次值必须
报错——确保断言不是恒真通过。

## 遗留 minor 及处置

| 编号 | 内容 | 用户决定 |
|---|---|---|
| impl-03 R-01 | `evidence/decision-doc-check.sh:30` 用 `cut -c1-100` 在当前环境按**字节**截断中文,导致 `tc05-decision-docs.txt` 第 11/13/17/19 行出现不完整 UTF-8 字节。评审判定不影响 TC-05 结论(断言本身仍成立),建议取消截断或改用 UTF-8 安全截取并重新生成证据 | **放弃**(用户 2026-07-26 裁决:仅影响证据文本观感,TC-05 断言与结论不受影响,不值得为此再跑一轮完整评审) |
