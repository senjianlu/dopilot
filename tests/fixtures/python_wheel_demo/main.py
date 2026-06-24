"""dopilot phase-2b demo wheel payload (user-facing code).

This is the ONLY user code packaged in the demo wheel; the ``.dist-info``
metadata files are added by the wheel format. It is intended to run with::

    python -m main

after the wheel is installed by the agent via
``pip install --no-deps --target <site> <wheel>`` and ``main`` is importable
because ``<site>`` is on ``PYTHONPATH`` (phase 2b strategy: no venv, no deps).

It requests a URL and prints the response headers using ONLY the Python
standard library. The URL is configurable via the ``DOPILOT_DEMO_URL``
environment variable so tests can target a local HTTP server instead of the
public default ``https://httpbin.org/headers`` (no external network in CI).
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request

DEFAULT_URL = "https://httpbin.org/headers"


def fetch_headers(url: str) -> dict[str, str]:
    """Return the response headers for ``url`` (stdlib only)."""
    request = urllib.request.Request(
        url, headers={"User-Agent": "dopilot-demo/0.1"}
    )
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
        return dict(response.headers.items())


def main() -> int:
    dopilot_env = {
        key: value for key, value in sorted(os.environ.items())
        if key.startswith("DOPILOT_")
    }
    print("dopilot-demo: dopilot env:", flush=True)
    print(json.dumps(dopilot_env, indent=2, sort_keys=True), flush=True)

    url = os.environ.get("DOPILOT_DEMO_URL", DEFAULT_URL)
    print(f"dopilot-demo: requesting {url}", flush=True)
    try:
        headers = fetch_headers(url)
    except Exception as exc:  # noqa: BLE001 - demo: surface any failure as exit 1
        print(f"dopilot-demo: request failed: {exc}", file=sys.stderr, flush=True)
        return 1
    print("dopilot-demo: response headers:", flush=True)
    print(json.dumps(headers, indent=2, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
