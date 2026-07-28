# 评审:第 01 轮

## 问题清单
- [plan-blocker] R-01 TC-03 的方案契约与升级文档要求互相矛盾
  - 详情:.ai/2026-07-28/unify-env-var-prefix/plan.md:210 要求扫描范围内旧名文本零残留，但同一方案在 :319 要求 README 和架构文档明确说明旧名升级方式，必然需要提及旧变量名；当前 README.md:123 正是这种必要提示。实现阶段自行改成“使用形态 + 文件白名单”不能修复已批准方案的矛盾；应先回到方案阶段，把 TC-03 正式改为区分实际使用与受控废弃说明，并重新确认测试契约。
- [blocker] R-02 TC-03 与 TC-06 的 A 档证据缺少命令和显式退出码
  - 详情:.ai/2026-07-28/unify-env-var-prefix/evidence/tc03-legacy-name-scan.log:1 和 evidence/tc06-k8s-env-check.log:1 均直接从脚本输出开始，末尾只有 RESULT: PASS，没有执行命令或进程退出码；但 implementation-round-01.md:41、:44 报告了 EXIT=0。按 A 档契约需补交：TC-03 的完整执行命令 `bash .ai/2026-07-28/unify-env-var-prefix/evidence/tc03-legacy-name-scan.sh`、完整 stdout/stderr、退出码；TC-06 的对应完整命令、完整 stdout/stderr、退出码。
- [major] R-03 改写后的 TC-03 正则漏掉行内文档变量名，未覆盖方案声明的逐文件基线断言
  - 详情:.ai/2026-07-28/unify-env-var-prefix/evidence/tc03-legacy-name-scan.sh:23 的“使用形态”正则不匹配 Markdown 反引号中的变量名；因此日志 :21 对 deploy/kubernetes/agent/README.md 报告“基线旧名=0、现新名=0”，尽管 HEAD 中该文件实际包含 `AGENT_ID`，当前实现也确实改成了 `DOPILOT_AGENT_ID`。这使该文件保持旧名、误删变量或正确改名都能通过，未满足 plan.md:304 的受影响文件基线保护目标。应为行内代码/文档映射增加可判别断言或显式逐文件旧名→新名检查，并重新生成完整 A 档证据。

## 总评
代码改名本身与主要部署配置一致，静态差异中未发现直接功能错误。但方案中的 TC-03 契约需要先修订，且当前 A 档证据与扫描覆盖均不满足评审标准，因此本轮判定 fail；按要求未运行任何测试。

VERDICT: fail
