# Codex Review

## Findings

- No blocking code findings after Codex review.

## Codex Corrections Applied

- Replaced residual README wording that still said "admin API secret" with
  "admin API token".
- Replaced `configs/server.example.toml`'s `token_secret = "change-me"` with the
  same generated long example value used by Docker config, per the user's
  explicit request not to leave the signing key as `change-me`.
- Updated source-of-truth docs:
  - `docs/dopilot/00-requirements.md`
  - `docs/dopilot/03-gap-realtime-logs.md`
  - `docs/dopilot/06-frontend-rewrite.md`

## Review Notes

- `get_current_admin()` accepts the static token only when web auth is enabled,
  so `admin_api_token` does not bypass fail-closed startup semantics.
- Static token comparison uses a constant-time compare with non-empty guards.
- `DOPILOT_ADMIN_API_SECRET` is no longer in server env overrides and no longer
  used by the agent fallback path. Remaining mentions are tests, code comments,
  and live docs that explicitly describe the removed variable as having no
  effect.
- Machine-token fallback now derives from `auth.admin_api_token`; when it is
  empty and no split token is configured, machine auth remains off. This is an
  intentional behavioral change and is documented.
- Default single-token Docker posture injects `DOPILOT_ADMIN_API_TOKEN` into
  server and all agents. The docs now call out that split tokens are required if
  a deployment does not want agents to hold a token that can also authenticate
  admin API requests.

## Residual Risks

- The baked Docker `token_secret` is committed in the open-source repo and
  therefore public. It is no longer `change-me`, but it is not a per-deployment
  secret. This is accepted by user decision for the default deployment path;
  high-security deployments should mount their own TOML.
