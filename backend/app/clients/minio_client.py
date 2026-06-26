from typing import Any

from botocore.exceptions import ClientError  # type: ignore[import-untyped]

from app.clients.factory import create_minio_client
from app.core.config import settings
from app.core.logging import get_logger

minio_client: Any | None = None
logger = get_logger("clients.minio")


def init_minio() -> None:
    global minio_client
    minio_client = create_minio_client(settings)
    try:
        if settings.minio_bootstrap_bucket:
            ensure_minio_bucket()
        else:
            minio_client.head_bucket(Bucket=settings.minio_bucket)
        logger.info(
            "minio.init.success",
            endpoint=str(settings.minio_endpoint),
            bucket=settings.minio_bucket,
            bootstrap_bucket=settings.minio_bootstrap_bucket,
        )
    except Exception as exc:
        logger.warning(
            "minio.init.unavailable",
            endpoint=str(settings.minio_endpoint),
            bucket=settings.minio_bucket,
            error=exc.__class__.__name__,
            detail=str(exc),
        )
        close_minio()


def close_minio() -> None:
    global minio_client
    if minio_client is not None:
        close_method = getattr(minio_client, "close", None)
        if callable(close_method):
            close_method()
        minio_client = None
        logger.info("minio.close")


def get_minio_client(*, lazy_init: bool = True) -> Any | None:
    """Return active MinIO client, optionally attempting a lazy initialization."""
    if minio_client is not None:
        return minio_client
    if not lazy_init:
        return None
    try:
        init_minio()
    except Exception as exc:
        logger.warning(
            "minio.lazy_init.failed",
            endpoint=str(settings.minio_endpoint),
            bucket=settings.minio_bucket,
            error=exc.__class__.__name__,
        )
        return None
    return minio_client


def check_minio_health() -> bool:
    if minio_client is None:
        return False
    try:
        minio_client.head_bucket(Bucket=settings.minio_bucket)
        return True
    except ClientError:
        return False
    except Exception:
        return False


def ensure_minio_bucket() -> None:
    if minio_client is None:
        raise RuntimeError("MinIO client is not initialized")

    try:
        minio_client.head_bucket(Bucket=settings.minio_bucket)
        logger.info("minio.bucket.exists", bucket=settings.minio_bucket)
        return
    except ClientError as exc:
        error_code = str(exc.response.get("Error", {}).get("Code", ""))
        if error_code not in {"404", "NoSuchBucket", "NotFound"}:
            logger.error(
                "minio.bucket.ensure.failed",
                bucket=settings.minio_bucket,
                error_code=error_code,
                error=exc.__class__.__name__,
                exc_info=exc,
            )
            raise

    minio_client.create_bucket(Bucket=settings.minio_bucket)
    logger.info("minio.bucket.created", bucket=settings.minio_bucket)
