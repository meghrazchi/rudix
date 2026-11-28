# DR: vector index loss

## Metadata

- `Owner`: Rudix maintainers
- `Status`: Active (0.8.0, R08-13); not yet exercised in a drill
- `Last Updated`: 2026-11-28
- `Related Docs`: [BACKUP_AND_RESTORE.md](./BACKUP_AND_RESTORE.md),
  [../27_INGESTION_AND_WORKERS_RUNBOOK.md](../27_INGESTION_AND_WORKERS_RUNBOOK.md)
  "Reindex and alias swap" and "Vector writes and memory",
  [../03_RAG_WORKFLOW.md](../03_RAG_WORKFLOW.md)

Scope: one or more Qdrant collections of the deployment are gone, empty, or return wrong
results (lost volume, a dropped collection, a corrupted segment, a failed cluster node with
replication factor 1). PostgreSQL is the source of truth: `document_chunks` holds every chunk's
text and metadata, so the index can always be rebuilt. The vector index is also the embedding
cache (docs/03): a rebuild after a full loss embeds every chunk again, which costs provider
tokens and is bound by provider rate limits.

## Detection

- `/api/v1/ready` reports `qdrant` down, or chat answers fall back to not-found for questions
  that used to have sources.
- Logs: `qdrant.collection.missing_on_write`, `Collection ... not found` (404) on search,
  `vector_index.query.dimension_fallback` in bulk, `QDRANT_POINT_COUNT_MISMATCH` on many
  documents.
- `python scripts/vector_index.py status` shows the alias pointing at a collection that
  `GET /collections` does not list, or a point count far below the indexed chunk count.
- Retrieval quality alerts (accuracy smoke, docs/12) drop sharply.

## Decision owner

- Incident commander: chooses snapshot restore, rebuild, or both, and accepts the
  embedding cost and the window of degraded answers.
- On-call engineer: runs the steps.
- Platform owner: Qdrant cluster capacity and the provider rate-limit and budget headroom
  for a full re-embedding.

## Steps

1. Contain: stop the beat entry that drops retired generations if it is on
   (`VECTOR_INDEX_AUTO_DROP_RETIRED=false`), and pause bulk reindex jobs. Leave ingestion on:
   new documents keep being written.
2. Assess from `backend/` with `DATABASE_MAINTENANCE_URL` set:
   `python scripts/vector_index.py status` (alias mode) and `GET /collections` on Qdrant.
   Note which collections exist and their point counts.
3. Decide the path:
   - **Snapshot restore** (fastest, when a recent `qdrant` backup exists): continue at step 4.
   - **Rebuild from PostgreSQL** (always possible; needed when no snapshot is usable or after a
     restore to catch up): continue at step 6.
4. Snapshot restore: `python scripts/backup_restore.py --kind qdrant --latest --out /restore/qdrant`,
   then upload each `<collection>.snapshot` with
   `POST /collections/<collection>/snapshots/upload?priority=snapshot` (header `api-key`) and
   recreate the aliases from `aliases.json` (`POST /collections/aliases`). The
   `deploy/scripts/restore_drill.sh` Qdrant step shows the exact calls; against production
   run them by hand after the incident commander approves.
5. Catch up after a snapshot restore: documents indexed or reindexed after the snapshot's
   `created_at` (in the manifest) are missing or stale. Reindex them: list them with
   `SELECT id FROM documents WHERE status = 'indexed' AND updated_at > '<created_at>'` and call
   `POST /api/v1/documents/{id}/reindex` for each (or rebuild, step 6). Deleted documents'
   points left in the snapshot are never served: retrieval filters by organisation and by
   existing document rows; reindex or delete them to clean up.
6. Rebuild from PostgreSQL with a new index generation (docs/27 "Reindex and alias swap"):
   - Legacy mode (`QDRANT_COLLECTION_ALIAS` unset): run `python -m app.clients.qdrant_bootstrap`
     to recreate an empty `QDRANT_COLLECTION` with its payload indexes, set
     `QDRANT_COLLECTION_ALIAS` on the API and workers, restart, and run
     `python scripts/vector_index.py adopt`. The empty collection becomes generation 1;
     answers stay not-found until the swap below.
   - Alias mode, alias target missing or broken: the next steps register a new generation;
     queries fail or come back empty until the swap.
   - Set `QDRANT_REPLICATION_FACTOR` (2 or more on a cluster) and the other tuning settings
     before this step: they apply only when a collection is created.
   - `python scripts/vector_index.py plan`, then `python scripts/vector_index.py build --enqueue`.
     It walks `document_chunks`, embeds, and writes the new generation; a killed build resumes
     from its cursor when the same command runs again. Follow `status` or
     `rudix_reindex_progress`.
   - When the build reports `verifying` (point count matches the chunk rows), run
     `python scripts/vector_index.py swap --yes`.
   - If the build ends `failed` with `point_count_mismatch` or `documents_missing`, run
     `build` again and check `vector_index.dual_write_failed` logs.
7. Keep the damaged collection (if any) until verification passes; `drop-retired --yes` it
   later. Re-enable `VECTOR_INDEX_AUTO_DROP_RETIRED` if it was on.
8. Run a `qdrant` backup once the index is healthy so the next restore starts from it.

## Verification

- `python scripts/vector_index.py status` shows the alias on an `active` generation whose
  collection exists; its point count matches the embeddable chunk rows.
- `/api/v1/ready` reports `qdrant` up; no `Collection ... not found` in logs for one hour.
- The accuracy smoke (`make eval-smoke`, docs/12) passes; a known question returns cited
  sources from more than one organisation's test data, each only to its own organisation.
- A new upload reaches `indexed` and is retrievable in chat.
- The next `qdrant` backup writes a fresh marker.
