"""Restore verification logic with a fake connection (R08-04); the real-server run is in
``test_verify_postgres_restore_pg.py``."""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

import asyncpg
import pytest
from backup_support import load_script

from app.ops import restore_verify

URL = "postgresql+asyncpg://rudix:s3cret-password@db.internal:5432/rudix_restore"


class FakeConn:
    """Answers the catalog queries from a complete schema; tests remove pieces."""

    def __init__(self) -> None:
        tables = set(restore_verify.required_tables())
        self.answers: dict[str, set[str]] = {
            "relkind IN": tables,
            "relrowsecurity": set(restore_verify.policy_tables()),
            "pg_policies": set(restore_verify.policy_tables()),
            "contype": set(tables),
            "indisvalid": set(restore_verify.KEY_INDEXES),
        }
        self.versions = [restore_verify.expected_head()]
        self.counts: dict[str, int] = {"documents": 7}
        self.closed = False

    async def fetch(self, query: str, *args: Any) -> list[tuple[str]]:
        if "alembic_version" in query:
            if self.versions is None:
                raise asyncpg.UndefinedTableError("missing")
            return [(version,) for version in self.versions]
        for marker, names in self.answers.items():
            if marker in query:
                return [(name,) for name in sorted(names)]
        raise AssertionError(query)

    async def fetchval(self, query: str) -> int:
        table = query.split('"')[1]
        return self.counts.get(table, 0)

    async def close(self) -> None:
        self.closed = True


def _connect(conn: FakeConn) -> Any:
    async def opener(url: str) -> FakeConn:
        assert url.startswith("postgresql://")
        return conn

    return opener


async def _verify(conn: FakeConn, **kwargs: Any) -> restore_verify.VerifyReport:
    return await restore_verify.verify_restore(
        URL,
        expected_revision=kwargs.pop("expected", restore_verify.expected_head()),
        connect=_connect(conn),
        **kwargs,
    )


async def test_complete_schema_passes() -> None:
    conn = FakeConn()
    report = await _verify(conn, floors={"documents": 5})
    assert report.passed and conn.closed
    assert "ok      rows documents 7 >= 5" in report.lines


@pytest.mark.parametrize(
    ("piece", "name", "line"),
    [
        ("pg_policies", "documents", "FAILED  rls_policy documents"),
        ("relrowsecurity", "api_keys", "FAILED  rls_enabled api_keys"),
        ("indisvalid", "idx_outbox_pending", "FAILED  index idx_outbox_pending"),
        ("contype", "users", "FAILED  primary_key users"),
        ("relkind IN", "chat_messages", "FAILED  table chat_messages"),
    ],
)
async def test_missing_pieces_fail(piece: str, name: str, line: str) -> None:
    conn = FakeConn()
    conn.answers[piece].discard(name)
    report = await _verify(conn)
    assert not report.passed and line in report.lines


async def test_revision_and_floor_failures() -> None:
    conn = FakeConn()
    conn.versions = ["20260101_0001"]
    report = await _verify(conn, floors={"documents": 8, "nope": 1})
    assert f"FAILED  alembic_version 20260101_0001 (expected {restore_verify.expected_head()})" in (
        report.lines
    )
    assert "FAILED  rows documents 7 < 8" in report.lines
    assert "FAILED  rows nope: table missing" in report.lines
    conn = FakeConn()
    conn.versions = []
    assert "FAILED  alembic_version empty" in " ".join((await _verify(conn)).lines)
    conn = FakeConn()
    conn.versions = None  # type: ignore[assignment]
    assert "FAILED  alembic_version table missing" in (await _verify(conn)).lines


async def test_connect_failure_never_echoes_the_url() -> None:
    async def refuse(url: str) -> Any:
        raise OSError(f"could not connect to {url}")

    report = await restore_verify.verify_restore(URL, expected_revision="x", connect=refuse)
    assert report.lines == ["FAILED  connect (OSError)"]


def test_urls_and_manifest(tmp_path: Path) -> None:
    assert restore_verify.libpq_url(URL).startswith("postgresql://rudix:")
    assert restore_verify.libpq_url("postgres+asyncpg://h/db") == "postgresql://h/db"
    assert restore_verify.libpq_url("postgresql://h/db") == "postgresql://h/db"
    with pytest.raises(ValueError, match="postgresql"):
        restore_verify.libpq_url("sqlite:///x.db")
    path = tmp_path / "m.json"
    path.write_text(json.dumps({"row_count_floors": {"documents": 3}}))
    assert restore_verify.load_manifest(path) == {"documents": 3}
    for bad in ({}, {"row_count_floors": {"Bad-Name": 1}}, {"row_count_floors": {"x": -1}}):
        path.write_text(json.dumps(bad))
        with pytest.raises(ValueError):
            restore_verify.load_manifest(path)
    path.write_text(json.dumps({"row_count_floors": {"x": True}}))
    with pytest.raises(ValueError):
        restore_verify.load_manifest(path)


def test_expected_head_is_the_single_alembic_head(tmp_path: Path) -> None:
    head = restore_verify.expected_head()
    versions = Path(restore_verify.BACKEND_DIR / "alembic" / "versions")
    assert any(path.name.startswith(head) for path in versions.glob("*.py"))
    assert restore_verify.required_tables()[0] < restore_verify.required_tables()[-1]


async def test_write_manifest(tmp_path: Path) -> None:
    conn = FakeConn()
    path = tmp_path / "floors.json"
    counts = await restore_verify.write_manifest(
        URL, path, tables=["documents", "users"], connect=_connect(conn)
    )
    assert counts == {"documents": 7, "users": 0}
    assert json.loads(path.read_text()) == {"row_count_floors": counts}
    with pytest.raises(ValueError):
        await restore_verify.write_manifest(URL, path, tables=['x"; drop'], connect=_connect(conn))


def test_cli_without_a_server(tmp_path: Path) -> None:
    module = load_script("verify_postgres_restore")
    conn = FakeConn()
    out, err = io.StringIO(), io.StringIO()
    assert module.main(["--database-url", URL], out=out, err=err, connect=_connect(conn)) == 0
    assert "s3cret-password" not in out.getvalue() + err.getvalue()
    manifest = tmp_path / "out.json"
    out = io.StringIO()
    argv = ["--database-url", URL, "--write-manifest", str(manifest), "--tables", "documents"]
    assert module.main(argv, out=out, err=io.StringIO(), connect=_connect(conn)) == 0
    assert out.getvalue() == "floor   documents 7\n"
    out = io.StringIO()
    argv = ["--database-url", URL, "--write-manifest", str(manifest)]
    assert module.main(argv, out=out, err=io.StringIO(), connect=_connect(conn)) == 0
    assert "floor   chat_messages 0" in out.getvalue()
    conn.answers["pg_policies"].discard("documents")
    err = io.StringIO()
    assert module.main(["--database-url", URL], out=io.StringIO(), err=err, connect=_connect(conn))
    assert "1 check(s)" in err.getvalue()
    err = io.StringIO()
    argv = ["--database-url", URL, "--manifest", str(tmp_path / "missing.json")]
    assert module.main(argv, out=io.StringIO(), err=err, connect=_connect(conn)) == 1
    assert "FileNotFoundError" in err.getvalue()

    async def boom(url: str) -> Any:
        raise asyncpg.PostgresError(f"server says {url}")

    err = io.StringIO()
    argv = ["--database-url", URL, "--write-manifest", str(manifest)]
    assert module.main(argv, out=io.StringIO(), err=err, connect=boom) == 1
    assert err.getvalue().strip() == "verify failed: PostgresError"


def test_expected_head_requires_a_single_head(monkeypatch: pytest.MonkeyPatch) -> None:
    from alembic.script import ScriptDirectory

    monkeypatch.setattr(ScriptDirectory, "get_heads", lambda self: ["a", "b"])
    with pytest.raises(ValueError, match="one alembic head, found 2"):
        restore_verify.expected_head()
