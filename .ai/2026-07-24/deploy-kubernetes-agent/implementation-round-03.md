---
task: deploy-kubernetes-agent
round: 03
date: 2026-07-24
---

# 实现记录:第 03 轮(修复轮)

修复 review-round-02-fail 的 1 个 blocker(R-01)。NN=03 ≤ 修复轮上限 3,
在范围内。纯证据修复,不动任何源码/清单/文档。

## 修复对照

| 编号 | 严重度 | 修复方式 |
|---|---|---|
| R-01 | blocker | **TC-04 A 档证据仍不完整**:round-02 的证据把诱饵创建写成 `printf '...'`(省略真实 payload),`cat "$DECOY"` 依赖的变量赋值也未落。本轮改用 `set -x`(bash xtrace)逐条追踪**实际执行**的命令——每条命令的完整参数(printf 的全 payload、grep 的完整模式与真实绝对路径)、stdout/stderr、退出码全部无省略落盘;并用 `/usr/bin/grep` 绕开本 shell 的交互式 `grep` 函数包装,追踪干净。额外把"同一模式扫 deploy/kubernetes 得 0 命中(exit 1)"并入同一份证据,既证明模式有效(命中诱饵 exit 0)、又证明仓库洁净且诱饵不在仓库。 |

## 本轮改动文件

| 文件 | 改动 |
|---|---|
| evidence/tc04-grep-selftest.txt | 重生成:set -x 完整追踪诱饵创建/读取/匹配 + 仓库扫描,payload 与路径零省略,各退出码齐备 |

未改:任何 .yaml / .md 清单与文档、apps/、packages/、compose、CI;其余
TC-01/02/03/05/06/07 证据 round-02 已完整,未触碰。

## 测试结果

| 编号 | 档位 | 结果 | 证据 |
|---|---|---|---|
| TC-01 | A | pass | evidence/tc01-yaml-parse.txt(round-02,完整程序源码+输出,exit 0) |
| TC-02 | A | pass | evidence/tc02-struct-assert.txt(round-02,完整程序源码+输出,exit 0) |
| TC-03 | A | pass | evidence/tc03-sanitize-grep.txt(round-02,plan 原契约 0 命中 exit 1) |
| TC-04 | A(边界) | pass | evidence/tc04-grep-selftest.txt(**本轮**,set -x 全追踪:诱饵命中 exit 0、仓库 0 命中 exit 1) |
| TC-05 | A | pass | evidence/tc05-healthcheck-entrypoint.txt(round-02,console-script 与探针同名 exit 0) |
| TC-06 | B | pass | AGENTS.md:93;docs/architecture/05-deployment.md:39-58 |
| TC-07 | A | pass | evidence/tc07-readme-todos.txt(round-02,plan 原关键词均命中 exit 0) |

## 与方案的偏差

无。TC-04 仍按 plan 声明的 A 档(边界)执行,仅补齐原始执行证据的完整性。
