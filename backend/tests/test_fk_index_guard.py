"""Foreign keys must be backed by an index (R04-02).

A foreign key column that does not lead any index makes ``ON DELETE CASCADE`` and joins on
that column scan the whole child table. Every single-column foreign key must be the leading
column of a non-partial index, unique constraint, or primary key, or be listed in
``tests/fixtures/fk_index_exemptions.txt``. The exemption list holds the foreign keys that
were unindexed at 0.4.0; it may only shrink, so a stale entry also fails.
"""

from pathlib import Path

import pytest
from sqlalchemy import (
    Column,
    ForeignKey,
    Index,
    MetaData,
    PrimaryKeyConstraint,
    Table,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.ext.asyncio import AsyncSession

import app.models  # noqa: F401
from app.db.base import Base

EXEMPTIONS_PATH = Path(__file__).resolve().parent / "fixtures" / "fk_index_exemptions.txt"

_PG_UNINDEXED_FKS_SQL = text(
    """
    SELECT cl.relname AS table_name, a.attname AS column_name
    FROM pg_constraint con
    JOIN pg_class cl ON cl.oid = con.conrelid
    JOIN pg_namespace n ON n.oid = cl.relnamespace
    JOIN pg_attribute a ON a.attrelid = con.conrelid AND a.attnum = con.conkey[1]
    WHERE con.contype = 'f'
      AND cardinality(con.conkey) = 1
      AND n.nspname = current_schema()
      AND NOT cl.relispartition
      AND NOT EXISTS (
          SELECT 1 FROM pg_index i
          WHERE i.indrelid = con.conrelid
            AND i.indkey[0] = con.conkey[1]
            AND i.indpred IS NULL
            AND i.indisvalid
      )
    """
)


SCOPE_BOTH = "both"
SCOPE_DB_ONLY = "@db-only"
SCOPE_MODEL_ONLY = "@model-only"
_SCOPES = {SCOPE_DB_ONLY, SCOPE_MODEL_ONLY}


def load_exemption_scopes(path: Path = EXEMPTIONS_PATH) -> dict[str, str]:
    """Parse ``table.column [@db-only|@model-only]  # reason`` lines.

    ``@db-only`` marks a foreign key that exists only in the migrated schema (the model does
    not declare it); ``@model-only`` one that only the model declares. Untagged entries apply
    to both, which is the normal case.
    """
    entries: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        parts = raw.split("#", 1)[0].split()
        if not parts:
            continue
        scope = parts[1] if len(parts) > 1 else SCOPE_BOTH
        if len(parts) > 2 or (len(parts) == 2 and scope not in _SCOPES):
            raise ValueError(f"Malformed exemption line: {raw!r}")
        entries[parts[0]] = scope
    return entries


def load_exemptions(path: Path = EXEMPTIONS_PATH, *, exclude: str | None = None) -> set[str]:
    """Return exempted ``table.column`` entries, leaving out those tagged ``exclude``."""
    return {entry for entry, scope in load_exemption_scopes(path).items() if scope != exclude}


def _is_partial(index: Index) -> bool:
    return any(
        options.get("where") is not None
        for options in (index.dialect_options[name] for name in ("postgresql", "sqlite"))
    )


def _leading_columns(table: Table) -> set[str]:
    leading: set[str] = set()
    for index in table.indexes:
        expressions = list(index.expressions)
        if expressions and isinstance(expressions[0], Column) and not _is_partial(index):
            leading.add(expressions[0].name)
    for constraint in table.constraints:
        if isinstance(constraint, UniqueConstraint | PrimaryKeyConstraint):
            columns = list(constraint.columns)
            if columns:
                leading.add(columns[0].name)
    for column in table.columns:
        if column.index or column.unique:
            leading.add(column.name)
    return leading


def unindexed_foreign_keys(metadata: MetaData) -> set[str]:
    """Return ``table.column`` for every single-column FK that leads no index."""
    tables = {table.name: table for table in metadata.tables.values()}
    missing: set[str] = set()
    for table in tables.values():
        leading = _leading_columns(table)
        for constraint in table.foreign_key_constraints:
            columns = list(constraint.columns)
            if len(columns) == 1 and columns[0].name not in leading:
                missing.add(f"{table.name}.{columns[0].name}")
    return missing


def _format(entries: set[str]) -> str:
    return "\n".join(f"  {entry}" for entry in sorted(entries))


def test_every_foreign_key_has_an_index_or_exemption() -> None:
    missing = unindexed_foreign_keys(Base.metadata) - load_exemptions(exclude=SCOPE_DB_ONLY)
    assert not missing, (
        "Foreign keys without a leading index. Add an Index (model + Alembic migration) or, "
        f"with a justification, a line in {EXEMPTIONS_PATH.name}:\n{_format(missing)}"
    )


def test_exemption_list_has_no_stale_entries() -> None:
    stale = load_exemptions(exclude=SCOPE_DB_ONLY) - unindexed_foreign_keys(Base.metadata)
    assert not stale, (
        f"Remove these entries from {EXEMPTIONS_PATH.name}; they are indexed now or the "
        f"foreign key no longer exists:\n{_format(stale)}"
    )


def test_new_indexes_from_r04_02_are_not_exempted() -> None:
    exemptions = load_exemptions()
    for entry in (
        "citations.document_id",
        "citations.chunk_id",
        "external_items.connection_id",
        "source_documents.document_id",
        "evaluation_results.evaluation_question_id",
        "organization_members.user_id",
        "usage_events.user_id",
        "audit_logs.user_id",
    ):
        assert entry not in exemptions


def _guard_fixture_metadata() -> MetaData:
    metadata = MetaData()
    Table("parents", metadata, Column("id", Uuid(), primary_key=True))
    Table(
        "indexed_children",
        metadata,
        Column("id", Uuid(), primary_key=True),
        Column("parent_id", Uuid(), ForeignKey("parents.id")),
        Index("idx_indexed_children_parent", "parent_id", "id"),
    )
    Table(
        "unique_children",
        metadata,
        Column("id", Uuid(), primary_key=True),
        Column("parent_id", Uuid(), ForeignKey("parents.id")),
        UniqueConstraint("parent_id"),
    )
    Table(
        "column_index_children",
        metadata,
        Column("id", Uuid(), primary_key=True),
        Column("parent_id", Uuid(), ForeignKey("parents.id"), index=True),
    )
    Table(
        "pk_children",
        metadata,
        Column("parent_id", Uuid(), ForeignKey("parents.id"), primary_key=True),
        Column("slot", Uuid(), primary_key=True),
    )
    Table(
        "unindexed_children",
        metadata,
        Column("id", Uuid(), primary_key=True),
        Column("parent_id", Uuid(), ForeignKey("parents.id")),
        Column("other_parent_id", Uuid(), ForeignKey("parents.id")),
        Index("idx_unindexed_children_trailing", "id", "parent_id"),
        Index(
            "idx_unindexed_children_partial",
            "other_parent_id",
            postgresql_where=text("other_parent_id IS NOT NULL"),
        ),
    )
    return metadata


def test_guard_reports_unindexed_trailing_and_partial_foreign_keys() -> None:
    assert unindexed_foreign_keys(_guard_fixture_metadata()) == {
        "unindexed_children.parent_id",
        "unindexed_children.other_parent_id",
    }


def test_guard_fails_for_a_new_foreign_key_without_index() -> None:
    metadata = _guard_fixture_metadata()
    Table(
        "new_children",
        metadata,
        Column("id", Uuid(), primary_key=True),
        Column("parent_id", Uuid(), ForeignKey("parents.id")),
    )
    exemptions = {"unindexed_children.parent_id", "unindexed_children.other_parent_id"}
    assert unindexed_foreign_keys(metadata) - exemptions == {"new_children.parent_id"}


def test_load_exemptions_ignores_comments_and_blank_lines(tmp_path: Path) -> None:
    path = tmp_path / "exemptions.txt"
    path.write_text(
        "# header\n\na.b\n  c.d  # reason\ne.f @db-only # fk only in migrations\ng.h @model-only\n",
        encoding="utf-8",
    )
    assert load_exemptions(path) == {"a.b", "c.d", "e.f", "g.h"}
    assert load_exemptions(path, exclude=SCOPE_DB_ONLY) == {"a.b", "c.d", "g.h"}
    assert load_exemptions(path, exclude=SCOPE_MODEL_ONLY) == {"a.b", "c.d", "e.f"}


@pytest.mark.parametrize("line", ["a.b @unknown", "a.b @db-only extra"])
def test_load_exemptions_rejects_malformed_lines(tmp_path: Path, line: str) -> None:
    path = tmp_path / "exemptions.txt"
    path.write_text(f"{line}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Malformed exemption line"):
        load_exemptions(path)


@pytest.mark.requires_postgres
@pytest.mark.asyncio
async def test_postgres_foreign_keys_match_exemptions(pg_session: AsyncSession) -> None:
    """Reads the migrated schema, so it also catches drift between models and migrations."""
    rows = (await pg_session.execute(_PG_UNINDEXED_FKS_SQL)).all()
    database_unindexed = {f"{row.table_name}.{row.column_name}" for row in rows}
    exemptions = load_exemptions(exclude=SCOPE_MODEL_ONLY)

    missing = database_unindexed - exemptions
    assert not missing, f"Unindexed foreign keys in the migrated schema:\n{_format(missing)}"
    stale = exemptions - database_unindexed
    assert not stale, f"Exempted foreign keys indexed in the migrated schema:\n{_format(stale)}"
