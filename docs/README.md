# docs:持久设计文档

本目录与 `.ai/` 的分工:

- **docs/ 存"现在为什么是这样"**:架构现状、已确认的决策及其理由。
  内容随决策演进而更新,永远反映当前真相。
- **.ai/ 存"当时怎么做的"**:每个任务的方案、实现记录、评审轮次。
  历史只增不改,是过程痕迹,不是现状描述。

## 组织

| 位置 | 内容 |
|---|---|
| `architecture/` | 架构目录:`README.md` 做汇总和导航,细节按主题下沉到同目录文件 |
| `decisions/` | 决策记录,一事一文,`NNNN-<slug>.md` |

## 回写纪律

任务改变了架构、或新增/推翻了关键决策时,须在收尾(/rawf-report)前
把变化写回本目录,并与代码同一提交——评审通过≠任务结束,文档回写完
才算。

## 历史

本仓库 2026-07-24 前采用 Codex+Claude 双代理治理(`docs/agent-governance/`)
与阶段制文档(`docs/phases/`、`docs/dopilot/`、`docs/refactor/`,以及作为
scrapydweb 行为分析的旧 `docs/architecture/`)。迁移到 rawf 工作流时
(见 [`decisions/0018`](decisions/0018-adopt-ai-workflow-template.md)),
长期有效的事实已收敛进 `architecture/` 与 `decisions/`,其余文档已删除,
git 历史可查。
