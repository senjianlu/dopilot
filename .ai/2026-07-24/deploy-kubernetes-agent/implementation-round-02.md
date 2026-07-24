---
task: deploy-kubernetes-agent
round: 02
date: 2026-07-24
---

# 实现记录:第 02 轮(修复轮)

修复 review-round-01-fail 的 4 个 blocker(R-01..R-04)。修复轮上限默认 3,
本轮 NN=02 < 3,在范围内。核心处置原则:**让实现回归 plan 原测试契约**,
而非在实现记录里改写验收条件——由此 round-01 记录的三条"偏差"全部撤回。

## 修复对照

| 编号 | 严重度 | 修复方式 |
|---|---|---|
| R-01 | blocker | **真实缺陷**:README 部署顺序把"在 `dopilot` namespace 建 Secret"排在"namespace 创建"之前,全新集群会报 namespace not found。改为四步显式顺序:① `kubectl create namespace dopilot` → ② 建 Secret → ③ 改 `DOPILOT_SERVER_URL` → ④ `kubectl apply -f statefulset.yaml`(顶部内置 Namespace 文档幂等重复应用,已存在显示 unchanged 不报错)。必填项行同步补上 `namespace dopilot`。见 README.md:22-44。 |
| R-02 | blocker | **A 档证据不完整**:tc01/02/04 原证据把 heredoc 程序体缩成一行注释、tc04 用 `<decoy>` 占位、仓库检查无退出码。全部重生成:TC-01/02 证据先 `cat` 出完整 Python 程序源码,再 `python3 <file>` 执行并 `echo "exit=$?"` 落退出码;TC-04 落诱饵**创建命令**(printf)、`cat` 诱饵内容、**真实路径**的扫描命令、每条 `echo exit`,并加仓库 `git status` 检查的显式退出码。 |
| R-03 | blocker | **回归 plan 契约,不改写验收条件**:plan TC-03 要求 `vault`(不区分大小写)在 deploy/kubernetes/ 下 0 命中。round-01 为保留 "Vault/Consul" 说明文案而在实现记录里自行加"注释豁免"判 PASS——属改写验收条件。本轮改为**去掉清单里的 Vault/Consul 字样**(statefulset.yaml 头注释 `(Vault/Consul/etc.)` → `bundles NO secret-injection sidecar`;README「扩展」标题去 "(Vault 等)"、`/vault/secrets/config.env` → `/run/secrets/`),使 `grep -riE "…|CONSUL_|vault"` 真正 0 命中、退出码 1,与 plan 完全一致。文案改为厂商中立表述,指导价值不减且更契合通用清单定位。 |
| R-04 | blocker | **回归 plan 契约**:plan TC-07 指定关键词含 `containerLogMaxSize`。round-01 擅自换成 k3s flag 拼写 `container-log-max-size` 且 README 无前者。本轮在 README kubelet 段补一句:两个 kubelet-arg flag 等价于 KubeletConfiguration 的 `containerLogMaxSize` / `containerLogMaxFiles` 字段——k3s flag 形式与配置字段名并存。`grep -niE "resources|ephemeral-storage|containerLogMaxSize"` 三关键词均命中、退出码 0,与 plan 一致。 |

## 本轮改动文件

| 文件 | 改动 |
|---|---|
| deploy/kubernetes/agent/statefulset.yaml | 头注释去 Vault/Consul 字样,改厂商中立表述 |
| deploy/kubernetes/agent/README.md | R-01 部署顺序 namespace 优先;R-03 去 Vault 字样、路径改 `/run/secrets/`;R-04 补 `containerLogMaxSize` 字段名 |
| evidence/tc0{1,2,3,4,5,7}-*.txt | 全部重生成(完整命令体 + stdout/stderr + 退出码;TC-03/07 回归 plan 原契约) |

未改:secret.example.yaml、AGENTS.md、docs/architecture/05-deployment.md、
apps/、packages/、compose、CI。

## 测试结果(全部回归 plan 原契约)

| 编号 | 档位 | 结果 | 证据 |
|---|---|---|---|
| TC-01 | A | pass | evidence/tc01-yaml-parse.txt(完整程序源码 + 输出;kind 集正确,exit 0) |
| TC-02 | A | pass | evidence/tc02-struct-assert.txt(完整程序源码 + 输出;ALL ASSERTIONS PASSED,exit 0) |
| TC-03 | A | pass | evidence/tc03-sanitize-grep.txt(plan 原单条 grep:真实凭据/tailscale.internal/CONSUL_/vault 0 命中,exit 1) |
| TC-04 | A(边界) | pass | evidence/tc04-grep-selftest.txt(诱饵创建命令 + 内容 + 真实路径扫描,命中 exit 0;仓库无诱饵) |
| TC-05 | A | pass | evidence/tc05-healthcheck-entrypoint.txt(console-script 与探针同名,exit 0) |
| TC-06 | B | pass | AGENTS.md:93;docs/architecture/05-deployment.md:39-58 |
| TC-07 | A | pass | evidence/tc07-readme-todos.txt(plan 原关键词 resources/ephemeral-storage/containerLogMaxSize 均命中,exit 0) |

## 与方案的偏差

无。本轮所有用例均严格按 plan 声明的档位与验收条件执行;round-01 记录的三条
"偏差"因实现回归契约而全部撤回,不再存在。
