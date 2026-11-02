---
task: public-repo-redaction
round: 03
date: 2026-11-02
---

# 实现记录:第 03 轮

## 本轮改动

| 文件 | 改动摘要 |
|---|---|
| `scripts/redaction/redact.py` | ① `scan_push`:删除记录(本地 id 全零)在扫描引用名**之前**跳过——删除远端引用不发布任何内容,一律放行;② 沿标签链逐层检查头部 `tag` 名称(按路径规则扫描)与说明正文;标签最终指向 blob 时扫描其内容(二进制照常拦截),指向 tree 时扫描整棵树;`push_ranges` 对不能剥成提交的目标不再交给 `rev-list`;③ `apply-tree` 对符号链接不跟随:按规则改写链接目标字符串(重建链接),再与普通文件一样按规则改名;普通文件的处理抽成 `redact_file` |
| `scripts/redaction/tests/test_redact.py` | 新增 4 条(共 49 条):内层标签名敏感而外层引用名与各层说明干净仍拦截、轻量标签指向敏感 blob 与附注标签指向含敏感文件的 tree 均拦截且干净 blob 标签放行、敏感命名的远端引用可删除而同名重新推送仍拦截、`apply-tree` 改写符号链接路径与目标且不跟随、二次运行零改动 |
| `docs/decisions/0024-public-repo-redaction.md` | 标题与第 6 条改为待执行表述:本决策随当前树脱敏提交,之后改写公开历史、经维护者确认再强推,实施结果记录在本任务目录 `history-rewrite.md` |
| `docs/decisions/README.md` | 0024 索引行同步改为"公开历史随之改写" |
| `.ai/2026-11-02/public-repo-redaction/plan.md` | TC-01/02 单元格就地标注第 03 轮新增覆盖 |

## 修复对照

| 评审问题编号 | 严重度 | 修复方式 |
|---|---|---|
| R-01 | major | 标签链逐层扫描头部名称与说明;最终对象为 blob/tree 时扫描其内容;新增反例 `test_hook_pre_push_scans_inner_tag_names`、`test_hook_pre_push_scans_tags_that_point_at_blobs_and_trees` |
| R-02 | major | 删除记录先于引用名扫描跳过;新增反例 `test_hook_pre_push_lets_sensitive_refs_be_deleted`(删除放行、同名重新推送仍拦截) |
| R-03 | major | `apply-tree` 不跟随地改写符号链接目标并改名;新增 `test_apply_tree_redacts_symlink_path_and_target_without_following` |
| R-04 | minor | 0024 标题、第 6 条与索引行改为待执行表述;强推完成后在 `history-rewrite.md` 记录结果,0024 同步更新为已完成 |

## 测试结果

| 编号 | 档位 | 结果 | 证据 |
|---|---|---|---|
| TC-01 | A | pass | TC-01-r03.log(49 passed) |
| TC-02 | A | pass | TC-02-r03.log(49 collected / 21 deselected / 28 selected,28 passed) |
| TC-03 | A | pass | TC-03-r03.log(49 collected / 44 deselected / 5 selected,5 passed) |
| TC-04 | A | pass | TC-04-r03.log(已跟踪 953 个文本、6 个二进制 0 hit;未跟踪新增 61 个文本 0 hit) |
| TC-05 | A | pass | TC-05-r03.log |
| TC-06 | A | pass | TC-06-r03.log(68 个提交;verify 六项 PASS,逐提交比对 37,357 个文件版本零不符,全历史 2,713 项文本零命中,旧 id 零残留;8 个 v1 证据结构有效;`scripts/redaction` 与 `.githooks` 共 7 个文件改写前后 blob 完全相同) |
| TC-07 | A | pass | TC-07-r03.log |
| TC-08 | A | pass | TC-08-r03.log |
| TC-09 | A | pass | TC-09-r03.log |
| TC-10 | A | pass | TC-10-r03.log |
| TC-11 | A | pass | TC-11-r03.log |
| TC-12 | C | pass | 实现者陈述(同前两轮,打码文件未变):4 行调度名与 4 行模板名文字完全遮盖、无残留笔画;徽标、开关、并发上限、触发方式、cron、下次运行与操作菜单完整可见,原任务版面结论可读。锚点:`~/.local/share/dopilot-private/schedules-after-fix.masked.png`;矩形坐标见 `evidence/screenshot-mask-check.py` 的 `RECTS` |

## 与方案的偏差

| 编号 | 类型 | 内容 | 原因 | 处置 |
|---|---|---|---|---|
| D-01 | 收窄 | (沿用)TC-10 本地未推送引用断言改为私有业务规则零命中 | 见第 01 轮记录 | 已经用户确认(2026-11-02 约 17:35) |
| D-02 | 替代 | (沿用)`check --tree` 默认扫描工作区内容 | 见第 01 轮记录 | 已实现 |
| D-03 | 替代 | (沿用)pytest 命令附加 `-p no:cacheprovider` | 见第 01 轮记录 | 已实现 |
| D-04 | 替代 | (沿用并扩展)修复所增覆盖在 plan TC-01/02/04/06 单元格就地标注 | 实现评审修复要求;不放宽任何断言 | 已实现 |
| D-05 | 替代 | (沿用)第 02 轮的测试改名与 r02b 留证 | 见第 02 轮记录 | 已实现 |

## 停车场

与前两轮相同:CI 接入(规则存 GitHub secret)、模板仓库脱敏、早期历史中的 `reference/scrapydweb`、
模板钩子扩展点。
