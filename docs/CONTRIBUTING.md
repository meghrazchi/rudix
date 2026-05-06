# Contributing Guide

## Scope

This repository currently contains architecture and implementation documentation for the AI Document Q&A Assistant.

## Workflow

1. Create a feature branch from `main`.
2. Make focused changes with clear commit messages.
3. Open a pull request with a short summary, rationale, and impacted docs.
4. Request review before merging.

## Pull Request Checklist

- Change is scoped and easy to review.
- Related docs are updated in the same PR.
- No broken links in Markdown files.
- Security or production-impacting changes are reflected in:
  - `11_SECURITY_AND_PRODUCTION_CHECKLIST.md`
  - `12_EVALUATION_AND_MONITORING.md`

## Documentation Contributions

- Keep only `README.md` in the repository root.
- Place all other documentation files in `docs/`.
- Update `docs/README.md` whenever you add, remove, or rename a doc.
- Follow standards in `DOCUMENTATION_STANDARDS.md`.
- Start new technical docs from `DOCUMENT_TEMPLATE.md`.
- Validate quality using `DOCUMENT_REVIEW_CHECKLIST.md`.

## Recommended Commit Message Style

Use short, descriptive messages:

- `docs: add API authentication error matrix`
- `docs: clarify qdrant index lifecycle`
- `docs: update docker deployment prerequisites`
