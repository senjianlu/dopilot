# 0011:认证边界：Web 管理员 fail-closed + 单一 agent 机器令牌

- 日期:2026-06-17（初始）；阶段 2.2 系列修订（见下）
- 背景:dopilot 有两类主体要认证——Web/API 的管理员（人）与 agent（机器）。
  两者的失效模式不同：管理员认证缺配置若静默放行等于匿名开放 API；机器
  认证则要在"部署摩擦"与"内网防误操作"间取平衡。
- 决定:**Web 管理员认证与 agent 机器认证分离**。
  - **Web 管理员认证 fail-closed**:生产启动时 `admin_username` /
    `admin_password` / `token_secret` 任一缺失即抛 `ConfigError` 拒绝启动；
    唯一逃生舱是显式 `DOPILOT_AUTH_DISABLED=true`。登录签发 opaque access
    token（无 refresh token）；另有静态 `admin_api_token`
    （env `DOPILOT_ADMIN_API_TOKEN`，非空须 ≥16 字符）供自动化直接作
    Bearer；SSE 建连用短期 `stream_token`（TTL 60s）。`token_secret` 是
    登录/SSE 的 HMAC 签名密钥，**仅 TOML 配置、无 env 覆盖**。
  - **agent 机器认证 = 单一令牌** `DOPILOT_AGENT_TOKEN`（server
    `[agents].agent_token` / agent `[agent].agent_token`，非空须 ≥16 字符），
    只认证 **agent→server 出站调用**（heartbeat + artifact/wheel 拉取）。
    config-present-or-off；Redis 另启用 AUTH/ACL。被否掉/删除的备选：拆分
    令牌对（`server_shared_token`/`agent_auth.shared_token`）与"从
    admin token 回退"——`admin_api_token` 仅管理员、仅 server 端，绝不
    下发给 agent、绝不充当机器令牌。
- 影响:
  - Token 认证不是传输加密：跨主机部署仍需 TLS/VPN/私有网络。定位是内网
    防误操作，不是互联网零信任。
  - 第一版不做 mTLS、token 轮换、RBAC。

## 修订

- 阶段 2.2.3:机器令牌收敛为上述单一 `agent_token`。
- 阶段 2.2.4:**server 运行时边界放宽**——未配置 `agent_token` 时，server
  运行时/CLI 自动生成强令牌（`secrets.token_urlsafe(32)`）并持久化到
  `<server.data_dir>/secrets/agent-token`（`[server].data_dir` 默认
  `/server-data`，env `DOPILOT_SERVER_DATA_DIR`），重启复用——机器认证经
  生成令牌即 ON。生成仅 server 端（agent 永不生成），是运行时步骤
  （`dopilot_server.agent_token`）；`load_settings()` 保持无副作用。
  `create_app(settings)` 把传入 settings 注入 `Depends(get_settings)`，保证
  入站鉴权读到写入生成令牌的同一 settings。运维用
  `dopilot-server agent-token print [--quiet]` 取令牌（无需 DB/Redis/ASGI）。
- 阶段 2.2.7:agent 纯出站后不存在 server→agent HTTP 方向；机器令牌仅
  出现在 agent 的出站请求里（见 [0008](0008-redis-streams-agent-communication.md)）。
