"""Local container healthcheck for the outbound-only agent (phase 2.2.7).

The agent no longer exposes an HTTP ``/health`` endpoint, so the container
healthcheck cannot probe a listener. This module is a tiny CLI the Docker
``healthcheck`` invokes:

- it loads the baked/default agent config (with env overrides), so a config that
  fails to load is itself a failure;
- when ``[scrapyd].start = true``, it verifies the local scrapyd the agent
  manages answers ``daemonstatus.json`` on its container-internal host/port;
- when ``[scrapyd].start = false`` (externally managed scrapyd), loading the
  config is the only assertion.

It opens **no** agent HTTP listener and requires none. It exits ``0`` on success
and non-zero on a config-load or managed-scrapyd failure. Real liveness is the
agent -> server heartbeat (server-side ``nodes.last_seen_at``); this check is
only a local restart hint.

Run as ``python -m dopilot_agent.healthcheck`` or via the ``dopilot-agent-healthcheck``
console script.
"""

from __future__ import annotations

import asyncio
import sys

from .config.loader import DEFAULT_CONFIG_PATH, load_settings
from .scrapyd.client import ScrapydClient, ScrapydError


async def _check_scrapyd(host: str, port: int) -> None:
    client = ScrapydClient(base_url=f"http://{host}:{port}", timeout=3.0)
    await client.daemonstatus()


def main() -> int:
    try:
        settings = load_settings(default_path=DEFAULT_CONFIG_PATH)
    except Exception as exc:  # noqa: BLE001 - any load failure is unhealthy
        print(f"agent healthcheck: config load failed: {exc}", file=sys.stderr)
        return 1

    if settings.scrapyd.start:
        try:
            asyncio.run(_check_scrapyd(settings.scrapyd.host, settings.scrapyd.port))
        except ScrapydError as exc:
            print(
                f"agent healthcheck: local scrapyd not ready: {exc}",
                file=sys.stderr,
            )
            return 1
        except Exception as exc:  # noqa: BLE001 - unreachable / unexpected
            print(
                f"agent healthcheck: local scrapyd check failed: {exc}",
                file=sys.stderr,
            )
            return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
