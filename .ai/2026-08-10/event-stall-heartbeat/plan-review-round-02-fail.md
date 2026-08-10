# Plan 评审:第 02 轮

## 问题清单
- [plan-blocker] R-01 方案擅自将 plan 与实现修复轮次上限设为 15，违反 rawf 的用户授权约束。
  - 详情:定位：plan.md frontmatter 第 6-7 行。CLAUDE.md 及 rawf-plan/rawf-implement/rawf-review 均规定，plan_review_max_rounds 与 impl_fix_max_rounds 只能在用户明确要求放宽时写入；本次评审指令未提供该授权。删除两字段以使用默认 3 轮，或在获得用户明确授权后记录授权及摘要声明。
- [major] R-02 升级风险的“统一镜像同版本部署天然满足 server 先于 agent”结论不成立，混布时仍可能由新 agent 向旧 server 发送未知事件。
  - 详情:定位：plan.md“风险与回滚 / 升级顺序”。现有 all-in-one compose 中 agent 仅依赖 Redis、并不依赖 server 健康（deploy/docker/docker-compose.yml 的 x-agent）；远端 agent 更独立（docker-compose.agent.yml）。因此拉取同一新镜像并执行常规更新不能保证 server 先完成切换，新 agent 的 heartbeat 可先阻塞旧 server 的事件流。方案应删除该错误保证，明确 all-in-one 与远端 agent 的可执行升级顺序/停机措施，并将该操作约束回写到相应部署文档。

## 总评
协议、状态机分支及测试证据契约本身较完整：11 条用例均逐条声明 A 档与完整原始输出，且覆盖多项异常路径。上述工作流授权与版本偏斜处理仍会导致实施或上线返工，修订方案后应重新评审。

VERDICT: fail
