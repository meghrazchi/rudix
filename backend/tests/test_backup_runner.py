"""Backup runners, store, markers, restore, and the CLIs (R08-06) with fakes only."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from backup_support import (
    BUCKET,
    DUMP,
    NOW,
    OTHER_KEY_BYTES,
    PREFIX,
    FakeQdrant,
    FakeS3,
    backup_config,
    make_key,
    make_store,
    snapshot_transport,
    source_bucket,
)
from pydantic import SecretStr, ValidationError

from app.core.settings.backup import BackupSettings
from app.core.settings.enums import Environment
from app.ops.backup import objects as objects_backup
from app.ops.backup import qdrant as qdrant_backup
from app.ops.backup import restore as restore_ops
from app.ops.backup.markers import BackupMarker, MarkerError, marker_key
from app.ops.backup.postgres import PostgresDumpError, backup_postgres, check_dump
from app.ops.backup.store import (
    BackupConfigurationError,
    BackupStore,
    build_backup_s3_client,
    sse_extra_args,
)

# --- settings -----------------------------------------------------------------------------


class _EnvSettings(BackupSettings):
    environment: Environment = Environment.production


def test_backup_defaults_keep_backups_off() -> None:
    cfg = BackupSettings()
    assert cfg.backup_enabled is False and cfg.backup_freshness_check_enabled is False
    assert cfg.backup_kinds == ["postgres", "qdrant", "objects"]
    assert cfg.backup_s3_sse == "AES256" and cfg.backup_max_age_hours == 26
    assert cfg.backup_freshness_interval_seconds == 900 and cfg.backup_prefix == "rudix"


def test_backup_settings_validation_in_production(tmp_path: Path) -> None:
    assert _EnvSettings(backup_enabled=False).backup_bucket is None
    with pytest.raises(ValidationError, match="backup_bucket is required"):
        _EnvSettings(backup_enabled=True)
    with pytest.raises(ValidationError, match="backup_encryption_key_file is required"):
        _EnvSettings(backup_enabled=True, backup_bucket="rudix-backups")
    key = tmp_path / "k"
    with pytest.raises(ValidationError, match="backup_s3_sse=none"):
        _EnvSettings(
            backup_enabled=True,
            backup_bucket="rudix-backups",
            backup_encryption_key_file=key,
            backup_s3_sse="none",
        )
    ok = _EnvSettings(
        backup_enabled=True,
        backup_bucket="rudix-backups",
        backup_encryption_key_file=key,
        backup_s3_sse="none",
        backup_s3_sse_none_allowed=True,
    )
    assert ok.backup_s3_sse == "none"
    dev = BackupSettings(backup_enabled=True)
    assert dev.backup_bucket is None


def test_backup_kinds_and_prefix_parsing() -> None:
    cfg = BackupSettings(backup_kinds="postgres, neo4j,postgres,", backup_prefix="/rudix/prod/")
    assert cfg.backup_kinds == ["postgres", "neo4j"] and cfg.backup_prefix == "rudix/prod"
    with pytest.raises(ValidationError, match="unknown kind"):
        BackupSettings(backup_kinds="postgres,redis")
    with pytest.raises(ValidationError):
        BackupSettings(backup_kinds=5)
    with pytest.raises(ValidationError):
        BackupSettings(backup_prefix="rudix/../x")


# --- store and markers --------------------------------------------------------------------


def test_sse_arguments() -> None:
    assert sse_extra_args("AES256", None) == {"ServerSideEncryption": "AES256"}
    assert sse_extra_args("aws:kms", "arn:kms") == {
        "ServerSideEncryption": "aws:kms",
        "SSEKMSKeyId": "arn:kms",
    }
    assert sse_extra_args("aws:kms", None) == {"ServerSideEncryption": "aws:kms"}
    assert sse_extra_args("none", "ignored") == {}


def test_build_client_uses_path_style_only_with_an_endpoint(tmp_path: Path) -> None:
    cfg = backup_config(tmp_path, backup_s3_endpoint="http://minio-backup:9000/")
    cfg.backup_s3_access_key = SecretStr("AKIA")
    cfg.backup_s3_secret_key = SecretStr("secret")
    client = build_backup_s3_client(cfg)
    assert client.meta.endpoint_url.rstrip("/") == "http://minio-backup:9000"
    assert client.meta.config.s3 == {"addressing_style": "path"}
    aws = build_backup_s3_client(backup_config(tmp_path))
    assert "amazonaws.com" in aws.meta.endpoint_url
    assert not aws.meta.config.s3


def test_store_from_settings_checks_configuration(tmp_path: Path) -> None:
    with pytest.raises(BackupConfigurationError, match="disabled"):
        BackupStore.from_settings(backup_config(tmp_path, backup_enabled=False), client=FakeS3())
    with pytest.raises(BackupConfigurationError, match="BACKUP_BUCKET"):
        BackupStore.from_settings(backup_config(tmp_path, backup_bucket=None), client=FakeS3())
    store = BackupStore.from_settings(
        backup_config(tmp_path, backup_enabled=False), client=FakeS3(), require_enabled=False
    )
    assert store.bucket == BUCKET and store.prefix == PREFIX


def test_marker_round_trip_and_schema() -> None:
    marker = BackupMarker(
        kind="postgres",
        completed_at=NOW,
        object_key="rudix/postgres/20261128T031500Z/postgres.dump.rbk",
        size_bytes=10,
        sha256="a" * 64,
    )
    data = json.loads(marker.to_json())
    assert sorted(data) == sorted(
        ["kind", "completed_at", "object_key", "size_bytes", "sha256", "format_version"]
    )
    assert data["completed_at"] == "2026-11-28T03:15:00Z" and data["format_version"] == 1
    assert BackupMarker.from_json(marker.to_json(), prefix=PREFIX) == marker
    extra = dict(data, operator_note="ignored")
    assert BackupMarker.from_dict(extra).kind == "postgres"
    assert marker_key("rudix/", "qdrant") == "rudix/qdrant/latest.json"


@pytest.mark.parametrize(
    "change",
    [
        {"object_key": "s3://bucket/key"},
        {"object_key": "/var/backups/postgres.dump"},
        {"object_key": "rudix/postgres/../../etc"},
        {"object_key": "rudix/qdrant/x"},
        {"sha256": "XYZ"},
        {"size_bytes": -1},
        {"size_bytes": True},
        {"size_bytes": "10"},
        {"format_version": 0},
        {"format_version": "1"},
        {"kind": "Postgres!"},
        {"completed_at": "yesterday"},
        {"completed_at": "2026-11-28T03:15:00"},
        {"completed_at": 5},
        {"kind": 5},
    ],
)
def test_invalid_markers_are_rejected(change: dict[str, Any]) -> None:
    data = {
        "kind": "postgres",
        "completed_at": "2026-11-28T03:15:00Z",
        "object_key": "rudix/postgres/20261128T031500Z/postgres.dump.rbk",
        "size_bytes": 10,
        "sha256": "a" * 64,
        "format_version": 1,
    }
    data.update(change)
    with pytest.raises(MarkerError):
        BackupMarker.from_dict(data, prefix=PREFIX)


def test_marker_parse_errors() -> None:
    with pytest.raises(MarkerError, match="JSON"):
        BackupMarker.from_json(b"{not json")
    with pytest.raises(MarkerError, match="object"):
        BackupMarker.from_json(b"[]")
    with pytest.raises(MarkerError, match="missing"):
        BackupMarker.from_json(b"{}")
    with pytest.raises(MarkerError, match="timezone-aware"):
        BackupMarker(
            kind="postgres",
            completed_at=datetime(2026, 1, 1),
            object_key="rudix/postgres/x",
            size_bytes=1,
            sha256="a" * 64,
        ).to_dict()


def test_store_get_bytes_missing_and_errors() -> None:
    client = FakeS3()
    store = make_store(client)
    assert store.get_bytes("rudix/nothing") is None
    assert store.read_marker("postgres") is None
    client.fail_on.add("get_object")
    with pytest.raises(Exception, match="AccessDenied"):
        store.get_bytes("rudix/nothing")


# --- postgres -----------------------------------------------------------------------------


def test_postgres_backup_uploads_encrypted_dump_then_marker(tmp_path: Path) -> None:
    client = FakeS3()
    store = make_store(client, sse="aws:kms", kms_key_id="kms-1")
    work = tmp_path / "work"
    work.mkdir()
    (work / "postgres.dump").write_bytes(DUMP)
    marker = backup_postgres(store, make_key(), work_dir=work, now=lambda: NOW)
    assert marker.object_key == "rudix/postgres/20261128T031500Z/postgres.dump.rbk"
    blob = client.objects[(BUCKET, marker.object_key)]
    assert DUMP not in blob and blob.startswith(b"RUDIXBK1")
    assert marker.size_bytes == len(blob)
    assert client.extra[(BUCKET, marker.object_key)] == {
        "ServerSideEncryption": "aws:kms",
        "SSEKMSKeyId": "kms-1",
    }
    assert client.calls.index("upload_file") < client.calls.index("put_object")
    assert list(work.iterdir()) == []  # plaintext dump and ciphertext removed
    out = tmp_path / "restored.dump"
    restore_ops.restore_file(store, [make_key()], kind="postgres", object_key=None, out=out)
    assert out.read_bytes() == DUMP


def test_postgres_dump_checks(tmp_path: Path) -> None:
    with pytest.raises(PostgresDumpError, match="not found"):
        check_dump(tmp_path / "missing.dump")
    empty = tmp_path / "empty.dump"
    empty.write_bytes(b"")
    with pytest.raises(PostgresDumpError, match="empty"):
        check_dump(empty)
    plain = tmp_path / "plain.sql"
    plain.write_text("CREATE TABLE x();")
    with pytest.raises(PostgresDumpError, match="custom-format"):
        check_dump(plain)


def test_postgres_upload_failure_writes_no_marker_and_removes_plaintext(tmp_path: Path) -> None:
    client = FakeS3()
    client.fail_on.add("upload_file")
    work = tmp_path / "work"
    work.mkdir()
    (work / "postgres.dump").write_bytes(DUMP)
    with pytest.raises(Exception, match="AccessDenied"):
        backup_postgres(make_store(client), make_key(), work_dir=work, now=lambda: NOW)
    assert client.keys() == [] and list(work.iterdir()) == []


# --- qdrant -------------------------------------------------------------------------------


def test_qdrant_backup_snapshots_every_deployment_collection(tmp_path: Path) -> None:
    client = FakeS3()
    store = make_store(client)
    qdrant = FakeQdrant(["documents", "documents_te3_v2", "unrelated", "documentsx"])
    seen: list[httpx.Request] = []
    with httpx.Client(transport=snapshot_transport(seen)) as http:
        marker = qdrant_backup.backup_qdrant(
            store,
            make_key(),
            client=qdrant,
            http=http,
            qdrant_url="http://qdrant:6333/",
            api_key="qdrant-api-key",
            base_collection="documents",
            work_dir=tmp_path / "q",
            now=lambda: NOW,
        )
    assert qdrant.created == ["documents", "documents_te3_v2"]
    assert [name for name, _ in qdrant.deleted] == ["documents", "documents_te3_v2"]
    assert [request.headers["api-key"] for request in seen] == ["qdrant-api-key"] * 2
    assert seen[0].url.path == "/collections/documents/snapshots/documents-snap.snapshot"
    assert marker.object_key == "rudix/qdrant/20261128T031500Z/manifest.json.rbk"
    for key in client.keys():
        assert b"snapshot-of" not in client.objects[(BUCKET, key)]
    assert list((tmp_path / "q").iterdir()) == []
    out = tmp_path / "restore"
    result = restore_ops.restore_qdrant(store, [make_key()], object_key=None, out_dir=out)
    assert (out / "documents_te3_v2.snapshot").read_bytes() == b"snapshot-of-documents_te3_v2" * 100
    aliases = json.loads((out / "aliases.json").read_text())
    assert aliases == [{"alias": "documents_live", "collection": "documents_te3_v2"}]
    assert len(result.files) == 3


def test_qdrant_backup_failures(tmp_path: Path) -> None:
    store = make_store()
    with httpx.Client(transport=snapshot_transport([])) as http:
        with pytest.raises(qdrant_backup.QdrantBackupError, match="no Qdrant collection"):
            qdrant_backup.backup_qdrant(
                store,
                make_key(),
                client=FakeQdrant(["other"]),
                http=http,
                qdrant_url="http://qdrant:6333",
                api_key=None,
                base_collection="documents",
                work_dir=tmp_path,
            )
    failing = FakeQdrant(["documents"])

    def boom(*, collection_name: str, snapshot_name: str, wait: bool) -> None:
        raise RuntimeError("delete failed")

    failing.delete_snapshot = boom  # type: ignore[method-assign]
    denied = httpx.MockTransport(lambda request: httpx.Response(403))
    with httpx.Client(transport=denied) as http:
        with pytest.raises(httpx.HTTPStatusError):
            qdrant_backup.backup_qdrant(
                store,
                make_key(),
                client=failing,
                http=http,
                qdrant_url="http://qdrant:6333",
                api_key=None,
                base_collection="documents",
                work_dir=tmp_path / "q",
            )
    assert store.read_marker("qdrant") is None
    no_snapshot = FakeQdrant(["documents"])
    no_snapshot.create_snapshot = lambda **_: None  # type: ignore[method-assign]
    with httpx.Client(transport=snapshot_transport([])) as http:
        with pytest.raises(qdrant_backup.QdrantBackupError, match="no snapshot"):
            qdrant_backup.backup_qdrant(
                store,
                make_key(),
                client=no_snapshot,
                http=http,
                qdrant_url="http://qdrant:6333",
                api_key=None,
                base_collection="documents",
                work_dir=tmp_path / "q",
            )
    with pytest.raises(qdrant_backup.QdrantBackupError):
        qdrant_backup.parse_manifest(b'{"kind": "objects"}')
    with pytest.raises(qdrant_backup.QdrantBackupError):
        qdrant_backup.parse_manifest(b'{"kind": "qdrant"}')


# --- objects ------------------------------------------------------------------------------


def test_objects_mirror_is_incremental_and_propagates_deletes(tmp_path: Path) -> None:
    backup = FakeS3()
    store = make_store(backup)
    source = source_bucket({"org/a.pdf": b"A" * 10, "org/b.pdf": b"B" * 20, "org/c.txt": b"C"})
    times = iter(NOW + timedelta(minutes=minute) for minute in range(20))
    marker, stats = objects_backup.mirror_objects(
        store,
        make_key(),
        source_client=source,
        source_bucket="documents",
        work_dir=tmp_path / "o",
        now=lambda: next(times),
    )
    assert (stats.copied, stats.unchanged, stats.removed, stats.total) == (3, 0, 0, 3)
    data_keys = [key for key in backup.keys() if "/objects/data/" in key]
    assert len(data_keys) == 3 and not any("a.pdf" in key for key in backup.keys())
    source.objects[("documents", "org/b.pdf")] = b"changed"
    del source.objects[("documents", "org/c.txt")]
    source.objects[("documents", "org/d.docx")] = b"D"
    _, stats = objects_backup.mirror_objects(
        store,
        make_key(),
        source_client=source,
        source_bucket="documents",
        work_dir=tmp_path / "o",
        now=lambda: next(times),
    )
    assert (stats.copied, stats.unchanged, stats.removed, stats.total) == (2, 1, 1, 3)
    assert len([key for key in backup.keys() if "/objects/data/" in key]) == 3
    out = tmp_path / "restored"
    restore_ops.restore_objects(store, [make_key()], object_key=None, out_dir=out)
    assert (out / "org" / "b.pdf").read_bytes() == b"changed"
    assert sorted(path.name for path in (out / "org").iterdir()) == ["a.pdf", "b.pdf", "d.docx"]
    assert marker.kind == "objects"


def test_objects_mirror_refuses_to_empty_the_mirror(tmp_path: Path) -> None:
    store = make_store()
    source = source_bucket({"org/a.pdf": b"A"})
    kwargs: dict[str, Any] = {
        "source_client": source,
        "source_bucket": "documents",
        "work_dir": tmp_path / "o",
    }
    objects_backup.mirror_objects(store, make_key(), **kwargs)
    source.objects.clear()
    with pytest.raises(objects_backup.ObjectMirrorError, match="refusing"):
        objects_backup.mirror_objects(store, make_key(), **kwargs)
    assert len([key for key in store.client.keys() if "/objects/data/" in key]) == 1


def test_objects_mirror_after_key_rotation_copies_again(tmp_path: Path) -> None:
    store = make_store()
    source = source_bucket({"org/a.pdf": b"A"})
    kwargs: dict[str, Any] = {
        "source_client": source,
        "source_bucket": "documents",
        "work_dir": tmp_path / "o",
    }
    objects_backup.mirror_objects(store, make_key(), **kwargs)
    _, stats = objects_backup.mirror_objects(store, make_key(OTHER_KEY_BYTES), **kwargs)
    assert stats.copied == 1
    _, stats = objects_backup.mirror_objects(
        store,
        make_key(OTHER_KEY_BYTES),
        restore_keys=[make_key(OTHER_KEY_BYTES), make_key()],
        **kwargs,
    )
    assert stats.unchanged == 1


def test_object_paths_and_manifest_checks() -> None:
    assert objects_backup.safe_relative_path("org/x/./a.pdf") == Path("org/x/a.pdf")
    for bad in ("/etc/passwd", "org/../../x", "", "//"):
        with pytest.raises(objects_backup.ObjectMirrorError):
            objects_backup.safe_relative_path(bad)
    with pytest.raises(objects_backup.ObjectMirrorError):
        objects_backup.parse_manifest(b'{"kind": "qdrant"}')
    with pytest.raises(objects_backup.ObjectMirrorError):
        objects_backup.parse_manifest(b'{"kind": "objects", "objects": []}')
