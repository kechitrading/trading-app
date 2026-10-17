.DEFAULT_GOAL := help
UV ?= uv
COMPOSE ?= docker compose -f deploy/docker-compose.yml --env-file .env
SAFETY_COV_MODULES := src/aqta/risk/*,src/aqta/execution/*,src/aqta/audit/*

.PHONY: help
help: ## Show targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-16s %s\n", $$1, $$2}'

.PHONY: install
install: ## Install deps (incl. dev group) and pre-commit hooks
	$(UV) sync
	$(UV) run pre-commit install

.PHONY: dev
dev: ## Start api, worker, postgres(timescale), redis via docker compose (runs migrations)
	$(UV) run python scripts/init_env.py
	$(COMPOSE) up --build

.PHONY: env
env: ## Create .env from .env.example with random dev secrets (never overwrites)
	$(UV) run python scripts/init_env.py

.PHONY: down
down: ## Stop the local stack
	$(COMPOSE) down

.PHONY: api
api: ## Run the API on the host (needs postgres + redis)
	$(UV) run uvicorn aqta.api:create_app --factory --reload --host 127.0.0.1 --port 8000

.PHONY: worker
worker: ## Run the Arq worker on the host
	$(UV) run arq aqta.worker.WorkerSettings

.PHONY: migrate
migrate: ## Apply Alembic migrations to DATABASE_URL
	$(UV) run alembic upgrade head

.PHONY: audit-verify
audit-verify: ## Recompute the audit hash chain; non-zero exit on tamper
	$(UV) run python -m aqta.audit verify

.PHONY: format
format: ## Auto-format and fix lint
	$(UV) run ruff format .
	$(UV) run ruff check --fix .

.PHONY: lint
lint: ## ruff + format check + mypy + import-linter
	$(UV) run ruff check .
	$(UV) run ruff format --check .
	$(UV) run mypy
	$(UV) run lint-imports

.PHONY: test
test: ## Unit + integration tests (integration needs AQTA_TEST_DATABASE_URL) with coverage gates
	$(UV) run pytest --cov --cov-report=term-missing --cov-report=xml
	$(UV) run coverage report --include='src/aqta/risk/*' --fail-under=95
	$(UV) run coverage report --include='$(SAFETY_COV_MODULES)' --fail-under=90

.PHONY: test-unit
test-unit: ## Fast unit tests only
	$(UV) run pytest -m "not integration"

.PHONY: audit-deps
audit-deps: ## pip-audit against the locked dependency set
	mkdir -p build
	$(UV) export --frozen --all-extras --no-emit-project --format requirements-txt -o build/req-audit.txt
	$(UV) run pip-audit -r build/req-audit.txt --disable-pip
