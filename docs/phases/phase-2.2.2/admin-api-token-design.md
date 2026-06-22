# dopilot 改动设计：静态 admin API token + 收敛 token_secret 的 env

> 文档性质：实现就绪的设计草案（供决策 / Codex-Claude 实施 loop）。
> 生成：2026-06-22。`file:line` 为调查时的代码位置，落地前请就地复核。

---

## 0. 目标（按用户最新口径）

1. **舍弃 `DOPILOT_ADMIN_API_SECRET`** 这个 env 覆盖。配置文件里的 `auth.token_secret`
   **原样保留、行为不变**（仍是登录 token / stream token 的 HMAC 签名密钥），仅仅是
   **不再可被 env 覆盖**——它只从 TOML 读。
2. **新增 `auth.admin_api_token`**（env `DOPILOT_ADMIN_API_TOKEN`）：一个**静态、不过期**
   的管理员凭据，客户端用 `Authorization: Bearer <admin_api_token>` **直接**通过 admin 认证，
   免账号密码登录。
3. **机器 token 的回退源改为 `admin_api_token`**：当 `agents.server_shared_token`
   （= server_token）与 `agent_auth.shared_token`（= agent_token）**未配置**时，
   默认取 `admin_api_token`（**取代**原先从 `token_secret` 派生的逻辑）。

净效果：`admin_api_token` 成为「对外的单一密钥」——既能直接认证 admin API，又作机器
token 的默认值；`token_secret` 退回为**纯内部签名密钥**（TOML 写死、不暴露 env、不再
喂机器 token）。

---

## 1. 现状（已读源码，verified）

- `AuthSettings`（`config/settings.py:29-49`）：`disabled / admin_username / admin_password /
  token_secret / access_token_ttl_minutes / stream_token_ttl_seconds`；
  `enabled = not disabled AND (admin_username ∧ admin_password ∧ token_secret)`。
- `get_current_admin`（`auth/dependencies.py:45-73`）：`enabled=False` → 匿名 admin（mode off）；
  否则取 Bearer → `get_token_record`（DB 查、按 `token_secret` HMAC 哈希）→ 无则 401。
  **目前没有任何静态 key 直认路径。**
- `token_secret` 的用途：① 登录 token 的 HMAC key（`auth/tokens.py:43,65`）；
  ② stream token 签名（`logs/stream_token.py`、`api/v1/tasks.py:244,292`）；
  ③ **机器 token 默认值**（`config/loader.py:158-174` `_apply_machine_token_fallback`）；
  ④ fail-closed 必填项（`config/loader.py:177-203`）。
- env 覆盖表 `_STR_OVERRIDES`（`config/loader.py:45-61`）含
  `("DOPILOT_ADMIN_API_SECRET", "auth", "token_secret")`（line 51）。
- 机器 token：`agent_auth.shared_token`（server→agent，= agent_token，env
  `DOPILOT_AGENT_SHARED_TOKEN`）、`agents.server_shared_token`（agent→server，
  = server_token，env `DOPILOT_SERVER_SHARED_TOKEN`）。

---

## 2. 改动清单

### 2.1 `config/settings.py` — 新增字段

```python
class AuthSettings(BaseModel):
    disabled: bool = False
    admin_username: str | None = None
    admin_password: str | None = None
    token_secret: str | None = None
    admin_api_token: str | None = None        # 新增：静态 admin API token（直认 + 机器 token 回退源）
    access_token_ttl_minutes: int = 720
    stream_token_ttl_seconds: int = 3600

    @property
    def enabled(self) -> bool:
        # 不变：admin_api_token 是附加凭据，不参与 enabled 判定
        return not self.disabled and bool(
            self.admin_username and self.admin_password and self.token_secret
        )
```

> `admin_api_token` **不**进 `enabled`：交互式登录（web UI）仍需账号密码 + token_secret；
> 静态 token 只是额外的自动化凭据。

### 2.2 `auth/dependencies.py` — `get_current_admin` 增加静态 token 直认

```python
import hmac  # 新增

async def get_current_admin(request, settings=Depends(get_settings), session=Depends(get_session)):
    if not settings.auth.enabled:
        return AdminContext(mode="off", username="admin", authenticated=True, expires_at=None)

    token = _extract_bearer(request)

    # 静态 admin API token：常数时间比较；两侧都必须非空
    # （hmac.compare_digest("","") == True，必须用 api_token and token 守卫）。
    api_token = (settings.auth.admin_api_token or "").strip()
    if api_token and token and hmac.compare_digest(token, api_token):
        return AdminContext(
            mode="on",
            username=settings.auth.admin_username,
            authenticated=True,
            expires_at=None,            # 不过期
        )

    record = await get_token_record(session, settings, token) if token else None
    if record is None:
        raise ApiError(401, "auth.unauthorized", "errors.unauthorized", {})
    # ……（原有逻辑不变）
```

要点（安全）：
- `hmac.compare_digest` 防时序侧信道，**不要用 `==`**。
- **双非空守卫**（`api_token and token`）堵住 `compare_digest("","")==True` 的空串匹配洞。
- 整段仍在 `settings.auth.enabled` 为真的分支内 —— **不新增任何绕过 fail-closed 的路径**。
- `expires_at=None`（静态、不过期）。

### 2.3 `config/loader.py` — env 表调整

```python
# _STR_OVERRIDES：
#   删除： ("DOPILOT_ADMIN_API_SECRET", "auth", "token_secret")      # line 51
#   新增： ("DOPILOT_ADMIN_API_TOKEN",  "auth", "admin_api_token")
```

- `token_secret` 自此**无 env 覆盖**，只从 TOML 读（原样保留字段与签名行为）。
- `admin_api_token` 可经 `DOPILOT_ADMIN_API_TOKEN` 注入（部署/CI 用），也可写 TOML。

### 2.4 `config/loader.py` — 机器 token 回退源改为 `admin_api_token`

```python
def _apply_machine_token_fallback(settings) -> None:
    """server_token / agent_token 未配置时，默认取 admin_api_token（phase 2.2.x 调整）。"""
    secret = (settings.auth.admin_api_token or "").strip()   # 原：settings.auth.token_secret
    if not secret:
        return
    if not (settings.agent_auth.shared_token or "").strip():
        settings.agent_auth.shared_token = secret
    if not (settings.agents.server_shared_token or "").strip():
        settings.agents.server_shared_token = secret
```

并更新该函数 docstring 与 `_enforce_fail_closed_auth` 错误信息（`loader.py:163,201`）中
对 `DOPILOT_ADMIN_API_SECRET` 的措辞（token_secret 现在只提"TOML 设置"）。

> ⚠️ **行为变化须知**：原先机器 token 默认派生自 `token_secret`，而 token_secret 是
> fail-closed 必填项，所以生产里机器 token **总有默认值**（机器认证默认 on）。改用
> `admin_api_token`（**可选**）后：若 `admin_api_token` 未设且未显式配 server/agent token，
> 则机器认证回退到 **off**（config-present-or-off）。**要保持生产机器认证默认 on，请设置
> `admin_api_token`**（或显式配两个机器 token）。见 §5 决策 2。

### 2.5 配置示例（`configs/server.example.toml` / `server.docker.toml`）

```toml
[auth]
admin_username = "admin"
admin_password = "change-me"
token_secret   = "change-me-长随机串"     # 内部签名密钥；仅 TOML，无 env 覆盖
admin_api_token = "change-me-长随机串"    # 静态 admin API token；可经 DOPILOT_ADMIN_API_TOKEN 注入
access_token_ttl_minutes = 720
```

并删除示例顶部关于 `DOPILOT_ADMIN_API_SECRET` 的注释，新增 `DOPILOT_ADMIN_API_TOKEN` 说明
（"机器 token 留空时默认取它"）。

---

## 3. 调用方（API / CI）怎么用

- 任意 admin 端点（上传 wheel、模板、调度…均走 `get_current_admin`）直接带：
  `Authorization: Bearer <admin_api_token>`，无需先 `POST /auth/login`。
- 下载类端点走 `require_server_token`（机器 token），不受影响、也不需要 admin token。
- **CI / `scripts/dopilot_sync.py`**：新增 `DOPILOT_API_TOKEN` 支持——若设置，跳过账号密码
  登录、直接用作 Bearer；否则回退账号密码。`dopilot-deploy.yml` 加一个
  `DOPILOT_API_TOKEN` secret（其值 = 服务端的 `admin_api_token`）。好处：CI 不必存管理员
  账号密码，只存一个静态 token。

---

## 4. 安全考量

- **常数时间比较 + 双非空守卫**（§2.2），杜绝时序与空串匹配。
- **强度**：`admin_api_token` 建议 ≥ 32 字节随机（`secrets.token_urlsafe(32)`）；可在
  `load_settings` 末尾对「已设置但过短（如 < 16 字符）」抛 `ConfigError` 或告警（见 §5 决策 4）。
- **不可吊销 / 不过期**：静态 token 只能靠改配置 + 重启轮换；single-admin 自托管 + CI 场景
  可接受，文档写清轮换方式。
- **不入日志**：确保 token 不被打印（现有 ErrorResponse 不回显 header）。
- **作用域**：仅 admin web 平面（`get_current_admin`）。机器平面仍用 server/agent token。

---

## 5. 兼容 / 破坏面 & 开放决策

破坏面（无 DB 迁移，纯 auth/config 逻辑）：
- `apps/server/tests/test_config.py`：删除/改写 `DOPILOT_ADMIN_API_SECRET` 覆盖断言、以及
  机器 token「从 token_secret 派生」的断言（改为 admin_api_token）；新增
  `DOPILOT_ADMIN_API_TOKEN` 覆盖测试 + `get_current_admin` 静态 token 直认测试（命中/不命中/
  空串不命中）。
- `configs/server.example.toml`、`configs/server.docker.toml`、`docs/dopilot/08-docker-deployment.md`：
  更新（去 `DOPILOT_ADMIN_API_SECRET`，加 `admin_api_token` / `DOPILOT_ADMIN_API_TOKEN`）。
- `enabled` 判定不变；fail-closed 仍要求 admin_username + admin_password + token_secret。

开放决策：
1. **`admin_api_token` 是否进 env 注入**（`DOPILOT_ADMIN_API_TOKEN`）？→ 推荐是（CI/部署注入）。
2. **机器认证默认 on 的保持**（§2.4 提示）：建议生产**务必设置 `admin_api_token`**；
   或者保留链式回退 `admin_api_token → token_secret`（更稳，但偏离"只用它"的口径）。默认按
   你的口径：**只用 admin_api_token**。
3. **是否允许"仅 token、无账号密码"启动**（让 `enabled` 也认 admin_api_token）？→ 默认否
   （web UI 仍需账号密码登录）。
4. **是否加 `admin_api_token` 最小长度校验**？→ 推荐加（≥ 16/32 字符）。
