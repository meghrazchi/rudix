.PHONY: dev dev-down up up-d up-mcp down down-v down-mcp restart ps logs logs-api logs-worker logs-mcp logs-infra \
	up-observability down-observability logs-observability \
	up-ollama up-vllm up-litellm down-local-llm logs-local-llm pull-local-model \
	up-graph down-graph logs-graph reset-graph \
	migrate test lint check-backend \
	frontend-dev frontend-build frontend-lint frontend-typecheck frontend-test frontend-e2e frontend-format check-frontend \
	api-types api-types-check api-types-update \
	check-all install-hooks \
	eval-smoke eval-nightly

COMPOSE := docker compose
BACKEND_MAKE := $(MAKE) -C backend
NPM := npm
FRONTEND_DIR := frontend

# Local dev: infrastructure in Docker; API, workers and web on the host.
# Ctrl+C stops the host processes. See scripts/dev-local.sh for env toggles.
dev:
	./scripts/dev-local.sh

# Stop the infrastructure containers started by `make dev` (data is kept).
dev-down:
	$(COMPOSE) --profile enterprise-graph stop postgres redis rabbitmq qdrant minio clamav matomo-db matomo neo4j

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

## Prometheus & Grafana Observability
up-observability:
	$(COMPOSE) -f docker-compose.yml -f infra/observability/docker-compose.yml up -d prometheus alertmanager grafana postgres-exporter redis-exporter

down-observability:
	$(COMPOSE) -f docker-compose.yml -f infra/observability/docker-compose.yml stop prometheus alertmanager grafana postgres-exporter redis-exporter

logs-observability:
	$(COMPOSE) -f docker-compose.yml -f infra/observability/docker-compose.yml logs -f prometheus alertmanager grafana

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

install-hooks:
	$(BACKEND_MAKE) install-hooks

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

## Load testing (R03-09)
# Locust harness in ci/load (see ci/load/README.md). The stack is the integration compose
# file plus D2's LLM stub overlay; RUDIX_API_IMAGE and RUDIX_WORKER_IMAGE must name locally
# built images. Every target skips with a message when its prerequisites are missing.
# Install Locust with `make -C backend install-load`. Example:
#   make load-test LOAD_SCENARIO=documents_list LOAD_USERS=20 LOAD_SPAWN_RATE=5
.PHONY: load-stack-up load-stack-down load-test
LOAD_ENV_FILE ?= .env.ci.integration
LOAD_COMPOSE_FILES := -f deploy/compose/docker-compose.integration.yml \
	-f deploy/compose/docker-compose.integration-stub.yml
LOAD_COMPOSE = $(COMPOSE) $(LOAD_COMPOSE_FILES) --env-file $(LOAD_ENV_FILE)
LOCUST ?= backend/.venv/bin/locust
RUDIX_LOAD_BASE_URL ?= http://localhost:8000
LOAD_METRICS_URL ?= $(RUDIX_LOAD_BASE_URL)/metrics
LOAD_SCENARIO ?= documents_list
LOAD_USERS ?= 10
LOAD_SPAWN_RATE ?= 2
LOAD_DURATION_SECONDS ?= 300
LOAD_RESULTS_DIR ?= ci/load/results

load-stack-up:
	@if [ ! -f deploy/compose/docker-compose.integration-stub.yml ] || [ ! -f "$(LOAD_ENV_FILE)" ]; then \
		echo "load-stack-up: needs deploy/compose/docker-compose.integration-stub.yml and $(LOAD_ENV_FILE) (see ci/load/README.md); skipping."; \
		exit 0; \
	fi; \
	$(LOAD_COMPOSE) up -d --remove-orphans && \
	$(LOAD_COMPOSE) run --rm migrate && \
	if [ -n "$$BOOTSTRAP_ADMIN_EMAIL" ]; then \
		$(LOAD_COMPOSE) run --rm -e BOOTSTRAP_ADMIN_EMAIL -e BOOTSTRAP_ADMIN_PASSWORD \
			api python scripts/bootstrap_admin.py; \
	fi

load-stack-down:
	@if [ ! -f deploy/compose/docker-compose.integration-stub.yml ] || [ ! -f "$(LOAD_ENV_FILE)" ]; then \
		echo "load-stack-down: no load stack configuration found; skipping."; \
		exit 0; \
	fi; \
	$(LOAD_COMPOSE) down -v --remove-orphans

load-test:
	@case "$(LOAD_SCENARIO)" in \
		chat_ws) user_class=ChatWsUser ;; \
		chat_http) user_class=ChatHttpUser ;; \
		documents_list) user_class=DocumentsListUser ;; \
		upload_ingest) user_class=UploadIngestUser ;; \
		admin_dashboard) user_class=AdminDashboardUser ;; \
		*) echo "load-test: unknown LOAD_SCENARIO=$(LOAD_SCENARIO)"; exit 2 ;; \
	esac; \
	if [ ! -x "$(LOCUST)" ]; then \
		echo "load-test: $(LOCUST) not found; run 'make -C backend install-load' (skipping)."; \
		exit 0; \
	fi; \
	if ! curl -fsS "$(RUDIX_LOAD_BASE_URL)/api/v1/health" >/dev/null 2>&1; then \
		echo "load-test: no API at $(RUDIX_LOAD_BASE_URL); run 'make load-stack-up' (skipping)."; \
		exit 0; \
	fi; \
	mkdir -p "$(LOAD_RESULTS_DIR)"; \
	out="$(LOAD_RESULTS_DIR)/$(LOAD_SCENARIO)"; \
	python3 ci/load/collect_metrics.py run "$(LOAD_METRICS_URL)" \
		--duration "$(LOAD_DURATION_SECONDS)" --out "$${out}_metrics.json" & metrics_pid=$$!; \
	"$(LOCUST)" -f ci/load/locustfile.py --headless -u "$(LOAD_USERS)" -r "$(LOAD_SPAWN_RATE)" \
		-t "$(LOAD_DURATION_SECONDS)s" --csv "$$out" --only-summary "$$user_class"; \
	locust_status=$$?; \
	wait $$metrics_pid; \
	python3 ci/load/report.py --scenario "$(LOAD_SCENARIO)" --stats "$${out}_stats.csv" \
		--metrics "$${out}_metrics.json"; \
	exit $$locust_status
