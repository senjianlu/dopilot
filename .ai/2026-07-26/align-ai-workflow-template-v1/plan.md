---
status: approved
task: align-ai-workflow-template-v1
date: 2026-07-26
approved_at: 2026-07-26 14:36:55+0900
plan_review_max_rounds: 15
impl_fix_max_rounds: 15
---

# 方案:对齐 AI 工作流到 ai-workflow-template v1.0.0 并认领版本锚点

## 背景与目标

### 现状与版本判定

本仓库 2026-07-24 经 `85f182b` 采用
[senjianlu/ai-workflow-template](https://github.com/senjianlu/ai-workflow-template)
的 rawf 工作流(决策 `docs/decisions/0018`),但**未记录采用的模板版本**——
彼时模板尚未引入版本机制,`.ai-workflow/TEMPLATE-VERSION` 不存在。

版本经两条独立证据交叉判定,结论一致:

1. **时间线推算**:dopilot 采用日 2026-07-24;模板在该日之前的最后一个
   commit 是 `48a435a`(2026-07-20,"feat(workflow): 测试证据契约改为
   A/B/C 档位制");其后的 `819954b` / `2aeab2e` / `579f47a` 均为 07-25,
   晚于采用日。
2. **内容指纹**:模板 `48a435a` 侧的受管路径全集为 **20 个文件**
   (`.ai-workflow/` 11 个,含 `scripts/.gitkeep` 空占位;`.claude/hooks/`
   2 个;`.claude/settings.json`;
   `.claude/skills/rawf-{plan,implement,review,report}/SKILL.md` 4 个;
   `.githooks/commit-msg`;`.gitmessage`),dopilot 侧同名路径**一个不多、
   一个不少**,其中 19 个有内容的文件与模板快照**逐字节一致**(md5 全等),
   第 20 个为空占位。

故:**dopilot 当前工作流 = 模板 `48a435a`(v1.0.0 之前的未发版状态)**。
按模板 README「存量项目迁移」第 3 步,在完成对 v1.0.0 的全量基线对齐之前,
版本一律记 `unknown`,不得直接认领。

### 到 v1.0.0 的增量(模板侧 `48a435a..v1.0.0`,即 `2aeab2e`)

只有 07-25 的两个 commit,落到**受管路径**上共 4 项:

| 增量 | 模板文件 | 归类(CHANGELOG 头部) |
|---|---|---|
| ① 版本锚点文件 | `.ai-workflow/TEMPLATE-VERSION`(新增) | 可整体替换 |
| ② Scrapy 评审关注点(+4 行) | `.ai-workflow/review-standards.md` | 可整体替换 |
| ③ Scrapy 栈 skill(新增) | `.claude/skills/rawf-stack-scrapy/SKILL.md` | 可整体替换 |
| ④ 「技术栈 > 爬虫」章节(+62 行) | `AGENTS.md` | 需人工合并 |

其余 v1.0.0 变更(`CHANGELOG.md`、`README.md` 的「版本与升级」/「开新项目」/
「存量项目迁移」章节、`docs/decisions/0007` `0008`、`.ai/2026-07-25/*`)
都是**模板仓库自身的**版本历史、使用说明与过程痕迹,不属于 consumer 受管
路径,不拷入(判据:模板 `CHANGELOG.md` 头部「受管路径归类」两行清单)。

### 评审轮次授权(用户明确要求,非自行写入)

frontmatter 的 `plan_review_max_rounds: 15` / `impl_fix_max_rounds: 15`
**来自用户在本任务发起时的明确要求**,原话(2026-07-26 会话首条消息):

> 我需要你对齐当前的工作流到 https://github.com/senjianlu/ai-workflow-template
> 的 v1.0.0 版本。……**整体 plan 要过 codex review,plan 和改修的 review
> 轮数都到 15 轮。**

据此满足 CLAUDE.md「评审轮次上限默认均为 3 轮……仅当**用户明确要求放宽**时,
在当前任务 plan.md frontmatter 写 `plan_review_max_rounds` /
`impl_fix_max_rounds`(正整数)覆盖默认值,并在摘要或实现记录中声明」的授权
前提:两个字段各覆盖一类计数(plan 阶段评审 / 实现层修复),取值 15 与用户
指定值一致,未擅自扩大范围。本节即 CLAUDE.md 要求的「声明」,收尾摘要中
会再次列明实际用掉的轮次。

### 目标

1. 完成对 v1.0.0 的全量基线对齐核验(**含需人工合并类的逐 hunk 处置**),
   产出可复核证据;
2. 认领版本:新增 `.ai-workflow/TEMPLATE-VERSION`(version 1.0.0);
3. 按模板决策 0007 第 4 条,**三处联动剔除**与本项目无关的 Scrapy 标准栈
   (增量 ②③④ 均不认领,理由见下);
4. 把版本锚点、有意偏离清单、后续升级流程沉淀为项目决策记录,使下次升级
   可按 `OLD=1.0.0` 走模板 README 的增量流程,不再全量比较。

### 为何不认领 Scrapy 标准栈(用户 2026-07-26 裁决)

模板决策 0007 的爬虫栈规定了 **Scrapy 应用项目**的标准:数据层用
Postgres + SQLAlchemy async、部署走 `.egg` → GitHub Release → scrapyd
`addversion.json`/`schedule.json` 三段链路、包名与 `tests/` 约定等。

dopilot 是**调度这类项目的平台**,而非 Scrapy 应用:其三个可部署单元
(`apps/server`、`apps/agent`、`apps/web`)是 FastAPI + Next.js;仓库内
唯一的 Scrapy 代码是 `examples/scrapy_clock/`(约 10 个文件的最小示例被
调度对象,用于演示 `.egg` 链路,不承载业务)。把该栈写进 AGENTS.md 会把
dopilot 的技术栈表述错(声明了它并不使用的数据层与部署链路),并让评审
按无关标准打分。故按 0007 第 4 条三处联动删除。

代价与授权:`.ai-workflow/review-standards.md` 将与 v1.0.0 存在 4 行差异
(Scrapy 关注点)。该文件虽属「可整体替换」类,但差异位于其
`<!-- TEMPLATE: 按需删减。 -->` 注释所辖的「技术栈评审关注点」小节
(`review-standards.md:109`),裁剪由模板显式授权;差异被登记进本任务的
**有意偏离清单**,由 TC-01 逐条断言,不会退化为"漏对齐"。

## 改动范围

### 改动的文件(4 个)

| # | 文件 | 动作 |
|---|---|---|
| 1 | `.ai-workflow/TEMPLATE-VERSION` | 新增,三字段:`version: 1.0.0` / `source: <模板仓库 URL>` / `adopted: 2026-07-26` |
| 2 | `docs/decisions/0020-ai-workflow-template-version-anchor.md` | 新增决策记录(版本锚点 + 有意偏离清单 + 升级流程) |
| 3 | `docs/decisions/README.md` | 索引表追加 0020 一行 |
| 4 | `docs/decisions/0018-adopt-ai-workflow-template.md` | 「影响」段追加一行交叉引用,指向 0020(不改写既有结论) |

### 任务过程产物(随任务入库,不计入上表)

`.ai/2026-07-26/align-ai-workflow-template-v1/` 下的 plan.md、
implementation-round-NN.md、review-round-NN-*.md、summary.md,以及
`evidence/` 下的 6 个 bash 核验脚本(`baseline-check.sh`、
`manual-merge-check.sh`、`template-version-check.sh`、
`scrapy-absence-check.sh`、`decision-doc-check.sh`、`changeset-check.sh`)、
1 个 python 脚本 `link-check.py`、逐 hunk 处置台账
`manual-merge-ledger.tsv`,以及 8 条用例的原始输出
(`tc01-*.txt` … `tc08-*.txt`)。

### 明确不动

- **不改任何应用代码**:`apps/`、`packages/`、`deploy/`、`configs/`、
  `scripts/`、`examples/` 一律不碰(本任务是治理层对齐,零运行时影响)。
- **不动 19 个已对齐的受管文件**:它们与 v1.0.0 逐字节一致,任何改动都是
  倒退。TC-01 会把这一点作为断言。
- **不新增 Scrapy 三处**:`AGENTS.md` 不加「爬虫」章节、
  `review-standards.md` 不加 Scrapy 关注点、不建
  `.claude/skills/rawf-stack-scrapy/`。
- **不拷入模板自身产物**:模板的 `CHANGELOG.md`、`README.md`、
  `docs/decisions/0007` `0008`、`.ai/2026-07-25/*`、`logo.svg`。
  dopilot 的 `README.md` / `README.zh-CN.md` 是产品文档,与模板 README
  (模板使用说明)不同源,无可合并项。
- **不加 `.codex/agents/.gitkeep`**:模板中它是空占位目录,且**不在**
  CHANGELOG 的两类受管路径清单内(既非可整体替换、也非需人工合并),
  全仓 grep 确认无任何脚本/文档引用 `.codex`,加它只是噪声。
- **不加模板 remote、不 fetch 模板 tag**:按模板 README「版本与升级」,
  增量一律在模板仓库的**独立克隆**中读取(本任务用
  `/tmp/.../scratchpad/tpl`),consumer 仓库 git 历史与模板不同源。
- **不动 `.gitignore`**:其 rawf 运行时状态块(前 8 行)已与 v1.0.0 一致,
  其余为 dopilot 自有条目;`.gitignore` 不在受管路径清单内。
- **不改 `CLAUDE.md`**:详见下方偏离项 D-2。

## 实现方案

### 步骤 1:落地版本锚点文件

新建 `.ai-workflow/TEMPLATE-VERSION`,严格沿用 v1.0.0 的三字段形态(字段名、
顺序、`key: value` 写法与模板一致),把模板中 `adopted` 的占位说明替换为实际
日期:

```
version: 1.0.0
source: https://github.com/senjianlu/ai-workflow-template
adopted: 2026-07-26
```

`adopted` 取 **2026-07-26**(完成基线对齐、正式认领版本之日),而非 07-24
(采用 rawf 流程之日)——按模板 README「存量项目迁移」第 3 步,对齐完成前
不得写入版本,故认领日即对齐日;07-24 的采用事实由 0018 记录,两者不冲突,
0020 会写明这一区分。

### 步骤 2:核验脚本与全量基线对齐

在 `evidence/` 下写一个可复核脚本 `baseline-check.sh`(入参:模板克隆路径),
逻辑:

1. 断言克隆的 `v1.0.0` 解析为固定 commit
   `2aeab2eaca28b1364a46ec7cfc9195849cc61b68`(**钉死 SHA**,防止 tag 被移动
   导致比对基准漂移);不符即非零退出;
2. **路径集不手写,从模板现算**:取
   `git ls-tree -r --name-only v1.0.0`,按 CHANGELOG 头部「可整体替换」
   清单的六条 glob 过滤(`.ai-workflow/`、`.claude/hooks/`、
   `.claude/skills/rawf-*`、`.claude/settings.json`、`.githooks/`、
   `.gitmessage`)得到受管路径全集(含 `.ai-workflow/scripts/.gitkeep`
   这类易漏的占位文件),再逐条比对 dopilot 侧文件与
   `git show v1.0.0:<path>` 的 SHA-256;
3. **双向比对**:同时用同一组 glob 扫 dopilot 侧,凡 dopilot 有而 v1.0.0
   无的受管路径一律判 `UNEXPECTED-EXTRA` 并非零退出(单向比对会漏掉
   consumer 私自塞进受管目录的文件);
4. 判定只有四种,且**例外必须事先登记**——脚本内置一张仅含 3 条的例外表,
   不在表内的路径一律必须 `IDENTICAL`:

   | 路径 | 期望判定 | 断言细则 |
   |---|---|---|
   | `.ai-workflow/TEMPLATE-VERSION` | `EXPECTED-DIFF` | 除 `adopted` 行外内容与 v1.0.0 全等;且 `adopted` **整行严格等于 `adopted: 2026-07-26`**(不是仅校验日期格式——写成任意合法日期会让版本审计元数据失真) |
   | `.ai-workflow/review-standards.md` | `EXPECTED-DIFF` | `diff` 结果**只有删除、无新增**,且被删行恰好是 Scrapy 关注点那 4 行(D-1) |
   | `.claude/skills/rawf-stack-scrapy/SKILL.md` | `EXPECTED-ABSENT` | dopilot 侧该路径不存在,且缺席原因登记为 D-4;若它存在则判 fail(Scrapy 栈回流) |

5. 输出末尾打印各判定的计数汇总(`IDENTICAL` / `EXPECTED-DIFF` /
   `EXPECTED-ABSENT` / `UNEXPECTED-*`),计数由脚本现算,**不由本方案预先
   写死**;任一 `UNEXPECTED-*` 或例外表未命中即非零退出。

脚本连同完整原始输出落 `evidence/`。评审在只读沙箱且禁网,无法自行克隆模板,
故按 A 档证据协议:提交**命令 + 完整 stdout/stderr + 退出码**,并在输出中
内联 v1.0.0 侧文件的 SHA-256,使结论可对照公开 tag 复核。

### 步骤 2b:需人工合并类的逐 hunk 处置台账

「可整体替换」类可以逐字节比,「需人工合并」类不能——dopilot 的
`AGENTS.md` / `README.md` 是按项目重写的,与模板全文 diff 无意义。可审计的
命题是另一个:**模板 `48a435a → v1.0.0` 这段增量里,落在人工合并类路径上的
每一个 hunk,是否都被显式处置过**。该增量是有限且可枚举的:

| 路径 | v1.0.0 增量 hunk 数 |
|---|---|
| `AGENTS.md` | 1 |
| `README.md` | 9 |
| `CLAUDE.md` | 0 |
| `.agents/skills/` | 0(v1.0.0 侧无此路径) |
| `skills-lock.json` | 0(v1.0.0 侧无此文件) |

写台账 `evidence/manual-merge-ledger.tsv`(列:`path` / `hunk`(hunk 头) /
`disposition` / `note`),处置词表四选一:

- `divergence:D-NN` —— 有意偏离,须在 `0020` 的偏离清单中有同号条目;
- `absorbed:<锚点>` —— 语义已被本任务吸收进 dopilot 的产物,锚点须是
  **可 grep 的文件路径/串**,脚本逐条验证锚点真实存在;
- `n/a-template-doc` —— 模板仓库自身的使用说明(如「开新项目」步骤重编号),
  consumer 不承载;
- `no-op` —— 模板侧该路径无增量且无内容,无可并项。

10 条 hunk 的预定处置:

| hunk | 内容 | 处置 |
|---|---|---|
| `AGENTS.md@@-110,0+111,62` | 「### 爬虫」标准栈章节 | `divergence:D-3` |
| `README.md@@-31+31,3` | 「开新项目」新增"填 adopted 采用日期" | `absorbed:.ai-workflow/TEMPLATE-VERSION` |
| `README.md@@-33+35` … `@@-44+46`(5 条) | 「开新项目」步骤 3→8 重编号 | `n/a-template-doc` |
| `README.md@@-55+57,4` | 存量迁移:剔除无关栈须三处联动删 | `absorbed:docs/decisions/0020-…md`(D-1/D-3/D-4) |
| `README.md@@-58,3+63,9` | 存量迁移:版本认领须先全量基线对齐 | `absorbed:docs/decisions/0020-…md`(版本锚点段)|
| `README.md@@-79,0+91,37` | 新增「版本与升级」章节(SemVer + 升级流程) | `absorbed:docs/decisions/0020-…md`(升级流程段)|

脚本 `evidence/manual-merge-check.sh`(入参同上,模板克隆路径)断言:

1. 从模板克隆现算 `git diff --unified=0 48a435a v1.0.0 -- <5 条路径>` 的 hunk
   头集合,与台账的 hunk 列做**集合相等**比对(多一条=漏处置,少一条=台账
   造假,均非零退出)——这正是 R-02 指出的"脚本可在未完成核对时仍退出 0"
   的堵漏点;
2. 每条 `disposition` 属于上述四词表,`divergence:D-NN` 的编号能在
   `docs/decisions/0020-*.md` 中 grep 到,`absorbed:` 的锚点文件/串真实存在;
3. **`CLAUDE.md` 走全文比对**(它与模板同源):`diff` 模板 v1.0.0 版与
   dopilot 版,断言差异**恰好**是 D-2 那一行(只有删除、无新增、且被删行
   含 `docs/decisions/0003`);
4. **`AGENTS.md` 章节骨架断言**:模板 v1.0.0 的全部 `^## ` 顶级章节
   (技术栈 / 目录约定 / 通用硬规则 / Git 提交规范 / Skill 基线)在 dopilot
   的 `AGENTS.md` 中**全部存在**——防止"人工重写"顺手丢章节;`### 爬虫`
   缺席则由 D-3 与 TC-03 覆盖;
5. `.agents/skills/`、`skills-lock.json` 断言 `git ls-tree -r v1.0.0 --
   .agents skills-lock.json` 输出为空(证明"无可并项"是事实而非声称)。

### 步骤 3:决策记录 0020

新建 `docs/decisions/0020-ai-workflow-template-version-anchor.md`,按
`docs/decisions/README.md` 的四段体例(日期/背景/决定/影响)写:

- **决定**含三条:① 以 `.ai-workflow/TEMPLATE-VERSION` 记录采用版本
  1.0.0,adopted 2026-07-26;② 不认领 Scrapy 标准栈,三处联动删除
  (含理由与模板 0007 第 4 条依据);③ 后续升级按模板 README「版本与升级」
  流程,在模板独立克隆中取 `v$OLD..v$NEW` 增量,consumer 不加模板 remote。
- **影响**含**有意偏离清单**(升级时不得被"顺手对齐"掉):

  | 编号 | 文件 | 偏离 | 理由 |
  |---|---|---|---|
  | D-1 | `.ai-workflow/review-standards.md` | 缺 v1.0.0 的 Scrapy 关注点 4 行 | 三处联动删除;裁剪由该节 TEMPLATE 注释授权 |
  | D-2 | `CLAUDE.md` | 少一处 "(机制见 docs/decisions/0003)" 尾注 | 该引用指向**模板仓库**的 0003(可配置评审轮数上限);dopilot 的 `0003` 是「单管理员」,照抄会指向错误文档 |
  | D-3 | `AGENTS.md` | 无「技术栈 > 爬虫」章节 | 同 D-1;dopilot 非 Scrapy 应用 |
  | D-4 | `.claude/skills/rawf-stack-scrapy/` | 整个 skill 目录不存在 | 同 D-1;dopilot 不承载 Scrapy 应用的初始化/编码/测试约定 |
  | D-5 | `AGENTS.md` / `README.md` / `.agents/skills/` / `skills-lock.json` | 与模板结构性不同源 | 需人工合并类,均已按项目裁剪;模板 v1.0.0 未携带 `.agents/skills` 条目,无可并项 |

- 同时说明 0018 与 0020 的分工:0018 记「为什么采用 rawf」,0020 记
  「采用的是哪个版本、偏离了什么、以后怎么升」。

### 步骤 4:索引与交叉引用

- `docs/decisions/README.md` 索引表追加:
  `| [0020](0020-ai-workflow-template-version-anchor.md) | 认领 ai-workflow-template v1.0.0 版本锚点;不采用 Scrapy 标准栈 |`
- `docs/decisions/0018-*.md`「影响」段末尾追加一行,指向 0020(0018 的
  结论未被推翻,故**不加**"已被 NNNN 取代"标记——按
  `docs/decisions/README.md` 的约定,该标记只用于推翻)。

### 步骤 5:自测与留证

按下表逐条执行,原始输出落任务目录的 `evidence/`。

## 测试用例

**执行环境(对下表全部用例统一生效)**:

- **cwd 一律是仓库根** `/home/rabbir/Projects/dopilot`,表中所有路径均为
  仓库根相对路径,不存在中途 `cd`;
- 需要模板快照的用例(TC-01、TC-08)在执行前先
  `export TPL=<模板独立克隆的绝对路径>`,该 `export` 与其取值随原始输出
  一并落 `evidence/`,供评审核对命令可复现;
- 每条用例的留证命令统一形如
  `<命令> > evidence/<文件> 2>&1; echo "exit=$?" >> evidence/<文件>`,
  即 stdout/stderr 合并落盘并追加退出码(A 档三要素齐备)。

任务目录常量:`TD = .ai/2026-07-26/align-ai-workflow-template-v1`
(下表为避免歧义一律写全路径,不使用该缩写)。

| 编号 | 档位 | 前置条件 | 步骤(cwd=仓库根) | 预期结果 | 证据形态 |
|---|---|---|---|---|---|
| TC-01 | A | 模板已克隆到 `$TPL`(禁网前完成);步骤 1–4 已落地 | `bash .ai/2026-07-26/align-ai-workflow-template-v1/evidence/baseline-check.sh "$TPL"` | 退出码 0;v1.0.0 解析为 `2aeab2eaca28b1364a46ec7cfc9195849cc61b68`;受管路径集**由脚本从模板现算**(非预写死),逐行打印双方 SHA-256 与判定;除内置 3 条例外(`TEMPLATE-VERSION`=EXPECTED-DIFF、`review-standards.md`=EXPECTED-DIFF、`rawf-stack-scrapy/SKILL.md`=EXPECTED-ABSENT)外全部 `IDENTICAL`;无任何 `UNEXPECTED-EXTRA`/`UNEXPECTED-*`;末尾打印现算计数汇总 | 命令 + 完整 stdout/stderr + 退出码 → `.ai/2026-07-26/align-ai-workflow-template-v1/evidence/tc01-baseline-check.txt`;脚本本体同目录 `baseline-check.sh` |
| TC-02 | A | 步骤 1 已落地 | `bash .ai/2026-07-26/align-ai-workflow-template-v1/evidence/template-version-check.sh` | 退出码 0,6 项断言全 PASS:文件存在、恰好 3 行、字段名与顺序为 version/source/adopted、`version` 严格等于 `1.0.0`、`source` 等于模板仓库 URL、**第三行整行严格等于 `adopted: 2026-07-26`**;且不含模板占位文案「拷入 consumer」。含**反向自检**:把 scratchpad 临时副本的 adopted 改成另一合法日期 `2026-07-24`,断言检测函数返回非 0 | 命令 + 完整输出 + 退出码 → `.ai/2026-07-26/align-ai-workflow-template-v1/evidence/tc02-template-version.txt` |
| TC-03 | A | 步骤 1–4 已落地 | `bash .ai/2026-07-26/align-ai-workflow-template-v1/evidence/scrapy-absence-check.sh` | 退出码 0,三处**同时** ABSENT 才通过:`AGENTS.md` 无「### 爬虫」章节且无 `scrapyd-client`/`TWISTED_REACTOR` 串;`review-standards.md` 无 Scrapy 关注点行;`.claude/skills/rawf-stack-scrapy` 路径不存在。含**反向自检**:向 scratchpad 临时副本注入 `- Scrapy:` 行,断言检测函数返回非 0 | 命令 + 完整输出 + 退出码 → `.ai/2026-07-26/align-ai-workflow-template-v1/evidence/tc03-scrapy-absence.txt` |
| TC-04 | A | plan.md 已含 `plan_review_max_rounds: 15` | ① `bash .ai-workflow/scripts/plan-review.sh __resolve_max_rounds .ai/2026-07-26/align-ai-workflow-template-v1/plan.md`;② **异常路径**:对 scratchpad(仓库外)的三份伪造 plan 分别取 `plan_review_max_rounds:` 为空、`abc`、`0`,以同一命令形式重复调用 | ① 输出 `15`、退出码 0(证明 15 轮授权被脚本真实识别,而非仅写在纸面);② 三次均退出码 3 且 stderr 含"非法(须为正整数" | 命令 + 完整输出 + 退出码 → `.ai/2026-07-26/align-ai-workflow-template-v1/evidence/tc04-round-caps.txt` |
| TC-05 | A | 步骤 3–4 已落地 | `bash .ai/2026-07-26/align-ai-workflow-template-v1/evidence/decision-doc-check.sh` | 退出码 0,全部断言 PASS:0020 存在且含「- 日期:」「- 背景:」「- 决定:」「- 影响:」四段;偏离清单含 D-1…D-5 五行;`docs/decisions/README.md` 索引表含指向 `0020-…md` 的行且该文件存在;`0018-*.md` 含指向 `0020-` 的交叉引用;0018 **未**被加上"已被…取代"标记 | 命令 + 完整输出 + 退出码 → `.ai/2026-07-26/align-ai-workflow-template-v1/evidence/tc05-decision-docs.txt` |
| TC-06 | A | 步骤 3–4 已落地 | `python3 .ai/2026-07-26/align-ai-workflow-template-v1/evidence/link-check.py docs/decisions/README.md docs/decisions/0018-adopt-ai-workflow-template.md docs/decisions/0020-ai-workflow-template-version-anchor.md` | 退出码 0,无 BROKEN 行(逐个相对链接断言目标文件存在) | 命令 + 完整输出 + 退出码 → `.ai/2026-07-26/align-ai-workflow-template-v1/evidence/tc06-link-check.txt` |
| TC-07 | A | 全部步骤已落地,尚未提交 | `bash .ai/2026-07-26/align-ai-workflow-template-v1/evidence/changeset-check.sh`(内部取 `git status --porcelain`,与 plan「改动范围」声明的清单做**集合相等**断言,非仅包含) | 退出码 0;新增/修改集合**恰好** = 4 个受管/文档文件 + 本任务 `.ai/` 目录产物,**无第五个**受管或源码文件被触碰(反向证明"明确不动"部分确实没动) | 命令 + 完整输出 + 退出码 → `.ai/2026-07-26/align-ai-workflow-template-v1/evidence/tc07-changeset.txt` |
| TC-08 | A | 模板已克隆到 `$TPL`;步骤 2b、3、4 已落地 | `bash .ai/2026-07-26/align-ai-workflow-template-v1/evidence/manual-merge-check.sh "$TPL"` | 退出码 0。① 现算模板 `48a435a..v1.0.0` 在 5 条人工合并路径上的 hunk 头集合,与 `manual-merge-ledger.tsv` **集合相等**;② 每条 disposition 属四词表、`divergence:D-NN` 在 0020 中可 grep、`absorbed:` 锚点真实存在;③ `CLAUDE.md` 全文 diff 恰好为 D-2 一行删除;④ 模板 v1.0.0 的 5 个 `^## ` 章节在 dopilot `AGENTS.md` 全部存在;⑤ `git ls-tree -r v1.0.0 -- .agents skills-lock.json` 为空。含**反向自检**:对 scratchpad 的台账副本删掉任一行,断言脚本退出非 0 并指出缺失 hunk | 命令 + 完整输出 + 退出码 → `.ai/2026-07-26/align-ai-workflow-template-v1/evidence/tc08-manual-merge.txt`;台账与脚本同目录 `manual-merge-ledger.tsv` / `manual-merge-check.sh` |

档位说明:8 条全 A 档,C 档 0 条(本任务无人工交互验证项,符合
review-standards「C 档为 0 才是常态」)。非 happy-path 覆盖:TC-04②
(非法轮次值三种形态)、TC-03 自检(注入 Scrapy 残留必须被检出)、TC-02
反向自检(错误 adopted 日期必须被拒)、TC-07(集合相等,拦截意外改动)、
TC-08 反向自检(台账缺行必须被检出)。

## 风险与回滚

| 风险 | 说明 | 对策 |
|---|---|---|
| **版本判定错误** | 若判定基线错(实际不是 `48a435a`),认领 1.0.0 会掩盖未对齐的差异 | 双证据交叉(时间线 + 20 个受管路径中 19 个有内容文件 md5 全等)已互相印证;TC-01 再以 SHA-256 对 v1.0.0 侧**现算路径全集**复核(含双向比对与例外表),任一不符即失败,不靠推算兜底 |
| **tag 漂移** | 模板 `v1.0.0` tag 若被移动,比对基准失真 | TC-01 钉死 commit SHA `2aeab2e…`,不匹配即非零退出 |
| **有意偏离被误当漏对齐** | 下次升级时 D-1…D-5 可能被"顺手补齐",Scrapy 栈重新混入 | 偏离清单写进 0020(持久真相层),TC-01/TC-03 在本仓库形成可复跑断言 |
| **人工合并类漏对齐** | `AGENTS.md`/`README.md` 等无法逐字节比,若只"声明已处置",可能漏掉 v1.0.0 的某个 hunk 而仍全绿 | 步骤 2b 的逐 hunk 台账 + TC-08 的**集合相等**断言(hunk 集从模板现算,不取自台账)+ 台账缺行反向自检 |
| **评审无法复核 TC-01 / TC-08** | 评审只读禁网,无法克隆模板自证 | 按 A 档证据协议提交完整原始输出,并内联 v1.0.0 侧每个文件的 SHA-256 与现算 hunk 头,可对照公开 tag 离线复核;脚本与台账本体一并入库供审读 |
| **文档层改动影响运行时** | 理论上为零 | 改动集不含 `apps/`、`packages/`、`deploy/`、`configs/`;TC-07 以集合相等断言反向兜底 |

**回滚**:本任务只新增 2 个文件、改 2 个文档,无迁移、无配置、无运行时耦合。
回滚 = `git revert` 该提交(或删除 `.ai-workflow/TEMPLATE-VERSION` +
`docs/decisions/0020-*.md`,并还原 README 索引与 0018 的交叉引用行),
工作流行为回到当前状态,零副作用。

<!-- 过程产物落点:体量较大的验证证据(日志、截图)放任务目录 evidence/,
     引用素材(Design 稿、参考图)放 assets/;二者须在评审前落盘。 -->
