.PHONY: install lint test test-verbose audit run-api run-worker run-mcp-http run-mcp-stdio format check-revisions migrate downgrade seed-dev install-hooks

PYTHON := python3
VENV_DIR := .venv
VENV_BIN := $(VENV_DIR)/bin
RUFF := $(VENV_BIN)/ruff
MYPY := $(VENV_BIN)/mypy
PYTEST := $(VENV_BIN)/pytest
PIP_AUDIT := $(VENV_BIN)/pip-audit
UVICORN := $(VENV_BIN)/uvicorn
CELERY := $(VENV_BIN)/celery
ALEMBIC := $(VENV_BIN)/alembic
PYTHON_VENV := $(VENV_BIN)/python

# uv drives installs from the hashed uv.lock (R03-05). Use the uv on PATH, else bootstrap a
# pinned copy into .tools (git-ignored).
UV_VERSION ?= 0.12.17
UV ?= $(shell command -v uv 2>/dev/null)
ifeq ($(strip $(UV)),)
UV := .tools/bin/uv
endif
AUDIT_REQUIREMENTS := .audit-requirements.txt

.tools/bin/uv:
	$(PYTHON) -m venv .tools
	.tools/bin/pip install --quiet uv==$(UV_VERSION)

# Creates backend/.venv and installs the locked set (editable project). Fails if uv.lock is stale.
install: $(UV)
	$(UV) sync --frozen --extra dev

.PHONY: lock lock-check
lock: $(UV)
	$(UV) lock

lock-check: $(UV)
	$(UV) lock --check

install-hooks: install
	$(VENV_BIN)/pre-commit install --hook-type pre-commit --hook-type pre-push

lint:
	$(RUFF) check app tests
	$(MYPY) app

test:
	$(PYTEST)

test-verbose:
	$(PYTEST) -vv --timeout=60 --tb=short

.PHONY: test-cov
# Prints coverage and fails below [tool.coverage.report] fail_under in pyproject.toml (R03-02).
test-cov:
	$(PYTEST) --cov=app --cov-report=term

.PHONY: test-postgres
# The pg_migrated_url fixture also runs `alembic upgrade head`; the explicit step below
# surfaces migration errors before pytest starts. PYTEST_ARGS adds flags, e.g. --junitxml.
PYTEST_ARGS ?=
test-postgres:
	@test -n "$(TEST_DATABASE_URL)" || (echo "TEST_DATABASE_URL must be set (postgresql+asyncpg://...)"; exit 1)
	DATABASE_URL="$(TEST_DATABASE_URL)" $(ALEMBIC) upgrade head
	TEST_DATABASE_URL="$(TEST_DATABASE_URL)" $(PYTEST) -m "requires_postgres or requires_redis" $(PYTEST_ARGS)

# Audits the locked set (hash-pinned), not whatever happens to be installed.
audit: $(UV)
	$(UV) export --frozen --no-emit-project --all-extras --format requirements-txt -o $(AUDIT_REQUIREMENTS)
	$(PIP_AUDIT) -r $(AUDIT_REQUIREMENTS) --require-hashes --disable-pip

.PHONY: audit-report
# AUDIT_OUTPUT: absolute path of the JSON report. Findings do not fail the target; the
# severity gate in security.yml decides.
audit-report: $(UV)
	@test -n "$(AUDIT_OUTPUT)" || (echo "AUDIT_OUTPUT must be set to an absolute path"; exit 1)
	$(UV) export --frozen --no-emit-project --all-extras --format requirements-txt -o $(AUDIT_REQUIREMENTS)
	mkdir -p "$$(dirname "$(AUDIT_OUTPUT)")"
	$(PIP_AUDIT) -r $(AUDIT_REQUIREMENTS) --require-hashes --disable-pip --format json -o "$(AUDIT_OUTPUT)" || true
	@test -s "$(AUDIT_OUTPUT)" || (echo "pip-audit produced no report at $(AUDIT_OUTPUT)"; exit 1)

run-api:
	$(UVICORN) app.main:app --host 0.0.0.0 --port 8000 --reload --no-access-log

run-worker:
	$(CELERY) -A app.workers.celery_app:celery_app worker --loglevel=INFO

.PHONY: run-beat
run-beat:
	$(CELERY) -A app.workers.celery_app:celery_app beat --loglevel=INFO --schedule /tmp/celerybeat-schedule

run-mcp-http:
	$(PYTHON_VENV) -m app.mcp.main --transport streamable_http

run-mcp-stdio:
	$(PYTHON_VENV) -m app.mcp.main --transport stdio

format:
	$(RUFF) format app tests
	$(RUFF) check app tests --fix

check-revisions:
	@out=$$($(ALEMBIC) heads 2>&1); \
	count=$$(echo "$$out" | grep -c "(head)" || true); \
	if [ "$$count" -ne 1 ]; then \
		echo "ERROR: expected 1 alembic head, found $$count (duplicate revision IDs or unmerged branches):"; \
		echo "$$out"; \
		exit 1; \
	fi

migrate: check-revisions
	$(ALEMBIC) upgrade head

# Neo4j graph schema migrations (no-op unless ENTERPRISE_GRAPH_ENABLED=true).
migrate-graph:
	$(PYTHON_VENV) scripts/run_graph_migrations.py

downgrade:
	$(ALEMBIC) downgrade -1

seed-dev:
	$(PYTHON_VENV) scripts/seed_dev.py

# Locust load-test harness (ci/load, R03-09). Dev-only; never part of an image.
install-load: $(UV)
	$(UV) sync --frozen --extra dev --extra load
