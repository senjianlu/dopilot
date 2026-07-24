# 评审:第 02 轮

## 问题清单
- [blocker] R-01 A 档记录宣称全部用例通过，但实际测试未覆盖多项 plan 强制场景
  - 详情:apps/server/tests/test_resource_limits.py:92、199、330、342、375 / TC-01 只调用 apply_log_event 并以注释假定 consumer 会 ACK，没有驱动消费与 ACK；TC-03 仅覆盖正常路径和 unlink 异常，缺少 plan 要求的 SQL/commit 故障注入；TC-06 仅测试 stream_to_staging，未覆盖 egg/wheel endpoint、save_from_path、合法包成功、校验失败清理及无入库行；TC-18 仅测试 reserve_quota，未覆盖并发 endpoint、507 后 staging/DB 无残留和实际总量统计。implementation-round-02.md 将 TC-01、TC-03、TC-06、TC-18 全部记为 pass，与证据所显示的覆盖范围矛盾，按虚报测试处理。需补交上述四个用例各缺失场景的测试实现，以及包含执行命令、完整 stdout/stderr、退出码的 A 档原始证据。
- [major] R-02 Janitor 在释放锁后删除锁映射，仍可让同一执行出现两把并发锁
  - 详情:apps/agent/dopilot_agent/janitor.py:179-192、apps/agent/dopilot_agent/redis/commands.py:157-162、321、722-730 / janitor 退出 per-execution lock 后才调用 _release_execution，而该回调会从 _locks 删除锁。此间新命令可取得旧锁，随后映射被删除，第三个操作便会创建新锁并与已持旧锁的命令并发；_handle_cleanup 在持锁期间直接删除自身锁映射也存在同类问题。上一轮 R-04 因此未彻底修复。应保证锁仍被持有或存在等待者时绝不移除映射，并增加“删除完成后新命令进入与 release 交错”的竞态测试。
- [major] R-03 缓存淘汰只观察锁文件快照，没有按方案取得锁，仍会竞态删除正在安装的缓存
  - 详情:apps/agent/dopilot_agent/janitor.py:241-255、262-293 / janitor 扫描时仅记录 `.lock` 是否存在，之后直接执行删除；扫描后、删除前 cache ensure 可以成功创建锁并开始下载或安装，janitor 仍会删除其目录。plan 明确要求淘汰前取得既有锁并与安装/复用互斥。应以 O_CREAT|O_EXCL 实际获取每个候选的同一锁，获取失败即跳过，并在持锁期间重新核验引用与大小后淘汰。
- [major] R-04 Artifact 发布失败可留下未计入数据库配额的正文，聚合硬上限可被绕过
  - 详情:apps/server/dopilot_server/artifacts/scrapy_store.py:236-247、apps/server/dopilot_server/artifacts/wheel_store.py:214-225、apps/server/dopilot_server/api/v1/artifacts.py:139-151、211-222 / save_from_path 先将 staging 正文 os.replace 到最终路径，再发布 manifest；endpoint 随后才 upsert/commit。manifest 发布或数据库提交失败时，finally 只清理已被 rename 掉的 tmp，不会删除最终正文。反复上传不同内容并触发 DB/manifest 失败会产生不计入 stored_total_bytes 的文件，破坏 max_total_bytes 硬上限。应为发布与 DB 失败设计可回滚清理，或让配额统计覆盖磁盘正文，并补充各失败点无残留测试。

## 总评
上一轮 server unlink 失败重试问题已修复，A/B 档证据文件的命令、输出、退出码和行号形态也已补齐。但测试覆盖与“全部通过”的记录不一致，且 janitor 锁协调、缓存淘汰互斥和 artifact 配额失败路径仍存在必须修复的正确性问题，因此本轮评审失败。

VERDICT: fail
