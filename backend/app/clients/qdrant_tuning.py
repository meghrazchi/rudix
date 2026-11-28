"""Qdrant collection tuning (R06-07).

Every setting defaults to ``None``, which leaves the Qdrant server default, and is applied
only when a collection is created; an existing collection is never changed. Startup logs
``qdrant.collection.tuning_differs`` when a configured value differs from the collection.
Fields are those of qdrant-client 1.20 (``HnswConfigDiff``, ``ScalarQuantizationConfig``,
``VectorParams.on_disk``, ``create_collection`` arguments); the server image is not
pinned, so check them against the documentation of the deployed server version.
"""

from __future__ import annotations

from typing import Any

from qdrant_client.http.models import (
    HnswConfigDiff,
    ScalarQuantization,
    ScalarQuantizationConfig,
    ScalarType,
)

from app.core.config import Settings
from app.core.logging import get_logger

logger = get_logger("clients.qdrant")


def _value(config: Settings, name: str) -> Any:
    """A tuning setting; a partial settings object (tests, tools) means unset."""
    return getattr(config, name, None)


def _hnsw_config(config: Settings) -> HnswConfigDiff | None:
    values: dict[str, Any] = {
        "m": _value(config, "qdrant_hnsw_m"),
        "ef_construct": _value(config, "qdrant_hnsw_ef_construct"),
        "payload_m": _value(config, "qdrant_hnsw_payload_m"),
        "on_disk": _value(config, "qdrant_hnsw_on_disk"),
    }
    present = {key: value for key, value in values.items() if value is not None}
    return HnswConfigDiff(**present) if present else None


def _quantization_config(config: Settings) -> ScalarQuantization | None:
    if not _value(config, "qdrant_scalar_quantization"):
        return None
    return ScalarQuantization(
        scalar=ScalarQuantizationConfig(
            type=ScalarType.INT8,
            quantile=_value(config, "qdrant_quantization_quantile"),
            always_ram=_value(config, "qdrant_quantization_always_ram"),
        )
    )


def create_collection_kwargs(config: Settings) -> dict[str, Any]:
    """Extra ``create_collection`` arguments; empty when nothing is configured."""
    kwargs: dict[str, Any] = {}
    hnsw = _hnsw_config(config)
    if hnsw is not None:
        kwargs["hnsw_config"] = hnsw
    quantization = _quantization_config(config)
    if quantization is not None:
        kwargs["quantization_config"] = quantization
    for name, value in (
        ("on_disk_payload", _value(config, "qdrant_on_disk_payload")),
        ("shard_number", _value(config, "qdrant_shard_number")),
        ("replication_factor", _value(config, "qdrant_replication_factor")),
        ("write_consistency_factor", _value(config, "qdrant_write_consistency_factor")),
    ):
        if value is not None:
            kwargs[name] = value
    return kwargs


def vectors_on_disk(config: Settings) -> dict[str, Any]:
    """``VectorParams`` extra arguments (``on_disk``), empty when unset."""
    if _value(config, "qdrant_vectors_on_disk") is None:
        return {}
    return {"on_disk": _value(config, "qdrant_vectors_on_disk")}


def _existing_values(info: Any) -> dict[str, Any]:
    config = getattr(info, "config", None)
    params = getattr(config, "params", None)
    hnsw = getattr(config, "hnsw_config", None)
    quantization = getattr(config, "quantization_config", None)
    scalar = getattr(quantization, "scalar", None)
    vectors = getattr(params, "vectors", None)
    return {
        "qdrant_hnsw_m": getattr(hnsw, "m", None),
        "qdrant_hnsw_ef_construct": getattr(hnsw, "ef_construct", None),
        "qdrant_hnsw_payload_m": getattr(hnsw, "payload_m", None),
        "qdrant_hnsw_on_disk": getattr(hnsw, "on_disk", None),
        "qdrant_vectors_on_disk": getattr(vectors, "on_disk", None),
        "qdrant_on_disk_payload": getattr(params, "on_disk_payload", None),
        "qdrant_scalar_quantization": scalar is not None,
        "qdrant_quantization_quantile": getattr(scalar, "quantile", None),
        "qdrant_quantization_always_ram": getattr(scalar, "always_ram", None),
        "qdrant_shard_number": getattr(params, "shard_number", None),
        "qdrant_replication_factor": getattr(params, "replication_factor", None),
        "qdrant_write_consistency_factor": getattr(params, "write_consistency_factor", None),
    }


def tuning_differences(config: Settings, info: Any) -> dict[str, dict[str, Any]]:
    """Configured (non-None) tuning values that differ from an existing collection."""
    existing = _existing_values(info)
    differences: dict[str, dict[str, Any]] = {}
    for name, actual in existing.items():
        wanted = _value(config, name)
        if wanted is None or wanted == actual:
            continue
        differences[name] = {"configured": wanted, "collection": actual}
    return differences


def warn_on_tuning_drift(config: Settings, info: Any, *, collection: str) -> None:
    differences = tuning_differences(config, info)
    if differences:
        logger.warning(
            "qdrant.collection.tuning_differs",
            collection=collection,
            differences=differences,
            effect="none: tuning applies only when a collection is created",
        )
