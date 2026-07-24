# 评审:第 01 轮

## 问题清单
- [blocker] R-01 README 的首次部署顺序会在全新集群上先因 namespace 不存在而失败
  - 详情:deploy/kubernetes/agent/README.md:23-37 / 步骤 1 在 Namespace `dopilot` 创建前执行 `kubectl -n dopilot create secret`，而 Namespace 只随步骤 3 的 statefulset.yaml 被 apply；全新集群会报 namespace not found，无法按文档完成部署。应先创建/apply Namespace，再创建 Secret，最后 apply StatefulSet；或把 Namespace 独立成明确的第一步。
- [blocker] R-02 TC-01、TC-02 与 TC-04 的 A 档原始证据不完整
  - 详情:.ai/2026-07-24/deploy-kubernetes-agent/evidence/tc01-yaml-parse.txt:1；tc02-struct-assert.txt:1；tc04-grep-selftest.txt:2-11 / TC-01、TC-02 仅写 `python3 - <<PY` 与说明，缺失实际 heredoc 程序体；TC-04 用 `<decoy>` 代替真实执行参数，未记录诱饵创建命令，且第二条仓库检查没有明确退出码。因此无法按 A 档复核完整原始执行。需补交：TC-01 的完整命令（含全部 Python 程序体）、完整 stdout/stderr、退出码；TC-02 同样三项；TC-04 的诱饵创建命令、实际扫描命令与真实路径/参数、完整 stdout/stderr、每条命令及整体退出码。
- [blocker] R-03 TC-03 证据与 plan 的既定预期相反，却在实现记录中报告为通过
  - 详情:.ai/2026-07-24/deploy-kubernetes-agent/plan.md:83；evidence/tc03-sanitize-grep.txt:6-13；implementation-round-01.md:38,49-56 / plan 要求对 `vault`（不区分大小写）在 deploy/kubernetes/ 下 0 命中、grep 退出码 1；实际证据列出 3 个命中并退出 0，之后以实现阶段自行增加的“注释/README 豁免”判 PASS。按权威标准，任一档位证据与记录矛盾属于虚报测试。应让实现与原测试契约一致并重跑留证；若说明性 Vault 文案确属必须，须退回方案阶段正式修改验收条件，不能在实现记录中单方面改写。
- [blocker] R-04 TC-07 未执行 plan 规定的 A 档检查，却报告为通过
  - 详情:.ai/2026-07-24/deploy-kubernetes-agent/plan.md:87；evidence/tc07-readme-todos.txt:2-8；implementation-round-01.md:41,58-62 / plan 指定检查关键词 `containerLogMaxSize`，实际命令改为 `container-log-max-size`，README 也没有前者；因此现有证据不满足 TC-07 的既定步骤与预期。需补交 TC-07 按 plan 原命令执行的完整命令、stdout/stderr、退出码并使三个既定关键词均命中；如要采用 k3s flag 拼写，应先正式修订 plan 的测试契约。

## 总评
实现主体与通用 agent 清单目标大体一致，B 档 TC-06 的行号引用也存在并支持结论。但首次部署步骤存在实际阻断，且多个 A 档证据不完整或在实现阶段改写了既定验收条件；按评审标准本轮必须判 fail。

VERDICT: fail
