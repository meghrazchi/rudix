"""Restore verification against a real PostgreSQL scratch database (R08-04, contract 5.2.10).

Creates a scratch database on the TEST_DATABASE_URL server, migrates it to head, and runs
``scripts/verify_postgres_restore.py`` against it: it passes on a complete schema and fails
once an RLS policy, a key index, or the expected revision is missing. The scratch database
is dropped in teardown.
"""

from __future__ import annotations

import asyncio
import io
import json
import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import asyncpg
import pytest
from backup_support import load_script

from app.ops import restore_verify

pytestmark = pytest.mark.requires_postgres

BACKEND_DIR = Path(__file__).resolve().parents[1]


def _with_database(url: str, name: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, f"/{name}", parts.query, parts.fragment))


@pytest.fixture
async def scratch_url(pg_database_url: str) -> AsyncIterator[str]:
    name = f"rudix_restore_verify_{uuid.uuid4().hex[:12]}"
    admin_url = restore_verify.libpq_url(pg_database_url)
    admin = await asyncpg.connect(admin_url)
    try:
        await admin.execute(f'CREATE DATABASE "{name}"')
    finally:
        await admin.close()
    scratch = _with_database(pg_database_url, name)
    try:
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=BACKEND_DIR,
            env={**os.environ, "DATABASE_URL": scratch},
            capture_output=True,
            text=True,
            check=False,
            timeout=600,
        )
        assert result.returncode == 0, (result.stderr or result.stdout)[-4000:]
        yield scratch
    finally:
        admin = await asyncpg.connect(admin_url)
        try:
            await admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        finally:
            await admin.close()


async def _execute(url: str, statement: str) -> None:
    conn = await asyncpg.connect(restore_verify.libpq_url(url))
    try:
        await conn.execute(statement)
    finally:
        await conn.close()


async def _cli(*argv: str) -> tuple[int, str, str]:
    """The script calls ``asyncio.run``; run it off the test's event loop."""
    module = load_script("verify_postgres_restore")
    out, err = io.StringIO(), io.StringIO()
    code = await asyncio.to_thread(module.main, list(argv), out=out, err=err)
    return code, out.getvalue(), err.getvalue()


async def test_verify_passes_then_fails_without_an_rls_policy(
    scratch_url: str, tmp_path: Path
) -> None:
    report = await restore_verify.verify_restore(
        scratch_url, expected_revision=restore_verify.expected_head()
    )
    assert report.passed, report.lines

    await _execute(
        scratch_url,
        "INSERT INTO organizations (id, name, slug) VALUES (gen_random_uuid(), 'Drill', 'drill')",
    )
    manifest = tmp_path / "manifest.json"
    counts = await restore_verify.write_manifest(scratch_url, manifest, tables=["organizations"])
    assert counts == {"organizations": 1}
    report = await restore_verify.verify_restore(
        scratch_url,
        expected_revision=restore_verify.expected_head(),
        floors=restore_verify.load_manifest(manifest),
    )
    assert report.passed and "ok      rows organizations 1 >= 1" in report.lines

    await _execute(scratch_url, "DROP POLICY tenant_isolation_policy ON documents")
    report = await restore_verify.verify_restore(
        scratch_url, expected_revision=restore_verify.expected_head()
    )
    assert not report.passed
    assert "FAILED  rls_policy documents" in report.lines
    assert report.failures == 1


async def test_cli_against_postgres(scratch_url: str, tmp_path: Path) -> None:
    code, out, err = await _cli("--database-url", scratch_url)
    assert code == 0, err
    assert "restore verification passed" in out
    password = urlsplit(scratch_url).password or ""
    for text in (out, err):
        assert scratch_url not in text
        assert not password or password not in text

    manifest = tmp_path / "floors.json"
    manifest.write_text(json.dumps({"row_count_floors": {"documents": 5}}))
    code, out, err = await _cli("--database-url", scratch_url, "--manifest", str(manifest))
    assert code == 1 and "FAILED  rows documents 0 < 5" in out

    code, out, _ = await _cli("--database-url", scratch_url, "--expect-revision", "20990101_0001")
    assert code == 1 and "expected 20990101_0001" in out

    await _execute(scratch_url, "DROP INDEX idx_chunks_document_id")
    await _execute(scratch_url, "ALTER TABLE chat_sessions DISABLE ROW LEVEL SECURITY")
    code, out, _ = await _cli("--database-url", scratch_url)
    assert code == 1
    assert "FAILED  index idx_chunks_document_id" in out
    assert "FAILED  rls_enabled chat_sessions" in out

    await _execute(scratch_url, "DROP TABLE alembic_version")
    code, out, _ = await _cli("--database-url", scratch_url)
    assert code == 1 and "FAILED  alembic_version table missing" in out
