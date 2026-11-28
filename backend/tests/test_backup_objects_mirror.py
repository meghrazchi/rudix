"""Object mirror versioned copies and pruning (R08-06): a failed run never breaks the latest
restorable backup, and copies the current manifest does not reference are pruned safely."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from backup_support import OTHER_KEY_BYTES, FakeS3, make_key, make_store, source_bucket

from app.ops.backup import objects as objects_backup
from app.ops.backup import restore as restore_ops


class _FailManifestUpload(FakeS3):
    """Fails the upload of the run manifest, after the changed objects were copied."""

    fail_manifest = False

    def upload_file(self, **kwargs: Any) -> None:
        if self.fail_manifest and str(kwargs["Key"]).endswith("manifest.json.rbk"):
            raise RuntimeError("upload interrupted")
        super().upload_file(**kwargs)


def _mirror(store: Any, source: FakeS3, work: Path, **kwargs: Any) -> Any:
    return objects_backup.mirror_objects(
        store,
        kwargs.pop("key", make_key()),
        source_client=source,
        source_bucket="documents",
        work_dir=work,
        **kwargs,
    )


def _data_keys(client: FakeS3) -> list[str]:
    return [key for key in client.keys() if "/objects/data/" in key]


def test_a_failed_run_leaves_the_latest_backup_restorable(tmp_path: Path) -> None:
    backup = _FailManifestUpload()
    store = make_store(backup)
    source = source_bucket({"org/a.pdf": b"A" * 10, "org/b.pdf": b"B" * 20})
    _mirror(store, source, tmp_path / "o")
    first_copies = _data_keys(backup)

    source.objects[("documents", "org/b.pdf")] = b"changed"
    backup.fail_manifest = True
    with pytest.raises(RuntimeError, match="interrupted"):
        _mirror(store, source, tmp_path / "o")
    # The changed version went to a new key; the copies of the marker's manifest are intact.
    assert set(first_copies) < set(_data_keys(backup))

    out = tmp_path / "restored"
    restore_ops.restore_objects(store, [make_key()], object_key=None, out_dir=out)
    assert (out / "org" / "b.pdf").read_bytes() == b"B" * 20

    backup.fail_manifest = False
    _, stats = _mirror(store, source, tmp_path / "o")
    assert (stats.copied, stats.unchanged, stats.pruned) == (1, 1, 1)
    assert len(_data_keys(backup)) == 2
    restore_ops.restore_objects(store, [make_key()], object_key=None, out_dir=tmp_path / "r2")
    assert (tmp_path / "r2" / "org" / "b.pdf").read_bytes() == b"changed"


def test_mirror_keys_depend_on_version_and_key_only() -> None:
    store = make_store()
    item = objects_backup.SourceObject(key="org/a.pdf", etag="e1", size=3)
    first = objects_backup.mirror_key(store, item, make_key())
    assert first == objects_backup.mirror_key(store, item, make_key())
    assert first.startswith(objects_backup.data_prefix(store)) and "a.pdf" not in first
    changed = objects_backup.SourceObject(key="org/a.pdf", etag="e2", size=3)
    assert objects_backup.mirror_key(store, changed, make_key()) != first
    assert objects_backup.mirror_key(store, item, make_key(OTHER_KEY_BYTES)) != first


def test_rotation_without_the_old_key_prunes_the_old_copies(tmp_path: Path) -> None:
    store = make_store()
    source = source_bucket({"org/a.pdf": b"A", "org/b.pdf": b"B"})
    _mirror(store, source, tmp_path / "o")
    old_copies = set(_data_keys(store.client))
    _, stats = _mirror(store, source, tmp_path / "o", key=make_key(OTHER_KEY_BYTES))
    assert (stats.copied, stats.pruned, stats.prune_failed) == (2, 2, 0)
    assert not old_copies & set(_data_keys(store.client))
    out = tmp_path / "restored"
    restore_ops.restore_objects(store, [make_key(OTHER_KEY_BYTES)], object_key=None, out_dir=out)
    assert (out / "org" / "a.pdf").read_bytes() == b"A"


def test_prune_keeps_recent_unknown_and_undeletable_copies(tmp_path: Path) -> None:
    backup = FakeS3()
    store = make_store(backup)
    source = source_bucket({"org/a.pdf": b"A", "org/b.pdf": b"B"})
    _mirror(store, source, tmp_path / "o")
    prefix = objects_backup.data_prefix(store)
    recent = f"{prefix}concurrent/copy.rbk"
    unknown = f"{prefix}unknown/copy.rbk"
    for name in (recent, unknown):
        backup.objects[(store.bucket, name)] = b"x"
    backup.modified[(store.bucket, recent)] = datetime.now(UTC) + timedelta(hours=1)
    backup.modified[(store.bucket, unknown)] = None  # type: ignore[assignment]

    del source.objects[("documents", "org/b.pdf")]
    backup.fail_on.add("delete_object")
    marker, stats = _mirror(store, source, tmp_path / "o")
    assert (stats.removed, stats.pruned, stats.prune_failed) == (1, 0, 1)
    assert marker.kind == "objects"

    backup.fail_on.clear()
    _, stats = _mirror(store, source, tmp_path / "o")
    assert (stats.pruned, stats.prune_failed) == (1, 0)
    assert recent in backup.keys() and unknown in backup.keys()


def test_naive_last_modified_is_read_as_utc() -> None:
    before = datetime(2026, 11, 28, 3, 0, tzinfo=UTC)
    item = {"LastModified": datetime(2026, 11, 28, 2, 0)}
    assert objects_backup._modified_before(item, before) is True
    assert objects_backup._modified_before({"LastModified": "x"}, before) is False


def test_empty_listing_after_rotation_prunes_nothing(tmp_path: Path) -> None:
    store = make_store()
    source = source_bucket({"org/a.pdf": b"A"})
    _mirror(store, source, tmp_path / "o")
    source.objects.clear()
    # The previous manifest cannot be read with the new key, so the empty-source guard
    # cannot fire; the empty manifest must still leave every copy in place.
    _, stats = _mirror(store, source, tmp_path / "o", key=make_key(OTHER_KEY_BYTES))
    assert (stats.total, stats.pruned) == (0, 0)
    assert len(_data_keys(store.client)) == 1
