---
task: public-repo-redaction
date: 2026-11-02
rounds: 3
verdict: pass
---

# 任务小结:公开仓库信息脱敏机制 + 当前树与 git 历史脱敏

## 改动

| 文件 | 摘要 |
|---|---|
| `scripts/redaction/redact.py` | 检测/改写工具:私有规则 + 通用规则;`check --staged / --push / --range / --tree / --history / --files`、`apply`、`apply-tree`、`selftest`;说明桩路径强制、合并提交逐父比较、类型变更与符号链接按目标扫描、标签链逐层扫描名称与说明及最终对象、删除远端引用放行;规则文件缺失或出错一律 fail-closed |
| `scripts/redaction/rewrite_history.py` | 历史改写:撞名前置拒绝、fast-export/import 到新库、提交 id 映射;`verify` 逐提交核对元数据与整棵树、全量零命中、旧 id 零残留 |
| `scripts/redaction/generic-rules.tsv`、`tests/test_redact.py` | 通用规则;49 条测试(全部合成词) |
| `.githooks/pre-commit`、`.githooks/pre-push` | 提交与推送两处强制检查 |
| `docs/decisions/0024`(新)、`0020`(D-7)、`README.md`;`docs/README.md`;`docs/architecture/README.md` | 脱敏决策、模板偏离、索引与例外说明 |
| `AGENTS.md`、`CONTRIBUTING.md`、`pyproject.toml` | 公开仓库脱敏硬规则与 `.ai/` 例外;贡献者钩子说明;pytest 收录新测试 |
| 当前树 52 个路径 | 原始生产数据 20 个换说明桩(其中 2 个随规则改名)、截图打码 1 个、正文别名替换 31 个(`.ai/` 22、`apps/` 5 个仅测试夹具与注释、`docs/` 4) |

## 评审历程

| 轮次 | 结论 | 关键问题 |
|---|---|---|
| plan 第 01 轮 | fail | 公开历史的引用范围未定义;只核 tip 不核中间提交;钩子边界与失败路径缺验收;真实截图缺验收 |
| plan 第 02 轮 | fail | "别名 + 真实 appid"只改写不检测;pre-push 未扫附注标签 |
| plan 第 03 轮 | fail | 嵌套标签缺验收 |
| plan 第 04 轮 | pass | — |
| 实现第 01 轮 | fail | 测试夹具含真实词(TC-04 未扫新增文件);合并提交、其它远端、类型变更、通用规则缺失、说明桩路径五处扫描漏洞;记录与证据计数矛盾 |
| 实现第 02 轮 | fail | 内层标签名与 blob/tree 标签漏扫;删除敏感引用被拦;`apply-tree` 跳过符号链接;决策文档提前宣称已改写 |
| 实现第 03 轮 | pass | — |

## 范围核对

- 追加类偏差:无。
- 用户已确认的收窄:TC-10 对本地未推送引用只断言私有业务规则零命中(通用规则命中均为早期代码中的示例地址),2026-11-02 确认。
- plan 评审范围核对提出、经用户批准方案时确认的附加措施:正文与提交信息中的本仓库旧提交 id 映射为新 id。
- 用户决定不处理:作者邮箱(2026-11-02 选择"不改")。
- 停车场(交用户决定去向):① 脱敏检查接入 CI(规则存 GitHub secret);② 模板仓库 `ai-workflow-template` 同类词(14 个文件 23 处);③ 早期历史中的 `reference/scrapydweb`;④ 建议模板为钩子目录提供 consumer 扩展点。

## 遗留 minor 及处置

最后一轮评审无 minor;plan 评审各轮 minor(6 条)均已在 plan 修订中解决(见实现记录第 01 轮交接表)。

## 后续(本提交之后,强推前须用户确认)

按 plan D 节:bundle 备份 → `rewrite_history.py run/verify --ref master` → 停下请用户确认强推 →
同步本地、追加 `history-rewrite.md` 记录 → `--force-with-lease` 强推 → 从 GitHub 重新克隆复核。
