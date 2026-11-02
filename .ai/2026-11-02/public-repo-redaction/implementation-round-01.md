---
task: public-repo-redaction
round: 01
date: 2026-11-02
---

# 实现记录:第 01 轮

## 本轮改动

| 文件 | 改动摘要 |
|---|---|
| `scripts/redaction/redact.py` | 新增。规则解析(`lit` / `re` / `rewrite` / `stub` / `blob`)、词界 + 驼峰边界的大小写不敏感字面量、保持大小写形态的替换;`check --staged / --push / --range / --tree / --history`(`--summary` 只出计数)、`apply`、`apply-tree`、`stub-text`、`selftest`;pre-push 扫描引用名、附注标签说明(沿标签链逐层)与远端尚无的提交;二进制默认拦截;规则文件缺失/不可读/格式错误 exit 2 |
| `scripts/redaction/rewrite_history.py` | 新增。撞名前置检查 → fast-export/过滤/fast-import 到新裸库(支持多个 `--ref`、附注标签)、`get-mark` 逐提交取新 id 并映射正文中的旧 id、同提交内冗余 D/R 消解;`verify` 逐提交核对元数据与整棵树、引用与标签说明、全量零命中、旧 id 零残留 |
| `scripts/redaction/generic-rules.tsv` | 新增。RFC 1918 内网 IPv4、Tailscale 内网主机域名 |
| `scripts/redaction/tests/test_redact.py` | 新增。39 条 pytest,全部用合成词 |
| `.githooks/pre-commit`、`.githooks/pre-push` | 新增。调用 `redact.py check --staged / --push`,无 python3 时 fail-closed |
| `docs/decisions/0024-public-repo-redaction.md` | 新增。六类不得入库、证据写法、别名约定、机制、`.ai/` 脱敏例外、历史改写、被否备选、外部残留 |
| `AGENTS.md` | 通用硬规则新增"公开仓库脱敏";`.ai/` 只增不改补脱敏例外;目录约定 `scripts/` 补 redaction |
| `CONTRIBUTING.md` | 钩子段补 pre-commit / pre-push 脱敏检查与 `DOPILOT_REDACTION_RULES=none` |
| `pyproject.toml` | pytest `testpaths` 增 `scripts/redaction/tests` |
| `docs/README.md` | ".ai/ 历史只增不改"补脱敏例外 |
| `docs/decisions/README.md` | 索引增 0024 |
| `docs/decisions/0020-ai-workflow-template-version-anchor.md` | 修订小节追加 D-7(两个自有钩子) |
| `docs/architecture/README.md` | 目录树 `scripts/` 注释补 redaction |
| 当前树 52 个路径(`redact.py apply-tree` 产出) | 说明桩 20、打码截图 1、正文改写 31(`.ai/` 22、`apps/` 5、`docs/` 4)、其中 2 个说明桩随规则改名 |

本机私有物料(不入库):`~/.config/dopilot/redaction-rules.tsv`(104 条,权限 600;本轮把 4 条
appid 规则由 `rewrite` 改为可检测的 `re`)、`~/.local/share/dopilot-private/schedules-after-fix.masked.png`。

## plan 评审 minor 交接

`plan-review.sh __minors .ai/2026-11-02/public-repo-redaction` 汇总 6 条,均在 plan 修订中处理:

| 来源 | 内容 | 处置 |
|---|---|---|
| 01/R-05 | 验收命令脚本路径与仓库根工作目录不一致 | 已在 plan 修订中解决(统一从仓库根执行,写任务相对全路径) |
| 01/R-06 | 提交与强推步骤漏写二进制放行方式 | 已在 plan 修订中解决(D 节第 1、5 步) |
| 01/R-07 | "现有 v1 证据不受影响"表述不准确 | 已在 plan 修订中解决(区分正文与 `git_head` 头部映射,TC-06 复核) |
| 01/R-08 | docs/README.md 遗漏例外 | 已在 plan 修订中解决(B 表第 11 项),本轮实现 |
| 02/R-03 | TC-10 计数口径 | 已在 plan 修订中解决(去重并集 = 28) |
| 02/R-04 | TC-09 遗漏本任务目录例外 | 已在 plan 修订中解决 |

## 修复对照

第 1 轮,不适用。

## 测试结果

| 编号 | 档位 | 结果 | 证据 |
|---|---|---|---|
| TC-01 | A | pass | TC-01.log(39 passed) |
| TC-02 | A | pass | TC-02.log(`-k hook` 选中 19 条,全部通过) |
| TC-03 | A | pass | TC-03.log(`-k "rewrite or verify"` 选中 5 条,全部通过:端到端、撞名拒绝、多分支与附注标签、中间提交篡改被 verify 拦下、rewrite 规则不参与检测) |
| TC-04 | A | pass | TC-04.log(953 个文本、6 个二进制,0 hit) |
| TC-05 | A | pass | TC-05.log(apply-tree 第二遍零改动;selftest 0 problem;说明桩 20 个全部一致;改名 2 个均为说明桩;31 个正文文件全部等于 HEAD 版本经规则改写;改名所在任务目录 evidence/ 引用 5 处零断链) |
| TC-06 | A | pass | TC-06.log(68 个提交改写:文本 blob 改动 90、说明桩 38 处、二进制替换 1、改名路径 2、提交信息改动 5、旧 id 映射 34 处;verify 六项全部 PASS,逐提交比对 37,333 个文件版本零不符、全历史零命中、旧 id 零残留;2026-11-02 升级任务 8 个 v1 证据改写后 `bytes` 与正文一致、`git_head` 指向改写后库中的提交) |
| TC-07 | A | pass | TC-07.log(vitest 2 个文件 32 条通过;agent pytest 12 条通过;ruff 通过) |
| TC-08 | A | pass | TC-08.log |
| TC-09 | A | pass | TC-09.log(本任务目录外新增恰为 A 表 7 个;B 表 7 个均修改;C 节 52 = 修改 50 + 改名 2;apps/ 恰为 5 个;建议目录 19 个文件清单哈希不变且仍未跟踪) |
| TC-10 | A | pass | TC-10.log(远端只有 HEAD 与 master;本地 5 个未推送引用去重并集 28 个提交,私有业务规则命中均为 0;通用规则命中 0/3/2/15/15,均为早期代码与文档中的示例地址——按用户裁决只打印数量,见偏差 D-01) |
| TC-11 | A | pass | TC-11.log(工作区 PNG = 私有打码文件;原 blob 已登记;尺寸不变;矩形外差异 0 像素;矩形内 61,504 像素均为填充色且原图对应像素全部被覆盖) |
| TC-12 | C | pass | 实现者陈述:打码后逐行对照原图——4 行调度名与 4 行模板名的文字被完全覆盖,无残留笔画;"已自动禁用"徽标、启用开关、并发上限、触发方式、cron、下次运行与"⋯"操作菜单完整可见,原任务"长名截断后徽标与菜单不被挤出"的结论仍可读出。锚点:`~/.local/share/dopilot-private/schedules-after-fix.masked.png`;8 个遮盖矩形坐标见 `evidence/screenshot-mask-check.py` 的 `RECTS` |

## 与方案的偏差

| 编号 | 类型 | 内容 | 原因 | 处置 |
|---|---|---|---|---|
| D-01 | 收窄 | TC-10 对本地未推送引用的断言由"全规则 0 命中"改为"私有业务规则 0 命中,通用规则命中只打印数量" | 实测通用规则(内网 IP 正则)在这些从未推送的早期引用中命中 15 处,全是旧前端测试与 scrapydweb 参考代码中的示例地址,不含业务信息;这些引用按方案不改写 | **已经用户确认**(2026-11-02 约 17:35,对话中选择"改为业务规则零命中");plan TC-10 单元格已就地标注裁决 |
| D-02 | 替代 | `redact.py check --tree` 默认扫描对象由"暂存区"改为"工作区中已跟踪文件的实际内容"(`--rev REV` 仍扫提交) | 方案 TC-04 的语义是"当前树已脱敏";原型默认扫暂存区,在未暂存时会读到旧内容,与用例意图不符 | 已实现,TC-04 按新语义留证 |
| D-03 | 替代 | TC-01/02/03 的 pytest 命令附加 `-p no:cacheprovider` | 避免在仓库根写 `.pytest_cache`;不影响被测内容与断言 | 已在证据命令中如实体现 |

## 停车场

- 把脱敏检查接入 CI(规则文件存 GitHub secret),作为本机钩子之外的第二道闸。
- 模板仓库 `senjianlu/ai-workflow-template`(公开)含 14 个文件 23 处同类词,需在该仓库另做脱敏。
- 早期历史中的 `reference/scrapydweb` 第三方代码(与决策 0001 的参考边界相关),可另行评估是否从历史中移除。
- 模板上游:钩子目录缺少 consumer 扩展点(本仓库因此登记 D-7),可建议模板支持 `pre-commit.d/` 一类扩展机制。
