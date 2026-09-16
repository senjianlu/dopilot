# Plan 评审:第 02 轮

## 问题清单
- [plan-blocker] R-01 异步 reclaim 尚未完成，既有日志清理链就可能删除停止状态机。
  - 详情:定位：plan.md 第 4 节（176–202 行）。现有 server finalize_drained_logs 在 reclaim 已入队且 drain 到期后即可发送 cleanup_logs；默认 drain 为 30 秒，早于方案的 120 秒确认期限。agent 的 _handle_cleanup 会直接删除执行 state，因此停止仍未确认时，cleanup 就可能使后续 tick 永远无法重试或升级 KILL；对于早已 lost、刚恢复连接的执行，两条命令甚至可能同批到达。必须明确停止期间 cleanup 的持久延迟处理及最终释放机制，补充 reclaim→cleanup 提前到达、信号失败及重启后的 A 档测试。仅保持现有清理链不变无法满足方案的停止保证。
- [major] R-02 现有 runner 无法区分真实终态与 reclaim 自己制造的 canceled，收尾规则与 TC-20 冲突。
  - 详情:定位：plan.md 第 4 节收尾表（196 行）、TC-20。ScrapyRunner.stop 成功发送 TERM 后会调用 mark_canceled；之后 _resolve_status 在 job 进入 finished 列表或离开列表且日志存在时返回 canceled。方案让 watchdog 对这种终态调用 _finish_scrapy_attempt，将上报 canceled 并覆盖 server 的 lost，违反 TC-20 的“保持 lost、不 emit canceled”。需明确区分停止前已观察到的权威终态与 reclaim 发信号后的退出确认，必要时调整 runner 返回的事实信息；测试须使用真实 ScrapyRunner 配合假 ScrapydClient，覆盖该 canceled 标记路径，不能只模拟抽象 status。
- [major] R-03 首次 TERM 失败后的持久接管和重试路径没有闭合。
  - 详情:定位：plan.md 第 4 节（172–189 行）、TC-19。方案在发送 TERM 后才记录 stop_requested_at，而 watchdog 对未设置该字段的执行直接返回；同时 watchdog 只定义了到期发送 KILL，没有定义首次 TERM 失败后的重试分支。现有 _process 即使 handler 抛异常也会 XACK，因此不能依赖命令重投补救。需在首次网络请求前持久记录停止意图和总期限，将“尚未成功发送 TERM”作为明确状态，仅在发送成功后推进 escalation，并定义下一 tick 的重试。补充首次 TERM 返回 cancel_failed、抛异常以及请求前后重启的 A 档测试，验证停止请求不会丢失。
- [major] R-04 复用 flood watchdog 的采样会在关闭日志大小保护时使无进度检测失效。
  - 详情:定位：plan.md 第 1 节（心跳复用同一次读数）及测试表。现有 _flood_watchdog 在 max_job_log_bytes <= 0 时于读取 log_size 前直接返回；这是合法的关闭日志保护配置。因此仅复用其现有读数，会让日志可读的 Scrapy 执行持续发送 None，server 永远无法进行无进度检测。方案需明确将日志采样与 flood 开关解耦，启用保护时共用读数、关闭保护时仍采样。当前测试从 server 人工注入 log_bytes，不能检出 agent 未发送读数的问题；应新增 agent tick→心跳载荷的 A 档测试，覆盖保护开启、关闭及文件不可读。

## 总评
方案的证据契约合规：24 条用例均声明 A 档和证据形态，并包含异常路径；rawf 闸门与轮次声明也未发现冲突。但停止状态机与既有清理、runner 状态及命令确认机制存在实质冲突，需要修订方案并补充对应集成路径测试后重评。

VERDICT: fail
