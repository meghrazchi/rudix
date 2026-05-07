from botocore.exceptions import ClientError
import boto3

from app.core.config import settings

minio_client = None


def init_minio() -> None:
    global minio_client
    minio_client = boto3.client(
        "s3",
        endpoint_url=str(settings.minio_endpoint),
        aws_access_key_id=settings.minio_access_key,
        aws_secret_access_key=settings.minio_secret_key.get_secret_value(),
    )


def close_minio() -> None:
    return


def check_minio_health() -> bool:
    if minio_client is None:
        return False
    try:
        minio_client.head_bucket(Bucket=settings.minio_bucket)
        return True
    except ClientError:
        return False
