# Security Policy

## Supported versions

dopilot is pre-1.0 and under active development. Only the latest commit on the
default branch (`master`) receives security fixes. There are no maintained
release branches yet; pin to a specific commit if you deploy from source and
upgrade forward to pick up fixes.

| Version | Supported |
| --- | --- |
| `master` (latest) | ✅ |
| Older commits / tags | ❌ |

## Reporting a vulnerability

Please report suspected vulnerabilities privately rather than opening a public
issue:

- Use GitHub's **"Report a vulnerability"** (Security → Advisories) on the
  repository, or
- email the maintainer at **rabbirbot00@gmail.com** with `dopilot security` in
  the subject.

Include affected component (server / agent / web), a reproduction or proof of
concept, and the impact you observed. Please allow a reasonable window for a fix
before any public disclosure.

## Operator hardening — replace default secrets before exposure

dopilot ships **example** configuration with placeholder credentials. These are
for local development only and are **not production-safe**. Before exposing any
deployment to an untrusted network you **must** replace them:

- **Web admin auth** (`[auth]` in the server config): the example/compose
  `change-me` username/password must be changed. Web auth is
  *config-present-or-off* — if you leave it unset the admin UI/API is
  unauthenticated, so set real credentials before exposing the server.
- **Agent↔server token** (`[agent].server_shared_token`): replace the
  `change-me-agent-server-token` placeholder so agents authenticate to the
  server heartbeat endpoint.
- **Redis AUTH** (`[redis].url`): the example uses a `dopilot` password against a
  local Redis. Use a strong password (and ACLs) and do not expose Redis to
  untrusted networks. Redis is the server↔agent message bus.
- **PostgreSQL credentials**: the example `dopilot/dopilot` database credentials
  are for local development only.

dopilot is intentionally **single-admin** (no multi-user/RBAC) and the server
runs **single-replica**. It does not ship a reverse proxy or TLS termination —
put it behind your own TLS-terminating proxy when exposing it.

> A root `LICENSE` of MIT covers dopilot's own source. It does not audit the
> licenses of third-party runtime dependencies; a dependency license review is a
> separate public-release follow-up.
