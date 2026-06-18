"""Local scrapyd integration (phase 1).

The agent owns a single scrapyd child process bound to a container-internal
port (never exposed to the host) and talks to it over HTTP. This package holds:

- :mod:`dopilot_agent.scrapyd.process` — the scrapyd subprocess manager
  (writes ``scrapyd.conf``, start/stop/is_running/pid, parent-death best-effort);
- :mod:`dopilot_agent.scrapyd.client` — a thin async httpx client for scrapyd's
  ``addversion`` / ``schedule`` / ``cancel`` / ``listjobs`` JSON API.

The client is injectable (custom httpx transport) so tests drive a fake scrapyd
in-process without a real scrapyd binary.
"""
