# Changelog

All notable changes to this documentation set are recorded here.

## [Unreleased]

### Added

- `docs/DOCUMENT_TEMPLATE.md` for standardized technical documents.
- `docs/DOCUMENT_REVIEW_CHECKLIST.md` for document quality gating.

## [2026-06-02] — F210 Adaptive hybrid chunking

### Added

- `docs/03_RAG_WORKFLOW.md`: replaced stale "Start with recursive chunking" section with a full strategy reference table, adaptive hybrid selection priority table, reason code description, and updated chunk metadata schema.
- `docs/08_SERVICE_IMPLEMENTATION_GUIDE.md`: replaced single-function chunking snippet with strategy registry reference, adaptive hybrid description, `CHUNKING_STRATEGY` env var, and updated production requirements.
- `backend/README.md`: documented `CHUNKING_STRATEGY` env var and adaptive selection behaviour in configuration notes and document processing notes.

### Changed

- Expanded `docs/DOCUMENTATION_STANDARDS.md` into a formal standard.
- Updated `docs/README.md` with standards and templates links.
- Updated `docs/CONTRIBUTING.md` to require template and checklist usage.
- Removed platform-specific frontend deployment guidance across architecture and deployment docs.
- Standardized deployment guidance to containerized/self-hosted frontend and backend infrastructure.

## [2026-05-07]

### Added

- `docs/README.md` documentation index.
- `docs/CONTRIBUTING.md` contribution workflow and checklist.
- `docs/CODE_OF_CONDUCT.md` collaboration behavior policy.
- `docs/SECURITY.md` security reporting and response process.
- `docs/DOCUMENTATION_STANDARDS.md` writing and structure standards.

### Changed

- Moved architecture docs from repository root to `docs/`.
- Updated root `README.md` document paths to `docs/...`.
