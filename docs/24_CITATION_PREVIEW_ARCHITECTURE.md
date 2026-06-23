# Citation Preview Architecture

This document describes the citation preview drawer used in chat, shared-answer, document-detail, and knowledge-card surfaces.

## Purpose

The preview drawer helps users inspect evidence without leaving the current workflow. It is designed to be:

- Accessible by keyboard and screen readers.
- Fast enough to open without blocking chat interaction.
- Safe to observe through telemetry without leaking document text.
- Extensible for future connector-backed sources and additional file types.

## End-to-End Flow

1. A user clicks a citation chip or citation card.
2. The frontend opens the shared `CitationPreviewDrawer`.
3. The drawer shows the citation metadata immediately from the chat payload.
4. The drawer fetches permission-filtered document detail from `GET /documents/{document_id}`.
5. The response is used to resolve source links, ownership metadata, freshness state, and document-level warnings.
6. The drawer renders a truncated snippet and, when present, a highlighted excerpt.
7. The drawer emits safe observability events for open, load failure, permission denial, source missing, and external-link clicks.

## Frontend Components

- `frontend/src/components/chat/DocumentPreviewModal.tsx`
  - Shared drawer implementation.
  - Handles focus management, arrow-key navigation, Escape-to-close, truncation, and error states.
  - Limits rendered citations to a small bounded window to keep the drawer responsive.
- `frontend/src/components/chat/SharedAnswerPage.tsx`
  - Opens the drawer from shared answers.
- `frontend/src/components/chat/AnswerTrustPanel.tsx`
  - Opens the drawer from trust-panel citations.
- `frontend/src/components/documents/DocumentDetailPage.tsx`
  - Reuses the same drawer for document detail evidence inspection.

## API Contract

The preview drawer depends on the document detail API contract documented in [docs/07_API_DESIGN.md](./07_API_DESIGN.md) and the document detail endpoint used for citation enrichment.

Key response fields consumed by the drawer:

- `document_title` / `filename`
- `document_type` / `file_type`
- `document_owner_email` / `document_owner_display_name`
- `document_version_label`
- `document_last_updated_at`
- `document_last_indexed_at`
- `source_provider_label`
- `source_url`
- `source_link_allowed`
- `source_last_synced_at`
- `source_trust_status`
- `doc_review_status`
- `doc_last_updated_at`
- `doc_ocr_quality_status`

The drawer must treat the response as permission-filtered. If the API returns `403`, `404`, `409`, or `410`, the drawer shows a safe fallback state rather than attempting to infer hidden source content.

## Permission Behavior

Permission enforcement remains backend-owned.

- Document access is resolved before preview data is returned.
- Connector ACLs determine whether external source links are shown.
- Uploaded documents fall back to the internal Rudix document route when no external source link is available.
- When the source is unavailable, the UI must not leak source text, hidden URLs, or document content beyond the safe snippet already present in the citation payload.

The drawer distinguishes:

- `403` permission denied
- `404` source missing or inaccessible
- `409` citation not indexed or stale
- `410` deleted or retained under policy

## Observability

The drawer emits safe client-side events through the standard analytics layer and frontend breadcrumbs.

Tracked events:

- `feature.chat.citation_preview_opened`
- `feature.chat.citation_preview_load_failed`
- `feature.chat.citation_preview_permission_denied`
- `feature.chat.citation_preview_source_missing`
- `feature.chat.citation_preview_external_link_clicked`

These events intentionally carry only identifiers and state flags. They do not include raw document snippets, full document text, or source URLs.

## Performance Safeguards

- The drawer fetches document detail only when opened.
- The fetch is abortable so closing the drawer cancels in-flight work.
- The rendered citations are capped to a small, bounded set.
- Snippets are truncated before rendering.
- Loading indicators respect reduced-motion preferences.

## Test Fixtures

The regression suite uses the following fixtures and patterns:

- `frontend/src/components/chat/tests/DocumentPreviewModal.test.tsx`
  - accessibility smoke checks
  - arrow-key navigation
  - external-link telemetry
  - request cancellation
  - fallback states for permission denied, source missing, and server errors
- `backend/tests/test_citation_preview_api_f319.py`
  - API contract and permission behavior
- `backend/tests/test_analytics_api.py`
  - safe analytics event acceptance for citation preview events

When adding a new connector or file type:

1. Extend the backend preview contract first.
2. Add a safe test fixture with the new source metadata.
3. Update the frontend drawer to label the source clearly and keep the same fallback semantics.
4. Add a regression test for the new permission or source-state path.
