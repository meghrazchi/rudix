.PHONY: up up-d down down-v restart ps logs logs-api logs-worker logs-infra \
	migrate test lint check-backend \
	frontend-dev frontend-build frontend-lint frontend-typecheck frontend-test frontend-e2e frontend-format check-frontend \
	check-all

COMPOSE := docker compose
BACKEND_MAKE := $(MAKE) -C backend
NPM := npm
FRONTEND_DIR := frontend

up:
	$(COMPOSE) up --build

up-d:
	$(COMPOSE) up -d --build

down:
	$(COMPOSE) down

down-v:
	$(COMPOSE) down -v

restart:
	$(COMPOSE) restart

ps:
	$(COMPOSE) ps

logs:
	$(COMPOSE) logs -f

logs-api:
	$(COMPOSE) logs -f api

logs-worker:
	$(COMPOSE) logs -f worker

logs-infra:
	$(COMPOSE) logs -f postgres qdrant minio rabbitmq redis

migrate:
	$(BACKEND_MAKE) migrate

test:
	$(BACKEND_MAKE) test

lint:
	$(BACKEND_MAKE) lint

check-backend:
	$(BACKEND_MAKE) lint
	$(BACKEND_MAKE) test

frontend-dev:
	$(NPM) --prefix $(FRONTEND_DIR) run dev

frontend-build:
	$(NPM) --prefix $(FRONTEND_DIR) run build

frontend-lint:
	$(NPM) --prefix $(FRONTEND_DIR) run lint

frontend-typecheck:
	$(NPM) --prefix $(FRONTEND_DIR) run typecheck

frontend-test:
	$(NPM) --prefix $(FRONTEND_DIR) run test

frontend-e2e:
	$(NPM) --prefix $(FRONTEND_DIR) run test:e2e

frontend-format:
	$(NPM) --prefix $(FRONTEND_DIR) run format

check-frontend:
	$(MAKE) frontend-lint
	$(MAKE) frontend-typecheck
	$(MAKE) frontend-test

check-all:
	$(MAKE) check-backend
	$(MAKE) check-frontend
