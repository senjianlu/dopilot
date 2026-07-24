# Plan 评审:第 03 轮

## 问题清单
- [plan-blocker] R-01 server artifact 仅限制单次上传大小，聚合存储仍可无界增长，与“每个增长面获得硬上限”的目标矛盾
  - 详情:定位：Phase B/B5、明确不动、背景与目标。方案已将 artifacts“只增不减”列为增长面，却只新增 `max_upload_bytes`，并明确 artifact 正文不自动删除；任意数量的合法小文件仍可持续填满 `server-data`，因此没有形成资源硬上限。需在方案阶段补充可配置的总容量/数量配额及并发安全的准入策略，或设计可审计的回收机制；若产品决策确实禁止删除，则至少应在达到总配额后拒绝新上传，并增加容量边界及拒绝路径测试。
- [plan-blocker] R-02 C6 在 EOF 发布后删除 `_eof_sent` 会使终态执行在后续轮询中重复发送 EOF
  - 详情:定位：Phase C/C6、TC-17；现有 `apps/agent/dopilot_agent/redis/logs.py:130-147`。`publish_attempt()` 对仍保留的终态 state 使用 `_eof_sent` 作为唯一去重条件；按方案在 EOF 后移除该 id，而 state 要到数日后的 janitor 才删除，所以下一次 `publish_once()` 会再次发送 EOF，之后可无限重复。需重新设计有界且跨轮询保持幂等的 EOF 状态生命周期，例如仅在 state/游标清理时同步删除去重条目，或把 EOF 已发送状态持久化并令终态 state 不再参与扫描；TC-17 还应增加“EOF 后连续多个 publisher tick 仍只发送一次”的断言。

## 总评
方案的证据契约完整：所有用例均逐条声明档位与证据形态，C 档为 0，未发现降档或超限问题。但 server artifact 聚合容量仍无硬边界，且 agent EOF 簿记清理方案会直接破坏幂等性；两项都需先修订方案，因此本轮 fail。

VERDICT: fail
