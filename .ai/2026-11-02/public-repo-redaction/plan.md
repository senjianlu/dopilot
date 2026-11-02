---
status: approved
task: public-repo-redaction
date: 2026-11-02
approved_at: 2026-11-02 17:27:20+0900
evidence_format: v1
---

# 方案:公开仓库信息脱敏机制 + 当前树与 git 历史脱敏

## 需求原文

> 然后为这个开源项目制定信息脱敏机制，包括之前的证据和更新履历，目的是消除"我们正用这个项目爬取哪些网站"的信息，并进行检查和修改，包括 git 履历。（在你力所能及的范围内进行，我没法帮助你做更多）。
> 之后再 stash 出本次改修的建议，这些建议将在其他会话被完成，在这里出现的目的只是给你参考如何设计项目级别的脱敏规则。
>
> (补充)主要是我觉得证据目录存在太多业务信息，我整个项目开源在 github，泄露得太多了。

对齐中的用户裁决(2026-11-02):原始生产数据文件**换成说明桩**(全部历史一并替换,路径保留);
脱敏范围 = 目标站点/域名/接口 + **下游项目与业务名(含爬虫内部模块/类名)+ 生产基础设施 +
游戏/商品标识**;授权方式 = **提交免问,强推前问**。

**本任务交付**:① 一份项目级脱敏决策(什么不得入库、证据怎么写、别名约定、例外);② 一套
不含任何业务词的入库机制(检测/改写工具 + 通用规则 + pre-commit / pre-push 钩子),业务词只
存在于仓库外的私有规则文件;③ 当前树(含 `.ai/` 历史证据)按规则脱敏的一个提交;④ 本提交之后
用同一规则改写**全部公开历史**,经用户确认后强推 GitHub。

## 背景与目标

### 现状(2026-11-02 盘点,私有规则 + 通用规则扫描)

- 仓库 `senjianlu/dopilot` 在 GitHub **公开**(0 fork)。
- 当前树 953 个文本文件中 **48 个文件命中 3,088 处**(按出现计;重叠词会被多条规则同计):
  - **原始生产数据 20 个文件**,集中在 `.ai/2026-08-22/redis-log-stream-oom-investigation/evidence/`
    (console 系统 journal 3、服务端/爬虫日志 7、Redis 转储 3、Prometheus 时序 3、生产
    compose 1)与 `.ai/2026-09-15/stuck-scrapy-job-holds-schedule-slot/evidence/`(爬虫 job
    原始日志、爬虫侧 Valkey 时间线、爬虫侧 PG 查询结果各 1)——其中 17 个有词表命中且占命中量
    绝大多数,另 3 个(生产 compose、Redis 键扫描与流样本)无词表命中但同属原始生产数据;即便
    替换站点名,调度频率、数据量、报错原文、内部类名仍构成业务画像。
  - **`.ai/` 正文类 22 个文件**:各任务 plan / 调查报告 / 小结 / 交接文档 / 脚本里的调度名
    (如"<站点> 730")、下游爬虫仓库名、业务品牌、生产域名与主机名、内网 IP、爬虫内部
    类/表/函数名。
  - **应用与文档 9 个文件**:`apps/` 下 2 个 web 测试夹具 + 1 处注释 + 2 个 agent 测试夹具用了
    真实调度名/爬虫名;`docs/architecture/` 3 处、`docs/decisions/0021` 1 处举例用了真实名。
  - **截图 1 个**:`.ai/2026-09-16/fix-console-horizontal-overflow/evidence/schedules-after-fix.png`
    显示 4 个真实调度名与模板名。
  - **疑似真实凭据**:`.ai/2026-07-24/deploy-kubernetes-agent/` 的 TC-04 证据把"诱饵文件"内容
    原样打印,含真实 agent token 与 Redis 密码的前缀,完整串长度与真值相符(该任务 plan 原文
    即写"含真实 token 前缀");其 plan、TC-03 证据也以 grep 模式形式写出了这两个前缀。
- 历史中另有 **5 条提交信息**含站点名/业务名(如"<站点> 730 job hung""sync dashboard to
  <业务>-api");两个证据文件名含站点名(形如 `<站点>-730-job-log.txt`)。
- 盘点中**不构成业务信息、不处理**的:`/opt/dopilot`、`/opt/backup`(公开部署手册
  `docs/architecture/05-deployment.md` 推荐的通用约定路径);Tailscale / Infisical / Prometheus /
  Valkey / Consul 等通用工具名;`rabbir/dopilot` 镜像名与 GitHub 账号(项目自身身份)。
  ——这是对用户所选"生产基础设施"类的**收窄**:选项说明里我写了"/opt 下的部署路径",实查后
  它们只是手册约定,改写反而会让手册与证据对不上,故不改,在此声明。

### 引用范围(哪些历史算"公开历史")

- **远端公开引用只有 `refs/heads/master`**(`git ls-remote origin` 仅 `HEAD` 与
  `refs/heads/master`;无标签、无 PR 引用;GitHub API 显示 0 fork)。master 当前 67 个提交
  (含本地已提交未推送的工作流升级 `d85a4fb`,加上本任务提交为 68 个)。
- 本地 `git rev-list --all` 可达 95 个提交,多出的 28 个只属于**从未推送的本地引用**:
  `refs/heads/feat/phase-0-skeleton`、`refs/heads/chore/dev-toolchain-mcp-playwright`、
  `refs/heads/worktree-logo-asset`、`refs/original/refs/heads/feat/phase-0-skeleton`、
  `refs/tags/backup/pre-normalize`(均为 6 月早期阶段,早于任何生产数据)。处理:**排除、不改写、
  不删除**,但其独有提交须经 `check --range master..<ref>` 审计为零命中(TC-10);今后若推送,
  会被 pre-push 钩子扫描。`refs/remotes/origin/*` 在强推后由 fetch 更新;stash 为本地。
- 因此改写与发布范围 = `master`;`rewrite_history.py` 支持多个 `--ref`(含附注标签),由
  TC-03 用合成分支与标签验证,本次只传 `--ref master`。发布后核验范围 = 从 GitHub 重新克隆
  得到的全部引用。

### 目标

1. 把"什么不得入库、证据怎么写"变成有约束力的项目规则(决策记录 + AGENTS.md 硬规则)。
2. 把检测变成机器闸门:业务词只放仓库外私有文件,钩子在提交与推送两处拦截,检查失败或
   无法执行时一律拦截(fail-closed)。
3. 当前树零命中;改写后的公开历史零命中,**逐提交**的树与元数据与源历史经同一变换完全一致。
4. 旧提交 id 不再出现在任何内容里(否则可凭旧 id 在 GitHub 上找到未脱敏的悬空提交)。

## 改动范围

### A. 机制(新增 7 个)

| # | 文件 | 内容 |
|---|---|---|
| 1 | `scripts/redaction/redact.py` | 检测/改写工具,仅用标准库。规则格式:`lit`(大小写不敏感字面量,词界 + 驼峰边界,替换保持原大小写形态)、`re`(正则,检测 + 改写;"站点别名 + 真实 appid"即用限定上下文的 `re` 规则,别名后跟真实 appid 同样被拦截)、`rewrite`(只改写不检测,仅限本身不敏感的修饰性改写,私有规则当前未使用)、`stub`(整文件换说明桩)、`blob`(历史中按 blob id 替换二进制,用于打码截图)。规则按文件顺序逐条执行。子命令:`check --staged / --push / --range / --tree / --history`、`apply`、`apply-tree`、`stub-text`、`selftest`;`--summary` 只输出计数、不回显命中原文(供入库证据使用);含 `redaction:allow` 的行不报;暂存/推送中出现二进制文件默认拦截,人工看过后以单次环境变量 `DOPILOT_REDACTION_ALLOW_BINARY=1` 放行。规则文件缺失、不可读、字段数不对、未知类型、正则错误一律 exit 2 并说明原因 |
| 2 | `scripts/redaction/rewrite_history.py` | 历史改写:先检查每个在范围内的提交——**同一棵树里两个不同路径映射成同一新路径即拒绝**(exit 1,不创建目标库);再 `git fast-export <refs>` → 过滤 → `git fast-import` 到**新的**裸仓库(源仓库不动)。过滤:文本 blob 与提交/标签信息套规则;`stub` 路径改为内联说明桩;`blob` 规则替换二进制;路径套规则(文件改名);内容/提交信息中"是本仓库某个已改写提交唯一前缀"的 7–40 位十六进制串替换为新 id 的同长前缀(经 fast-import `get-mark` 逐提交取得);同一提交内"`D 旧路径` + `M 新路径`"被映射成同一路径时丢弃该 D(即本任务提交里 `git mv` 的那种冗余删除;真实撞名已在前置检查拒绝)。`verify`:**逐提交**核对父子(映射后)、作者/提交者行、提交信息 = 源信息经变换、**整棵树(路径/模式/内容)= 源树经同一变换**;引用指向映射后的对象、附注标签信息经变换;目标库全量零命中;旧 id 零残留。新旧 id 对照表只写在目标裸仓库内(仓库外) |
| 3 | `scripts/redaction/generic-rules.tsv` | 入库的通用规则(不含业务词):RFC 1918 内网 IPv4、Tailscale 内网主机域名(含 `*.ts.net`)|
| 4 | `scripts/redaction/tests/test_redact.py` | pytest(39 条):规则语义、钩子、历史改写及其反例,全部用合成词(如 `acmemart`)与 `tmp_path` 下的临时 git 仓库 |
| 5 | `.githooks/pre-commit` | `python3 scripts/redaction/redact.py check --staged`(扫描**暂存区**内容与路径);无 python3 时 fail-closed |
| 6 | `.githooks/pre-push` | `python3 scripts/redaction/redact.py check --push`(扫描待推**引用名**、**附注标签说明**(含嵌套标签),以及每个远端尚无的提交的提交信息、改动文件内容与路径;远端旧 id 本地不存在时按"新历史"扫描全部未在远端跟踪引用上的提交);无 python3 时 fail-closed |
| 7 | `docs/decisions/0024-public-repo-redaction.md` | 决策记录(见「实现方案」第 1 步) |

私有规则文件**不入库**:默认 `~/.config/dopilot/redaction-rules.tsv`(权限 600),可用
`DOPILOT_REDACTION_RULES` 指向别处;设为 `none` 表示有意只跑通用规则(外部贡献者)。本机已按
盘点结果生成该文件(凭据 4、基础设施 6、下游项目与业务 8、业务对象 8、爬虫内部名 7、站点 50、
appid 8(均为检测 + 改写的 `re` 规则)、说明桩 8、二进制替换 1);站点别名字母**随机分配**,不按字母序,避免反推。打码截图
(私有资源)在 `~/.local/share/dopilot-private/`(权限 700)。

### B. 规则与文档(改 7 个)

| # | 文件 | 改动 |
|---|---|---|
| 8 | `AGENTS.md` | 通用硬规则新增"公开仓库脱敏"一条(指向 0024,含证据写法要点);"`.ai/` 历史轮次文件只增不改"补"脱敏改写除外(仅经 redact.py,见 0024)";目录约定 `scripts/` 行补 `redaction` |
| 9 | `CONTRIBUTING.md` | 钩子启用段补:pre-commit / pre-push 的脱敏检查、外部贡献者用 `DOPILOT_REDACTION_RULES=none` |
| 10 | `pyproject.toml` | pytest `testpaths` 增 `scripts/redaction/tests` |
| 11 | `docs/README.md` | ".ai/ 历史只增不改"补脱敏例外并指向 0024 |
| 12 | `docs/decisions/README.md` | 索引增 0024 |
| 13 | `docs/decisions/0020-ai-workflow-template-version-anchor.md` | 有意偏离新增 **D-7**:`.githooks/pre-commit`、`.githooks/pre-push` 为本仓库自有文件,位于模板"可整体替换"目录,升级时须保留(基线核验会报 UNEXPECTED-EXTRA,属预期) |
| 14 | `docs/architecture/README.md` | 目录树 `scripts/` 注释补 `redaction` |

### C. 当前树脱敏(`redact.py apply-tree` 一次产出,试跑结果:52 个路径)

- 说明桩 20 个文件(上节列出的原始生产数据;路径不变,内容换为固定说明:已移出公开仓库、
  结论以同任务正文为准、原件在维护者本机私有备份)。
- 打码截图 1 个(遮住名称列与模板列,保留"已自动禁用"徽标与操作菜单,原用例要证明的版面
  结论仍可见)。
- 正文改写 31 个文件:`.ai/` 下 22 个、`apps/` 5 个(仅字符串字面量与 1 处注释,不改逻辑)、
  `docs/` 4 个。
- 改名 2 个:即上述说明桩中两个以站点名命名的证据文件(引用它们的正文同步改写,TC-05 断言
  无断链)。

合计触及:机制 7 + 规则文档 7 + 当前树 52 = **66 个路径**(> 10,走 plan 评审闸)。

### D. 提交之后:历史改写与强推(本任务内,强推前停下问用户)

1. 提交:本任务提交含打码 PNG,人工已核对打码结果(TC-12)后,以
   `DOPILOT_REDACTION_ALLOW_BINARY=1 git commit …` 单次放行 pre-commit 的二进制拦截。
2. 备份:`git bundle create ~/.local/share/dopilot-private/dopilot-pre-redaction-2026-11-02.bundle --all`
   + 未跟踪的建议目录打包(均在仓库外、权限 700)。
3. `rewrite_history.py run --src <本仓库> --dst ~/.local/share/dopilot-private/rewrite-2026-11-02.git --ref master`,
   再 `verify --ref master`,结果须全部 PASS。
4. **停下向用户呈现 verify 结果,请求强推确认。**
5. 用户确认后:本仓库 `git fetch <dst> master` → `git reset --hard FETCH_HEAD`(未跟踪文件不受
   影响)→ 追加一条仅含改写记录的提交(`history-rewrite.md`,只有统计与核验结论,不含新旧 id
   对照)→ 列出待推历史中的全部二进制文件(都是已入库的图标/截图/测试夹具,另含打码 PNG)并
   人工确认后,`DOPILOT_REDACTION_ALLOW_BINARY=1 git push --force-with-lease=master:<当前 origin/master id> origin master`
   (pre-push 钩子对全部待推提交的信息、内容、路径再扫一遍文本命中)。
6. 推送后:`git ls-remote origin` 只有新 master;从 GitHub 重新克隆,`redact.py check --history
   --summary` 零命中;结果写入对话汇报。

## 非目标

- **stash 2026-11-02 改修建议**:用户要求的下一步,本任务之后单独执行;建议目录保持未跟踪、
  本任务不改其内容(其中的原始数据在那边会话入库时会被新钩子拦下,届时按 0024 处理)。
- **作者邮箱**:全部提交的作者邮箱为手机号形态的个人邮箱,属个人信息而非"爬取哪些网站",
  不在本任务交付内;强推确认时向用户提一句,用户若要求处理,另作追加并记录确认。
- **本地未推送引用**(见「引用范围」):不改写、不删除,只审计。
- **模板仓库 `senjianlu/ai-workflow-template`**(同样公开,14 个文件 23 处同类词)与下游
  `senjianlu/dopilot-with-deps`:不是本仓库,不在本任务改;收尾时列为残留供用户决定。
- **GitHub 侧残留**:强推后旧提交在 GitHub 垃圾回收前仍可按完整 id 访问,公共 Events API 保留
  近 90 天的推送事件(含提交信息);只能由 GitHub Support 清除,用户已说明无法协助,收尾列出。
- **Docker Hub 旧镜像**:历史镜像内含 `apps/` 测试夹具中的旧调度名;删旧 tag 属外部操作,只列出。
- **凭据轮换**:本任务只从仓库与历史中清除;是否轮换 agent token / Redis 密码由用户决定(收尾
  强烈建议)。
- `/opt/*` 通用部署路径与通用工具名不改写(理由见背景)。
- 不把检查接入 CI(CI 拿不到私有规则;停车场备选:用 GitHub secret 存规则文件)。
- 不改 `.ai-workflow/`、`.claude/`(模板受管,脱敏规则写在 AGENTS.md 对任何工具生效即可)。
- 不清理 `reference/scrapydweb` 在早期历史中的残留(与本需求无关,另记停车场)。

## 实现方案

1. **决策 0024**(四段式):
   - 背景:公开仓库;盘点数字;过程产物取自生产导致泄露。
   - 决定:① 六类不得入库(目标站点/数据源;下游项目与业务名,含爬虫内部模块/类/表/函数名;
     业务对象如 appid、商品、币种组合;生产基础设施:公网域名、主机名、内网 IP 与内网域名;凭据及其
     任意前缀;原始生产数据:journal、原始日志、DB/Redis 转储、API 快照、监控时序、生产配置、
     生产截图)。② 证据写法:原始数据只放本机私有目录(建议
     `~/.local/share/dopilot-private/<日期>/<任务>/`),仓库只放结论、聚合统计与脱敏摘录;要入库
     的命令输出先经 `redact.py apply -`;A 档证据命令不得直接打印原始生产数据;截图先打码。
     ③ 别名约定:站点 `site-xx`(随机字母)、appid `g1…`、下游爬虫 `crawler-a`、业务 `biz`、主机
     `console-host` / `agent-host-NN`、内网 IP → `192.0.2.0/24`(RFC 5737)、域名 → `example.com` /
     `internal.example`;**对照表只在私有规则文件里**。④ 机制:私有规则 + 通用规则 + 两个钩子;
     规则文件格式与位置;fail-closed。⑤ `.ai/` 只增不改的例外:仅限经 redact.py 的脱敏改写,不得
     借机改结论。⑥ 历史:本次改写公开历史并强推;内容中的本仓库提交 id 已映射为新 id;再发现
     泄露时同法处理,强推须用户确认。⑦ 被否备选:删掉整个 `.ai/` 证据、仓库转私有、只改当前树、
     词表入库、原始数据只做别名(用户裁决换说明桩)。
   - 影响:新机器须先放私有规则文件,否则钩子拦截;0020 D-7;已知外部残留清单。
2. **工具与钩子**:把仓库外原型(已在本仓库临时克隆上端到端试跑通过:68 个提交、37,307 个文件
   版本逐提交比对零不符)按上表落入 `scripts/redaction/` 与 `.githooks/`。
3. **测试**:`scripts/redaction/tests/test_redact.py`,不依赖本机私有规则文件(通过
   `DOPILOT_REDACTION_RULES` 指向测试生成的规则文件)。
4. **当前树脱敏**:`python3 scripts/redaction/redact.py apply-tree`;盘点阶段已在临时克隆上通读全部
   正文改动,并据此补入凭据、爬虫内部业务名两类规则。
5. **规则文档**:按 B 表编辑。
6. 提交(用户已预授权提交),随后按 D 节执行历史改写,强推前停下。

## 测试用例

所有命令**从仓库根执行**;辅助脚本位于本任务目录 `evidence/`,下文以 `$E` 代指
`.ai/2026-11-02/public-repo-redaction/evidence`(命令中写全路径)。所有 A 档证据只输出计数、
合成词或别名侧路径,**不得回显真实业务词**(本任务的提交自身就要通过新的 pre-commit 钩子)。

| 编号 | 档位 | 前置条件 | 步骤 | 预期结果 | 证据形态 |
|---|---|---|---|---|---|
| TC-01 | A | 实现完成 | `evidence.sh TC-01 -- .venv/bin/python -m pytest scripts/redaction/tests -v` | 全部通过〔第 02 轮修复(实现评审 R-01~R-06):测试增至 45 条,夹具全部改用不命中私有规则的合成词;第 03 轮修复(实现评审第 02 轮 R-01~R-03)增至 49 条〕。规则语义部分覆盖:字面量词界(不误伤更长单词与十六进制串)、驼峰边界、大小写形态、规则顺序、正则反向引用、`rewrite` 不参与检测、**"别名 + 真实 appid"被检测、"别名 + appid 别名"放行、改写幂等**、`stub` 通配、`redaction:allow`、二进制判定、`apply -`、`selftest` 发现别名自命中、私有规则文件缺失 exit 2、`none` 只跑通用规则 | evidence/TC-01.log,写法 (a) |
| TC-02 | A | 同上 | `evidence.sh TC-02 -- .venv/bin/python -m pytest scripts/redaction/tests -v -k hook` | 全部通过。临时仓库 `core.hooksPath` 指向本仓库 `.githooks`。**pre-commit**:暂存敏感内容拦截、敏感路径拦截、**暂存区含敏感内容而工作区已清理仍拦截**、干净提交通过且 commit-msg 规范检查仍生效、二进制默认拦截且单次放行变量可放行;**fail-closed**:规则文件缺失 / 不可读 / 字段数错 / 正则错 / 未知类型、PATH 中无 python3,均非零退出并说明原因〔第 02 轮修复:另含通用规则文件缺失(R-05)〕。**pre-push**:提交信息敏感、文件内容敏感、路径敏感、**较早提交泄露而 tip 已清理**、**引用名敏感**、**指向已推送提交的附注标签说明敏感**(无新增提交)、**嵌套标签中外层干净而内层说明敏感**(最终提交已在远端)均拦截,改为干净的引用名/各层标签说明后放行;**远端旧 id 本地不存在**(推送另一条独立历史)时扫描整条新历史——含泄露拦截、干净放行;二进制默认拦截、放行变量可放行〔第 02 轮修复:另含只存在于合并结果中的敏感内容(R-02)、敏感提交已在其它远端而首次推往目标远端(R-03)、普通文件改为指向敏感目标的符号链接(R-04)、无敏感词的原始数据放在说明桩路径(R-06)均拦截;第 03 轮修复:内层标签名敏感、标签指向含敏感内容的 blob/tree 均拦截,删除敏感命名的远端引用放行(同名重新推送仍拦截)〕 | evidence/TC-02.log,写法 (a) |
| TC-03 | A | 同上 | `evidence.sh TC-03 -- .venv/bin/python -m pytest scripts/redaction/tests -v -k "rewrite or verify"` | 全部通过。合成仓库端到端(敏感词在提交信息/内容/文件名;stub 路径;二进制替换;引用早先提交 id;本任务式改名)`run` + `verify` PASS、id 已映射、stub 与二进制在中间提交亦已替换、改名文件未被映射后的 D 删除;**真实路径撞名 → run exit 1 且不创建目标库**;**额外分支 + 附注标签**全部改写且 verify PASS、只传 master 时目标库只有 master;**中间提交被篡改而 tip 树完全相同 → verify 判 FAIL** | evidence/TC-03.log,写法 (a) |
| TC-04 | A | 当前树已脱敏 | `evidence.sh TC-04 -- python3 scripts/redaction/redact.py check --tree --summary`(使用本机私有规则)〔第 02 轮修复(R-01):改为 `bash -c` 依次执行该命令与 `check --summary --files <本仓库全部未跟踪新增文件,排除建议目录>`,新增的工具、测试、决策与本任务产物一并扫描〕 | exit 0;两次扫描均 `0 hit(s)`(扫描同时校验说明桩路径内容) | evidence/TC-04.log,写法 (a) |
| TC-05 | A | 同上 | `evidence.sh TC-05 -- bash .ai/2026-11-02/public-repo-redaction/evidence/tree-consistency-check.sh` | exit 0:`apply-tree` 再跑一遍零改动(幂等);`selftest` 0 problem;说明桩 20 个且逐个等于 `stub-text`;改名 2 个且均为说明桩;C 节 31 个正文文件**逐个等于 HEAD 版本经规则改写**(证明无规则外的手改,`apps/` 只动了含别名的字面量/注释);改名所在任务目录内 `evidence/` 引用零断链 | evidence/TC-05.log,写法 (b) |
| TC-06 | A | 同上 | `evidence.sh TC-06 -- bash .ai/2026-11-02/public-repo-redaction/evidence/history-dry-run.sh`:克隆本仓库 → 同步当前工作区并在克隆中提交 → `rewrite_history run --ref master` + `verify --ref master` → 检查改写后 tip 中 rawf-evidence v1 证据结构 | exit 0;verify 六项 PASS(提交数与映射、引用、逐提交元数据、逐提交整棵树、全历史零命中、旧 id 零残留);2026-11-02 升级任务的 8 个 v1 证据文件在改写后头部 `git_head` 已映射为新 id、`bytes:` 仍等于正文字节数;〔第 02 轮修复(R-01):`scripts/redaction/` 与 `.githooks/` 全部文件改写前后 blob 完全相同,证明规则不改动工具与测试语义〕只打印统计 | evidence/TC-06.log,写法 (b) |
| TC-07 | A | 同上 | `evidence.sh TC-07 -- bash -c 'corepack pnpm --filter web exec vitest run "app/(app)/schedules" components/layout && .venv/bin/python -m pytest apps/agent/tests/test_logcap.py apps/agent/tests/test_scrapyd_stats.py -q && .venv/bin/ruff check apps packages scripts'` | 全部通过(改了夹具的 web/agent 用例仍绿;ruff 无告警) | evidence/TC-07.log,写法 (a) |
| TC-08 | A | 同上 | `evidence.sh TC-08 -- bash .ai/2026-11-02/public-repo-redaction/evidence/docs-check.sh` | exit 0:0024 存在且四段齐全、六类与例外条款在;索引含 0024;AGENTS.md 含脱敏硬规则与 `.ai/` 例外;docs/README.md 含例外;0020 含 D-7 且既有正文未改(前缀断言);CONTRIBUTING 含两钩子说明;架构目录树与 pyproject 已更新;相对链接全部可解析 | evidence/TC-08.log,写法 (b) |
| TC-09 | A | 同上 | `evidence.sh TC-09 -- bash .ai/2026-11-02/public-repo-redaction/evidence/changeset-check.sh` | exit 0:本任务目录以外的新增恰为 A 表 7 个(本任务目录的 plan、评审记录、辅助脚本与证据随任务入库,不计);修改含 B 表 7 个;C 节按 HEAD 路径计 52 个(修改 50 + 改名 2);`apps/` 恰为 C 节 5 个;仓库根与其它目录只改 B 表文件;未跟踪建议目录内容未变且仍未跟踪 | evidence/TC-09.log,写法 (b) |
| TC-10 | A | 同上 | `evidence.sh TC-10 -- bash .ai/2026-11-02/public-repo-redaction/evidence/refs-scope-check.sh` | exit 0:`git ls-remote origin` 的引用名只有 `HEAD` 与 `refs/heads/master`(只打印引用名);本地未推送的 5 个引用相对 master 的提交 **去重并集 = 28**(= `--all` 95 − master 67),且对每个引用分别 `redact.py check --range master..<ref> --summary` 的**私有业务规则**命中均为 0(各范围有重叠,逐个之和为 64,只作信息打印;通用规则命中只打印数量)〔用户裁决 2026-11-02:原断言为全规则 0 命中;实测通用规则命中 15 处,均为早期代码/文档中的示例地址,不含业务信息,改为业务规则零命中;见实现记录 D-01〕 | evidence/TC-10.log,写法 (b) |
| TC-11 | A | 同上 | `evidence.sh TC-11 -- python3 .ai/2026-11-02/public-repo-redaction/evidence/screenshot-mask-check.py` | exit 0:工作区 PNG 的 sha256 = 私有打码文件;HEAD 中原 blob id = 私有规则 `blob` 条目的 id;尺寸不变;8 个遮盖矩形**以外**的像素与原图逐像素相同,矩形**以内**为单一填充色(证明只遮了名称列与模板列,徽标/开关/操作菜单原样保留) | evidence/TC-11.log,写法 (b) |
| TC-12 | C | 同上 | 人工打开原图与打码图对照 | 4 行调度名与 4 行模板名的文字全部被遮住、无残留笔画;"已自动禁用"徽标、启用开关、并发上限、cron、操作菜单完整可见,原任务"长名截断后徽标与菜单不被挤掉"的结论仍可从图中读出 | 实现者陈述 + 锚点:私有打码文件 `~/.local/share/dopilot-private/schedules-after-fix.masked.png`、遮盖矩形坐标见 TC-11 脚本。**不可自动化理由**:"文字是否被完全遮住、版面结论是否仍可辨认"是视觉判断,TC-11 只能证明改动局限在矩形内,无法判断矩形是否盖全了字形 |

A 档 11 条、C 档 1 条(≤ 1/3)、B 档 0 条。D 节(提交后的真实改写与推送)的核验结果写入
`history-rewrite.md` 并在对话中汇报,不作为送审用例(它发生在评审与提交之后)。

## 风险与回滚

- **误伤**:字面量带词界与驼峰边界,长词在前;盘点阶段已在临时克隆上通读全部正文改动;
  TC-05 断言 C 节改动全部由规则产生;TC-07 回归受影响的测试。
- **漏网**:规则基于盘点,未登记的新站点名不会被识别——这是词表机制的固有限制;决策中写明
  "新接入的数据源须先登记私有规则";通用规则兜底内网地址。
- **历史改写不可逆**:源仓库不动,先 bundle 备份;verify 逐提交全量比对,六项全过才进入强推
  确认;强推用 `--force-with-lease` 绑定当前远端 id。回滚 = 用 bundle 恢复后再强推(会让旧内容
  重新公开,仅在改写出错时考虑)。
- **旧 id 指向未脱敏悬空提交**:内容中的 id 已映射为新 id;GitHub 侧悬空提交只能等 GC 或找
  Support,列为残留。
- **钩子依赖 python3**:无 python3 时 fail-closed;外部贡献者可 `DOPILOT_REDACTION_RULES=none`。
- **历史证据完整性**:被脱敏的旧证据不再是逐字节原始输出(旧格式证据本无机器校验)。现有
  rawf-evidence v1 证据(仅 2026-11-02 升级任务)不含业务词,正文不变;但其头部 `git_head` 记录的
  本仓库提交 id 会被映射为等长新 id——`bytes:` 只计正文,结构仍有效,TC-06 复核。
