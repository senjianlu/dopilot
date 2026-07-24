# 配置与认证

> 决策依据:[0015 TOML 配置](../decisions/0015-toml-config-no-scrapydweb-quirks.md)、
> [0011 认证边界](../decisions/0011-auth-boundaries.md)。

## 配置形态

- TOML 配置经 `DOPILOT_CONFIG` 显式指定路径加载;样例在
  `configs/server.example.toml` / `configs/agent.example.toml`
  （`configs/server.docker.toml` 是烤进镜像的容器默认配置源）。
- Docker 镜像内置角色默认配置路径 `/app/configs/server.toml` /
  `/app/configs/agent.toml`;常规部署用 `DOPILOT_*` 环境变量覆盖
  （env 优先于 TOML），进阶部署把自有 TOML 只读挂载到默认路径。
- 本地开发不 `DOPILOT_CONFIG` 也可用 `DOPILOT_DATABASE_URL` /
  `DOPILOT_REDIS_URL` 等覆盖关键连接。
- `load_settings()` 无副作用:不建文件、不生成密钥。

关键配置段（键名以 `configs/*.toml` 为准）:

| 端 | 段 | 要点 |
|---|---|---|
| server | `[server]` | `host`/`port`/`public_url`;`data_dir`（默认 `/server-data`，生成令牌的持久化锚点） |
| server | `[database]` | PostgreSQL URL（env `DOPILOT_DATABASE_URL`） |
| server | `[auth]` | `admin_username`/`admin_password`/`token_secret`（仅 TOML）/`admin_api_token`/`access_token_ttl_minutes`/`stream_token_ttl_seconds` |
| server | `[redis]` | `url`、三条 stream 的 maxlen、`log_retention_seconds`、`consumer_name`、`require_aof` |
| server | `[agents]` | `heartbeat_timeout_seconds`/`stalled_attempt_seconds`/`lost_after_stalled_seconds`/`agent_token` |
| server | `[scheduler]` | `enabled`（in-process runner 开关）、`timezone` |
| server | `[logs]` | `root_dir=/server-data/logs`、drain/保留窗口参数 |
| server | `[nodes]` | `agents` 仅作未 heartbeat 节点的占位提示（不再是 poll 目标） |
| server | `[i18n]` | `locale`（默认 `zh`）、`timezone` |
| agent | `[redis]` | `url`/`command_block_ms`/`pending_idle_ms`/`event_outbox_dir` |
| agent | `[agent]` | `agent_id`（稳定标识）/`server_url`（env `DOPILOT_SERVER_URL` 可覆盖）/`heartbeat_interval_seconds`/`agent_token` |

## 认证体系

| 凭证 | 谁用 | 语义 |
|---|---|---|
| `admin_username` + `admin_password` | 管理员登录 | **fail-closed**:与 `token_secret` 任一缺失即拒绝启动;唯一逃生舱 `DOPILOT_AUTH_DISABLED=true` |
| opaque access token | Web/API 会话 | 登录签发，无 refresh token;由 `token_secret` HMAC 签名 |
| `stream_token` | SSE 建连 | POST 换取、TTL 60s、只校验建连 |
| `admin_api_token`（`DOPILOT_ADMIN_API_TOKEN`） | 自动化/CI | 静态 Bearer，直接认证 admin;**仅管理员、仅 server 端，绝不下发给 agent** |
| `agent_token`（`DOPILOT_AGENT_TOKEN`） | agent 出站调用 | 唯一机器令牌（heartbeat + artifact/wheel 拉取）;server 与每个 agent 同值;非空须 ≥16 字符;未配置时 server 运行时自动生成并持久化到 `<data_dir>/secrets/agent-token`（`dopilot-server agent-token print` 读取） |

Token 认证不是传输加密——跨主机部署把 Redis 与 server HTTP 置于
TLS/VPN/私有网络之后。Redis 自身启用 AUTH（compose 中 `--requirepass`）。
