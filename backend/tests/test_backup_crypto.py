"""RUDIXBK1 streaming AES-256-GCM format and key handling (R08-06)."""

from __future__ import annotations

import base64
import io
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
import structlog
from backup_support import KEY_BYTES, OTHER_KEY_BYTES, FakeS3, make_key, make_store

from app.ops.backup import crypto
from app.ops.backup.crypto import (
    HEADER_BYTES,
    TAG_BYTES,
    BackupFormatError,
    BackupIntegrityError,
    BackupKey,
    BackupKeyError,
    BackupWrongKeyError,
    decrypt_file,
    decrypt_stream,
    encrypt_file,
    encrypt_stream,
    generate_key_text,
    load_key,
    sha256_file,
)
from app.ops.backup.postgres import backup_postgres

CHUNK = 16


def _encrypt(data: bytes, key: BackupKey | None = None, chunk_size: int = CHUNK) -> bytes:
    out = io.BytesIO()
    encrypt_stream(io.BytesIO(data), out, key or make_key(), chunk_size=chunk_size)
    return out.getvalue()


def _decrypt(blob: bytes, *keys: BackupKey) -> bytes:
    out = io.BytesIO()
    decrypt_stream(io.BytesIO(blob), out, list(keys) or [make_key()])
    return out.getvalue()


class _Trickle(io.RawIOBase):
    """Returns at most 5 bytes per read, like a socket."""

    def __init__(self, data: bytes) -> None:
        self._buffer = io.BytesIO(data)

    def readable(self) -> bool:
        return True

    def read(self, size: int = -1) -> bytes:
        return self._buffer.read(min(5, size if size >= 0 else 5))


@pytest.mark.parametrize("size", [0, 1, CHUNK - 1, CHUNK, CHUNK + 1, 3 * CHUNK, 3 * CHUNK + 7])
def test_round_trip(size: int) -> None:
    data = bytes((index * 7) % 251 for index in range(size))
    blob = _encrypt(data)
    full, rest = divmod(size, CHUNK)
    assert len(blob) == HEADER_BYTES + full * (CHUNK + TAG_BYTES) + rest + TAG_BYTES
    assert _decrypt(blob) == data


def test_result_reports_sizes_and_ciphertext_hash() -> None:
    out = io.BytesIO()
    result = encrypt_stream(io.BytesIO(b"x" * 40), out, make_key(), chunk_size=CHUNK)
    assert result.plaintext_bytes == 40
    assert result.ciphertext_bytes == len(out.getvalue())
    decrypted = io.BytesIO()
    check = decrypt_stream(io.BytesIO(out.getvalue()), decrypted, [make_key()])
    assert check.sha256 == result.sha256 and check.plaintext_bytes == 40
    assert check.key_id == make_key().key_id_hex


def test_short_reads_are_handled() -> None:
    data = b"abcdefghij" * 9
    blob = _encrypt(data)
    out = io.BytesIO()
    encrypt_stream(_Trickle(data), out, make_key(), chunk_size=CHUNK)  # type: ignore[arg-type]
    assert _decrypt(out.getvalue()) == data
    assert _decrypt(blob) == data


def test_empty_input_still_has_an_authenticated_final_chunk() -> None:
    blob = _encrypt(b"")
    assert len(blob) == HEADER_BYTES + TAG_BYTES
    assert _decrypt(blob) == b""
    with pytest.raises(BackupIntegrityError):
        _decrypt(blob[:HEADER_BYTES])


def test_fresh_nonce_per_file() -> None:
    assert _encrypt(b"same data") != _encrypt(b"same data")


@pytest.mark.parametrize("offset", range(HEADER_BYTES, HEADER_BYTES + CHUNK + TAG_BYTES))
def test_tampering_with_a_chunk_fails(offset: int) -> None:
    blob = bytearray(_encrypt(b"y" * (2 * CHUNK + 3)))
    blob[offset] ^= 0x01
    with pytest.raises(BackupIntegrityError):
        _decrypt(bytes(blob))


@pytest.mark.parametrize(
    ("offset", "error"),
    [
        (0, BackupFormatError),  # magic
        (8, BackupFormatError),  # version
        (12, BackupIntegrityError),  # chunk size (still in range: bound by the AAD)
        (13, BackupWrongKeyError),  # key id
        (HEADER_BYTES - 1, BackupIntegrityError),  # base nonce
    ],
)
def test_tampering_with_the_header_fails(offset: int, error: type[Exception]) -> None:
    blob = bytearray(_encrypt(b"z" * (2 * CHUNK)))
    blob[offset] ^= 0x01
    with pytest.raises(error):
        _decrypt(bytes(blob))


def test_reordered_chunks_fail() -> None:
    blob = _encrypt(bytes(range(3 * CHUNK)))
    sealed = CHUNK + TAG_BYTES
    first = blob[HEADER_BYTES : HEADER_BYTES + sealed]
    second = blob[HEADER_BYTES + sealed : HEADER_BYTES + 2 * sealed]
    swapped = blob[:HEADER_BYTES] + second + first + blob[HEADER_BYTES + 2 * sealed :]
    with pytest.raises(BackupIntegrityError):
        _decrypt(swapped)


@pytest.mark.parametrize("cut", ["final_chunk", "inside_chunk", "inside_header", "tag_only"])
def test_truncation_fails(cut: str) -> None:
    blob = _encrypt(bytes(range(2 * CHUNK)))  # two full chunks + an empty final chunk
    sealed = CHUNK + TAG_BYTES
    truncated = {
        "final_chunk": blob[: HEADER_BYTES + 2 * sealed],
        "inside_chunk": blob[: HEADER_BYTES + sealed + 5],
        "inside_header": blob[: HEADER_BYTES - 3],
        "tag_only": blob[: HEADER_BYTES + 7],
    }[cut]
    with pytest.raises((BackupIntegrityError, BackupFormatError)):
        _decrypt(truncated)


def test_trailing_data_fails() -> None:
    with pytest.raises(BackupIntegrityError):
        _decrypt(_encrypt(b"abc") + b"\x00")


def test_wrong_key_fails_and_the_matching_key_is_selected() -> None:
    old, new = make_key(KEY_BYTES), make_key(OTHER_KEY_BYTES)
    blob = _encrypt(b"rotated", key=old)
    with pytest.raises(BackupWrongKeyError):
        _decrypt(blob, new)
    assert _decrypt(blob, new, old) == b"rotated"


def test_a_key_with_a_forged_id_fails_authentication() -> None:
    forged = make_key(OTHER_KEY_BYTES)
    forged.key_id = make_key().key_id
    with pytest.raises(BackupIntegrityError):
        _decrypt(_encrypt(b"secret"), forged)


def test_not_a_backup_file_and_bad_chunk_sizes() -> None:
    with pytest.raises(BackupFormatError):
        _decrypt(b"PGDMP" + b"\x00" * 64)
    with pytest.raises(BackupFormatError):
        encrypt_stream(io.BytesIO(b""), io.BytesIO(), make_key(), chunk_size=0)
    blob = bytearray(_encrypt(b"abc"))
    blob[9:13] = (0).to_bytes(4, "big")
    with pytest.raises(BackupFormatError):
        _decrypt(bytes(blob))
    blob[8] = 2
    with pytest.raises(BackupFormatError, match="version 2"):
        _decrypt(bytes(blob))


def test_file_helpers_keep_nothing_on_failure(tmp_path: Path) -> None:
    source = tmp_path / "plain.bin"
    source.write_bytes(b"q" * 100)
    encrypted = tmp_path / "plain.bin.rbk"
    result = encrypt_file(source, encrypted, make_key(), chunk_size=CHUNK)
    assert encrypted.stat().st_mode & 0o777 == 0o600
    assert sha256_file(encrypted) == result.sha256
    restored = tmp_path / "restored.bin"
    decrypt_file(encrypted, restored, [make_key()])
    assert restored.read_bytes() == b"q" * 100
    damaged = bytearray(encrypted.read_bytes())
    damaged[-1] ^= 0x01
    encrypted.write_bytes(bytes(damaged))
    target = tmp_path / "damaged.bin"
    with pytest.raises(BackupIntegrityError):
        decrypt_file(encrypted, target, [make_key()])
    assert not target.exists() and not (tmp_path / "damaged.bin.partial").exists()


def test_load_key(tmp_path: Path) -> None:
    path = tmp_path / "key"
    text = generate_key_text()
    path.write_text(text + "\n")
    key = load_key(path)
    assert key.key_id == BackupKey(base64.b64decode(text)).key_id
    with pytest.raises(BackupKeyError, match="not found"):
        load_key(tmp_path / "missing")
    path.write_text("not base64 !!")
    with pytest.raises(BackupKeyError, match="not valid base64") as excinfo:
        load_key(path)
    assert "not base64 !!" not in str(excinfo.value)
    short = base64.b64encode(b"short").decode()
    path.write_text(short)
    with pytest.raises(BackupKeyError, match="32 bytes") as excinfo:
        load_key(path)
    assert short not in str(excinfo.value)
    with pytest.raises(BackupKeyError):
        BackupKey(b"short")
    with pytest.raises(BackupKeyError, match="unreadable"):
        load_key(tmp_path)


def test_key_material_never_in_repr() -> None:
    key = make_key()
    for text in (repr(key), str(key), f"{key}"):
        assert KEY_BYTES.hex() not in text
        assert base64.b64encode(KEY_BYTES).decode() not in text
        assert key.key_id_hex in text


def test_key_absent_from_logs_and_markers(tmp_path: Path) -> None:
    client = FakeS3()
    store = make_store(client)
    work = tmp_path / "work"
    work.mkdir()
    (work / "postgres.dump").write_bytes(b"PGDMP" + b"\x01" * 50)
    with structlog.testing.capture_logs() as logs:
        marker = backup_postgres(
            store, make_key(), work_dir=work, now=lambda: datetime(2026, 11, 28, tzinfo=UTC)
        )
    forbidden = [
        KEY_BYTES.hex(),
        base64.b64encode(KEY_BYTES).decode(),
        make_key().key_id_hex,
        str(tmp_path),
    ]
    marker_text = client.objects[("rudix-backups", "rudix/postgres/latest.json")].decode()
    dumped_logs = json.dumps(logs, default=str)
    for value in forbidden:
        assert value not in marker_text
        assert value not in dumped_logs
    assert json.loads(marker_text)["object_key"] == marker.object_key
    assert crypto.MAGIC not in client.objects[("rudix-backups", "rudix/postgres/latest.json")]


class _EofThenData(io.RawIOBase):
    """Signals end of stream once, then has more bytes (a pipe that was appended to)."""

    def __init__(self, data: bytes, extra: bytes) -> None:
        self._data, self._extra, self._eof_sent = io.BytesIO(data), extra, False

    def readable(self) -> bool:
        return True

    def read(self, size: int = -1) -> bytes:
        chunk = self._data.read(size)
        if chunk:
            return chunk
        if not self._eof_sent:
            self._eof_sent = True
            return b""
        extra, self._extra = self._extra, b""
        return extra


def test_data_after_a_signalled_end_of_stream_fails() -> None:
    stream = _EofThenData(_encrypt(b"abc"), b"\x00")
    with pytest.raises(BackupIntegrityError, match="after the final chunk"):
        decrypt_stream(stream, io.BytesIO(), [make_key()])  # type: ignore[arg-type]
