# Plan 评审:第 11 轮

## 问题清单
- [major] R-01 生产配置不会实际采用方案声明的 32MiB server 日志上限，且既有环境变量名称写错。
  - 详情:定位：plan.md 第 88、94 行及 TC-26。生产镜像由 deploy/docker/Dockerfile 复制 configs/server.docker.toml，而该文件显式配置 max_file_bytes=104857600；方案只修改 configs/server.example.toml 和 Pydantic 默认值，因此生产仍为 100MiB。现有 loader 的环境变量是 DOPILOT_LOG_MAX_FILE_BYTES，方案却把 DOPILOT_LOGS_MAX_FILE_BYTES 标为“已有”，照此实现会遗漏或破坏既有覆盖契约。应把 configs/server.docker.toml 纳入范围、保留现有环境变量，并增加加载生产 TOML及旧环境变量的 A 档回归测试。
- [major] R-02 0 表示关闭上限的既有语义未贯穿新防护路径，会导致所有 Scrapyd 作业被立即判洪泛、所有执行被判错误。
  - 详情:定位：plan.md 第 78—84、105 行及 TC-02/TC-18。现有 AgentSettings.max_job_log_bytes 和 LogsSettings.max_file_bytes 明确规定 0=disabled；方案只有 logcap 对 n=0 不激活，但 watchdog 使用 size>=cap、LogPublisher 使用 cap 限制，cap=0 时会立即停止/封顶。server 的 execution_is_erroneous 又以 log_bytes>=logs.max_file_bytes 判错，max_file_bytes=0 时任何非负 log_bytes 都命中。应对所有相关路径增加 cap>0 前置条件，并补充两个上限为 0 时“不终止、不截断、不误判”的 A 档测试。
- [major] R-03 方案和测试使用不存在的 Schedule PATCH 接口，与既有 PUT 契约冲突。
  - 详情:定位：plan.md 第 113、263 行。现有 apps/server/dopilot_server/api/v1/schedules.py 注册的是 @router.put，apps/web/lib/api/schedules.ts 也调用 axios.put；方案却称“沿用现有 PATCH”，TC-23 发送 PATCH，而改动范围没有新增 PATCH 路由，因此该验收用例会直接得到 405。应统一改为现有 PUT；若确需引入 PATCH，则必须明确列入 API/客户端范围并增加兼容性测试。
- [major] R-04 删除 Redis 卷所依赖的 sent 对账仍引用不存在的时间字段，测试也未覆盖其周期接线。
  - 详情:定位：plan.md 第 90、260 行及恢复 runbook。CommandOutbox 现有字段只有 created_at/updated_at，没有方案所用的 sent_at，迁移 0013 的字段清单也未新增 sent_at；TC-20e 仅直接调用 reconcile_sent_once，未验证年龄门槛或 dispatcher 启动/周期 tick 确实调用该对账。这样实现可在测试通过时仍未接线，删除 Redis volume 后 sent 命令仍会永久丢失。应明确使用写入 sent 状态时的 updated_at，或正式新增并维护 sent_at；同时测试过新/过期分支以及 dispatcher tick 的实际调用。

## 总评
证据契约合规：所有用例逐条声明为 A 档并给出文本证据形态，C 档为 0；整体并发和异常路径覆盖也较充分。但生产配置、关闭上限语义、既有 API 契约及恢复所依赖的 sent 对账仍有会导致实现返工或验收失真的问题，因此本轮 fail。

VERDICT: fail
