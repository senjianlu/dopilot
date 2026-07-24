---
task: adopt-ai-workflow-template
round: 02
date: 2026-07-24
---

# 实现记录:第 02 轮

## 本轮改动

本轮不改仓库源码/文档(第 01 轮交付物原样不动),仅补齐任务产物与证据:

| 文件 | 改动摘要 |
|---|---|
| `plan.md`(新增) | 追认性 plan(用户裁决 R-01 处置,2026-07-24):背景/范围/方案/逐项测试档位/风险;frontmatter 标注 `retroactive: true`,`approved` 对应用户对该处置的明确确认 |
| `evidence/link-check-round02.py`、`evidence/stale-refs-check-round02.sh`(新增) | TC-01 / TC-03 的完整可复跑脚本(消除第 01 轮证据中的占位命令) |
| `evidence/tc01–tc07-*-round02.txt`(新增 7 份) | 全部用例的 A 档证据:完整字面命令 + 完整 stdout/stderr + 退出码;第 01 轮旧证据文件按"历史只增不改"原样保留,以本轮 round02 系列为准 |
| `implementation-round-02.md`(本文) | 修复对照与测试结果 |

环境侧(非仓库文件):为执行 TC-06/TC-07,本轮在环境中 editable 安装了
`packages/protocol`、`apps/server[dev]`、`apps/agent[dev]` 并补装
scrapy/ruff(见 tc04 证据的 `pip list` 节)。

## 修复对照

| 评审问题编号 | 严重度 | 修复方式 |
|---|---|---|
| R-01 | plan-blocker | **用户裁决:补追认性 plan**(2026-07-24)。已补 `plan.md`,如实标注追认性质,逐项声明测试档位与证据形态;不伪称先于实现存在 |
| R-02 | blocker | 证据全部重制为 round02 系列:TC-01/TC-03 的脚本本体落盘 `evidence/`(link-check-round02.py / stale-refs-check-round02.sh),证据 txt 记录完整字面命令、完整输出与逐条退出码;TC-05 改为逐脚本 `bash -n` + 明确 `ls -l` 参数,均带退出码 |
| R-03 | major | **用户裁决:不修,按模板保持现状**(2026-07-24)。Bash 写入绕过是模板 README「已知限制」明文记载的设计取舍(纪律靠 CLAUDE.md 硬规则);"活动任务缺 plan 时放行"同属模板 gate-plan.sh 原样行为。用户已定"以 ai-workflow-template 为准",不做本地偏离;残留风险已记入 plan.md「风险与回滚」第 3 条,后续如需加固另起任务并新增 docs/decisions/ 记录 |
| R-04 | major | **用户裁决:不修,按模板保持现状**(2026-07-24)。整目录排除 `.claude/` 是模板 review.sh 头部注释明文说明的有意设计(评审期间 Claude Code 会并发写 settings.local.json,纳入指纹会误判隔离失败)。同上,不做本地偏离,风险留痕同 R-03 |

> R-03/R-04 按 rawf-review skill 第 4 条处理:评审意见未被"解释掉",
> 已原样呈交用户裁决,用户明确选择"按模板保持现状",本记录如实注明。

## 测试结果

| 编号 | 档位 | 结果 | 证据 |
|---|---|---|---|
| TC-01 相对链接全通 | A | pass | evidence/tc01-link-check-round02.txt(脚本:evidence/link-check-round02.py) |
| TC-02 py_compile 全通 | A | pass | evidence/tc02-py-compile-round02.txt |
| TC-03 无现行死引用(白名单外) | A | pass | evidence/tc03-stale-refs-round02.txt(脚本:evidence/stale-refs-check-round02.sh) |
| TC-04 改动集清单 + hooks/CLI/工具就绪 | A | pass | evidence/tc04-changeset-hooks-round02.txt |
| TC-05 工作流脚本 bash -n + 可执行位 | A | pass | evidence/tc05-workflow-scripts-round02.txt |
| TC-06 pytest 全量(535 passed) | A | pass | evidence/tc06-pytest-round02.txt |
| TC-07 ruff check apps packages | A | pass | evidence/tc07-ruff-round02.txt |

## 与方案的偏差

- 第 01 轮"环境未装 pytest/ruff、以 py_compile 代跑"的表述已作废:本轮
  补装依赖后全量执行了 pytest(535 passed)与 ruff(All checks passed),
  见 TC-06/TC-07。plan.md 的用例表与说明已同步(plan 允许在轮次间修订,
  轮次记录不改)。
- 首跑 pytest 曾有 1 例失败(`test_builtin_artifacts` 需 `scrapy` 包),
  属环境缺包而非代码问题;`pip install scrapy` 后复跑通过,最终全量
  证据(tc06)为 535 passed、退出码 0。
- 其余无偏差:仓库改动集与 plan「改动范围」一致,本轮未新增任何仓库
  源码/文档改动。
