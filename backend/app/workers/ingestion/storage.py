"""Object storage helpers for ingestion and deletion (R06-01; streamed reads R06-02)."""

from __future__ import annotations

import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from botocore.exceptions import ClientError  # type: ignore[import-untyped]

from app.clients import minio_client as minio_module
from app.core.config import settings
from app.workers.base_task import PermanentTaskError, TransientTaskError


def _open_object_body(*, bucket: str, object_key: str) -> Any:
    minio = minio_module.get_minio_client()
    if minio is None:
        raise TransientTaskError("Object storage is unavailable")

    try:
        response = minio.get_object(Bucket=bucket, Key=object_key)
    except ClientError as exc:
        error_code = str(exc.response.get("Error", {}).get("Code", ""))
        if error_code in {"NoSuchKey", "404", "NotFound"}:
            raise PermanentTaskError("Stored file was not found in object storage") from exc
        raise TransientTaskError("Object storage read failed") from exc
    except Exception as exc:
        raise TransientTaskError("Object storage read failed") from exc

    body = response.get("Body")
    if body is None:
        raise TransientTaskError("Object storage response body is missing")
    return body


def _close(body: Any) -> None:
    close_method = getattr(body, "close", None)
    if callable(close_method):
        close_method()


def _iter_body(body: Any) -> Iterator[bytes]:
    """Sized reads only (R06-02): ``read()`` without a size would load the whole object."""
    size = settings.ingest_download_chunk_bytes
    try:
        while True:
            try:
                data = body.read(size)
            except Exception as exc:
                raise TransientTaskError("Object storage read failed") from exc
            if not isinstance(data, bytes):
                raise TransientTaskError("Object storage returned invalid payload")
            if not data:
                return
            yield data
    finally:
        _close(body)


def _read_object_bytes(*, bucket: str, object_key: str) -> bytes:
    """The whole object in memory; kept for facade callers (the extract stage streams)."""
    body = _open_object_body(bucket=bucket, object_key=object_key)
    return b"".join(_iter_body(body))


@contextmanager
def download_to_tempfile(bucket: str, key: str) -> Iterator[Path]:
    """Stream the object to a temporary file under ``INGEST_TEMP_DIR`` (R06-02).

    The file is removed when the block exits, on success and on failure. Memory stays at
    one ``INGEST_DOWNLOAD_CHUNK_BYTES`` read whatever the object size.
    """
    body = _open_object_body(bucket=bucket, object_key=key)
    try:
        handle = tempfile.NamedTemporaryFile(
            prefix="rudix-ingest-", dir=settings.ingest_temp_dir, delete=False
        )
    except OSError as exc:
        _close(body)
        raise TransientTaskError("Ingestion temporary file could not be created") from exc
    path = Path(handle.name)
    try:
        with handle:
            for data in _iter_body(body):
                try:
                    handle.write(data)
                except OSError as exc:
                    raise TransientTaskError("Ingestion temporary file write failed") from exc
        yield path
    finally:
        path.unlink(missing_ok=True)


def _object_key_prefix(object_key: str) -> str:
    normalized = object_key.strip()
    if not normalized:
        return normalized
    stem, separator, suffix = normalized.rpartition(".")
    if separator and suffix and "/" not in suffix:
        return stem
    return normalized


def _delete_objects_by_prefix(*, bucket: str, prefix: str) -> int:
    minio = minio_module.get_minio_client()
    if minio is None:
        raise TransientTaskError("Object storage is unavailable")

    deleted_count = 0
    continuation_token: str | None = None
    while True:
        list_kwargs: dict[str, Any] = {"Bucket": bucket, "Prefix": prefix}
        if continuation_token:
            list_kwargs["ContinuationToken"] = continuation_token
        try:
            response = minio.list_objects_v2(**list_kwargs)
        except Exception as exc:
            raise TransientTaskError("Object storage listing failed") from exc

        contents = response.get("Contents", [])
        for item in contents:
            key = item.get("Key")
            if not isinstance(key, str) or not key:
                continue
            try:
                minio.delete_object(Bucket=bucket, Key=key)
            except ClientError as exc:
                error_code = str(exc.response.get("Error", {}).get("Code", ""))
                if error_code in {"NoSuchKey", "404", "NotFound"}:
                    continue
                raise TransientTaskError("Object storage delete failed") from exc
            except Exception as exc:
                raise TransientTaskError("Object storage delete failed") from exc
            deleted_count += 1

        if not response.get("IsTruncated"):
            break
        next_token = response.get("NextContinuationToken")
        if not isinstance(next_token, str) or not next_token:
            break
        continuation_token = next_token

    return deleted_count
