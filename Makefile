.PHONY: up up-d up-mcp down down-v down-mcp restart ps logs logs-api logs-worker logs-mcp logs-infra \
	migrate test lint check-backend \
	frontend-dev frontend-build frontend-lint frontend-typecheck frontend-test frontend-e2e frontend-format check-frontend \
	api-types api-types-check api-types-update \
	check-all

COMPOSE := docker compose
BACKEND_MAKE := $(MAKE) -C backend
NPM := npm
FRONTEND_DIR := frontend

up:
	$(COMPOSE) up --build

up-d:
	$(COMPOSE) up -d --build

up-mcp:
	$(COMPOSE) --profile mcp up -d --build mcp

down:
	$(COMPOSE) down

down-v:
	$(COMPOSE) down -v

down-mcp:
	$(COMPOSE) --profile mcp stop mcp

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

logs-mcp:
	$(COMPOSE) --profile mcp logs -f mcp

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

## API type generation
# Regenerate src/lib/api/generated/schema.d.ts from the committed openapi.json.
api-types:
	$(NPM) --prefix $(FRONTEND_DIR) run api:generate

# Verify that generated types match the committed openapi.json (used in CI).
api-types-check:
	$(NPM) --prefix $(FRONTEND_DIR) run api:check

# Fetch a fresh openapi.json from the backend and regenerate types.
# Requires the backend API to be reachable (run `make up-d` first).
api-types-update:
	$(NPM) --prefix $(FRONTEND_DIR) run api:update-schema

check-all:
	$(MAKE) check-backend
	$(MAKE) check-frontend
	$(MAKE) api-types-check
