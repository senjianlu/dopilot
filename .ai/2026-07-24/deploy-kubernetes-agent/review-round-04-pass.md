# 评审:第 04 轮

## 问题清单
- [plan-blocker] R-01 方案错误地假定未替换的 server URL 占位符会使 Pod 保持 NotReady
  - 详情:deploy/kubernetes/agent/statefulset.yaml:85-87、deploy/kubernetes/agent/README.md:44-47、docs/architecture/05-deployment.md:47-49 / `dopilot-agent-healthcheck` 实际只校验配置能否加载及本地 scrapyd；`server_url` 是未经 URL 校验的普通字符串（apps/agent/dopilot_agent/config/settings.py:29），探针不会检查 agent 能否连接 server。因此占位符可能被接受且 Pod 仍为 Ready，与方案的“探针自然暴露”风险控制相悖。该行为来自方案既定设计，需退回方案阶段决定：增加可自动化的占位符/URL 启动校验，或明确接受 Pod Ready 但未入群的风险并修正文档及测试契约。

## 总评
上一轮 TC-04 的 A 档证据已补齐诱饵创建、内容、模式命中、仓库扫描及仓库外定位信息；其余 A/B 档证据也符合各自契约，未发现 blocker、major 或 minor 实现问题。清单总体忠于方案，但方案本身对 readiness 探针能力的判断不成立，已单列为不影响本轮 pass/fail 的 plan-blocker。

VERDICT: pass
