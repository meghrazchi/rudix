"""Migration safety check (0.8.0, R08-08): rules, markers, allowlist, base-ref mode, history.

Each rule gets a synthetic migration that must fail and its safe variant that must pass. The
migrations live in a temporary backend directory with its own ``app/models``; the real
``scripts/migration_safety_config.json`` supplies the large tables.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import textwrap
from pathlib import Path
from types import ModuleType

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = BACKEND_DIR / "scripts"
CONFIG = SCRIPTS_DIR / "migration_safety_config.json"
ALLOWLIST = SCRIPTS_DIR / "migration_safety_allowlist.json"


def _load_cli() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "check_migration_safety", SCRIPTS_DIR / "check_migration_safety.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cli = _load_cli()
from migration_safety import rules  # noqa: E402
from migration_safety.models import schema_from_sources  # noqa: E402
from migration_safety.sql import sql_events  # noqa: E402

MODELS = """
from sqlalchemy import Column, String, Table
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.common import TimestampMixin


class Document(TimestampMixin, Base):
    __tablename__ = "documents"
    id: Mapped[str] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    meta: Mapped[dict] = mapped_column("metadata", String)


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(primary_key=True)


tags = Table("tags", Base.metadata, Column("name", String))
"""
COMMON = """
from sqlalchemy.orm import Mapped, mapped_column


class TimestampMixin:
    created_at: Mapped[str] = mapped_column()
"""

TEMPLATE = '''"""synthetic migration"""

import sqlalchemy as sa

from alembic import op

revision = "{revision}"
down_revision = None
{marker}

{helpers}

def upgrade() -> None:
{body}


def downgrade() -> None:
    op.drop_column("documents", "title")
    op.drop_table("documents")
'''


def _backend(tmp_path: Path) -> Path:
    backend = tmp_path / "backend"
    (backend / "alembic" / "versions").mkdir(parents=True)
    models = backend / "app" / "models"
    models.mkdir(parents=True)
    (models / "document.py").write_text(MODELS)
    (models / "common.py").write_text(COMMON)
    return backend


def _migration(
    backend: Path,
    body: str,
    *,
    revision: str = "20990101_0001",
    marker: str = "",
    helpers: str = "",
) -> Path:
    path = backend / "alembic" / "versions" / f"{revision}_synthetic.py"
    path.write_text(
        TEMPLATE.format(
            revision=revision,
            marker=marker,
            helpers=textwrap.dedent(helpers),
            body=textwrap.indent(textwrap.dedent(body).strip(), "    "),
        )
    )
    return path


def _run(
    backend: Path, capsys: pytest.CaptureFixture[str], *args: str, allowlist: Path | None = None
) -> tuple[int, str]:
    if allowlist is None:
        allowlist = backend / "allowlist.json"
        if not allowlist.exists():
            allowlist.write_text(json.dumps({"entries": []}))
    code = cli.main(
        [
            *(args or ("--all",)),
            "--backend-dir",
            str(backend),
            "--config",
            str(CONFIG),
            "--allowlist",
            str(allowlist),
        ]
    )
    captured = capsys.readouterr()
    return code, captured.out + captured.err


AUTOCOMMIT = "with op.get_context().autocommit_block():\n    {}"

# (rule, unsafe body, safe body)
CASES: list[tuple[str, str, str]] = [
    (
        rules.DROP_COLUMN,
        'op.drop_column("documents", "title")',
        'op.drop_column("documents", "legacy")',
    ),
    (
        rules.DROP_COLUMN,
        'op.execute("ALTER TABLE documents DROP COLUMN metadata")',
        'op.execute("ALTER TABLE documents DROP COLUMN IF EXISTS legacy")',
    ),
    (rules.DROP_TABLE, 'op.drop_table("documents")', 'op.drop_table("legacy_things")'),
    (
        rules.DROP_TABLE,
        'op.execute("DROP TABLE IF EXISTS tags")',
        'op.execute("DROP TABLE IF EXISTS legacy_things")',
    ),
    (
        rules.RENAME_COLUMN,
        'op.alter_column("documents", "title", new_column_name="name")',
        'op.alter_column("documents", "legacy", new_column_name="old")',
    ),
    (
        rules.RENAME_COLUMN,
        'op.execute("ALTER TABLE documents RENAME COLUMN created_at TO born_at")',
        'op.execute("ALTER TABLE documents RENAME CONSTRAINT a TO b")',
    ),
    (
        rules.RENAME_TABLE,
        'op.rename_table("users", "people")',
        'op.rename_table("legacy_things", "old_things")',
    ),
    (
        rules.RENAME_TABLE,
        'op.execute("ALTER TABLE users RENAME TO people")',
        'op.execute("ALTER TABLE legacy RENAME TO old")',
    ),
    (
        rules.ALTER_COLUMN_TYPE,
        'op.alter_column("documents", "title", type_=sa.Text())',
        'op.alter_column("tags", "name", type_=sa.Text())',
    ),
    (
        rules.ALTER_COLUMN_TYPE,
        'op.execute("ALTER TABLE documents ALTER COLUMN title TYPE text")',
        'op.execute("ALTER TABLE tags ALTER COLUMN name TYPE text")',
    ),
    (
        rules.SET_NOT_NULL,
        'op.alter_column("documents", "title", nullable=False)',
        'op.alter_column("documents", "title", nullable=True)',
    ),
    (
        rules.SET_NOT_NULL,
        'op.execute("ALTER TABLE usage_events ALTER COLUMN user_id SET NOT NULL")',
        'op.execute("ALTER TABLE usage_events ALTER COLUMN user_id DROP NOT NULL")',
    ),
    (
        rules.CREATE_INDEX_NON_CONCURRENT,
        'op.create_index("ix_t", "documents", ["title"])',
        AUTOCOMMIT.format(
            'op.create_index("ix_t", "documents", ["title"], postgresql_concurrently=True)'
        ),
    ),
    (
        rules.CREATE_INDEX_NON_CONCURRENT,
        'op.execute("CREATE INDEX ix_t ON chat_messages (created_at)")',
        AUTOCOMMIT.format(
            'op.execute("CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_t ON chat_messages (created_at)")'
        ),
    ),
    (
        rules.FOREIGN_KEY_VALIDATING,
        'op.create_foreign_key("fk_u", "documents", "users", ["user_id"], ["id"])',
        'op.create_foreign_key("fk_u", "documents", "users", ["user_id"], ["id"], postgresql_not_valid=True)',
    ),
    (
        rules.FOREIGN_KEY_VALIDATING,
        'op.create_foreign_key("fk_d", "tags", "documents", ["doc_id"], ["id"])',
        'op.create_foreign_key("fk_d", "tags", "users", ["user_id"], ["id"])',
    ),
    (
        rules.CHECK_CONSTRAINT_VALIDATING,
        'op.create_check_constraint("ck_t", "documents", "length(title) > 0")',
        'op.create_check_constraint("ck_t", "documents", "length(title) > 0", postgresql_not_valid=True)',
    ),
    (
        rules.ADD_CONSTRAINT_VALIDATING,
        'op.execute("ALTER TABLE documents ADD CONSTRAINT ck_t CHECK (length(title) > 0)")',
        'op.execute("ALTER TABLE documents ADD CONSTRAINT ck_t CHECK (length(title) > 0) NOT VALID")',
    ),
    (
        rules.VOLATILE_DEFAULT,
        'op.add_column("documents", sa.Column("token", sa.UUID(), server_default=sa.text("gen_random_uuid()")))',
        'op.add_column("documents", sa.Column("seen_at", sa.DateTime(), server_default=sa.text("now()")))',
    ),
    (
        rules.VOLATILE_DEFAULT,
        'op.execute("ALTER TABLE documents ADD COLUMN r float DEFAULT random()")',
        'op.execute("ALTER TABLE documents ADD COLUMN r float DEFAULT 0")',
    ),
    (
        rules.LOCK_TABLE,
        'op.execute("LOCK TABLE documents IN ACCESS EXCLUSIVE MODE")',
        "op.execute(\"SET lock_timeout = '5s'\")",
    ),
    (rules.VACUUM_FULL, 'op.execute("VACUUM FULL documents")', 'op.execute("ANALYZE documents")'),
    (
        rules.CLUSTER,
        'op.execute("CLUSTER documents USING ix_t")',
        'op.execute("ALTER TABLE documents CLUSTER ON ix_t")',
    ),
    (
        rules.CONCURRENTLY_OUTSIDE_AUTOCOMMIT,
        'op.create_index("ix_t", "tags", ["name"], postgresql_concurrently=True)',
        AUTOCOMMIT.format(
            'op.create_index("ix_t", "tags", ["name"], postgresql_concurrently=True)'
        ),
    ),
    (
        rules.CONCURRENTLY_OUTSIDE_AUTOCOMMIT,
        'op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_t")',
        AUTOCOMMIT.format('op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_t")'),
    ),
]


@pytest.mark.parametrize(
    ("rule", "unsafe", "safe"), CASES, ids=[f"{c[0]}-{i}" for i, c in enumerate(CASES)]
)
def test_each_rule_fails_unsafe_and_passes_safe(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], rule: str, unsafe: str, safe: str
) -> None:
    backend = _backend(tmp_path)
    path = _migration(backend, unsafe)
    code, output = _run(backend, capsys)
    assert code == 1, output
    assert f" {rule}: " in output
    assert "20990101_0001 alembic/versions/20990101_0001_synthetic.py:" in output

    path.unlink()
    _migration(backend, safe)
    code, output = _run(backend, capsys)
    assert code == 0, output
    assert "OK, 1 file(s)" in output


def test_lock_rules_skip_small_and_new_tables(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    backend = _backend(tmp_path)
    _migration(
        backend,
        """
        op.create_table("documents_archive", sa.Column("id", sa.Integer(), primary_key=True))
        op.create_index("ix_a", "documents_archive", ["id"])
        op.alter_column("documents_archive", "id", nullable=False)
        op.execute("CREATE TABLE IF NOT EXISTS documents_shadow (id int)")
        op.execute("CREATE INDEX ix_s ON documents_shadow (id)")
        op.create_index("ix_tags", "tags", ["name"])
        """,
    )
    code, output = _run(backend, capsys)
    assert code == 0, output


def test_unresolved_table_counts_as_large(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    backend = _backend(tmp_path)
    _migration(
        backend,
        """
        for table in ("documents", "tags"):
            op.create_index(f"ix_{table}", table, ["id"])
        """,
    )
    code, output = _run(backend, capsys)
    assert code == 1
    assert "<unresolved table>" in output


def test_non_postgres_branches_helpers_and_batch_mode(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    backend = _backend(tmp_path)
    helpers = """
    def _is_postgresql() -> bool:
        return op.get_bind().dialect.name == "postgresql"


    def _build() -> None:
        op.create_index("ix_t", "documents", ["title"], postgresql_concurrently=True)
    """
    _migration(
        backend,
        """
        if op.get_bind().dialect.name != "postgresql":
            op.create_index("ix_t", "documents", ["title"])
            return
        if not _is_postgresql():
            op.alter_column("documents", "title", type_=sa.Text())
        is_pg = op.get_bind().dialect.name == "postgresql"
        if is_pg:
            pass
        else:
            op.execute("VACUUM FULL documents")
        with op.get_context().autocommit_block():
            _build()
        """,
        helpers=helpers,
    )
    code, output = _run(backend, capsys)
    assert code == 0, output

    _migration(
        backend,
        """
        _build()
        with op.batch_alter_table("documents") as batch_op:
            batch_op.alter_column("title", type_=sa.Text())
            batch_op.drop_column("title")
        """,
        revision="20990101_0002",
        helpers=helpers,
    )
    code, output = _run(backend, capsys)
    assert code == 1
    assert "20990101_0002" in output
    for rule in (
        rules.CONCURRENTLY_OUTSIDE_AUTOCOMMIT,
        rules.ALTER_COLUMN_TYPE,
        rules.DROP_COLUMN,
    ):
        assert f" {rule}: " in output, rule


def test_override_marker_needs_a_reason(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    backend = _backend(tmp_path)
    body = 'op.create_index("ix_t", "documents", ["title"])'
    marker = (
        '# migration-safety: allow=create-index-non-concurrent reason="documents is empty here"'
    )
    path = _migration(backend, body, marker=marker)
    code, output = _run(backend, capsys)
    assert code == 0, output

    for bad in (
        "# migration-safety: allow=create-index-non-concurrent",
        '# migration-safety: allow=create-index-non-concurrent reason=""',
        '# migration-safety: allow=create-index-non-concurrent reason="  "',
        '# migration-safety: allow=not-a-rule reason="typo"',
        "# migration-safety: please allow",
    ):
        path.write_text(path.read_text().replace(marker, bad))
        code, output = _run(backend, capsys)
        assert code == 1, bad
        assert f" {rules.INVALID_MARKER}: " in output, bad
        path.write_text(path.read_text().replace(bad, marker))

    multi = '# migration-safety: allow=create-index-non-concurrent,drop-column reason="staged"'
    path.write_text(path.read_text().replace(marker, multi))
    path.write_text(
        path.read_text().replace(body, body + '\n    op.drop_column("documents", "title")')
    )
    code, output = _run(backend, capsys)
    assert code == 0, output


def test_allowlist_entries_suppress_and_stale_entries_fail(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    backend = _backend(tmp_path)
    _migration(backend, 'op.create_index("ix_t", "documents", ["title"])')
    allowlist = tmp_path / "allow.json"
    entry = {"revision": "20990101_0001", "rule": "create-index-non-concurrent", "reason": "old"}
    allowlist.write_text(json.dumps({"entries": [entry]}))
    assert _run(backend, capsys, allowlist=allowlist)[0] == 0

    stale = {"revision": "20990101_0001", "rule": "drop-column", "reason": "fixed since"}
    missing = {"revision": "20000101_0001", "rule": "drop-table", "reason": "gone"}
    allowlist.write_text(json.dumps({"entries": [entry, stale, missing]}))
    code, output = _run(backend, capsys, allowlist=allowlist)
    assert code == 1
    assert "20990101_0001 allowlist: stale entry for drop-column" in output
    assert "20000101_0001 allowlist: stale entry for drop-table" in output

    allowlist.write_text(json.dumps({"entries": [{**entry, "reason": ""}]}))
    code, output = _run(backend, capsys, allowlist=allowlist)
    assert code == 2
    assert "needs a reason" in output
    allowlist.write_text(json.dumps({"entries": [{**entry, "rule": "invalid-marker"}]}))
    assert _run(backend, capsys, allowlist=allowlist)[0] == 2


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        [
            "git",
            "-c",
            "user.email=ci@example.invalid",
            "-c",
            "user.name=CI",
            "-c",
            "commit.gpgsign=false",
            "-c",
            "core.hooksPath=/dev/null",
            *args,
        ],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def test_base_ref_mode_uses_the_previous_models(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = tmp_path
    backend = _backend(repo)
    _git(repo, "init", "-q", "-b", "main")
    # An old migration with a finding that base-ref mode must not re-check.
    _migration(
        backend, 'op.create_index("ix_old", "documents", ["title"])', revision="20980101_0001"
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")

    # The new release drops documents.title from the model and the schema in one step.
    models = backend / "app" / "models" / "document.py"
    models.write_text(
        models.read_text().replace("    title: Mapped[str] = mapped_column(String(255))\n", "")
    )
    _migration(backend, 'op.drop_column("documents", "title")', revision="20990101_0001")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "contract too early")

    code, output = _run(backend, capsys, "--base-ref", "main~1")
    assert code == 1, output
    assert "20990101_0001" in output and " drop-column: " in output
    assert "20980101_0001" not in output
    assert "1 file(s)" in output

    # --all compares with the working-tree models, which no longer map the column.
    allowlist = backend / "allow.json"
    allowlist.write_text(
        json.dumps(
            {
                "entries": [
                    {
                        "revision": "20980101_0001",
                        "rule": "create-index-non-concurrent",
                        "reason": "old",
                    }
                ]
            }
        )
    )
    assert _run(backend, capsys, "--all", allowlist=allowlist)[0] == 0

    # An untracked migration is checked too; one dropping a never-mapped column passes.
    _migration(backend, 'op.drop_column("documents", "legacy")', revision="20990101_0002")
    code, output = _run(backend, capsys, "--base-ref", "main~1")
    assert "2 file(s)" in output
    assert code == 1  # 20990101_0001 still fails

    code, output = _run(backend, capsys, "--base-ref", "no-such-ref")
    assert code == 2
    assert "git" in output


def test_real_history_passes_with_no_stale_entries(capsys: pytest.CaptureFixture[str]) -> None:
    code = cli.main(["--all"])
    output = capsys.readouterr().out
    assert code == 0, output
    versions = [path for path in (BACKEND_DIR / "alembic" / "versions").glob("*.py")]
    assert f"OK, {len(versions)} file(s)" in output


def test_allowlist_entries_name_real_revisions_with_reasons() -> None:
    data = json.loads(ALLOWLIST.read_text())
    revisions = {
        path.name.split("_", 2)[0] + "_" + path.name.split("_", 2)[1]
        for path in (BACKEND_DIR / "alembic" / "versions").glob("*.py")
    }
    keys = set()
    for entry in data["entries"]:
        assert entry["revision"] in revisions
        assert entry["rule"] in rules.OVERRIDABLE_RULES
        assert len(entry["reason"]) > 40
        keys.add((entry["revision"], entry["rule"]))
    assert len(keys) == len(data["entries"])


def test_config_lists_large_tables_that_models_map() -> None:
    config = json.loads(CONFIG.read_text())
    models = sorted((BACKEND_DIR / "app" / "models").rglob("*.py"))
    schema = schema_from_sources(path.read_text() for path in models)
    required = {
        "documents",
        "document_chunks",
        "document_pages",
        "chat_messages",
        "citations",
        "usage_events",
        "audit_logs",
        "authorization_decision_logs",
        "activity_timeline_events",
        "webhook_deliveries",
        "outbox_messages",
    }
    assert required <= set(config["large_tables"])
    assert sorted(set(config["large_tables"]) - schema.tables) == []


def test_model_parsing_follows_mixins_names_and_tables() -> None:
    schema = schema_from_sources([MODELS, COMMON, "def broken(:\n"])
    assert schema.maps_column("documents", "title")
    assert schema.maps_column("documents", "metadata")
    assert not schema.maps_column("documents", "meta")
    assert schema.maps_column("documents", "created_at")
    assert schema.maps_column("tags", "name")
    assert schema.maps_table("users") and not schema.maps_table("legacy")


def test_sql_events_handle_comments_quotes_and_placeholders() -> None:
    events = sql_events(
        '-- DROP TABLE documents\nALTER TABLE ONLY public."documents" DROP COLUMN "title", '
        "ADD COLUMN x int DEFAULT nextval('s'); CREATE UNIQUE INDEX ix ON {} (id)"
    )
    found = {(event.rule, event.table, event.column) for event in events}
    assert (rules.DROP_COLUMN, "documents", "title") in found
    assert (rules.VOLATILE_DEFAULT, "documents", None) in found
    assert (rules.CREATE_INDEX_NON_CONCURRENT, None, None) in found
    assert not any(event.rule == rules.DROP_TABLE for event in events)
    assert sql_events("ALTER TABLE documents ALTER COLUMN title DROP DEFAULT") == []
