---
task: deploy-kubernetes-agent
round: 05
date: 2026-07-24
---

# 实现记录:第 05 轮(plan-blocker 订正轮)

review-round-04 判 **pass**(实现层零 blocker/major/minor),但单列一条
**plan-blocker(R-01)**:plan/文档错诰了 readiness 探针能力——声称占位
`DOPILOT_SERVER_URL` 忘改会让 Pod 停在 NotReady"自然暴露"。经核对
[healthcheck.py](../../../apps/agent/dopilot_agent/healthcheck.py) 只校验配置加载
+ 本地 scrapyd,[settings.py:29](../../../apps/agent/dopilot_agent/config/settings.py#L29)
`server_url` 是无 URL 校验的普通字符串,探针**不测 server 连通性**。故占位 URL
下 agent 照常起、Pod 变 Ready、但从未入群——故障是"看着 Ready 实则未入群"。

按硬规则 plan-blocker 不进入自动修复:已完整转述给用户,用户裁定
**"只改文档口径"**(退回 plan 修正措辞 + 文档,不扩到 agent 代码加启动校验)。
据此本轮:先订正 plan.md 风险节,再订正 3 处文档,使描述与真实故障形态一致。
测试契约不变(TC-01..07 无一条断言"探针暴露坏 URL")。

## 本轮改动文件

| 文件 | 改动 |
|---|---|
| .ai/.../plan.md | 风险节"占位符"条订正为真实故障形态(Pod Ready 但未入群、须 server 侧确认),注明 review-round-04 plan-blocker 来源与"本期不加启动校验"的用户裁定 |
| deploy/kubernetes/agent/statefulset.yaml | `DOPILOT_SERVER_URL` 注释(原"probe keeps the pod NotReady")订正:探针只校验 config+scrapyd,占位下 Pod 仍 Ready、agent 不入群,须 server 侧 nodes.last_seen_at 验证 |
| deploy/kubernetes/agent/README.md | 必填项段(原"exec 探针持续失败、Pod 停在 NotReady")订正为同口径,并指引到 `/maintenance` agent 板块确认入群 |
| docs/architecture/05-deployment.md | Kubernetes 小节必填项条(原"忘改会让 Pod 停在 NotReady 自然暴露")订正为同口径 |
| evidence/tc0{1,2,3,5,7}-*.txt | 因 statefulset.yaml/README 有编辑,重生成以反映 round-05 文件状态 |

未改:apps/agent 代码(用户裁定不加启动校验)、secret.example.yaml、
packages/、compose、CI;TC-04 证据 round-04 已达完整,未触碰。

## 测试结果

| 编号 | 档位 | 结果 | 证据 |
|---|---|---|---|
| TC-01 | A | pass | evidence/tc01-yaml-parse.txt(round-05 重生成;kind 集正确,exit 0) |
| TC-02 | A | pass | evidence/tc02-struct-assert.txt(round-05 重生成;ALL ASSERTIONS PASSED,exit 0) |
| TC-03 | A | pass | evidence/tc03-sanitize-grep.txt(round-05 重生成;0 命中 exit 1) |
| TC-04 | A(边界) | pass | evidence/tc04-grep-selftest.txt(round-04;字面命令含重定向 + ls -l + 命中/仓库 0 命中) |
| TC-05 | A | pass | evidence/tc05-healthcheck-entrypoint.txt(round-05 重生成;探针与 console-script 同名 exit 0) |
| TC-06 | B | pass | AGENTS.md:93;docs/architecture/05-deployment.md:39(Kubernetes 小节,含订正后口径 49-51 行) |
| TC-07 | A | pass | evidence/tc07-readme-todos.txt(round-05 重生成;plan 关键词均命中 exit 0) |

## 与方案的偏差

无。plan 风险节已随本轮订正,文档与之一致;测试契约未变。
