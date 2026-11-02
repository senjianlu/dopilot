---
task: upgrade-ai-workflow-template-v1-2-1
date: 2026-11-02
rounds: 1
verdict: pass
---

# 任务小结:rawf 工作流从 ai-workflow-template v1.0.0 增量升级到 v1.2.1

## 改动

| 文件 | 摘要 |
|---|---|
| `.ai-workflow/`(13 个) | 从 v1.2.1(`246db2af…96cc`)整体拷入:评审脚本改 flock 锁 + 看门狗 + stdin 接 /dev/null;新增 `evidence.sh` / `evidence-check.sh`;plan 评审分轮模式与 `__minors`;prompts/schemas/templates 同步;review-standards 重新施加 D-1;TEMPLATE-VERSION 记 1.2.1 / 2026-11-02 |
| `.claude/hooks/gate-review.sh`、`.claude/skills/rawf-*`(5 个) | 从 v1.2.1 整体拷入:评审进行中 Stop hook 放行;skills 承接证据留证、范围自省、后台评审 |
| `CLAUDE.md`、`AGENTS.md`、`.gitignore` | 人工合并:plan 评审默认 5 轮、两条新硬规则、锁文件忽略;模板决策引用按新增偏离 D-6 写作"模板决策 00NN" |
| `docs/decisions/0020`、`docs/decisions/README.md` | 追加升级修订记录与 D-6;索引行标注升级 |

## 评审历程

| 轮次 | 结论 | 关键问题 |
|---|---|---|
| plan 第 01 轮 | pass | 无 |
| 实现第 01 轮 | pass | 无(新版 review.sh 首跑,evidence-check 前置核验 8/8 OK) |

## 范围核对

- 追加类偏差:无(D-01/D-02 为测试覆盖面扩展的"替代",不改变用例意图)。
- 评审「范围核对」节:无。
- 停车场:① 建议模板上游把 `docs/decisions/00NN` 改为显式"模板决策",从源头消除 D-2/D-6 类偏离——用户已预授权提交,本条随汇报交用户决定是否向模板提 issue;② 更新本机记忆"后台评审卡 stdin"为已由 v1.0.1 修复(仓库外,收尾时完成)。

## 遗留 minor 及处置

无。
