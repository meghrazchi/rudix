"""Backup restore, the runner entry point, and the CLIs (R08-06) with fakes only."""

from __future__ import annotations

import io
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from backup_support import (
    BUCKET,
    DUMP,
    NOW,
    OTHER_KEY_BYTES,
    FakeQdrant,
    FakeS3,
    backup_config,
    load_script,
    make_key,
    make_store,
    snapshot_transport,
    source_bucket,
    write_key_file,
)

from app.ops.backup import restore as restore_ops
from app.ops.backup import runner
from app.ops.backup.crypto import BackupIntegrityError
from app.ops.backup.postgres import backup_postgres
from app.ops.backup.store import (
    BackupConfigurationError,
)

# --- restore ------------------------------------------------------------------------------


def test_restore_checks_hash_prefix_and_marker(tmp_path: Path) -> None:
    client = FakeS3()
    store = make_store(client)
    with pytest.raises(restore_ops.RestoreError, match="no postgres marker"):
        restore_ops.restore_file(
            store, [make_key()], kind="postgres", object_key=None, out=tmp_path
        )
    with pytest.raises(restore_ops.RestoreError, match="outside"):
        restore_ops.restore_file(
            store, [make_key()], kind="postgres", object_key="rudix/qdrant/x", out=tmp_path / "x"
        )
    work = tmp_path / "work"
    work.mkdir()
    (work / "postgres.dump").write_bytes(DUMP)
    marker = backup_postgres(store, make_key(), work_dir=work, now=lambda: NOW)
    client.objects[(BUCKET, marker.object_key)] += b"tampered"
    out = tmp_path / "out.dump"
    with pytest.raises(restore_ops.RestoreError, match="SHA-256"):
        restore_ops.restore_file(store, [make_key()], kind="postgres", object_key=None, out=out)
    assert not out.exists()
    with pytest.raises(BackupIntegrityError):
        restore_ops.restore_file(
            store, [make_key()], kind="postgres", object_key=marker.object_key, out=out
        )


def test_restore_rejects_unsafe_collection_names(tmp_path: Path) -> None:
    store = make_store()
    manifest = {"kind": "qdrant", "collections": [{"name": "../x"}], "aliases": []}
    from app.ops.backup.store import encrypt_bytes_and_upload

    encrypt_bytes_and_upload(
        store,
        make_key(),
        json.dumps(manifest).encode(),
        name="manifest.json",
        object_key="rudix/qdrant/run/manifest.json.rbk",
        work_dir=tmp_path,
    )
    with pytest.raises(restore_ops.RestoreError, match="plain name"):
        restore_ops.restore_qdrant(
            store,
            [make_key()],
            object_key="rudix/qdrant/run/manifest.json.rbk",
            out_dir=tmp_path / "out",
        )


# --- runner and CLIs ----------------------------------------------------------------------


def test_runner_dispatch_and_keys(tmp_path: Path) -> None:
    cfg = backup_config(tmp_path)
    store = make_store()
    with pytest.raises(BackupConfigurationError, match="unknown"):
        runner.run_backup("redis", cfg, store=store)
    work = Path(cfg.backup_work_dir)
    work.mkdir()
    (work / "postgres.dump").write_bytes(DUMP)
    assert runner.run_backup("postgres", cfg, store=store).kind == "postgres"
    source = source_bucket({"a": b"1"})
    marker = runner.run_backup("objects", cfg, store=store, source_client=source)
    assert marker.kind == "objects"
    with httpx.Client(transport=snapshot_transport([])) as http:
        marker = runner.run_backup(
            "qdrant", cfg, store=store, qdrant_client=FakeQdrant(["documents"]), http=http
        )
    assert marker.kind == "qdrant"
    with pytest.raises(BackupConfigurationError, match="KEY_FILE"):
        runner.configured_key(backup_config(tmp_path, backup_encryption_key_file=None))
    with pytest.raises(BackupConfigurationError, match="no backup key"):
        runner.restore_keys(backup_config(tmp_path, backup_encryption_key_file=None))
    old = write_key_file(tmp_path / "old.key", OTHER_KEY_BYTES)
    keys = runner.restore_keys(cfg, [old])
    assert [key.key_id for key in keys] == [make_key().key_id, make_key(OTHER_KEY_BYTES).key_id]


def test_runner_builds_default_clients(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import app.clients.factory as factory

    cfg = backup_config(tmp_path, backup_qdrant_timeout_seconds=1800)
    store = make_store()
    timeouts: list[float | None] = []

    def fake_qdrant(_: object, *, timeout_seconds: float | None = None) -> FakeQdrant:
        timeouts.append(timeout_seconds)
        return FakeQdrant(["documents"])

    monkeypatch.setattr(factory, "create_qdrant_client", fake_qdrant)
    monkeypatch.setattr(factory, "create_minio_client", lambda _: source_bucket({"a": b"1"}))
    real_client = httpx.Client
    monkeypatch.setattr(
        runner.httpx, "Client", lambda: real_client(transport=snapshot_transport([]))
    )
    assert runner.run_backup("qdrant", cfg, store=store).kind == "qdrant"
    # Snapshots block until written: the backup client never uses the 2 s request timeout.
    assert timeouts == [1800]
    assert runner.run_backup("objects", cfg, store=store).kind == "objects"


def test_qdrant_factory_timeout_override() -> None:
    from app.clients.factory import create_qdrant_client

    cfg = SimpleNamespace(
        qdrant_url="http://qdrant:6333", qdrant_api_key=None, qdrant_timeout_seconds=2.0
    )
    default = create_qdrant_client(cfg)  # type: ignore[arg-type]
    backup = create_qdrant_client(cfg, timeout_seconds=1800)  # type: ignore[arg-type]
    assert default._client._timeout == 2
    assert backup._client._timeout == 1800


def test_backup_run_cli(tmp_path: Path) -> None:
    module = load_script("backup_run")
    cfg = backup_config(tmp_path)
    store = make_store()
    out, err = io.StringIO(), io.StringIO()
    assert module.main(["--kind", "postgres"], config=cfg, out=out, err=err, store=store) == 1
    assert "dump file not found" in err.getvalue()
    work = Path(cfg.backup_work_dir)
    work.mkdir(exist_ok=True)
    (work / "postgres.dump").write_bytes(DUMP)
    out, err = io.StringIO(), io.StringIO()
    assert module.main(["--kind", "postgres"], config=cfg, out=out, err=err, store=store) == 0
    payload = json.loads(out.getvalue())
    assert sorted(payload) == ["completed_at", "kind", "size_bytes"]
    client = FakeS3()
    client.fail_on.add("get_object")
    err = io.StringIO()
    code = module.main(
        ["--kind", "objects"],
        config=cfg,
        out=io.StringIO(),
        err=err,
        store=make_store(client),
        source_client=source_bucket({"a": b"1"}),
    )
    assert code == 1 and err.getvalue().strip() == "backup objects failed: ClientError"


def test_backup_restore_cli(tmp_path: Path) -> None:
    module = load_script("backup_restore")
    cfg = backup_config(tmp_path)
    store = make_store()
    work = Path(cfg.backup_work_dir)
    work.mkdir()
    (work / "postgres.dump").write_bytes(DUMP)
    backup_postgres(store, make_key(), work_dir=work, now=lambda: NOW)
    out = io.StringIO()
    target = tmp_path / "restore" / "postgres.dump"
    argv = ["--kind", "postgres", "--latest", "--out", str(target)]
    assert module.main(argv, config=cfg, store=store, out=out, err=io.StringIO()) == 0
    assert target.read_bytes() == DUMP
    assert "pg_restore --no-owner" in out.getvalue() and "$RESTORE_DATABASE_URL" in out.getvalue()
    err = io.StringIO()
    argv = ["--kind", "qdrant", "--latest", "--out", str(tmp_path / "q")]
    assert module.main(argv, config=cfg, store=store, out=io.StringIO(), err=err) == 1
    assert "no qdrant marker" in err.getvalue()
    with httpx.Client(transport=snapshot_transport([])) as http:
        runner.run_backup(
            "qdrant", cfg, store=store, qdrant_client=FakeQdrant(["documents"]), http=http
        )
    runner.run_backup("objects", cfg, store=store, source_client=source_bucket({"k/a": b"1"}))
    out = io.StringIO()
    assert module.main(argv, config=cfg, store=store, out=out, err=io.StringIO()) == 0
    assert "aliases.json" in out.getvalue()
    argv = ["--kind", "objects", "--latest", "--out", str(tmp_path / "o")]
    assert module.main(argv, config=cfg, store=store, out=io.StringIO(), err=io.StringIO()) == 0
    assert (tmp_path / "o" / "k" / "a").read_bytes() == b"1"
    broken = FakeS3()
    broken.fail_on.add("get_object")
    err = io.StringIO()
    code = module.main(argv, config=cfg, store=make_store(broken), out=io.StringIO(), err=err)
    assert code == 1 and err.getvalue().strip() == "restore objects failed: ClientError"
