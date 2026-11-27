# Documentation Index

This repository keeps `README.md` at the root and all other documentation under `docs/`.

## Architecture and Implementation

1. [01_ARCHITECTURE_OVERVIEW.md](./01_ARCHITECTURE_OVERVIEW.md)
2. [02_PRODUCTION_STACK.md](./02_PRODUCTION_STACK.md)
3. [03_RAG_WORKFLOW.md](./03_RAG_WORKFLOW.md)
4. [04_COMPONENT_DIAGRAMS.md](./04_COMPONENT_DIAGRAMS.md)
5. [05_SEQUENCE_DIAGRAMS.md](./05_SEQUENCE_DIAGRAMS.md)
6. [06_DATABASE_SCHEMA.md](./06_DATABASE_SCHEMA.md)
7. [07_API_DESIGN.md](./07_API_DESIGN.md)
8. [08_SERVICE_IMPLEMENTATION_GUIDE.md](./08_SERVICE_IMPLEMENTATION_GUIDE.md)
9. [09_FRONTEND_UI_DESIGN.md](./09_FRONTEND_UI_DESIGN.md)
10. [10_DEPLOYMENT_DOCKER.md](./10_DEPLOYMENT_DOCKER.md)
11. [11_SECURITY_AND_PRODUCTION_CHECKLIST.md](./11_SECURITY_AND_PRODUCTION_CHECKLIST.md)
12. [12_EVALUATION_AND_MONITORING.md](./12_EVALUATION_AND_MONITORING.md)
13. [13_AGENTIC_ARCHITECTURE_AND_CAPABILITY_MODEL.md](./13_AGENTIC_ARCHITECTURE_AND_CAPABILITY_MODEL.md)
14. [14_GITHUB_ACTIONS_CI_CD_PIPELINE.md](./14_GITHUB_ACTIONS_CI_CD_PIPELINE.md)
15. [15_MCP_SERVER_DEPLOYMENT_MODE.md](./15_MCP_SERVER_DEPLOYMENT_MODE.md) — MCP architecture (Mermaid), deployment, tools/resources/prompts
16. [16_CHUNKING_OBSERVABILITY.md](./16_CHUNKING_OBSERVABILITY.md)
17. [16_CONNECTOR_PLATFORM.md](./16_CONNECTOR_PLATFORM.md)
18. [17_CONNECTOR_OPERATIONS_RUNBOOK.md](./17_CONNECTOR_OPERATIONS_RUNBOOK.md)
19. [18_LANGFUSE_OBSERVABILITY.md](./18_LANGFUSE_OBSERVABILITY.md)
20. [19_LOCAL_LLM_PROVIDER_INTEGRATION.md](./19_LOCAL_LLM_PROVIDER_INTEGRATION.md)
21. [20_COLLABORATION_BOT_INTEGRATION.md](./20_COLLABORATION_BOT_INTEGRATION.md)
22. [21_ENTERPRISE_GRAPH_EXTRACTION.md](./21_ENTERPRISE_GRAPH_EXTRACTION.md) — Entity/relation extraction, GraphRAG, Neo4j schema, configuration, troubleshooting
23. [22_AUTHORIZATION_SYSTEM.md](./22_AUTHORIZATION_SYSTEM.md) — Authorization model, enforcement paths, and permission boundaries
24. [23_MULTILINGUAL_DOCUMENTATION_HELP_ROLLOUT.md](./23_MULTILINGUAL_DOCUMENTATION_HELP_ROLLOUT.md) — Multilingual UI locales, language-aware RAG, OCR guidance, support playbook, and QA checklist
25. [24_CITATION_PREVIEW_ARCHITECTURE.md](./24_CITATION_PREVIEW_ARCHITECTURE.md) — Citation preview drawer architecture, API contract, permission behavior, observability, and test fixtures
26. [25_PROMETHEUS_GRAFANA_OBSERVABILITY_PLAN.md](./25_PROMETHEUS_GRAFANA_OBSERVABILITY_PLAN.md) — Prometheus and Grafana metrics, dashboards, exporters, and SLO alerts (development overlay implemented; staging and production rollout planned)
27. [26_VERSIONED_ROADMAP_AND_RELEASE_PLAN.md](./26_VERSIONED_ROADMAP_AND_RELEASE_PLAN.md) — Planned release train from `0.1.0` to `1.0.0`, product-area version map, flag graduation, performance targets, and open decisions
28. [27_INGESTION_AND_WORKERS_RUNBOOK.md](./27_INGESTION_AND_WORKERS_RUNBOOK.md) — Staged ingestion chain, queues, resume and reaper, transactional outbox, failed stage retry, worker tenant binding

## Roadmap Specs (planned work)

- [roadmap/00_AUDIT_BASELINE.md](./roadmap/00_AUDIT_BASELINE.md) — Feature catalogue and audit findings at `0.1.0`
- [roadmap/01_EXECUTION_PLAN.md](./roadmap/01_EXECUTION_PLAN.md) — How the roadmap is run: roles, branch and merge process, status, and what blocks each version
- [roadmap/V0_2_0_CORRECTNESS_AND_SAFETY.md](./roadmap/V0_2_0_CORRECTNESS_AND_SAFETY.md)
- [roadmap/V0_2_0_IMPLEMENTATION_PLAN.md](./roadmap/V0_2_0_IMPLEMENTATION_PLAN.md) — File-level steps, merge order, and tests for `0.2.0`
- [roadmap/V0_3_0_TEST_AND_RELEASE_FOUNDATION.md](./roadmap/V0_3_0_TEST_AND_RELEASE_FOUNDATION.md)
- [roadmap/V0_3_0_IMPLEMENTATION_PLAN.md](./roadmap/V0_3_0_IMPLEMENTATION_PLAN.md) — File-level steps, shared-file owners, and contracts for `0.3.0`
- [roadmap/V0_3_0_LOAD_BASELINE.md](./roadmap/V0_3_0_LOAD_BASELINE.md) — Load-test baseline template for `0.3.0` (not yet measured)
- [roadmap/V0_4_0_DATA_LAYER_PERFORMANCE.md](./roadmap/V0_4_0_DATA_LAYER_PERFORMANCE.md)
- [roadmap/V0_4_0_IMPLEMENTATION_PLAN.md](./roadmap/V0_4_0_IMPLEMENTATION_PLAN.md) — File-level steps, migration chain, shared-file owners, and contracts for `0.4.0`
- [roadmap/V0_5_0_CHAT_PIPELINE_AND_STREAMING.md](./roadmap/V0_5_0_CHAT_PIPELINE_AND_STREAMING.md)
- [roadmap/V0_5_0_IMPLEMENTATION_PLAN.md](./roadmap/V0_5_0_IMPLEMENTATION_PLAN.md) — Work packages, chains, shared-file anchors, and cross-chain contracts for `0.5.0`
- [roadmap/V0_6_0_INGESTION_AND_WORKERS.md](./roadmap/V0_6_0_INGESTION_AND_WORKERS.md)
- [roadmap/V0_6_0_IMPLEMENTATION_PLAN.md](./roadmap/V0_6_0_IMPLEMENTATION_PLAN.md) — Work packages, chains, migration chain, shared-file anchors, and cross-chain contracts for `0.6.0`
- [roadmap/V0_7_0_FRONTEND_PERFORMANCE.md](./roadmap/V0_7_0_FRONTEND_PERFORMANCE.md)
- [roadmap/V0_8_0_PRODUCTION_INFRASTRUCTURE.md](./roadmap/V0_8_0_PRODUCTION_INFRASTRUCTURE.md)
- [roadmap/V0_9_0_PRODUCT_COMPLETENESS.md](./roadmap/V0_9_0_PRODUCT_COMPLETENESS.md)
- [roadmap/V1_0_0_GENERAL_AVAILABILITY.md](./roadmap/V1_0_0_GENERAL_AVAILABILITY.md)

## Setup and Operations

- [INSTALL.md](./INSTALL.md)

## Collaboration and Governance

- [CONTRIBUTING.md](./CONTRIBUTING.md)
- [CODE_OF_CONDUCT.md](./CODE_OF_CONDUCT.md)
- [SECURITY.md](./SECURITY.md)
- [CHANGELOG.md](./CHANGELOG.md)
- [DOCUMENTATION_STANDARDS.md](./DOCUMENTATION_STANDARDS.md)

## Standards and Templates

- [DOCUMENT_TEMPLATE.md](./DOCUMENT_TEMPLATE.md)
- [DOCUMENT_REVIEW_CHECKLIST.md](./DOCUMENT_REVIEW_CHECKLIST.md)
