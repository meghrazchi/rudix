.PHONY: install venv lint test test-verbose audit run-api run-worker run-mcp-http run-mcp-stdio format migrate downgrade seed-dev

PYTHON := python3
VENV_DIR := .venv
VENV_BIN := $(VENV_DIR)/bin
PIP := $(VENV_BIN)/pip
RUFF := $(VENV_BIN)/ruff
MYPY := $(VENV_BIN)/mypy
PYTEST := $(VENV_BIN)/pytest
PIP_AUDIT := $(VENV_BIN)/pip-audit
UVICORN := $(VENV_BIN)/uvicorn
CELERY := $(VENV_BIN)/celery
ALEMBIC := $(VENV_BIN)/alembic
PYTHON_VENV := $(VENV_BIN)/python

venv:
	$(PYTHON) -m venv $(VENV_DIR)

install: venv
	$(PIP) install --upgrade pip
	$(PIP) install -e .[dev]

lint:
	$(RUFF) check app tests
	$(MYPY) app

test:
	$(PYTEST)

test-verbose:
	$(PYTEST) -vv --timeout=60 --tb=short

audit:
	$(PIP_AUDIT)

run-api:
	$(UVICORN) app.main:app --host 0.0.0.0 --port 8000 --reload --no-access-log

run-worker:
	$(CELERY) -A app.workers.celery_app:celery_app worker --loglevel=INFO

run-mcp-http:
	$(PYTHON_VENV) -m app.mcp.main --transport streamable_http

run-mcp-stdio:
	$(PYTHON_VENV) -m app.mcp.main --transport stdio

format:
	$(RUFF) check app tests --fix

migrate:
	$(ALEMBIC) upgrade head

downgrade:
	$(ALEMBIC) downgrade -1

seed-dev:
	$(PYTHON_VENV) scripts/seed_dev.py
