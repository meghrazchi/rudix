.PHONY: install venv lint test run-api run-worker format migrate downgrade seed-dev

PYTHON := python3
VENV_DIR := .venv
VENV_BIN := $(VENV_DIR)/bin
PIP := $(VENV_BIN)/pip
RUFF := $(VENV_BIN)/ruff
MYPY := $(VENV_BIN)/mypy
PYTEST := $(VENV_BIN)/pytest
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

run-api:
	$(UVICORN) app.main:app --host 0.0.0.0 --port 8000 --reload --no-access-log

run-worker:
	$(CELERY) -A app.workers.celery_app:celery_app worker --loglevel=INFO

format:
	$(RUFF) check app tests --fix

migrate:
	$(ALEMBIC) upgrade head

downgrade:
	$(ALEMBIC) downgrade -1

seed-dev:
	$(PYTHON_VENV) scripts/seed_dev.py
