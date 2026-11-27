"""Object storage helpers for ingestion and deletion (moved from document_tasks, R06-01)."""

from __future__ import annotations

from typing import Any

from botocore.exceptions import ClientError  # type: ignore[import-untyped]

from app.clients import minio_client as minio_module
from app.workers.base_task import PermanentTaskError, TransientTaskError


def _read_object_bytes(*, bucket: str, object_key: str) -> bytes:
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
    try:
        data = body.read()
    except Exception as exc:
        raise TransientTaskError("Object storage read failed") from exc
    finally:
        close_method = getattr(body, "close", None)
        if callable(close_method):
            close_method()
    if not isinstance(data, bytes):
        raise TransientTaskError("Object storage returned invalid payload")
    return data


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
