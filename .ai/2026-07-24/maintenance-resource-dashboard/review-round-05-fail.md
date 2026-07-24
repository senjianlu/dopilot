# 评审:第 05 轮

## 问题清单
- [blocker] R-01 上一轮的目录访问失败误报零值问题仍未完整修复，且 TC-09 A 档证据未覆盖剩余失败路径
  - 详情:apps/agent/dopilot_agent/janitor.py:490、apps/agent/dopilot_agent/janitor.py:503、apps/agent/dopilot_agent/janitor.py:509 / 三个 helper 先调用 `Path.exists()`；该调用会把部分访问错误当作不存在，进而返回 0。尤其 `_count_glob` 在 511 行使用 `Path.glob()`，其目录扫描会吞掉 `OSError`，所以不可读的 logpos 目录仍可能被报告为正常的 0。implementation-round-05.md 声称 `_count_dirs`/`_count_glob` 会传播不可读错误，但代码不支持该结论；新增测试只模拟 `_dir_bytes`/`os.walk` 的 scrapyd 路径，未覆盖计数 helper。修复时应仅将 `FileNotFoundError` 解释为不存在，传播 `PermissionError` 等其他错误，并用不会吞扫描错误的实现替换 `Path.glob()`。需补交 TC-09 A 档证据：①覆盖 `_count_dirs`、`_count_glob` 及 `exists/stat` 访问失败路径的测试；②实际执行命令；③完整 stdout/stderr；④退出码。
- [major] R-02 缓存清扫后的磁盘样本仍上报淘汰前的缓存大小
  - 详情:apps/agent/dopilot_agent/janitor.py:256-260、apps/agent/dopilot_agent/janitor.py:270-278 / `_last_cache_bytes` 在开始淘汰前写入 `total`，后续成功删除缓存条目并递减局部 `total` 后没有更新该字段；紧接着的 `_collect_disk_sample` 因而会发布淘汰前的用量，可能继续显示 warn/critical 达一个 janitor 周期。应在淘汰循环结束后把最终 `total` 写回 `_last_cache_bytes`，并增加“超限缓存被淘汰后样本等于剩余实际大小”的回归测试。

## 总评
第 04 轮指出的 scrapyd 字节遍历路径已得到修复，但目录计数及存在性检查仍会把部分访问失败伪装为零，上一轮 blocker 尚未完全关闭。另有缓存淘汰后快照使用旧总量的正确性问题，因此本轮判定 fail。

VERDICT: fail
