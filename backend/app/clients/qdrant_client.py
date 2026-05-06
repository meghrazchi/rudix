from qdrant_client import QdrantClient

from app.core.config import settings

qdrant_client: QdrantClient | None = None


def init_qdrant() -> None:
    global qdrant_client
    qdrant_client = QdrantClient(
        url=settings.qdrant_url,
        api_key=settings.qdrant_api_key.get_secret_value() if settings.qdrant_api_key else None,
        timeout=5,
    )


def close_qdrant() -> None:
    if qdrant_client is not None:
        qdrant_client.close()


def check_qdrant_health() -> bool:
    if qdrant_client is None:
        return False
    try:
        qdrant_client.get_collections()
        return True
    except Exception:
        return False
