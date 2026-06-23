# Trust Panel Observability and Analytics (F317)

This document explains how to use the trust panel observability system to measure answer quality, monitor trust score trends, and improve RAG accuracy over time.

## Overview

F317 adds three layers of observability to the trust panel:

1. **Server-side metrics** — emitted after every answered chat turn into the `usage_events` table.
2. **Admin analytics API** — `GET /admin/trust-analytics` aggregates those metrics into a dashboard.
3. **Client-side interaction tracking** — trust panel opens, citation clicks, warning interactions, and feedback submissions are tracked via the product analytics system.

Additionally, when [Langfuse](https://langfuse.com/) is configured, trust metadata is included in every chat trace.

---

## Server-Side Metrics

### How metrics are emitted

`TrustMetricsService.record()` is called after every chat answer. It stores a `UsageEvent` row with `event_type = "trust.answer_metrics"` containing:

| Field | Description |
|---|---|
| `trust_level` | `high / medium / low / warning / not_found` |
| `confidence_score` | Raw confidence float (0–1) |
| `confidence_category` | `high / medium / low` |
| `citation_support_score` | Citation-backed support score (0–1) |
| `verification_support_score` | Grounded verifier aggregate score |
| `not_found` | Whether the answer was a refusal |
| `conflict_detected` | Whether source conflict was detected |
| `conflict_agreement_level` | `full / partial / conflicting` |
| `unsupported_claims_removed` | Count of claims removed by the grounded verifier |
| `stale_source_warning` | At least one stale/expired source was cited |
| `stale_count` | Number of stale sources |
| `ocr_warning` | OCR quality issue on a cited source |
| `extraction_warning` | Document extraction issue on a cited source |
| `processing_warning` | Processing incomplete on a cited source |
| `evidence_quality_warning` | Any aggregated evidence quality issue |
| `citation_count` | Number of citations in the answer |
| `retrieved_count` | Total chunks retrieved |
| `langfuse_trace_id` | Langfuse trace ID (when Langfuse is enabled) |

**Privacy**: no raw question/answer text, document IDs, or chunk IDs are stored. Only safe aggregates.

### Integrating with the chat pipeline

Call `TrustMetricsService` in your pipeline after trust metadata is computed:

```python
from app.domains.chat.services.trust_metrics_service import (
    TrustMetricsService,
    TrustMetricsSnapshot,
)

snapshot = TrustMetricsSnapshot(
    organization_id=org_id,
    user_id=user_id,
    message_id=message_id,
    session_id=session_id,
    trust_level=trust_metadata.confidence.trust_level,
    confidence_score=trust_metadata.confidence.score,
    confidence_category=trust_metadata.confidence.category,
    citation_support_score=trust_metadata.confidence.citation_support_score,
    verification_support_score=trust_metadata.confidence.verification_support_score,
    not_found=trust_metadata.not_found,
    citation_validation_failed=trust_metadata.citation_validation_failed,
    conflict_detected=trust_metadata.conflict.detected,
    conflict_agreement_level=trust_metadata.conflict.agreement_level,
    unsupported_claims_removed=trust_metadata.grounded_verification.removed_count,
    stale_source_warning=trust_metadata.freshness.warning,
    stale_count=trust_metadata.freshness.stale_count,
    ocr_warning=any(c.doc_ocr_low_confidence_warning for c in trust_metadata.citations),
    extraction_warning=trust_metadata.evidence_quality.extraction_warning_count > 0,
    processing_warning=trust_metadata.evidence_quality.processing_warning_count > 0,
    evidence_quality_warning=bool(trust_metadata.evidence_quality.warning_reasons),
    citation_count=len(trust_metadata.citations),
    retrieved_count=trust_metadata.retrieval.retrieval_count,
    langfuse_trace_id=langfuse_trace_id,
)
await trust_metrics_service.record(db_session, snapshot)
```

`record()` never raises — failures are logged at DEBUG level.

---

## Admin Analytics API

### Endpoint

```
GET /admin/trust-analytics?from=YYYY-MM-DD&to=YYYY-MM-DD
```

Requires `owner` or `admin` role. Default range is 30 days. Maximum is 90 days.

### Response shape

```json
{
  "organization_id": "...",
  "range": { "from": "2026-05-24", "to": "2026-06-22" },
  "generated_at": "2026-06-23T00:00:00Z",
  "total_answers": 450,
  "not_found_rate": 0.04,
  "avg_confidence_score": 0.79,
  "avg_citation_support_score": 0.83,
  "avg_verification_support_score": 0.71,
  "unsupported_claims_removed_total": 38,
  "conflict_detection_rate": 0.06,
  "trust_distribution": {
    "high_count": 320,
    "medium_count": 100,
    "low_count": 20,
    "warning_count": 5,
    "not_found_count": 5,
    "high_pct": 0.711,
    ...
  },
  "warnings": {
    "stale_source_count": 22,
    "conflict_count": 27,
    "ocr_count": 8,
    "extraction_count": 3,
    "processing_count": 1,
    "evidence_quality_count": 11,
    "citation_validation_failed_count": 15
  },
  "daily_trends": [...],
  "langfuse": {
    "enabled": true,
    "traces_linked_count": 420
  },
  "telemetry_missing": false
}
```

`telemetry_missing: true` is returned when no trust metric events exist for the requested period.

### Admin UI

Navigate to `/admin/trust-analytics` to view the dashboard. It shows:
- Summary metric cards (total answers, not-found rate, avg confidence, avg citation support)
- Trust score distribution bar chart
- Warning type breakdown table
- Daily trends table with per-day not-found rate and confidence averages
- Langfuse integration status badge

---

## Langfuse Trace Integration

When Langfuse is configured (`LANGFUSE_ENABLED=true`), trust metadata is added to every chat trace as metadata fields on the root span:

| Trace field | Source |
|---|---|
| `trust_level` | `AnswerTrustMetadataResponse.confidence.trust_level` |
| `trust_citation_support_score` | `confidence.citation_support_score` |
| `trust_unsupported_claims_removed` | `grounded_verification.removed_count` |
| `trust_stale_source_warning` | `freshness.warning` |
| `trust_conflict_detected` | `conflict.detected` |
| `trust_ocr_warning` | any citation OCR warning |
| `trust_extraction_warning` | any citation extraction warning |
| `trust_evidence_quality_warning` | any evidence quality warning |

Trace tags include `trust:<level>` (e.g., `trust:high`, `trust:not_found`) for easy filtering in the Langfuse UI.

The `langfuse_trace_id` is stored in the `trust.answer_metrics` UsageEvent when a trace is emitted, enabling cross-referencing from the admin analytics API.

When Langfuse is disabled or unreachable, trust fields default to safe empty values and the pipeline continues normally.

---

## Evaluation Fixtures

Use `TrustMetadataEvalCase` and `score_trust_metadata_case` to assert trust metadata correctness in evaluation runs:

```python
from app.domains.evaluations.services.evaluation_metrics_service import (
    TrustMetadataEvalCase,
    score_trust_metadata_case,
)

# Assert that an in-scope question gets high trust level with strong citation support.
case = TrustMetadataEvalCase(
    expected_trust_level="high",
    min_citation_support_score=0.6,
    expected_not_found=False,
)

result = score_trust_metadata_case(
    case,
    actual_trust_level=trust_metadata.confidence.trust_level,
    actual_not_found=trust_metadata.not_found,
    actual_citation_support_score=trust_metadata.confidence.citation_support_score,
    actual_confidence_score=trust_metadata.confidence.score,
    actual_conflict_detected=trust_metadata.conflict.detected,
    actual_stale_warning=trust_metadata.freshness.warning,
)
assert result.overall_pass, result.as_dict()
```

`overall_pass` is `True` only when every provided expectation is satisfied. Omitted expectations are ignored, so you can assert subsets of trust metadata correctness.

---

## Client-Side Interaction Tracking

The following analytics events are fired from the trust panel:

| Event | When |
|---|---|
| `feature.chat.trust_panel_opened` | When the trust panel mounts (deduplicated per message) |
| `feature.chat.trust_panel_citation_clicked` | When the citation preview button is clicked |
| `feature.chat.trust_panel_feedback_submitted` | When "Report issue" is clicked |
| `feature.chat.trust_panel_warning_clicked` | When the warning banner area is clicked |

All events use `surface: "app"`, `featureArea: "chat"`, and `entityId: <messageId>`.

These events flow through the standard product analytics system (backend `usage_events` table, optional Matomo). They respect the user's analytics consent and the organization's `analytics_enabled` flag.

---

## Using Trust Metrics to Improve Accuracy

### Not-found rate too high?

1. Check `GET /admin/query-analytics/summary` for unanswered queries — these may represent knowledge gaps.
2. Add missing content via the admin document upload or connector sync.
3. Review RAG profile `top_k` and score thresholds — too strict thresholds reject borderline but relevant chunks.

### Citation support score trending down?

1. Check `trust_distribution.low_count` and `trust_distribution.warning_count` trends.
2. Review `warnings.extraction_count` — poor extraction quality reduces citation accuracy.
3. Trigger a re-index or OCR retry for documents with low OCR confidence.
4. Enable the grounded answer verifier (`feature_enable_grounded_answer_verifier`) in strict mode.

### High conflict detection rate?

1. Review `GET /admin/query-analytics/summary` for conflict-flagged topics.
2. Use the Source Conflict section in the trust panel to identify the documents involved.
3. Mark authoritative documents as `trusted` via `PATCH /admin/documents/{id}/trust-status`.
4. Consider using document versioning to supersede outdated sources.

### Langfuse traces not appearing?

1. Check `GET /admin/langfuse/status` to confirm the client is initialized and reachable.
2. Verify `LANGFUSE_ENABLED=true`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, and `LANGFUSE_BASE_URL` are set.
3. Check `LANGFUSE_SAMPLE_RATE` — set to `1.0` for full capture during debugging.
4. Ensure the Langfuse service is reachable from the API container (`reachable: true` in the status response).
