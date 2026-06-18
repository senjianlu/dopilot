# dopilot dev Makefile. Commands are copy-pasteable; run from the repo root.
#
# Python packages install in dependency order: protocol -> server -> agent.
# uvicorn always runs workers=1 (single-instance hard constraint).

.PHONY: install web-install db-up migrate server agent web test compose-config fmt lint

# --- Python: create venv + editable installs (protocol first) --------------
install:
	python3.12 -m venv .venv
	. .venv/bin/activate && pip install -U pip wheel
	. .venv/bin/activate && pip install -e ./packages/protocol
	. .venv/bin/activate && pip install -e "./apps/server[dev]"
	. .venv/bin/activate && pip install -e "./apps/agent[dev]"

# --- Web: pnpm workspace install -------------------------------------------
web-install:
	corepack enable pnpm
	pnpm install

# --- Local Postgres (compose, db service only) -----------------------------
db-up:
	cd deploy/docker && docker compose up -d db

# --- Alembic migrations (server owns the schema) ---------------------------
migrate:
	cd apps/server && DOPILOT_CONFIG=../../configs/server.example.toml alembic upgrade head

# --- Run processes ----------------------------------------------------------
server:
	DOPILOT_CONFIG=configs/server.example.toml dopilot-server

agent:
	DOPILOT_CONFIG=configs/agent.example.toml dopilot-agent

web:
	pnpm --filter web dev

# --- Tests (python three dirs + web) ---------------------------------------
test:
	pytest apps/server/tests apps/agent/tests packages/protocol/tests
	pnpm --filter web test

# --- Compose validation -----------------------------------------------------
compose-config:
	cd deploy/docker && docker compose config

# --- Formatting / linting ---------------------------------------------------
fmt:
	ruff format .

lint:
	ruff check .
