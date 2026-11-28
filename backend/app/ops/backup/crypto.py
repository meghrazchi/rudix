"""Streaming AES-256-GCM encryption for backup artifacts (format ``RUDIXBK1``, R08-06).

Layout::

    header  = magic "RUDIXBK1" (8) | version (1) | chunk size (4, big endian)
              | key id (8) | base nonce (12, random per file)
    chunk_i = AES-256-GCM(key, nonce_i, plaintext_i, aad_i): ciphertext || 16-byte tag

- ``nonce_i`` is the base nonce with its last 8 bytes XORed with the chunk counter ``i``,
  so no nonce repeats within a file and a fresh random base nonce is drawn per file.
- ``aad_i`` = header || ``i`` (8 bytes) || final flag (1 byte). Every chunk is bound to the
  header, to its position, and to whether it is the last one, so reordering, dropping,
  truncating, or editing any chunk or the header fails authentication.
- Every chunk but the last holds exactly ``chunk size`` plaintext bytes; the last holds
  fewer (possibly zero), so a file always ends with an authenticated final chunk and a
  truncation on a chunk boundary is detected too.
- The key id is the first 8 bytes of SHA-256 over a fixed label and the key. It lets a
  restore pick the right key after rotation (old keys are kept for restore); it reveals
  nothing about a 256-bit random key.

The key comes from a file holding the base64 of 32 random bytes. It is never logged, never
part of an exception message, and never written to a marker.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import os
import struct
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Final

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAGIC: Final[bytes] = b"RUDIXBK1"
FORMAT_VERSION: Final[int] = 1
DEFAULT_CHUNK_SIZE: Final[int] = 4 * 1024 * 1024
MAX_CHUNK_SIZE: Final[int] = 64 * 1024 * 1024
KEY_BYTES: Final[int] = 32
NONCE_BYTES: Final[int] = 12
TAG_BYTES: Final[int] = 16
KEY_ID_BYTES: Final[int] = 8
_HEADER = struct.Struct(">8sBI8s12s")
HEADER_BYTES: Final[int] = _HEADER.size
_KEY_ID_LABEL: Final[bytes] = b"rudix-backup-key-id-v1"
_COPY_BYTES: Final[int] = 1024 * 1024


class BackupCryptoError(Exception):
    """Base error; messages never contain key material or plaintext."""


class BackupKeyError(BackupCryptoError):
    """The key file is missing, unreadable, or not base64 of 32 bytes."""


class BackupFormatError(BackupCryptoError):
    """Not a RUDIXBK1 file, unsupported version, or malformed header."""


class BackupWrongKeyError(BackupCryptoError):
    """No configured key matches the key id in the header."""


class BackupIntegrityError(BackupCryptoError):
    """Authentication failed: tampered, reordered, or truncated ciphertext."""


class BackupKey:
    """A 256-bit backup key. ``repr`` and ``str`` never show the material."""

    __slots__ = ("_material", "key_id")

    def __init__(self, material: bytes) -> None:
        if len(material) != KEY_BYTES:
            raise BackupKeyError(f"backup key must be {KEY_BYTES} bytes")
        self._material = bytes(material)
        self.key_id = hashlib.sha256(_KEY_ID_LABEL + self._material).digest()[:KEY_ID_BYTES]

    @property
    def key_id_hex(self) -> str:
        return self.key_id.hex()

    def aead(self) -> AESGCM:
        return AESGCM(self._material)

    def __repr__(self) -> str:
        return f"BackupKey(key_id={self.key_id_hex})"

    __str__ = __repr__


def load_key(path: Path) -> BackupKey:
    """Read a key file (base64 of 32 bytes). Errors name the problem, never the content."""
    try:
        raw = path.read_bytes()
    except FileNotFoundError as exc:
        raise BackupKeyError("backup key file not found") from exc
    except OSError as exc:
        raise BackupKeyError(f"backup key file unreadable ({type(exc).__name__})") from exc
    try:
        material = base64.b64decode(raw.strip(), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise BackupKeyError("backup key file is not valid base64") from exc
    if len(material) != KEY_BYTES:
        raise BackupKeyError(f"backup key file must hold base64 of {KEY_BYTES} bytes")
    return BackupKey(material)


def generate_key_text() -> str:
    """Base64 of 32 random bytes, the key file format (``openssl rand -base64 32``)."""
    return base64.b64encode(os.urandom(KEY_BYTES)).decode("ascii")


@dataclass(frozen=True, slots=True)
class EncryptResult:
    plaintext_bytes: int
    ciphertext_bytes: int
    sha256: str  # hex digest of the ciphertext (the uploaded object)


@dataclass(frozen=True, slots=True)
class DecryptResult:
    plaintext_bytes: int
    ciphertext_bytes: int
    sha256: str  # hex digest of the ciphertext that was read
    key_id: str


def _nonce(base_nonce: bytes, counter: int) -> bytes:
    prefix, tail = base_nonce[:4], int.from_bytes(base_nonce[4:], "big")
    return prefix + (tail ^ counter).to_bytes(8, "big")


def _aad(header: bytes, counter: int, final: bool) -> bytes:
    return header + counter.to_bytes(8, "big") + (b"\x01" if final else b"\x00")


def _read_exact(src: BinaryIO, size: int) -> bytes:
    """Up to ``size`` bytes; fewer only at end of stream (short reads are retried)."""
    parts: list[bytes] = []
    remaining = size
    while remaining > 0:
        data = src.read(remaining)
        if not data:
            break
        parts.append(data)
        remaining -= len(data)
    return b"".join(parts)


def encrypt_stream(
    src: BinaryIO,
    dst: BinaryIO,
    key: BackupKey,
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> EncryptResult:
    """Encrypt ``src`` into ``dst`` chunk by chunk; memory stays at about one chunk."""
    if not 1 <= chunk_size <= MAX_CHUNK_SIZE:
        raise BackupFormatError("chunk size out of range")
    base_nonce = os.urandom(NONCE_BYTES)
    header = _HEADER.pack(MAGIC, FORMAT_VERSION, chunk_size, key.key_id, base_nonce)
    digest = hashlib.sha256(header)
    dst.write(header)
    written = len(header)
    plaintext_total = 0
    aead = key.aead()
    counter = 0
    while True:
        data = _read_exact(src, chunk_size)
        final = len(data) < chunk_size
        sealed = aead.encrypt(_nonce(base_nonce, counter), data, _aad(header, counter, final))
        dst.write(sealed)
        digest.update(sealed)
        written += len(sealed)
        plaintext_total += len(data)
        counter += 1
        if final:
            break
    return EncryptResult(plaintext_total, written, digest.hexdigest())


def _parse_header(header: bytes) -> tuple[int, bytes, bytes]:
    if len(header) < HEADER_BYTES:
        raise BackupFormatError("file is shorter than the RUDIXBK1 header")
    magic, version, chunk_size, key_id, base_nonce = _HEADER.unpack(header)
    if magic != MAGIC:
        raise BackupFormatError("not a RUDIXBK1 backup file")
    if version != FORMAT_VERSION:
        raise BackupFormatError(f"unsupported backup format version {version}")
    if not 1 <= chunk_size <= MAX_CHUNK_SIZE:
        raise BackupFormatError("chunk size out of range")
    return chunk_size, key_id, base_nonce


def _select_key(key_id: bytes, keys: Sequence[BackupKey]) -> BackupKey:
    for candidate in keys:
        if hmac.compare_digest(candidate.key_id, key_id):
            return candidate
    raise BackupWrongKeyError(f"no configured backup key matches key id {key_id.hex()}")


def decrypt_stream(src: BinaryIO, dst: BinaryIO, keys: Sequence[BackupKey]) -> DecryptResult:
    """Decrypt ``src`` into ``dst``. Raises before writing any unauthenticated chunk.

    A failure after some chunks leaves those (authenticated) chunks in ``dst``; callers
    write to a temporary file and keep it only on success (``decrypt_file``).
    """
    header = _read_exact(src, HEADER_BYTES)
    chunk_size, key_id, base_nonce = _parse_header(header)
    key = _select_key(key_id, keys)
    aead = key.aead()
    digest = hashlib.sha256(header)
    read_total = len(header)
    plaintext_total = 0
    counter = 0
    sealed_size = chunk_size + TAG_BYTES
    while True:
        sealed = _read_exact(src, sealed_size)
        if len(sealed) < TAG_BYTES:
            raise BackupIntegrityError("backup file is truncated (final chunk missing)")
        final = len(sealed) < sealed_size
        try:
            data = aead.decrypt(_nonce(base_nonce, counter), sealed, _aad(header, counter, final))
        except InvalidTag as exc:
            raise BackupIntegrityError(f"backup chunk {counter} failed authentication") from exc
        dst.write(data)
        digest.update(sealed)
        read_total += len(sealed)
        plaintext_total += len(data)
        counter += 1
        if final:
            break
    if src.read(1):
        raise BackupIntegrityError("unexpected data after the final chunk")
    return DecryptResult(plaintext_total, read_total, digest.hexdigest(), key.key_id_hex)


def encrypt_file(
    src_path: Path, dst_path: Path, key: BackupKey, *, chunk_size: int = DEFAULT_CHUNK_SIZE
) -> EncryptResult:
    """Encrypt one file; ``dst_path`` is created with mode 0600."""
    fd = os.open(dst_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with src_path.open("rb") as src, os.fdopen(fd, "wb") as dst:
        return encrypt_stream(src, dst, key, chunk_size=chunk_size)


def decrypt_file(src_path: Path, dst_path: Path, keys: Sequence[BackupKey]) -> DecryptResult:
    """Decrypt into ``dst_path`` through ``<dst>.partial``; nothing is kept on failure."""
    partial = dst_path.with_name(dst_path.name + ".partial")
    fd = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with src_path.open("rb") as src, os.fdopen(fd, "wb") as dst:
            result = decrypt_stream(src, dst, keys)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    partial.replace(dst_path)
    return result


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(_COPY_BYTES):
            digest.update(block)
    return digest.hexdigest()
