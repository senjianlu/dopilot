---
task: deploy-kubernetes-agent
round: 01
date: 2026-07-24
---

# 实现记录:第 01 轮

按 approved plan 实现:`deploy/kubernetes/agent/` 落通用版 agent 接入清单
(去 Vault、凭据脱敏),回写 AGENTS.md 与 docs/architecture/05-deployment.md。
纯部署清单 + 文档,无运行时行为变更。

## 改动清单

| 文件 | 状态 | 摘要 |
|---|---|---|
| deploy/kubernetes/agent/statefulset.yaml | 新增 | Namespace `dopilot` + StatefulSet `dopilot-agent`。以用户现网 yaml 为底:**删** Vault init/sidecar 容器、vault-* volumes、serviceAccountName、Consul env;**脱敏** `DOPILOT_AGENT_TOKEN`/`DOPILOT_REDIS_URL` → `secretKeyRef(dopilot-agent, agent-token/redis-url)`,`DOPILOT_SERVER_URL` → 占位 + 必填注释;**保持** hostNetwork/ClusterFirstWithHostNet、控制面排除 nodeAffinity + 每节点一实例 podAntiAffinity、exec 探针 `dopilot-agent-healthcheck`、`AGENT_ID` fieldRef pod 名、replicas 2、20Gi volumeClaimTemplate。镜像 `rabbir/dopilot:latest` |
| deploy/kubernetes/agent/secret.example.yaml | 新增 | Secret `dopilot-agent` 占位(`stringData`:agent-token / redis-url,值为 `<...>`);注释含 imperative `kubectl create secret` 与 server 侧 `agent-token print` 获取法 |
| deploy/kubernetes/agent/README.md | 新增 | 部署步骤、必填项、安全口径(纯出站、token≠加密、永不注入 admin token)、PVC 即磁盘硬顶且对应仪表盘 agent 板块、**待办**(容器 resources / ephemeral-storage / kubelet container-log-max-size,附 k3s config.yaml 片段)、Vault 等 secrets sidecar 属站点扩展 |
| AGENTS.md | 改 | 目录约定 `deploy/` 行补 kubernetes(AGENTS.md:93) |
| docs/architecture/05-deployment.md | 改 | 新增「Kubernetes / k3s(参考清单)」小节(05-deployment.md:39-58):必填项、PVC 硬顶对应仪表盘、日志轮转归 kubelet、去 sidecar 口径 |

明确未动:apps/、packages/、协议、配置加载器、CI、compose 文件、
deploy/docker/;未新增顶级目录(kubernetes 在既有 deploy/ 下)。

## 测试结果

| 编号 | 档位 | 结果 | 证据 |
|---|---|---|---|
| TC-01 | A | pass | evidence/tc01-yaml-parse.txt(3 文档解析 OK,kind 集={Namespace,Secret,StatefulSet},exit 0) |
| TC-02 | A | pass | evidence/tc02-struct-assert.txt(token/redis 均 secretKeyRef 且对应 secret 键、单容器、无 SA/initContainers/volumes、探针=healthcheck、PVC 20Gi;ALL ASSERTIONS PASSED) |
| TC-03 | A | pass | evidence/tc03-sanitize-grep.txt(a:真实 token/密码前缀/tailscale.internal/CONSUL_ 键 0 命中 exit 1;b:vault/consul 词仅现于注释与 README 散文,YAML 内非键值) |
| TC-04 | A(边界) | pass | evidence/tc04-grep-selftest.txt(scratchpad 诱饵文件被同一模式命中 exit 0 → TC-03a 的 0 命中为真;诱饵不在仓库) |
| TC-05 | A | pass | evidence/tc05-healthcheck-entrypoint.txt(pyproject console-script 与探针引用同名) |
| TC-06 | B | pass | AGENTS.md:93;docs/architecture/05-deployment.md:39-58 |
| TC-07 | A | pass | evidence/tc07-readme-todos.txt(resources / ephemeral-storage / container-log-max-size 均命中) |

全部通过。无 pytest/vitest(纯清单 + 文档,无运行时变更)。

## 与方案的偏差

1. **TC-02 的去 Vault 校验由"原文扫描无 vault/consul 词"改为结构化断言**
   (无 serviceAccountName / initContainers / volumes)。原因:通用版清单在
   **注释**里正当地保留了"本版不含 Vault/Consul,需要请自行叠加"的说明,
   原文扫描会把这些说明性注释误判为残留。结构化断言直接证明清单实体里没有
   任何 Vault init/sidecar/SA/卷,更贴合"去 Vault"的真实意图,且更强。

2. **TC-03 由单一 grep 拆为 03a/03b 两部分**。03a 对真实机密(token/密码
   前缀)、内网主机名(tailscale.internal)、Consul 环境变量键(CONSUL_HOST/
   PORT)断言 0 命中——这是"脱敏"的实质。03b 对 `vault`/`consul` 词做枚举,
   断言其在 YAML 内只出现于注释行(README.md 散文豁免)。原因同偏差 1:清单
   为指导用户扩展而在注释/README 里正当提及 Vault,不能作为泄漏。拆分后脱敏
   意图不降反强(明确区分"活配置泄漏"与"说明性提及")。

3. **TC-07 关键词 `containerLogMaxSize` → `container-log-max-size`**。前者是
   KubeletConfiguration 的 YAML 字段名,后者是 k3s `kubelet-arg` 用的命令行
   flag 形式;README 采用 k3s 实际可用的 flag 形式,grep 关键词随之调整。
   "容器日志轮转待办存在"这一意图完全满足。

以上均为自测手段/文案层细化,不动方案核心(目录、清单形态、脱敏范围、
待办清单),按 rawf-implement 记录于此,不停机。
