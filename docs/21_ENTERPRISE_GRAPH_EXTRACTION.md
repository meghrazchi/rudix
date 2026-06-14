# 21 — Enterprise Graph Extraction

Enterprise Graph Extraction enriches indexed documents with a Neo4j knowledge graph of canonical entities, relationships, and evidence links. The graph layer is entirely optional — all upload, RAG, and chat flows continue to work normally when it is disabled.

---

## Table of Contents

1. [Architecture overview](#1-architecture-overview)
2. [Configuration reference](#2-configuration-reference)
3. [Extraction pipeline](#3-extraction-pipeline)
4. [Entity types](#4-entity-types)
5. [Relationship types](#5-relationship-types)
6. [Entity resolution](#6-entity-resolution)
7. [Graph extraction lifecycle](#7-graph-extraction-lifecycle)
8. [Neo4j schema](#8-neo4j-schema)
9. [GraphRAG retrieval](#9-graphrag-retrieval)
10. [API reference](#10-api-reference)
11. [Deployment](#11-deployment)
12. [Troubleshooting](#12-troubleshooting)

---

## 1. Architecture overview

```
Upload / Connector sync
        │
        ▼
  Document pipeline (Celery worker)
        │
        ├── text extraction → chunking → embeddings → Qdrant
        │
        └── graph extraction (when enabled)
                │
                ├── Stage 1: Entity extraction (LLM → Neo4j Entity nodes)
                ├── Stage 2: Entity resolution (dedup / merge)
                ├── Stage 3: Relation extraction (LLM → Neo4j typed edges)
                └── Evidence linking (Chunk → Entity provenance)
```

**Storage responsibilities**

| Store      | Holds |
|------------|-------|
| PostgreSQL | Source-of-truth for documents, chunks, users, workspaces |
| Qdrant     | Dense embeddings for semantic similarity search |
| Neo4j      | Derived canonical entities, aliases, typed relationships, evidence links |

Neo4j is derived data only. Dropping the graph database and re-indexing all documents rebuilds it completely.

---

## 2. Configuration reference

All variables are set in `.env`. Restart the API and Celery workers after changes.

### 2.1 Neo4j connection

| Variable | Default | Description |
|----------|---------|-------------|
| `ENTERPRISE_GRAPH_ENABLED` | `false` | Master switch. Set `true` to activate the graph layer. |
| `NEO4J_URI` | `bolt://localhost:7687` | Bolt URI. Supported schemes: `bolt://`, `neo4j://`, `bolt+s://`, `neo4j+s://`. |
| `NEO4J_USERNAME` | `neo4j` | Neo4j username. |
| `NEO4J_PASSWORD` | *(required)* | Neo4j password. Never logged. Rotate before production. |
| `NEO4J_DATABASE` | `neo4j` | Target database name. |
| `NEO4J_CONNECTION_TIMEOUT_SECONDS` | `5` | TCP connect timeout. |
| `NEO4J_QUERY_TIMEOUT_SECONDS` | `10` | Per-query execution timeout. |
| `NEO4J_MAX_CONNECTION_POOL_SIZE` | `50` | Bolt connection pool per process. |

### 2.2 Entity extraction

| Variable | Default | Description |
|----------|---------|-------------|
| `FEATURE_ENABLE_ENTITY_EXTRACTION` | `false` | Enable LLM-based entity extraction after chunking. Requires `ENTERPRISE_GRAPH_ENABLED=true`. |
| `ENTITY_EXTRACTION_BATCH_SIZE` | `10` | Chunks sent to the LLM per batch (1–50). |
| `ENTITY_EXTRACTION_TIMEOUT_SECONDS` | `60` | Per-batch LLM call timeout (5–300 s). |
| `ENTITY_EXTRACTION_MAX_RETRIES` | `2` | Retry count on LLM timeout or error (0–5). |
| `ENTITY_EXTRACTION_STRICT_MODE` | `false` | When `true`, extraction failure aborts the document pipeline. Default: count errors and continue. |

### 2.3 Entity resolution

| Variable | Default | Description |
|----------|---------|-------------|
| `FEATURE_ENABLE_ENTITY_RESOLUTION` | `false` | Enable cross-document deduplication of canonical entities. |
| `ENTITY_RESOLUTION_AUTO_MERGE_THRESHOLD` | `0.88` | Score ≥ this → auto-merge into existing canonical record. |
| `ENTITY_RESOLUTION_REVIEW_THRESHOLD` | `0.65` | Score in [review_threshold, auto_merge_threshold) → flag for manual review. |

### 2.4 Relation extraction

| Variable | Default | Description |
|----------|---------|-------------|
| `FEATURE_ENABLE_RELATION_EXTRACTION` | `false` | Enable LLM-based relationship extraction. Runs after entity extraction. |
| `RELATION_EXTRACTION_BATCH_SIZE` | `10` | Chunks per LLM batch (1–50). |
| `RELATION_EXTRACTION_TIMEOUT_SECONDS` | `60` | Per-batch LLM call timeout (5–300 s). |
| `RELATION_EXTRACTION_MAX_RETRIES` | `2` | Retry count on LLM error (0–5). |
| `RELATION_CONFIDENCE_THRESHOLD` | `0.5` | Relations below this score receive status `low_confidence`. |
| `RELATION_EXTRACTION_REVIEW_MODE` | `false` | When `true`, all relations start as `unverified` regardless of confidence. |
| `RELATION_EXTRACTION_STRICT_MODE` | `false` | When `true`, pipeline fails on extraction error. |

### 2.5 GraphRAG retrieval

| Variable | Default | Description |
|----------|---------|-------------|
| `GRAPH_RAG_MAX_HOPS` | `2` | Maximum traversal depth from seed entities (1–5). |
| `GRAPH_RAG_MAX_RELATED_ENTITIES` | `8` | Entity expansion limit per query (1–50). |
| `GRAPH_RAG_MAX_CHUNKS` | `5` | Graph-sourced chunks merged into retrieval context (1–50). |
| `GRAPH_RAG_CONFIDENCE_THRESHOLD` | `0.6` | Minimum evidence confidence for GraphRAG inclusion. |
| `GRAPH_RAG_RELATION_TYPE_ALLOWLIST` | All types | Comma-separated list of relation types to follow during traversal. |

The admin feature-flag surface also includes per-organization rollout controls
for `graph_rag`, `graph_extraction`, and `graph_explorer`. The graph
observability dashboard combines extraction health, entity/relation quality,
GraphRAG latency, fallback usage, and daily trend snapshots so admins can
roll out safely and spot regressions early.

### 2.6 Docker Compose image

| Variable | Default | Description |
|----------|---------|-------------|
| `NEO4J_IMAGE` | `neo4j:5-community` | Neo4j image. Use `neo4j:5-enterprise` for `NODE KEY` constraint support. |
| `NEO4J_HEAP_INITIAL` | `256m` | JVM initial heap. |
| `NEO4J_HEAP_MAX` | `1G` | JVM max heap. |
| `NEO4J_PAGECACHE` | `256m` | Page cache size. |
| `NEO4J_MEMORY_LIMIT` | `2g` | Container memory limit. |

---

## 3. Extraction pipeline

Graph extraction runs as a stage inside the Celery document processing task, after chunking and embedding are complete. The full sequence for a single document is:

```
1. mark  graph_extraction_status = pending
2. clear prior graph facts for this document (re-index only)
3. mark  graph_extraction_status = extracting
4. create ExtractionRun node (status = running)

── Entity extraction ────────────────────────────────────────────
5. batch chunks → LLM (JSON mode, temperature 0)
   Response: { "entities": [ { type, name, original_name, aliases,
                                language, confidence, evidence_span,
                                source_chunk_index } ] }
6. validate response against ExtractionBatchSchema (Pydantic)
   → invalid batches are counted; they never reach the graph
7. for each valid entity:
   a. derive deterministic entity_id = UUID5(org + type + name)
   b. if FEATURE_ENABLE_ENTITY_RESOLUTION: resolve against existing records
   c. MERGE Entity node in Neo4j
   d. MERGE EntityAlias node (source mention)
   e. create Evidence link (Chunk → Entity) with provenance fields

── Relation extraction (if FEATURE_ENABLE_RELATION_EXTRACTION) ──
8. batch chunks again with entity context → LLM
   Response: { "relations": [ { from_entity_name, to_entity_name,
                                 rel_type, confidence, evidence_span,
                                 source_chunk_index } ] }
9. validate against RelationExtractionBatchSchema
10. resolve entity names to UUIDs from the name→id lookup built in step 7
    → relations referencing unknown entities are counted and skipped
11. derive deterministic relation_id = UUID5(org + from_id + rel_type + to_id)
12. MERGE typed relationship edge in Neo4j with evidence

── Finalise ─────────────────────────────────────────────────────
13. update ExtractionRun (status = completed, entity_count)
14. mark  graph_extraction_status = completed
```

### Deterministic IDs

Both entity and relation IDs are UUID5 (namespace + content key), so the same logical entity or relationship extracted from different documents always maps to the same Neo4j node/edge. This makes MERGE idempotent and enables cross-document deduplication without a separate reconciliation step.

- **Entity ID**: `UUID5(namespace, "{org_id}:{entity_type}:{name.lower().strip()}")`
- **Relation ID**: `UUID5(namespace, "{org_id}:{from_entity_id}:{rel_type}:{to_entity_id}")`

---

## 4. Entity types

The LLM is constrained to these 14 types. Extractions that reference any other type are rejected by schema validation.

| Type | Description |
|------|-------------|
| `vendor` | Third-party supplier or service provider |
| `customer` | Organisation or person receiving goods/services |
| `policy` | Internal or external policy document |
| `control` | Security, compliance, or operational control |
| `contract` | Agreement between parties |
| `risk` | Identified risk item |
| `product` | Software, hardware, or service product |
| `project` | Named initiative or project |
| `person` | Individual human |
| `system` | IT system or platform |
| `process` | Business or operational process |
| `ticket` | Issue tracker or work-management ticket |
| `date` | Specific date or time period |
| `obligation` | Regulatory or contractual obligation |

---

## 5. Relationship types

| Type | Meaning |
|------|---------|
| `MENTIONS` | Document mentions an entity (generic, used when no stronger type applies) |
| `OWNS` | Owner → owned entity |
| `RELATES_TO` | General association (directional) |
| `COVERS_CONTROL` | Policy or contract covers a control |
| `CONTAINS_OBLIGATION` | Contract or policy contains an obligation |
| `PROVIDES_SERVICE_TO` | Vendor provides service to customer |
| `SUPERSEDES` | Newer version replaces older |
| `AFFECTS` | Risk or change affects entity |
| `DEPENDS_ON` | System or process depends on another |

Relations below `RELATION_CONFIDENCE_THRESHOLD` receive `status = low_confidence` and are excluded from GraphRAG traversal by default. Admins can review and promote them via `PATCH /admin/graph/relations/{id}/status`.

---

## 6. Entity resolution

Entity resolution deduplicates entities across documents by scoring incoming extractions against existing canonical records in Neo4j.

### Scoring signals

| Signal | Max score | Notes |
|--------|-----------|-------|
| Exact source external ID | 1.00 | Connector-assigned stable ID matches |
| Exact normalised name | 0.98 | After diacritic removal, lowercasing, punctuation strip |
| Similar name | 0.90 × similarity | SequenceMatcher ratio ≥ 0.9 |
| Alias match (canonical name) | 0.96 | Input name matches an existing alias |
| Alias match (alias set) | 0.95 | Input alias matches any existing alias |
| Embedding similarity | blended 35 % | Optional, when embedding is provided |

### Decision thresholds

```
score ≥ ENTITY_RESOLUTION_AUTO_MERGE_THRESHOLD (0.88)
  → status = auto_merged  → reuse existing entity_id

score ∈ [ENTITY_RESOLUTION_REVIEW_THRESHOLD (0.65), 0.88)
  → status = review  → new entity_id, flagged for admin review

score < 0.65  (or no candidates)
  → status = new  → new entity_id
```

Manual overrides are recorded as `EntityResolutionDecision` nodes (`merge` or `split` kind) and respected on subsequent extractions. A `split` decision blocks auto-merge for the affected entity pair.

---

## 7. Graph extraction lifecycle

Each document carries `graph_extraction_status` and `graph_extraction_run_id` columns in PostgreSQL.

```
┌─────────────────────────────────────────────────────────────────┐
│                    graph_extraction_status                       │
├──────────────┬──────────────────────────────────────────────────┤
│ pending      │ Queued — graph work is next                       │
│ extracting   │ LLM calls in progress                            │
│ completed    │ Entities and relations written to Neo4j           │
│ failed       │ Extraction error (see logs for run_id)           │
│ skipped      │ Feature flags disabled; no graph work performed   │
└──────────────┴──────────────────────────────────────────────────┘
```

**Re-extraction** — `POST /documents/{document_id}/graph/reindex` clears the previous graph facts for the document (evidence links, aliases, relations derived from it) and queues a fresh extraction. Orphaned entity nodes (no remaining evidence) are pruned automatically.

**Delete** — document deletion removes all evidence links and relation edges for that document, then prunes orphaned entity nodes.

**Connector re-sync** — when a connector updates or creates a document, `graph_extraction_status` resets to `pending` so the graph is kept in sync with the source.

---

## 8. Neo4j schema

### Node labels

| Label | Key constraint |
|-------|---------------|
| `Entity` | `(organization_id, entity_id)` |
| `EntityAlias` | `(organization_id, alias_id)` |
| `Document` | `(organization_id, document_id)` |
| `Chunk` | `(organization_id, chunk_id)` |
| `EntityResolutionDecision` | `(organization_id, decision_id)` |
| `ExtractionRun` | `run_id` |

Additional semantic labels (`Person`, `Vendor`, `Customer`, `Product`, `Project`, `Policy`, `Contract`, `Control`, `Risk`, `Ticket`, `System`, `Process`, `Obligation`) co-exist on entity nodes but are not used for key constraints.

### Schema migration

Migrations are stored in `app/domains/graph/schema.py` as `GraphMigration` objects and run automatically at API startup via `lifespan.py`. They are idempotent — every DDL statement uses `IF NOT EXISTS`.

Applied migrations are recorded as `__GraphMigration` nodes in Neo4j. Check migration status with:

```
GET /admin/graph/migrate
```

To re-run migrations manually:

```
POST /admin/graph/migrate
```

> **Community Edition note**: `NODE KEY` constraints (migration 0001) require Neo4j Enterprise Edition. On Community Edition the migration will fail and constraints won't be applied. Graph writes continue to work — entities are still created via MERGE — but uniqueness is not enforced at the DB level. Use `neo4j:5-enterprise` for production.

---

## 9. GraphRAG retrieval

When the graph layer is available, the chat retrieval path augments the standard Qdrant semantic search with graph-sourced context:

```
User question
    │
    ├── Qdrant vector search  →  top-k chunks (standard)
    │
    └── GraphRAG expansion
            │
            ├── Extract entity names from question (name match + alias lookup)
            ├── Traverse Neo4j up to GRAPH_RAG_MAX_HOPS hops via
            │   allowed relation types
            ├── Filter by GRAPH_RAG_CONFIDENCE_THRESHOLD
            ├── Collect up to GRAPH_RAG_MAX_CHUNKS evidence-backed chunks
            └── Merge with Qdrant results (deduplication by chunk_id)
```

If Neo4j is unavailable, the GraphRAG stage is skipped and the answer is generated from Qdrant results alone — no error is returned to the user.

Debug metadata in the chat response includes `graph_context_enabled`, `graph_entity_count`, and `graph_chunk_count` when graph expansion ran.

---

## 10. API reference

### Member endpoints (authenticated, org-scoped)

All endpoints return `503 enterprise_graph_unavailable` when the graph layer is disabled or unreachable.

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/graph/entities` | Search entities. Filters: `query`, `entity_type`, `min_confidence`, `source_document_id`, `source_connector`, `rel_type`, `relationship_direction`. Pagination: `skip`, `limit` (max 200). |
| `GET` | `/graph/entities/{entity_id}` | Entity detail: aliases, evidence, relationships, connected documents and entities. |

### Document lifecycle endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/documents/{document_id}` | Includes `graph_extraction_status` and `graph_extraction_run_id`. |
| `POST` | `/documents/{document_id}/graph/reindex` | Queue a graph-only re-extraction. Clears prior facts for the document first. |

### Admin endpoints (owner / admin role)

#### Health and migration

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/admin/graph/health` | Neo4j connection status and version. |
| `GET` | `/admin/graph/migrate` | List applied schema migrations. |
| `POST` | `/admin/graph/migrate` | Apply pending migrations. |

#### Entity management

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/admin/graph/entities` | List entities with optional `entity_type`, `workspace_id` filters. |
| `GET` | `/admin/graph/entities/{entity_id}` | Fetch single entity. |
| `DELETE` | `/admin/graph/entities/{entity_id}` | Delete entity and its aliases. |
| `GET` | `/admin/graph/entities/{entity_id}/aliases` | List source mentions for an entity. |
| `GET` | `/admin/graph/entities/{entity_id}/citations` | Citation-ready provenance for the entity. |
| `GET` | `/admin/graph/observability` | Graph extraction health, quality metrics, latency, and alert thresholds. |

#### Provenance and evidence

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/admin/graph/evidence` | Manually create an evidence link (Entity ← Chunk). |
| `GET` | `/admin/graph/documents/{document_id}/provenance` | All evidence derived from a document. |

#### Relationships

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/admin/graph/relations` | List relations. Filters: `status`, `rel_type`, `min_confidence`. |
| `POST` | `/admin/graph/relations` | Create an evidence-backed relation. |
| `GET` | `/admin/graph/relations/{relation_id}` | Fetch single relation. |
| `PATCH` | `/admin/graph/relations/{relation_id}/status` | Transition to `verified`, `rejected`, or `low_confidence`. |
| `DELETE` | `/admin/graph/relations/{relation_id}` | Delete by stable relation ID. |

#### Entity resolution

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/admin/graph/entity-resolution/candidates` | List resolution candidates for a normalised name. |
| `POST` | `/admin/graph/entity-resolution/merge` | Record a manual merge decision. |
| `POST` | `/admin/graph/entity-resolution/split` | Record a manual split decision. |

---

## 11. Deployment

### Quick start

```bash
# 1. Start Neo4j
make up-graph          # starts the enterprise-graph Docker Compose profile

# 2. Enable in .env
ENTERPRISE_GRAPH_ENABLED=true
FEATURE_ENABLE_ENTITY_EXTRACTION=true
NEO4J_URI=bolt://localhost:7687
NEO4J_PASSWORD=<your-password>

# 3. Restart API and workers
make restart-api
make restart-worker
```

Migrations run automatically at API startup. Re-index a document to populate the graph:

```bash
curl -X POST http://localhost:8000/api/v1/documents/<doc-id>/graph/reindex \
  -H "Authorization: Bearer <token>"
```

### Neo4j Edition

The default image (`neo4j:5-community`) works for development but does not support `NODE KEY` constraints. Use `neo4j:5-enterprise` for production to get full constraint enforcement and clustering support. Set `NEO4J_ACCEPT_LICENSE_AGREEMENT=yes` and uncomment the relevant line in `docker-compose.yml`.

### Worker initialisation

The Neo4j driver is initialised in each Celery worker process via the `worker_process_init` signal in `app/workers/celery_app.py`. This is required because workers are separate OS processes and do not inherit the driver instance created by the FastAPI lifespan.

If you observe `graph_extraction_status = completed` but 0 nodes/relationships in Neo4j, verify that workers were started after the `init_neo4j()` call was added to `_initialize_worker`.

### Memory sizing

Recommended minimums for production with a medium corpus:

| Resource | Minimum | Notes |
|----------|---------|-------|
| Heap | 2 G | `NEO4J_HEAP_MAX=2G` |
| Page cache | 2 G | `NEO4J_PAGECACHE=2G` |
| Container | 6 G | `NEO4J_MEMORY_LIMIT=6g` |

Use the [Neo4j memory calculator](https://neo4j.com/developer/guide-performance-tuning/) to tune for your dataset size.

---

## 12. Troubleshooting

### Graph shows 0 nodes after indexing

**Symptom**: Document shows `graph_extraction_status = completed` but `MATCH (n) RETURN count(n)` in Neo4j Browser returns 0.

**Cause**: The Celery worker never initialised the Neo4j driver. `get_driver()` returned `None` and all writes silently no-oped.

**Fix**: Ensure `app/workers/celery_app.py` calls `run_async(init_neo4j())` inside `_initialize_worker`. Restart workers, then re-index the document (`POST /documents/{id}/graph/reindex`).

---

### `graph_extraction_status = skipped`

Both `ENTERPRISE_GRAPH_ENABLED=true` and `FEATURE_ENABLE_ENTITY_EXTRACTION=true` must be set. If either is `false`, graph extraction is skipped silently.

---

### `graph_extraction_status = failed`

Look up the `graph_extraction_run_id` from the document and search worker logs:

```
log.event = "graph.entity.upsert_error"   → Neo4j write failed
log.event = "entity_extraction.llm_error" → LLM call failed
log.event = "entity_extraction.timeout"   → LLM call timed out
```

Common causes:

| Error | Likely cause |
|-------|-------------|
| `ServiceUnavailable` | Neo4j is down or the bolt URI is wrong |
| `AuthError` | Wrong `NEO4J_USERNAME` / `NEO4J_PASSWORD` |
| `TimeoutError` on LLM call | Increase `ENTITY_EXTRACTION_TIMEOUT_SECONDS` |
| `schema_validation_error` | LLM returned malformed JSON; increase `ENTITY_EXTRACTION_MAX_RETRIES` |

---

### Migration fails on Community Edition

```
Neo4j.ClientError.Schema.EquivalentSchemaRuleAlreadyExists  — or —
Neo4j.ClientError.Statement.NotImplemented: NODE KEY is an enterprise feature
```

Switch to `NEO4J_IMAGE=neo4j:5-enterprise` or accept that uniqueness constraints won't be enforced (the graph still works).

---

### Entity resolution merging too aggressively / not enough

Tune the thresholds:

```
# Raise auto-merge threshold (be more conservative):
ENTITY_RESOLUTION_AUTO_MERGE_THRESHOLD=0.95

# Lower review threshold (catch more potential duplicates):
ENTITY_RESOLUTION_REVIEW_THRESHOLD=0.55
```

Use `GET /admin/graph/entity-resolution/candidates?normalized_name=<name>` to inspect scored candidates before changing thresholds.

---

### Relations show `status = low_confidence`

Relations below `RELATION_CONFIDENCE_THRESHOLD` (default 0.5) are stored but excluded from GraphRAG by default. To include them, lower the threshold:

```
RELATION_CONFIDENCE_THRESHOLD=0.3
```

Or promote individual relations via `PATCH /admin/graph/relations/{id}/status` with `{"status": "verified"}`.
