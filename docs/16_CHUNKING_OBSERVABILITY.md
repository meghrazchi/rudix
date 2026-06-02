# 16 — Chunking Observability, Rollout Controls, and Runbook

This document covers how to monitor and debug the configurable chunking pipeline, how to safely roll out new strategies, and how to recover from chunking failures in production.

---

## Strategy catalog

| Strategy | Best for | Key behaviour |
|---|---|---|
| `token_recursive` | General text, unknown structure | Recursive split by paragraph → sentence → token. Safe conservative default. |
| `token_fixed` | Uniform token budgets, embedding benchmarks | Hard token boundary; no overlap by default. |
| `paragraph_recursive` | Short knowledge articles, FAQ, policy snippets | Keeps paragraph boundaries intact before falling back to token split. |
| `sentence_window` | Q&A, conversational retrieval | Embeds a tight sentence window; retrieves surrounding context at query time. |
| `page_aware` | OCR PDFs, evidence documents, contracts | One chunk per page; preserves citation provenance exactly. |
| `heading_aware` | DOCX, Markdown, well-structured PDFs | Splits on heading boundaries; section path stored for citation. |
| `hierarchical` | Long documents requiring both broad and precise retrieval | Parent chunks for context; child chunks for precision. Embeds children only. |
| `adaptive_hybrid` | Mixed document corpus with unknown structure | Analyses document signals and delegates to one of the above strategies automatically. |

### Recommended profiles by document type

| Document type | Recommended strategy | Notes |
|---|---|---|
| Scanned / OCR PDF | `page_aware` | Citation provenance requires page boundaries |
| Multi-page PDF | `page_aware` | Selected automatically by `adaptive_hybrid` |
| DOCX / Markdown | `heading_aware` | Section structure improves citation quality |
| Short knowledge article (< 500 tokens) | `paragraph_recursive` | Avoids over-splitting tiny documents |
| Long structured report | `hierarchical` | Enables coarse + fine retrieval |
| Unknown / mixed corpus | `token_recursive` (conservative default) | Switch to `adaptive_hybrid` after evaluation gates pass |

---

## Observability

### Structured log events

All chunking events are emitted to the `events.chunking` logger.  Fields never include raw document text.

#### `document.chunking.started`

| Field | Type | Description |
|---|---|---|
| `document_id` | string | Document UUID |
| `organization_id` | string | Organisation UUID |
| `strategy` | string | Configured strategy name |
| `profile_source` | string | `system_default` or `custom_profile` |
| `index_version` | string | Document index version |

#### `document.chunking.completed`

| Field | Type | Description |
|---|---|---|
| `strategy` | string | Final strategy applied (may differ from config when `adaptive_hybrid` delegates) |
| `chunk_count` | int | Total chunks produced |
| `avg_tokens` | float | Average tokens per chunk |
| `max_tokens` | int | Largest chunk in tokens |
| `min_tokens` | int | Smallest chunk in tokens |
| `duration_ms` | int | Time spent in `svc.chunk()` |
| `profile_source` | string | Profile origin |
| `reason_codes` | list[str] | Selector reason codes (only present for `adaptive_hybrid`) |
| `empty_pages` | int | Pages with no extractable text |
| `language` | string or null | ISO 639-1 code detected by adaptive selector |
| `index_version` | string | Document index version |

#### `document.chunking.failed`

| Field | Type | Description |
|---|---|---|
| `error_code` | string | Machine-readable error code (e.g. `EMPTY_CHUNK_SET`) |
| `error_message` | string | Human-readable message |

### Reason codes

`reason_codes` are short `snake_case` tokens emitted by the `adaptive_hybrid` selector.

| Code | Meaning |
|---|---|
| `pdf_ocr_applied` | PDF processed with OCR; page boundaries critical |
| `pdf_multi_page` | Multi-page PDF; page_aware preserves evidence boundaries |
| `pdf_structured` | Single-page PDF with high heading density |
| `docx_md_structured` | DOCX or Markdown with high heading density |
| `docx_md_file_type` | DOCX or Markdown without dense headings |
| `high_heading_density` | Any file type with dense headings |
| `short_document` | Total token count below short-document threshold |
| `fallback_low_confidence` | No signal matched; using safe default |
| `force_override` | Admin or experiment override via `force_strategy` |

### Pipeline explorer

Every document processing run records a `chunk` pipeline node.  The node detail panel shows:

- **Config**: `strategy`, `chunk_size_tokens`, `chunk_overlap_tokens`, `index_version`, `profile_source`
- **Outputs / metrics**: `chunk_count`, `avg_tokens`, `max_tokens`, `min_tokens`, `empty_pages`, `duration_ms`, `strategy`, `reason_codes`, `language`

---

## Feature flags

| Flag | Default | Purpose |
|---|---|---|
| `FEATURE_ENABLE_CHUNKING_PROFILES` | `false` | Enable the admin UI and API for org-scoped chunking profiles |
| `FEATURE_ENABLE_ADAPTIVE_CHUNKING` | `false` | Enable `adaptive_hybrid` as a selectable strategy in profiles and the system default |

Set in `.env` or environment variables.  Both flags are reflected in the `/configz` endpoint under `features`.

### Environment defaults

| Environment | `FEATURE_ENABLE_ADAPTIVE_CHUNKING` | `CHUNKING_STRATEGY` |
|---|---|---|
| development | `false` (override freely) | `token_recursive` |
| staging | `false` (enable manually for evaluation) | `token_recursive` |
| production | `false` (enable only after evaluation gate) | `token_recursive` |

The default remains `token_recursive` until the evaluation gate described below approves the rollout.

---

## Rollout plan: `token_recursive` → `adaptive_hybrid`

### Phase 1 — Evaluation baseline (staging)

1. Ensure all existing documents are indexed with `token_recursive`.
2. Run the evaluation pipeline on a representative question set; record `retrieval_precision`, `answer_faithfulness`, and `citation_accuracy` as baseline metrics.
3. Merge baseline scores into the evaluation dashboard.

### Phase 2 — Shadow indexing (staging)

1. Set `FEATURE_ENABLE_ADAPTIVE_CHUNKING=true` and `FEATURE_ENABLE_CHUNKING_PROFILES=true` in staging.
2. Create a test org chunking profile with `strategy=adaptive_hybrid`.
3. Re-index a representative document sample using the test profile.
4. Run the same evaluation question set against the `adaptive_hybrid`-indexed documents.
5. Compare metrics against the baseline. Required gates before proceeding:
   - `retrieval_precision` ≥ baseline − 2 pp
   - `answer_faithfulness` ≥ baseline − 2 pp
   - `citation_accuracy` ≥ baseline − 1 pp
   - No regression in existing upload, chat, or citation tests

### Phase 3 — Production rollout

1. After evaluation gates pass, set in production:
   - `FEATURE_ENABLE_ADAPTIVE_CHUNKING=true`
   - `CHUNKING_STRATEGY=adaptive_hybrid`
2. Monitor `events.chunking` logs for `reason_codes` distribution; confirm expected strategy distribution for the document corpus.
3. Monitor pipeline explorer for increased chunk stage `duration_ms` (adaptive adds a signal-computation pass; expect ~10–30 ms overhead per document).
4. After 48 hours with no quality regressions, the rollout is complete.

---

## Admin runbook

### Failed chunking — `document.chunking.failed`

1. Find the affected document in the pipeline explorer.  The `chunk` node will show `failed` status.
2. Check `error_code`:
   - `EMPTY_CHUNK_SET` — document extracted no chunks. Usually caused by an empty or non-parseable file. Ask the user to re-upload. No re-index needed.
   - `TEXT_EXTRACTION_FAILED` — extraction stage failed before chunking. Check the `extract` node logs.
3. If the document should be re-processed, trigger a re-index from the admin panel or via the API: `POST /api/v1/admin/documents/{id}/reindex`.

### Bad retrieval quality after profile change

1. Check `events.chunking` logs for the affected documents. Look at `strategy`, `reason_codes`, and `avg_tokens` to confirm the expected profile was applied.
2. If `adaptive_hybrid` selected an unexpected strategy, review the document signals in the pipeline explorer `chunk` node outputs (`adaptive_signals` in `chunking_config_snapshot`).
3. If the document type would be better served by a different strategy, create a custom org chunking profile with `force_strategy` set to the desired strategy, then re-index.
4. If the issue is corpus-wide, see "Re-index rollback" below.

### Re-index rollback

Trigger a backfill with the previous profile config:

```bash
# Replace <ORG_ID> with the affected organisation UUID
curl -X POST /api/v1/admin/documents/backfill \
  -H "Authorization: Bearer <admin-token>" \
  -d '{"organization_id": "<ORG_ID>", "chunking_profile_config": {"strategy": "token_recursive"}}'
```

The backfill task dispatches idempotent `documents.reindex` jobs for every indexed document in the org. Monitor progress in the pipeline explorer. Existing chat and citation functionality continues to work against the old chunks until each document is re-indexed.

### Emergency fallback — revert `adaptive_hybrid` to `token_recursive`

1. Set `FEATURE_ENABLE_ADAPTIVE_CHUNKING=false` and `CHUNKING_STRATEGY=token_recursive` in the environment.
2. Restart workers (Celery) to pick up the new default.
3. Trigger a backfill for affected orgs (see "Re-index rollback").

No migration is required. The `chunking_strategy` field on each document record tracks which strategy was applied; old documents remain accessible until the rollback re-index completes.

---

## Configuration precedence

When determining the chunking strategy for a document:

1. **Inline profile config** passed directly to the task (`chunking_profile_config` kwarg) — highest priority.
2. **Organisation default profile** (from `organization_chunking_profiles` table with `is_default=true`).
3. **System default** from `CHUNKING_STRATEGY` environment variable (defaults to `token_recursive`).

When `adaptive_hybrid` is the resolved strategy, it further selects among the other strategies at runtime based on document signals, respecting the `force_strategy` option in the profile config.

---

## Re-index workflow

Re-indexing is safe to run at any time. Each `documents.reindex` task:

1. Reads the current document bytes from object storage.
2. Re-extracts, re-cleans, re-chunks, and re-embeds using the supplied or system-default profile.
3. Replaces old vectors in Qdrant atomically (delete then upsert).
4. Updates `chunking_strategy`, `chunking_profile_version`, and `chunking_config_snapshot` on the document record.

Documents remain searchable (with the old index) until step 3 completes, then switch atomically to the new index.

Idempotency: re-running the same re-index task on an already-indexed document with the same profile produces the same chunk set (deterministic strategies guarantee this). Running it again is always safe.
