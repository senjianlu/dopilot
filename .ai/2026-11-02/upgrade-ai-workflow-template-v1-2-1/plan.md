---
status: approved
task: upgrade-ai-workflow-template-v1-2-1
date: 2026-11-02
approved_at: 2026-11-02 16:22:49+0900
evidence_format: v1
---

# 方案:把 rawf 工作流从 ai-workflow-template v1.0.0 增量升级到 v1.2.1

## 需求原文

> 这个项目里现在有一些需要优化的建议。
> 但是先不急着改修，先把 ai 工作流更新到最新。
> 然后为这个开源项目制定信息脱敏机制……(脱敏为后续独立任务,见「非目标」)

**本任务交付**:按模板 README「版本与升级」的增量流程,把本仓库受管路径从
v1.0.0 升到模板当前最新发布版 v1.2.1,保留 `docs/decisions/0020` 登记的有意
偏离(D-1~D-5),新增一条偏离 D-6(见下),更新 `TEMPLATE-VERSION` 与 0020 的
升级记录。不改任何应用代码。

## 背景与目标

- 现状:`.ai-workflow/TEMPLATE-VERSION` 记 `version: 1.0.0 / adopted: 2026-07-26`。
  对模板 v1.0.0(`2aeab2eaca28b1364a46ec7cfc9195849cc61b68`)逐文件 sha256 比对,
  本仓库 21 个「可整体替换」类文件中 19 个逐字节一致,仅
  `TEMPLATE-VERSION`(adopted 行)与 `review-standards.md`(D-1:删去 Scrapy 4 行)
  不同,`rawf-stack-scrapy/` 不存在(D-4)——即**无漂移**,可以走纯增量升级。
- 最新版:模板 tag `v1.2.1` = `246db2af223f4279f2ddc3773c5c3171dc8096cc`
  (2026-10-22;本地模板克隆 `~/Projects/ai-workflow-template` 已与 origin 同步,
  另克隆一份到 `/tmp/claude-1000/awt/tpl` 并 `checkout --detach v1.2.1` 作对照物,
  不在本仓库加 remote、不 fetch 模板 tag,遵循 0020 决定 3)。
- `v1.0.0..v1.2.1` 在受管路径上的增量(模板 CHANGELOG 1.0.1 / 1.1.0 / 1.2.0 /
  1.2.1 四个条目):
  - 1.0.1:评审脚本锁 mkdir→flock、codex `--json` 事件流 + 看门狗、stdin 接
    /dev/null(根治本仓库记忆中"后台评审卡 stdin"的问题);gate-review.sh 在评审
    锁被持有时放行;rawf-review/rawf-plan 改为后台启动 + 完成通知唤回;
    `.gitignore` 增两行锁文件。
  - 1.1.0:新增 `evidence.sh`(A 档证据留证器)与 `evidence-check.sh`(评审前机器
    核验);plan 模板必填「需求原文」「非目标」;实现记录偏差分收窄/替代/追加 +
    「停车场」;评审 schema 新增必填 `scope_findings`;CLAUDE.md 硬规则增两条。
  - 1.2.0:plan 评审分轮(1、2 轮全量穷尽,3 轮起收敛)、每轮快照 plan.md、
    默认上限 3→5;`plan-review.sh __minors` 交接入口;CLAUDE.md/AGENTS.md 轮数文案。
  - 1.2.1:review.sh 注入证据报告时关闭 `patsub_replacement`;shellcheck 清零(行为不变)。

## 改动范围

### A. 可整体替换类(从 v1.2.1 快照逐文件拷入覆盖,共 18 个)

| # | 文件 | 动作 |
|---|---|---|
| 1 | `.ai-workflow/TEMPLATE-VERSION` | 拷入后把 adopted 占位行改为 `adopted: 2026-11-02`(version 随模板为 1.2.1) |
| 2 | `.ai-workflow/prompts/plan-review.md` | 覆盖 |
| 3 | `.ai-workflow/prompts/review.md` | 覆盖 |
| 4 | `.ai-workflow/review-standards.md` | 覆盖后**重新施加 D-1**:删去「技术栈评审关注点」小节里 Scrapy 4 行(位于 `<!-- TEMPLATE: 按需删减。 -->` 注释所辖范围) |
| 5 | `.ai-workflow/schemas/plan-review.schema.json` | 覆盖 |
| 6 | `.ai-workflow/schemas/review.schema.json` | 覆盖 |
| 7 | `.ai-workflow/scripts/evidence-check.sh` | 新增(可执行位) |
| 8 | `.ai-workflow/scripts/evidence.sh` | 新增(可执行位) |
| 9 | `.ai-workflow/scripts/plan-review.sh` | 覆盖 |
| 10 | `.ai-workflow/scripts/review.sh` | 覆盖 |
| 11 | `.ai-workflow/templates/implementation-round.md` | 覆盖 |
| 12 | `.ai-workflow/templates/plan.md` | 覆盖 |
| 13 | `.ai-workflow/templates/summary.md` | 覆盖 |
| 14 | `.claude/hooks/gate-review.sh` | 覆盖 |
| 15–18 | `.claude/skills/rawf-{plan,implement,review,report}/SKILL.md` | 覆盖 |

v1.0.0→v1.2.1 未变的受管文件(`gate-plan.sh`、`.claude/settings.json`、
`.githooks/commit-msg`、`.gitmessage`、`scripts/.gitkeep`)不动,由 TC-01 断言仍与
v1.2.1 逐字节一致。

### B. 需人工合并类(按 CHANGELOG 升级指引逐 hunk 处理,共 3 个)

| # | 文件 | 合并内容 |
|---|---|---|
| 19 | `CLAUDE.md` | ① 第 1b 步"默认最多 3 轮"→"默认最多 5 轮(第 1、2 轮全量穷尽、第 3 轮起收敛……)";② 轮次上限硬规则改为"plan 评审 5 轮、实现层修复 3 轮";③ 新增两条硬规则(A 档证据经 evidence.sh;追加类偏差不得自行实现)。模板文案中指向**模板仓库**决策的 `docs/decisions/0012`、`0010`、`0011` 一律改写为"模板决策 00NN"(偏离 D-6,理由同 D-2);D-2 省略的 `0003` 尾注继续省略 |
| 20 | `AGENTS.md` | 通用硬规则中 plan-review"默认最多 3 轮"→"默认最多 5 轮" |
| 21 | `.gitignore` | rawf 块追加 `.ai/**/.review-lock`、`.ai/**/.plan-review-lock` 两行(注释中的 `docs/decisions/0009` 同按 D-6 改写为"模板决策 0009") |

`README.md` / `README.zh-CN.md`、`.agents/skills/`、`skills-lock.json`:按 0020 D-5
不合并(dopilot README 是产品文档,不含工作流机制速览;后两者模板侧本次无变化)。

### C. 文档(共 2 个)

| # | 文件 | 动作 |
|---|---|---|
| 22 | `docs/decisions/0020-ai-workflow-template-version-anchor.md` | 末尾追加「修订」小节:2026-11-02 升至 v1.2.1(增量来源、采用方式);有意偏离表新增 **D-6**;并注明"可整体替换类文件(脚本注释、review-standards.md、skills)中的 `docs/decisions/0005/0009/0010/0011/0012` 指模板仓库决策,为保持可整体替换不做改写"——此为 v1.0.0 起已存在的现象(`review.sh` 注释的 0005),本次只是数量增加,登记以免下次升级被误当成漏改 |
| 23 | `docs/decisions/README.md` | 0020 索引行补"(2026-11-02 升至 v1.2.1)" |

合计触及 23 个文件(>10,走 plan 评审闸)。任务过程产物另计:本目录 plan.md、
implementation-round-NN.md、review-round-NN-*.md、summary.md、`evidence/` 下的
核验脚本与 `TC-NN.log`。

## 非目标

- **信息脱敏机制与 git 历史改写**:用户需求的第二部分,另立 rawf 任务
  (`.ai/2026-11-02/public-repo-redaction` 拟名),本任务不碰任何 `.ai/` 历史
  证据、不改写历史。
- **2026-11-02 的调度熔断改修建议**(`.ai/2026-11-02/transient-failures-permanent-disable/`,
  未跟踪):用户要求后续另行 stash,本任务不读改、不入库。
- 不采用 Scrapy 标准栈(D-1/D-3/D-4 维持);不拷入模板自身产物(CHANGELOG、
  模板 README、模板 docs/decisions、logo、`.codex/`)。
- 不改写可整体替换类文件中指向模板决策编号的注释(理由见 C-22)。
- 不改应用代码、配置、部署文件;不回填历史任务的 plan(历史 plan 无
  `evidence_format: v1`,按模板设计走历史路径)。
- 不改本机记忆;收尾后视情况把"后台评审卡 stdin"记忆标为已由 v1.0.1 修复
  (仓库外操作,不入 diff)。

## 实现方案

1. **锚定对照物**:`/tmp/claude-1000/awt/tpl` 为模板克隆,`git rev-parse v1.2.1`
   必须等于 `246db2af223f4279f2ddc3773c5c3171dc8096cc`、`v1.0.0` 必须等于
   `2aeab2eaca28b1364a46ec7cfc9195849cc61b68`(钉死 SHA,防 tag 漂移)。
2. **A 类拷入**:对 18 个路径执行 `git -C <tpl> show v1.2.1:<path> > <path>`
   (从 tag 对象取内容,不依赖克隆工作区状态),新增的两个脚本 `chmod +x`,
   既有脚本保持 +x。随后:
   - `TEMPLATE-VERSION` 第 3 行替换为 `adopted: 2026-11-02`;
   - `review-standards.md` 删去 Scrapy 关注点的 4 行(内容与 v1.0.0 时删去的
     4 行逐字节相同,TC-01 断言)。
3. **B 类合并**:按上表手工编辑,只动列出的 hunk;dopilot 自有内容(中文
   沟通、docs/ 回写等)原样保留。
4. **C 类文档**:按上表编辑。
5. **核验脚本**(落 `evidence/`,均以 evidence.sh 包住执行,见测试用例):
   - `baseline-check.sh <tpl>`:受管路径集**不手写**,由
     `git ls-tree -r --name-only v1.2.1` 按 CHANGELOG 头部「可整体替换」六条
     glob 现算;逐条比对本仓库文件与 `git show v1.2.1:<path>` 的 sha256;并用同
     一组 glob 反扫本仓库(`git ls-files` + 工作区)找 `UNEXPECTED-EXTRA`。例外
     表只有 3 条:`TEMPLATE-VERSION`(仅第 3 行不同且整行等于
     `adopted: 2026-11-02`)、`review-standards.md`(diff 只有删除、恰为 v1.0.0
     时 D-1 删去的同一 4 行块)、`rawf-stack-scrapy/SKILL.md`(必须不存在)。
     其余必须 `IDENTICAL`,否则非零退出;末尾打印各判定计数。
   - `manual-merge-check.sh`:对 CLAUDE.md / AGENTS.md / .gitignore 断言新 hunk
     的关键行存在、旧文案("默认最多 3 轮"、"评审轮次上限默认均为 3 轮")不存在,
     CLAUDE.md 与 .gitignore 中不出现裸的 `docs/decisions/00(09|10|11|12)` 引用
     (D-6),且 D-2 的 `0003` 尾注仍不存在。
   - `gate-review-check.sh`:在 `mktemp -d` 的假项目里构造
     `.ai/.current-task` + `implementation-round-01.md`(无 review 文件),以
     `CLAUDE_PROJECT_DIR=<假项目>` 调用 `.claude/hooks/gate-review.sh`,覆盖三种
     情形:无锁 → 输出 `decision: block`;后台 `flock` 持有 `.review-lock` →
     无输出 exit 0;`.review-lock` 是目录 → 仍 block(fail-closed)。
   - `evidence-tools-check.sh`:在假项目里跑 `evidence.sh`(退出码透传、头尾字段
     齐全、同名二次运行 exit 3 拒绝覆盖),再对假任务目录跑 `evidence-check.sh`
     (完整 → exit 0;实现记录缺一行 → 非零并打印补交清单)。
   - `decision-doc-check.sh`:0020 含「修订」小节、v1.2.1 两个钉死 SHA、D-6 行;
     README 索引行已更新;两文件内相对链接全部可解析。
   - `changeset-check.sh`:`git status --porcelain` 的变更集**恰好**等于上表
     23 个文件 ∪ 本任务目录(另允许既有未跟踪目录
     `.ai/2026-11-02/transient-failures-permanent-disable/` 原样存在、内容不变——
     以本任务开始时记录在**仓库外** `/tmp/claude-1000/awt/untracked-baseline.sha256`
     的清单比对;该目录含业务信息,证据输出只打印文件数与清单整体 sha256,
     不打印路径与内容),`apps/ packages/ deploy/ configs/ scripts/ examples/
     tests/` 零改动。

## 测试用例

| 编号 | 档位 | 前置条件 | 步骤 | 预期结果 | 证据形态 |
|---|---|---|---|---|---|
| TC-01 | A | 实现完成;模板克隆在 `/tmp/claude-1000/awt/tpl` | `evidence.sh TC-01 -- bash evidence/baseline-check.sh /tmp/claude-1000/awt/tpl` | exit 0;两个 tag SHA 与钉死值一致;IDENTICAL = 其余全部受管文件(含未变的 5 个),EXPECTED-DIFF=2,EXPECTED-ABSENT=1,UNEXPECTED-*=0 | evidence/TC-01.log,写法 (b) 断言脚本 |
| TC-02 | A | 同上 | `evidence.sh TC-02 -- bash evidence/manual-merge-check.sh` | exit 0;逐条断言 PASS | evidence/TC-02.log,写法 (b) |
| TC-03 | A | 同上 | `evidence.sh TC-03 -- bash -c 'for f in .ai-workflow/scripts/*.sh .claude/hooks/*.sh .githooks/commit-msg; do bash -n "$f" && test -x "$f" && echo "OK $f" || { echo "BAD $f"; exit 1; }; done'` | exit 0;每个脚本语法通过且可执行 | evidence/TC-03.log,写法 (b) |
| TC-04 | A | 同上;系统有 flock | `evidence.sh TC-04 -- bash evidence/gate-review-check.sh` | exit 0;三种情形(无锁 block / 锁被持有放行 / 锁为目录仍 block)判定符合预期——含非 happy-path | evidence/TC-04.log,写法 (b) |
| TC-05 | A | 同上 | `evidence.sh TC-05 -- bash evidence/evidence-tools-check.sh` | exit 0;evidence.sh 退出码透传 7、头尾字段齐全、同名重跑 exit 3;evidence-check 对完整假任务 exit 0、对缺行假任务非零——含非 happy-path | evidence/TC-05.log,写法 (b) |
| TC-06 | A | 同上 | `evidence.sh TC-06 -- bash .ai-workflow/scripts/plan-review.sh __minors .ai/2026-07-26/align-ai-workflow-template-v1` | exit 0;输出该历史任务各轮 plan 评审的 minor 汇总(新入口对历史任务只读可用) | evidence/TC-06.log,写法 (a) |
| TC-07 | A | 同上 | `evidence.sh TC-07 -- bash evidence/decision-doc-check.sh` | exit 0 | evidence/TC-07.log,写法 (b) |
| TC-08 | A | 同上;实现开始前已把未跟踪建议目录的 sha256 清单存到仓库外 `/tmp/claude-1000/awt/untracked-baseline.sha256` | `evidence.sh TC-08 -- bash evidence/changeset-check.sh` | exit 0;变更集恰为 23 个文件 + 本任务目录,应用代码零改动,未跟踪建议目录内容未变 | evidence/TC-08.log,写法 (b) |

C 档 0 条;B 档 0 条。评审(新版 review.sh)启动前会以本表为基准自动跑
evidence-check,本任务即为新机制的首个实战样本。

## 风险与回滚

- **自举风险**:本任务的 plan 评审用旧版 plan-review.sh(实现前),实现评审用
  新版 review.sh(实现后)。新 review.sh 若在本仓库环境下异常(flock/setsid/
  pgrep 缺失等),会 exit 3 且不消耗轮次;已确认 `/usr/bin/flock`、`setsid`、
  `pgrep`、`jq`、`codex` 均在。
- **D-1 重施加漏删/多删**:由 TC-01 的块级逐字节断言兜底。
- **决策编号串号**(把模板 0009–0012 误读为本仓库同号决策):CLAUDE.md 与
  .gitignore 改写为"模板决策 00NN"(D-6,TC-02 断言);可整体替换类文件保持
  原文并在 0020 登记。
- 回滚:全部改动在一个提交内,`git revert` 即回到 v1.0.0;无数据/运行时影响。
