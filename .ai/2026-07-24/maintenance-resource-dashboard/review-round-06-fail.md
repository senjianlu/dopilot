# 评审:第 06 轮

## 问题清单
- [blocker] R-01 TC-09 的访问失败修复与 A 档证据仍不完整，且实现记录所称“其他 OSError 一律传播”与代码矛盾
  - 详情:apps/agent/dopilot_agent/janitor.py:517、apps/agent/dopilot_agent/janitor.py:521、apps/agent/tests/test_resource_limits.py:712、.ai/2026-07-24/maintenance-resource-dashboard/evidence/tc09-10-agent-disk.txt:1 / `_count_dirs` 会捕获 `DirEntry.is_dir()` 抛出的任意 `OSError` 并继续计数，因此单个目录项发生 `PermissionError` 或其他访问错误时仍会返回偏小的正常计数，而不会传播至 `_guard` 使子项变为 null。这与 implementation-round-06.md 声称“PermissionError 等一律传播”矛盾；现有测试只覆盖 `os.scandir()` 直接抛错，未覆盖 `entry.is_dir()` 的访问失败。此外，证据首行的 `... -k tc09 -v AND ... disk tests -v` 不是可执行的实际命令。需补交 TC-09 A 档证据：①覆盖 `_count_dirs` 中 `DirEntry.is_dir()` 抛出 PermissionError/其他 OSError 并验证传播的测试；②修复后的真实、可执行 pytest 命令；③完整 stdout/stderr；④退出码。
- [major] R-02 Server 目录采样仍可能把访问失败误报为零用量
  - 详情:apps/server/dopilot_server/resource_stats.py:185 / `_du` 先用 `os.path.exists()` 判断目录是否存在；该 API 在部分权限或路径访问错误下会返回 false，于是函数直接返回 0，绕过后续 `os.walk(onerror=...)` 的失败检测。这会把日志或 artifacts 根目录的访问故障显示为正常零用量。应仅将明确的 `FileNotFoundError` 解释为目录不存在，并让 PermissionError/其他 OSError 返回 unknown 或使对应 scope 降级；同时补充该路径的回归测试。

## 总评
上一轮缓存淘汰后回写最终大小的修复已落实，但目录访问失败语义仍未彻底修正。TC-09 的实现说明、代码与 A 档证据之间存在实质矛盾，另有 server 侧同类零值误报，因此本轮判定 fail。

VERDICT: fail
