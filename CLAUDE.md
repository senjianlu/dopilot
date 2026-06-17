# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is right now

**dopilot is currently a docs-first planning repo.** There is no dopilot application code yet — the only code present is the upstream **scrapydweb 1.6.0** snapshot under `reference/scrapydweb/`, kept as a *read-only baseline reference*. dopilot is the private scheduling platform being built by reworking scrapydweb (Flask-based Scrapyd cluster manager).

Two things follow from this and matter constantly:

1. **`reference/scrapydweb/` is reference only.** Do not treat it as the project source, do not "fix" it, and it must NOT be part of any Docker build context (`.dockerignore` must exclude `reference/`). It exists so you can read how scrapydweb works and diff against upstream.
2. **The `docs/` tree is the source of truth** for goals, decisions, and the rework plan. When the user asks for behavior/architecture decisions, the answer is usually already written there. Update docs when decisions change.

## Where to read first

- `docs/dopilot/00-requirements.md` — **北极星 / north-star**: product goals, the confirmed decisions table, the 4-phase roadmap. Read this before proposing anything.
- `docs/dopilot/10-roadmap.md` — consolidated rework roadmap (ties together current-state + gaps + decisions).
- `docs/architecture/` — how scrapydweb works today (the rework baseline): overview, bootstrap/config, data model, scheduler engine, views/frontend, scrapyd cluster I/O, auth/utils.
- `docs/dopilot/0x-gap-*.md` — per-area gap analyses (executors, scheduling/nodes/push, realtime logs, i18n).

**Docs convention:** assertions are cited as `file:line`, and those paths are **relative to `reference/scrapydweb/`** (e.g. `vars.py:29` means `reference/scrapydweb/scrapydweb/vars.py:29`). Keep this convention when editing docs.

## Confirmed decisions you must respect

These are locked in `docs/dopilot/00-requirements.md` §4 — don't relitigate them:

- **Three scheduled-object types, done in strict order:** ① Scrapy (via scrapyd) → ③ plain Python3 scripts → ② Docker long-lived crawlers. One type stable before the next.
- **Two deploy roles, both Docker:** `server` (Web + scheduler hub) and `agent` (worker executor).
- **Single admin only** — no multi-user/RBAC.
- **Frontend = full rewrite:** Vue 3 + Element Plus + Vite + TypeScript, front/back split (Flask collapses to `/api/v1/*` JSON), progressive strangler migration.
- **Realtime logs = SSE** (one-way, works under plain WSGI) + a `LogSource` abstraction.
- **Push mode** = dispatch a task to a specific worker for immediate execution.
- **Image publishing (decision 7):** build & push to **Docker Hub `rabbir/dopilot:latest`** (server) and `rabbir/dopilot-agent:latest` (agent). ⚠️ Image namespace `rabbir` ≠ git `origin` `senjianlu/dopilot` — they are unrelated; never use `senjianlu` as an image prefix.
- **Monorepo (decision 8):** server and agent are developed in **this same repo**; not split into multiple repos.

The three "abstract-first" seams to establish in phase 0/1 (so you don't edit three executors three times): `BaseExecutor`, `LogSource`, `node_strategy`. See `10-roadmap.md` §1.

## Critical pitfalls (verified against scrapydweb source)

- **`pkg_resources` / setuptools:** APScheduler 3.6.0 imports `from pkg_resources import ...`, which `setuptools>=81` removed. `pip install -e` pulls in new setuptools and breaks `import scrapydweb`. Fix: `pip install "setuptools<81"` (or bump APScheduler to 3.10.x and re-verify). Pin the chosen fix in `requirements.txt`. See `docs/dopilot/05-dev-setup-and-known-issues.md` §4.1.
- **Startup wipes directories:** `vars.py` runs at import time and deletes `*.*` files in `parse/`, `deploy/`, `schedule/` under `DATA_PATH` on every process/container start (keeps only `ScrapydWeb_demo.log`). These dirs are transient — never expect their contents to survive a restart. Persist only `database/` (4 SQLite DBs + APScheduler jobstore), plus optionally `history_log/` and `stats/`. See `docs/dopilot/08-docker-deployment.md` §3.
- **Single-instance scheduler:** the in-process `BackgroundScheduler` has no distributed lock — multiple server replicas = duplicate timer firing. Server runs single-replica until scheduling is externalized.
- **Hardcoded config file:** config filename `scrapydweb_settings_v11.py` is hardcoded (`vars.py:29`) and only found in `os.getcwd()` (`run.py:124`). Containers must mount it into the working directory.
- **Base image must be glibc (slim/debian), not Alpine** — subprocess parent-death signaling uses `libc.so.6` prctl (`sub_process.py:38`), which musl doesn't satisfy.

## Running the scrapydweb baseline (current dev setup)

Per `docs/dopilot/05-dev-setup-and-known-issues.md`:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip wheel
pip install -e reference/scrapydweb     # editable install of the scrapydweb baseline
pip install "setuptools<81"             # REQUIRED — see pitfall above, else import fails
scrapydweb                              # first run scaffolds scrapydweb_settings_v11.py in cwd, then configure SCRAPYD_SERVERS
```

There is no dopilot build/test/lint pipeline yet — those land in phase 0 (rename per `09-package-rename.md`, then `Dockerfile.server` / `Dockerfile.agent` / `.dockerignore` / `.github/workflows/docker.yml` per `08-docker-deployment.md` §7). The scrapydweb regression tests live at `reference/scrapydweb/tests/` and are the zero-regression safety net (`docs/dopilot/07-testing-baseline.md`).

## Git remotes

- `origin` → https://github.com/senjianlu/dopilot (this repo)
- `upstream` → https://github.com/my8100/scrapydweb.git (track upstream for diff/cherry-pick; do NOT merge its history)
