# Contributing Guide

## Scope

This repository currently contains architecture and implementation documentation for the AI Document Q&A Assistant.

## Workflow

1. Create a feature branch from `main`.
2. Make focused changes with clear commit messages.
3. Open a GitHub pull request with a short summary, rationale, and impacted docs.
4. Request review before merging.

## Pull Request Checklist

- Change is scoped and easy to review.
- Related docs are updated in the same PR.
- No broken links in Markdown files.
- Workflow changes are kept in sync with `README.md` and `docs/14_GITHUB_ACTIONS_CI_CD_PIPELINE.md`.
- Security or production-impacting changes are reflected in:
  - `11_SECURITY_AND_PRODUCTION_CHECKLIST.md`
  - `12_EVALUATION_AND_MONITORING.md`

## Database migrations

Migrations are Alembic revisions in `backend/alembic/versions`, with exactly one head
(`make check-revisions`). They run before new code takes traffic: the chart's migrate Job is a
`pre-install,pre-upgrade` hook (docs/28), and the Compose deploy runs `alembic upgrade head`
before it restarts the services (`deploy/scripts/deploy_compose_remote.sh`). A failed
migration stops the release. Nothing downgrades automatically; a downgrade is a manual,
reviewed operator step.

**Expand-contract.** During a rolling deploy the previous release runs against the new schema,
so every migration must keep the previous version working:

1. Expand (release N): add the new table, column (nullable or with a constant default), or
   index. Old code ignores it.
2. Backfill: fill the new column in batches (a Celery task or script, not one long `UPDATE` in
   the migration) while both versions run.
3. Switch reads and writes to the new shape (still release N, or N+1), behind a setting when
   behaviour changes.
4. Contract (release N+1 or later): drop or rename the old column or table only after no
   deployed release maps it. Constraints on large tables go in as `NOT VALID` first and are
   validated by a later migration.

**Checks.** `backend/scripts/check_migration_safety.py` (`make check-migration-safety`; CI job
`backend-alembic`, step "Check migration safety") reads each migration's `upgrade()` and the
module helpers it calls, skipping branches that run only on non-PostgreSQL dialects:

- `--all`: every migration, against the working-tree models and the allowlist.
- `--base-ref <ref>`: only migrations added or changed since the merge base with the ref
  (plus untracked ones), with drops and renames compared against `app/models` at the ref,
  the models the previous release runs. CI uses the pull request base.

| Rule | Fails when |
|---|---|
| `drop-column`, `drop-table` | `op.drop_column`, `op.drop_table`, or raw `DROP TABLE` / `ALTER TABLE ... DROP COLUMN` removes something the reference models still map |
| `rename-column`, `rename-table` | `op.alter_column(new_column_name=...)`, `op.rename_table`, or raw `RENAME` on something the reference models still map |
| `alter-column-type` | `op.alter_column(type_=...)` or raw `ALTER COLUMN ... TYPE` on a large table |
| `set-not-null` | `op.alter_column(nullable=False)` or raw `SET NOT NULL` on a large table |
| `create-index-non-concurrent` | `op.create_index` without `postgresql_concurrently=True`, or raw `CREATE INDEX` without `CONCURRENTLY`, on a large table |
| `foreign-key-validating` | `op.create_foreign_key` without `postgresql_not_valid=True` when either table is large |
| `check-constraint-validating` | `op.create_check_constraint` without `postgresql_not_valid=True` on a large table |
| `add-constraint-validating` | raw `ALTER TABLE ... ADD CONSTRAINT` without `NOT VALID` (or `USING INDEX`) on a large table |
| `volatile-default` | a new column whose server default calls `random()`, `gen_random_uuid()`, `uuid_generate_v4()`, `clock_timestamp()`, `timeofday()`, or `nextval()` on a large table (`now()` is fine) |
| `lock-table`, `vacuum-full`, `cluster` | raw `LOCK TABLE`, `VACUUM FULL`, or `CLUSTER` on a large table |
| `concurrently-outside-autocommit` | `CONCURRENTLY` (or `postgresql_concurrently=True`) outside `with op.get_context().autocommit_block():` |
| `invalid-marker` | an override marker with an unknown rule or without a reason (cannot be overridden) |

Large tables are listed in `backend/scripts/migration_safety_config.json`; a table created in
the same migration never counts, and a table the check cannot resolve (a variable or an
f-string placeholder) counts as large. SQL built at run time by imported helpers (the RLS
policy statements) is not inspected. The safe index pattern is `20261128_0003`: build with
`postgresql_concurrently=True` inside the autocommit block with `lock_timeout` set, and drop
an INVALID leftover first.

**Override marker.** When a flagged operation is safe for a stated reason (for example the
table is empty in every deployment), put this comment anywhere in the migration file; it
covers the listed rules for that file:

```python
# migration-safety: allow=create-index-non-concurrent,set-not-null reason="table is created empty in 20990101_0001 and not yet written"
```

The reason is required and must not be empty. Reviewers check every marker.

**Allowlist.** `backend/scripts/migration_safety_allowlist.json` holds findings of migrations
that were already applied everywhere when the check (or a rule, or a large table) was added.
Add an entry `{"revision": "<revision id>", "rule": "<rule>", "reason": "<why it is safe or
already applied>"}` only for such a migration, never for a new one (use the marker). `--all`
fails on an entry that matches no finding or names no existing revision, so remove an entry
when its finding goes away.

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
