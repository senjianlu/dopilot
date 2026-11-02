---
task: public-repo-redaction
round: 02
date: 2026-11-02
---

# 实现记录:第 02 轮

## 本轮改动

| 文件 | 改动摘要 |
|---|---|
| `scripts/redaction/redact.py` | ① 通用规则文件缺失 → exit 2(fail-closed);② 新增 `Scan.file()`:匹配 `stub` 规则的路径只接受原样说明桩,否则记命中(输出固定文案,不回显内容);暂存/提交/工作区/`--files` 扫描全部经此入口;③ `scan_commits` 改用 `diff-tree -m`(合并提交对每个父提交都比较)并把 `T`(类型变更)纳入 `--diff-filter`,按 (blob, 路径) 去重;`scan_staged` 同样纳入 `T`;④ `check --push [REMOTE]`:新分支或远端旧 id 本地未知时,只排除 `refs/remotes/<REMOTE>/*` 上的提交,远端为 URL 或无跟踪引用时扫描完整待推历史;⑤ 工作区扫描与新增的 `check --files` 对符号链接读链接目标、不跟随;`apply-tree` 不跟随符号链接 |
| `.githooks/pre-push` | 把 git 传入的远端名(`$1`)交给 `check --push` |
| `scripts/redaction/tests/test_redact.py` | 夹具中 3 类真实词(某交易所名、某交易方式缩写、真实 appid)全部换成合成词(`c3d`、`QUOTE`、`4242`),本文件 `check --files` 零命中;新增 6 条反例(共 45 条):通用规则缺失、说明桩路径放无敏感词原始数据、`check --files` 扫未跟踪文件、只存在于合并结果中的敏感内容、敏感提交已在其它远端、普通文件改为指向敏感目标的符号链接 |
| `docs/decisions/0024-public-repo-redaction.md` | 机制段补:合并/类型变更/符号链接的扫描口径、说明桩路径强制、通用规则缺失同样拦截 |
| `.ai/2026-11-02/public-repo-redaction/plan.md` | TC-01/02/04/06 单元格就地标注第 02 轮修复所增的覆盖(见下表与偏差 D-04) |
| `.ai/2026-11-02/public-repo-redaction/evidence/history-dry-run.sh` | 增加"`scripts/redaction/` 与 `.githooks/` 改写前后 blob 完全相同"的断言 |

本机私有规则:为两个改名后的说明桩新路径各补 1 条 `stub` 规则(共 106 条,`selftest` 0 problem),
防止有人在新路径放回原始数据。

## 修复对照

| 评审问题编号 | 严重度 | 修复方式 |
|---|---|---|
| R-07 | blocker | 第 01 轮记录把 TC-02 选中数写成 19,证据实为 20——本轮所有数字直接取自 r02/r02b 证据原文(TC-02-r02b.log:"25 passed, 20 deselected"),并核对一遍 |
| R-01 | major | 夹具改为合成词;TC-04 增扫全部未跟踪新增文件(工具、测试、决策、本任务产物共 47 个文本,0 命中);TC-06 增断言:机制文件(含测试)改写前后 blob 完全相同,历史变换不会改动测试语义 |
| R-02 | major | `diff-tree -m`;新增反例 `test_hook_pre_push_scans_content_that_only_exists_in_a_merge` |
| R-03 | major | `check --push REMOTE`,只信任目标远端的跟踪引用;新增反例 `test_hook_pre_push_does_not_trust_other_remotes` |
| R-04 | major | `--diff-filter=AMT`,符号链接按目标扫描、不跟随;新增反例 `test_hooks_scan_symlink_targets_and_type_changes`(pre-commit、pre-push、`check --tree` 三处) |
| R-05 | major | 通用规则缺失 exit 2;新增反例 `test_hook_fails_closed_when_generic_rules_file_is_missing`(含 `DOPILOT_REDACTION_RULES=none` 场景) |
| R-06 | major | `Scan.file()` 说明桩强制;新增反例 `test_hook_stub_paths_only_accept_the_stub_notice`(pre-commit 与 `check --files` 均拦截,放入原样说明桩后通过) |

## 测试结果

| 编号 | 档位 | 结果 | 证据 |
|---|---|---|---|
| TC-01 | A | pass | TC-01-r02b.log(45 passed) |
| TC-02 | A | pass | TC-02-r02b.log(45 collected / 20 deselected / 25 selected,25 passed) |
| TC-03 | A | pass | TC-03-r02.log(45 collected / 40 deselected / 5 selected,5 passed) |
| TC-04 | A | pass | TC-04-r02b.log(已跟踪 953 个文本、6 个二进制 0 hit;未跟踪新增 47 个文本 0 hit) |
| TC-05 | A | pass | TC-05-r02.log |
| TC-06 | A | pass | TC-06-r02.log(68 个提交;文本 blob 改动 95、说明桩 40 处、二进制替换 1、改名路径 2、提交信息改动 5、旧 id 映射 40 处;verify 六项 PASS,逐提交比对 37,341 个文件版本零不符,全历史 2,697 项文本零命中(含说明桩路径强制);8 个 v1 证据结构有效;`scripts/redaction` 与 `.githooks` 共 7 个文件改写前后 blob 完全相同) |
| TC-07 | A | pass | TC-07-r02.log |
| TC-08 | A | pass | TC-08-r02.log |
| TC-09 | A | pass | TC-09-r02.log(C 节 52 = 修改 50 + 改名 2;apps/ 恰为 5 个) |
| TC-10 | A | pass | TC-10-r02.log(远端只有 HEAD 与 master;本地 5 个未推送引用私有业务规则命中均为 0) |
| TC-11 | A | pass | TC-11-r02.log |
| TC-12 | C | pass | 实现者陈述(同第 01 轮,打码文件未变):4 行调度名与 4 行模板名文字完全遮盖、无残留笔画;徽标、开关、并发上限、触发方式、cron、下次运行与操作菜单完整可见,原任务版面结论可读。锚点:`~/.local/share/dopilot-private/schedules-after-fix.masked.png`;矩形坐标见 `evidence/screenshot-mask-check.py` 的 `RECTS` |

## 与方案的偏差

| 编号 | 类型 | 内容 | 原因 | 处置 |
|---|---|---|---|---|
| D-01 | 收窄 | (沿用第 01 轮)TC-10 本地未推送引用断言改为私有业务规则零命中 | 见第 01 轮记录 | 已经用户确认(2026-11-02 约 17:35) |
| D-02 | 替代 | (沿用第 01 轮)`check --tree` 默认扫描工作区内容 | 见第 01 轮记录 | 已实现 |
| D-03 | 替代 | (沿用第 01 轮)pytest 命令附加 `-p no:cacheprovider` | 见第 01 轮记录 | 已实现 |
| D-04 | 替代 | TC-04 命令扩为"已跟踪 + 未跟踪新增"两次扫描;TC-06 脚本加机制文件不变断言;TC-01/02 覆盖面随修复扩大——plan 对应单元格已就地标注 | 实现评审 R-01~R-06 的修复要求;同一验收目标,覆盖更严,不放宽任何断言 | 已实现 |
| D-05 | 替代 | 一条新增测试改名为 `test_hook_stub_paths_only_accept_the_stub_notice`,使其落入 TC-02 的 `-k hook` 选择;TC-01/02/04 因此以 `-l r02b` 重新留证(r02 版本保留,只增不改) | 让 TC-02 证据覆盖 plan 中列出的"说明桩路径"场景 | 已实现 |

## 停车场

与第 01 轮相同:CI 接入(规则存 GitHub secret)、模板仓库脱敏、早期历史中的 `reference/scrapydweb`、
模板钩子扩展点。
