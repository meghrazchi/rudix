.PHONY: up up-d up-mcp down down-v down-mcp restart ps logs logs-api logs-worker logs-mcp logs-infra \
	up-ollama up-vllm up-litellm down-local-llm logs-local-llm pull-local-model \
	up-graph down-graph logs-graph reset-graph \
	migrate test lint check-backend \
	frontend-dev frontend-build frontend-lint frontend-typecheck frontend-test frontend-e2e frontend-format check-frontend \
	api-types api-types-check api-types-update \
	check-all \
	eval-smoke eval-nightly

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

## Local model profiles — F222
# Start one provider at a time; each binds to the internal network only (no host ports).
# Set LOCAL_LLM_BASE_URL and LLM_DEFAULT_PROVIDER=local in .env before starting the stack.
# See .env.example for per-provider URL and model name guidance.

up-ollama:
	$(COMPOSE) --profile ollama up -d --build ollama

up-vllm:
	$(COMPOSE) --profile vllm up -d --build vllm

up-litellm:
	$(COMPOSE) --profile litellm up -d --build litellm

down-local-llm:
	$(COMPOSE) --profile ollama --profile vllm --profile litellm stop ollama vllm litellm 2>/dev/null; true

logs-local-llm:
	$(COMPOSE) --profile ollama --profile vllm --profile litellm logs -f ollama vllm litellm 2>/dev/null; true

pull-local-model:
	$(COMPOSE) --profile ollama exec ollama ollama pull $${OLLAMA_MODEL:-llama3.2}

## Enterprise Graph (Neo4j) — F279
# Start the Neo4j container and enable graph support.
# Prerequisites: set ENTERPRISE_GRAPH_ENABLED=true, NEO4J_URI=bolt://neo4j:7687,
# NEO4J_USERNAME, and NEO4J_PASSWORD in .env, then restart the main stack.
# Neo4j binds to the internal Docker network only (no host ports by default).
# To allow host access for the Neo4j Browser, add a docker-compose.override.yml with
#   ports: ["7474:7474", "7687:7687"] under the neo4j service.

up-graph:
	$(COMPOSE) --profile enterprise-graph up -d neo4j

down-graph:
	$(COMPOSE) --profile enterprise-graph stop neo4j

logs-graph:
	$(COMPOSE) --profile enterprise-graph logs -f neo4j

reset-graph:
	$(COMPOSE) --profile enterprise-graph stop neo4j
	docker volume rm $$($(COMPOSE) --profile enterprise-graph config --volumes | grep neo4j_data) 2>/dev/null; true
	$(COMPOSE) --profile enterprise-graph up -d neo4j

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

## Local model benchmark (F226)
# Run local model benchmark suites against cloud_baseline and local_profile, then
# fetch the model-profile comparison report. Requires a running API and the
# RUDIX_API_BASE_URL / RUDIX_API_TOKEN environment variables to be set.
benchmark-local-model:
	python ci/scripts/local_model_benchmark.py

## Accuracy evaluation gates (F302)
# Run the accuracy eval CI script in smoke or nightly mode.
# Requires RUDIX_API_BASE_URL, RUDIX_API_TOKEN, ACCURACY_EVAL_SET_ID, and
# QUALITY_GATE_ID to be set in your environment.
eval-smoke:
	EVAL_MODE=smoke python ci/scripts/accuracy_eval_runner.py

eval-nightly:
	EVAL_MODE=nightly python ci/scripts/accuracy_eval_runner.py
