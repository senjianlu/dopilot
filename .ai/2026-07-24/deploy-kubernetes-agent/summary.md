---
task: deploy-kubernetes-agent
date: 2026-07-24
rounds: 5
verdict: pass
---

# 任务小结:deploy/kubernetes 目录落地(本期仅 agent 通用清单)

用户现网以 k3s StatefulSet 运行 dopilot agent(自管 yaml,含其特有的 Vault
init/sidecar 与明文凭据),仓库 `deploy/` 此前只有 docker compose。本任务在
`deploy/kubernetes/agent/` 落一套**通用版** agent 接入清单(对标
`docker-compose.agent.yml` 角色:纯出站 agent 接入远端 server),以现网结构
为底完成去 Vault 化 + 凭据脱敏,并回写 AGENTS.md 与部署文档。防膨胀增强
(容器 resources / ephemeral-storage / kubelet 日志轮转)按用户拍板本期只
记 README 待办,不写进清单。

## 改动

新增 3 文件 + 修改 2 文件(+ .ai 任务目录过程产物)。

| 文件 | 摘要 |
|---|---|
| deploy/kubernetes/agent/statefulset.yaml(新) | Namespace `dopilot` + StatefulSet:单容器 agent,`command:[dopilot-agent]`;去 Vault init/sidecar、Consul env、serviceAccountName;token/redis 走 `secretKeyRef(dopilot-agent)`,`DOPILOT_SERVER_URL` 占位 + 必填注释(如实说明探针不测 server 连通性、占位下 Pod 仍 Ready 但未入群);保持 hostNetwork、控制面排除 + 每节点一实例反亲和、exec 探针 `dopilot-agent-healthcheck`、`AGENT_ID` fieldRef pod 名、replicas 2、20Gi PVC;镜像 `rabbir/dopilot:latest` |
| deploy/kubernetes/agent/secret.example.yaml(新) | Secret `dopilot-agent` 占位(agent-token / redis-url);注释含 imperative `kubectl create secret` 与 server 侧 `agent-token print` 获取法;真值绝不入库 |
| deploy/kubernetes/agent/README.md(新) | 部署四步(namespace→secret→改 URL→apply)、必填项与安全口径(纯出站、token≠加密、永不注入 admin token、入群须 server 侧确认)、PVC 即磁盘硬顶对应 `/maintenance` agent 板块、待办(resources / ephemeral-storage / kubelet containerLogMaxSize 附 k3s config 片段)、secrets 注入 sidecar 属站点扩展 |
| AGENTS.md | 目录约定 `deploy/` 行补 `kubernetes/` K8s 参考清单 |
| docs/architecture/05-deployment.md | 新增「Kubernetes / k3s(参考清单)」小节:必填项、探针能力口径、PVC 硬顶对应仪表盘、日志轮转归 kubelet、去 sidecar |

未动:apps/(用户裁定不加启动期 URL 校验)、packages/、协议、CI、compose、
deploy/docker/;未新增顶级目录(kubernetes 在既有 deploy/ 下,无需新决策记录)。

## 评审历程

Plan:≤10 文件,未走 plan 评审闸。代码评审 5 轮(修复轮上限经用户一次
授权由默认 3 放宽到 6)。

| 轮次 | 结论 | 关键问题 |
|---|---|---|
| 01 | fail | R-01 README 部署顺序 namespace 未先建(真实缺陷);R-02 TC-01/02/04 A 档证据不完整;R-03 TC-03、R-04 TC-07 在实现记录里单方面改写了 plan 验收条件 |
| 02 | fail | R-01 TC-04 证据仍把诱饵创建写成 `printf '...'` 省略 payload |
| 03 | fail | R-01 TC-04 用 set -x,但 xtrace 不显示 `>` 重定向,未证明诱饵文件创建 |
| 04 | **pass** | 实现层零问题;单列 plan-blocker:plan/文档错诰探针能暴露坏 server URL |
| 05 | **pass** | 无 |

修复要点累积:部署顺序改 namespace 优先;去掉清单里 Vault/Consul 字样使
TC-03 回归 plan 原契约(0 命中);README 补 `containerLogMaxSize` 字段名使
TC-07 回归;TC-04 证据以字面命令 + `ls -l` + `cat` 决定性证明诱饵创建;
plan-blocker 按用户裁定"只改文档口径"订正 plan 风险节 + 3 处文档,如实说明
"占位 URL 下 Pod Ready 但未入群,须 server 侧确认"。

## 遗留 minor 及处置

review-round-05 问题清单为空,无 minor/major/blocker,无遗留项。

review-round-04 的 plan-blocker(探针不暴露坏 URL)已按用户裁定以文档订正
关闭;是否加启动期 URL 校验作为**可选后续增强**(非本期范围),未立项。
