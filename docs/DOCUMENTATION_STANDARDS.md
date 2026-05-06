# Documentation Standards

## Purpose

This standard defines how documentation is written, reviewed, and maintained in this repository.

## Repository Rules

- Keep only `README.md` at repository root.
- Keep all other documentation in `docs/`.
- Keep links relative within `docs/`.

## Standard Document Set

The repository SHOULD include these baseline documents:

- `docs/README.md` for documentation index and navigation.
- `docs/CONTRIBUTING.md` for contribution workflow.
- `docs/CODE_OF_CONDUCT.md` for collaboration behavior.
- `docs/SECURITY.md` for vulnerability reporting.
- `docs/CHANGELOG.md` for notable changes.
- `docs/DOCUMENTATION_STANDARDS.md` for writing standards.
- `docs/DOCUMENT_TEMPLATE.md` for new technical docs.
- `docs/DOCUMENT_REVIEW_CHECKLIST.md` for quality review.

## Naming Convention

- Use numbered files (`01_...`, `02_...`) for ordered architecture or implementation tracks.
- Use descriptive uppercase snake case for core technical docs.
- Use conventional names for governance docs (`CONTRIBUTING.md`, `SECURITY.md`, and similar).

## Required Metadata

Every new technical document SHOULD start with:

- `Owner`
- `Status` (`Draft`, `Review`, `Approved`, or `Deprecated`)
- `Last Updated` (`YYYY-MM-DD`)
- `Related Docs`

Use `docs/DOCUMENT_TEMPLATE.md` as the default structure.

## Required Technical Sections

For architecture, API, data, or deployment docs, include:

1. Purpose
2. Scope
3. Assumptions and Constraints
4. Design or Procedure
5. Failure Modes and Recovery
6. Security Considerations
7. Observability and Operations
8. Open Questions

If a section is not applicable, state `Not applicable` instead of omitting it.

## Writing Rules

- Prefer concrete and implementation-oriented language.
- Use RFC-style keywords when needed (`MUST`, `SHOULD`, `MAY`).
- Avoid ambiguous wording like "probably" or "somehow".
- Include examples for API payloads, schemas, commands, and operational procedures.
- Keep paragraphs short and headings specific.

## Link and Change Management

- Update `docs/README.md` when adding, removing, or renaming docs.
- Update `docs/CHANGELOG.md` for meaningful documentation changes.
- Preserve existing links or provide redirects by updating references in the same change.

## Review and Approval Standard

A document is review-ready when:

- It follows `docs/DOCUMENT_TEMPLATE.md`.
- It passes `docs/DOCUMENT_REVIEW_CHECKLIST.md`.
- All cross-references resolve.
- Operational and security implications are documented.
