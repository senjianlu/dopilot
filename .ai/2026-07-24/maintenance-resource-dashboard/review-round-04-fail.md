# 评审:第 04 轮

## 问题清单
- [blocker] R-01 TC-09 的 A 档证据未覆盖不可读目录，且实际遍历错误会被误报为零用量
  - 详情:apps/agent/dopilot_agent/janitor.py:83、apps/agent/dopilot_agent/janitor.py:475、apps/agent/tests/test_resource_limits.py:649 / `_tree_size` 未设置 `os.walk(onerror=...)`，`_count_dirs` 和 `_count_glob` 又将 `OSError` 转成 0，因此 scrapyd、workspace、outbox 等目录不可读时可能生成正常的零值，而不会按 plan 将对应子项置为 null。现有 TC-09 仅将 `_volume` 替换为直接抛错，未执行 plan 明确要求的不可读目录遍历路径，A 档覆盖不完整。需修复这些采集 helper 以传播访问失败，并补交 TC-09 证据：①覆盖实际目录遍历访问失败的测试；②实际执行命令；③完整 stdout/stderr；④退出码。

## 总评
上一轮 TC-12 的页面断言已经补齐，server 目录和 nodes 查询的降级修复也已落实；TC-16 的 B 档引用存在且支持结论。但 agent 目录采集仍会把访问失败伪装成零值，且 TC-09 的 A 档证据没有覆盖该计划场景，因此本轮判定 fail。

VERDICT: fail
