from qdrant_client import QdrantClient
from qdrant_client.http.models import VectorParams

from app.clients.factory import create_qdrant_client, qdrant_distance_to_model
from app.core.config import settings
from app.core.logging import get_logger

qdrant_client: QdrantClient | None = None
logger = get_logger("clients.qdrant")


def init_qdrant() -> None:
    global qdrant_client
    qdrant_client = create_qdrant_client(settings)
    try:
        qdrant_client.get_collections()
        if settings.qdrant_bootstrap_collection:
            ensure_qdrant_collection()
        logger.info(
            "qdrant.init.success",
            url=str(settings.qdrant_url),
            collection=settings.qdrant_collection,
            vector_size=settings.qdrant_vector_size,
            distance=settings.qdrant_distance.value,
            bootstrap_collection=settings.qdrant_bootstrap_collection,
        )
    except Exception as exc:
        logger.error(
            "qdrant.init.failed",
            url=str(settings.qdrant_url),
            collection=settings.qdrant_collection,
            error=exc.__class__.__name__,
            exc_info=exc,
        )
        close_qdrant()
        raise


def close_qdrant() -> None:
    if qdrant_client is not None:
        qdrant_client.close()
        logger.info("qdrant.close")


def check_qdrant_health() -> bool:
    if qdrant_client is None:
        return False
    try:
        qdrant_client.get_collections()
        return True
    except Exception:
        return False


def _normalize_distance(value: object) -> str:
    if value is None:
        return ""
    text = str(value).lower()
    if "." in text:
        text = text.split(".")[-1]
    return text


def ensure_qdrant_collection() -> None:
    if qdrant_client is None:
        raise RuntimeError("Qdrant client is not initialized")

    exists = qdrant_client.collection_exists(settings.qdrant_collection)
    if not exists:
        qdrant_client.create_collection(
            collection_name=settings.qdrant_collection,
            vectors_config=VectorParams(
                size=settings.qdrant_vector_size,
                distance=qdrant_distance_to_model(settings.qdrant_distance),
            ),
        )
        logger.info(
            "qdrant.collection.created",
            collection=settings.qdrant_collection,
            vector_size=settings.qdrant_vector_size,
            distance=settings.qdrant_distance.value,
        )
        return

    collection_info = qdrant_client.get_collection(settings.qdrant_collection)
    vectors = getattr(collection_info.config.params, "vectors", None)
    existing_size = getattr(vectors, "size", None)
    existing_distance = _normalize_distance(getattr(vectors, "distance", None))
    expected_distance = settings.qdrant_distance.value

    if existing_size != settings.qdrant_vector_size or existing_distance != expected_distance:
        logger.error(
            "qdrant.collection.mismatch",
            collection=settings.qdrant_collection,
            expected_vector_size=settings.qdrant_vector_size,
            actual_vector_size=existing_size,
            expected_distance=expected_distance,
            actual_distance=existing_distance or None,
        )
        raise RuntimeError(
            "Existing Qdrant collection does not match configured vector size/distance "
            f"for collection '{settings.qdrant_collection}'."
        )

    logger.info(
        "qdrant.collection.exists",
        collection=settings.qdrant_collection,
        vector_size=settings.qdrant_vector_size,
        distance=expected_distance,
    )
