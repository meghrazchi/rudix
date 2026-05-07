.PHONY: up up-d down down-v restart ps logs logs-api logs-worker logs-infra migrate test lint

COMPOSE := docker compose
BACKEND_MAKE := $(MAKE) -C backend

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
