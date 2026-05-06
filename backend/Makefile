.PHONY: install lint test run-api run-worker format

install:
	python3 -m pip install --upgrade pip
	python3 -m pip install -e .[dev]

lint:
	ruff check app tests
	mypy app

test:
	pytest

run-api:
	uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

run-worker:
	celery -A app.workers.celery_app:celery_app worker --loglevel=INFO

format:
	ruff check app tests --fix
