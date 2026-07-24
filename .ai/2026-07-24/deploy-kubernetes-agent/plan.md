---
status: approved
task: deploy-kubernetes-agent
date: 2026-07-24
approved_at: 2026-07-24 10:05
# 用户于 review-round-03 后明确授权把修复轮上限由默认 3 放宽到 6
# (仅剩 TC-04 一条证据格式 blocker)。
impl_fix_max_rounds: 6
---

# 方案:deploy/kubernetes 目录落地(本期仅 agent 清单)

## 背景与目标

用户现网以 k3s StatefulSet 运行 dopilot agent(自管 yaml,含其基础设施特有
的 Vault init/sidecar 与明文凭据)。仓库 `deploy/` 目前只有 docker compose
编排,K8s 用户没有官方参考清单。

目标:在 `deploy/kubernetes/agent/` 落一套**通用版** agent 接入清单
(与 `docker-compose.agent.yml` 同一角色:agent-only 接入远端 server),
口径对齐现网结构但完成脱敏与去 Vault 化;并回写 AGENTS.md / docs 的
deploy 目录说明。

范围决策(已与用户对齐,2026-07-24):

1. 只入库通用版:**不含** Vault init/sidecar、Consul env、vault 相关
   volumes/serviceAccount;用户的 Vault 部分继续留在现网自管。
2. **先原样入库**:保持现网结构(hostNetwork、控制面排除 + pod 反亲和、
   exec 探针 `dopilot-agent-healthcheck`、20Gi PVC volumeClaimTemplate、
   replicas 2、`AGENT_ID` 取 `metadata.name`);防膨胀增强(agent 容器
   resources、ephemeral-storage 限额、kubelet containerLogMaxSize 轮转)
   本期**不写进清单**,记入 README 待办。
3. 凭据脱敏:`DOPILOT_AGENT_TOKEN`、`DOPILOT_REDIS_URL` 走 K8s Secret
   引用(`secretKeyRef`),仓库另放 `secret.example.yaml` 占位示例;
   任何真实 token/密码/内网主机名(`*.tailscale.internal`)不得入库。
4. 镜像用仓库统一镜像 `rabbir/dopilot:latest`(docs/architecture/05 口径),
   README 注明可换自有衍生镜像。

## 改动范围

新增(4 个文件):

| 文件 | 内容 |
|---|---|
| `deploy/kubernetes/agent/statefulset.yaml` | Namespace(`dopilot`)+ StatefulSet:单容器 `agent`,`command: ["dopilot-agent"]`,env(`AGENT_ID` fieldRef、`AGENT_WORKDIR=/agent-data`、`DOPILOT_SERVER_URL` 占位、token/redis 走 secretKeyRef),readiness/liveness exec 探针,hostNetwork + `ClusterFirstWithHostNet`,nodeAffinity 排除控制面 + 每节点一实例反亲和,`volumeClaimTemplates` 20Gi;注释说明 serviceName 占位口径(纯出站无 Service)与各处可调项 |
| `deploy/kubernetes/agent/secret.example.yaml` | Secret `dopilot-agent`(`stringData`:`agent-token`、`redis-url`),值为 `<...>` 占位 + 获取方式注释(server 侧 `dopilot-server agent-token print`) |
| `deploy/kubernetes/agent/README.md` | 部署步骤(创建 secret → apply)、与 compose 接入栈的口径对照(必填项、纯出站、永不注入 admin token)、**待办清单**:agent 容器 resources / ephemeral-storage 限额 / kubelet `containerLogMaxSize` 轮转(k3s `/etc/rancher/k3s/config.yaml` kubelet-arg 示例)/ Vault 等 secrets 注入属用户侧扩展 |
| （目录本身) | — |

修改(2 个文件):

| 文件 | 内容 |
|---|---|
| `AGENTS.md` | 目录约定表 `deploy/` 行:"Dockerfile 之外的编排(compose)" → 补 kubernetes |
| `docs/architecture/05-deployment.md` | 新增「Kubernetes(参考清单)」小节:目录指引、与 compose agent 栈同口径(token/URL 必填、纯出站无端口)、PVC 即 agent 磁盘硬顶且仪表盘 agent 板块显示的就是该卷用量/容量、容器日志轮转由 kubelet 负责(非 docker json-file) |

明确不动:apps/ 与 packages/ 源码、协议、配置加载器、CI、compose 文件、
`deploy/docker/` 任何内容;不新增顶级目录(kubernetes 在既有 `deploy/` 下,
无需新决策记录)。

## 实现方案

- **statefulset.yaml 结构**(以用户现网 yaml 为底,做三类变换):
  1. 删:Vault init/sidecar 容器、vault-* volumes、`serviceAccountName`
     (仅为 Vault k8s auth 而设)、Consul env;
  2. 脱敏:`DOPILOT_AGENT_TOKEN`/`DOPILOT_REDIS_URL` 改
     `valueFrom.secretKeyRef`(Secret `dopilot-agent`,key `agent-token` /
     `redis-url`);`DOPILOT_SERVER_URL` 改占位
     `http://<server-host-or-dns>:5000` 并注释必填口径(与
     compose agent 栈 `:?` 快速失败同义,K8s 无等价机制故靠注释+README);
  3. 保持:hostNetwork/dnsPolicy、affinity 两段、exec 探针参数、
     `imagePullPolicy: Always`、20Gi PVC、replicas 2、`serviceName` 占位
     注释。镜像改 `rabbir/dopilot:latest`。
- **Namespace**:`namespace: dopilot` 由 statefulset.yaml 顶部附
  Namespace 文档块(`---` 多文档),避免单独文件;README 写明已有
  namespace 时可删该段。
- **安全口径**(照抄 compose agent 栈注释精神):agent 永不注入
  `DOPILOT_ADMIN_API_TOKEN`;token 认证≠传输加密,跨主机需私网/VPN/TLS。
- **README 待办**即用户已拍板"本期不做"的增强项,逐条列出并给出将来
  加法(yaml 片段级提示),不展开实现。
- **docs 回写**与代码同一提交(收尾时执行,遵守硬规则)。

## 测试用例

校验脚本一次性写在命令行内(python -c / grep),不落仓库;完整输出落
`evidence/`。

| 编号 | 档位 | 前置条件 | 步骤 | 预期结果 | 证据形态 |
|---|---|---|---|---|---|
| TC-01 | A | 清单已写 | `python` 遍历 `deploy/kubernetes/agent/*.yaml` 逐文件 `yaml.safe_load_all` 并打印各文档 `kind` | 全部解析成功,退出码 0;kind 集合 = {Namespace, StatefulSet, Secret} | evidence/tc01-yaml-parse.txt(命令+输出+退出码) |
| TC-02 | A | 同上 | `python -c` 结构断言:StatefulSet 中 `DOPILOT_AGENT_TOKEN`/`DOPILOT_REDIS_URL` 均为 `secretKeyRef` 且 (name,key) ∈ secret.example.yaml 的 `stringData` 键;容器数 == 1;无 `serviceAccountName`;探针为 exec `dopilot-agent-healthcheck`;PVC 请求 20Gi | 断言全过,退出码 0 | evidence/tc02-struct-assert.txt |
| TC-03 | A | 同上 | `grep -rn` 在 `deploy/kubernetes/` 中搜真实凭据前缀(`xUXNML4`、`dCa7nJn2`)与 `tailscale.internal`、`CONSUL_`、`vault`(不区分大小写) | 全部 0 命中(grep 退出码 1) | evidence/tc03-sanitize-grep.txt |
| TC-04 | A(边界) | 同上 | 自检脱敏检测有效性:把含真实 token 前缀的诱饵文件写入 scratchpad,同一 grep 模式扫之 | 命中(退出码 0),证明 TC-03 的 0 命中非模式失效所致;诱饵文件不在仓库内 | evidence/tc04-grep-selftest.txt |
| TC-05 | A | 探针命令须真实存在 | `grep -n "dopilot-agent-healthcheck" apps/agent/pyproject.toml deploy/kubernetes/agent/statefulset.yaml` | 两处均命中:console-script 定义与探针引用同名 | evidence/tc05-healthcheck-entrypoint.txt |
| TC-06 | B | 文档已回写 | 查看 AGENTS.md deploy 行与 docs/architecture/05-deployment.md 新小节 | AGENTS.md `deploy/` 行含 kubernetes;05-deployment.md 有「Kubernetes」小节且含 PVC 硬顶与 kubelet 日志轮转口径 | 实现记录引用 `文件:行号` |
| TC-07 | A | README 已写 | `grep -n -i "resources\|ephemeral-storage\|containerLogMaxSize" deploy/kubernetes/agent/README.md` | 三个待办关键词均命中(与用户拍板的"本期不做、记待办"一致) | evidence/tc07-readme-todos.txt |

C 档 0 条(无人工交互项)。本任务无运行时行为变更(纯部署清单 + 文档),
不涉及 pytest/vitest 回归;不新增顶级目录,无需新决策记录。

## 风险与回滚

- **清单未经真实集群验证**:仓库侧只能做语法/结构校验(kubectl 离线
  dry-run 需 API server,已实测不可行);逻辑口径以用户现网正在运行的
  同构 yaml 为底,风险低。用户 apply 后如有出入,属后续修订。
- **占位符不会被探针暴露(经 review-round-04 plan-blocker 订正)**:
  `DOPILOT_SERVER_URL` 占位若用户忘改,**不会**被 readiness/liveness 探针
  拦住——`dopilot-agent-healthcheck` 只校验配置能否加载与本地 scrapyd 应答
  (apps/agent/dopilot_agent/healthcheck.py),`server_url` 是无 URL 校验的
  普通字符串(settings.py:29),探针不测 server 连通性。故占位 URL 下 agent
  照常启动、Pod 变 Ready,但心跳连不上 server、**从未真正入群**——故障形态
  是"看着 Ready 实则未入群",须在 server 侧确认(节点是否出现在
  `nodes.last_seen_at` / 运维仪表盘 agent 板块),不能凭 Pod Ready 判定入群。
  文档(README「必填项」、statefulset 注释、05-deployment)按此口径如实描述,
  并提示运维改完 URL 后到 server 侧验证入群。本期不加启动期 URL 校验(用户
  拍板"只改文档口径,不扩到 agent 代码")。
- 回滚:纯新增目录 + 两处文档行级修改,`git revert` 单提交即可,无状态
  迁移。
