"""Qdrant collection tuning settings (R06-07).

Defaults are ``None`` (server defaults) and parent text stays on the payload, so recall
cannot change unless an operator sets a value; values reach ``create_collection`` only for
a new collection, and a difference on an existing collection is logged, never applied.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from qdrant_client.http.models import (
    Distance,
    HnswConfigDiff,
    ScalarQuantization,
    ScalarType,
)

from app.clients import qdrant_client as qdrant_module
from app.clients import qdrant_tuning
from app.core.config import QdrantDistance, Settings, settings

TUNING = (
    "qdrant_hnsw_m",
    "qdrant_hnsw_ef_construct",
    "qdrant_hnsw_payload_m",
    "qdrant_hnsw_on_disk",
    "qdrant_vectors_on_disk",
    "qdrant_on_disk_payload",
    "qdrant_scalar_quantization",
    "qdrant_quantization_quantile",
    "qdrant_quantization_always_ram",
    "qdrant_shard_number",
    "qdrant_replication_factor",
    "qdrant_write_consistency_factor",
)


def test_recall_affecting_defaults_are_unchanged() -> None:
    fields = Settings.model_fields
    assert all(fields[name].default is None for name in TUNING)
    assert fields["qdrant_store_parent_text"].default is True
    assert fields["embedding_max_concurrent_batches"].default == 1
    assert fields["qdrant_search_timeout_seconds"].default is None


@pytest.fixture
def cfg(monkeypatch: pytest.MonkeyPatch) -> Settings:
    """A private settings copy used by ``qdrant_client`` (other tests reload modules)."""
    copy = settings.model_copy()
    copy.qdrant_distance = QdrantDistance.cosine
    monkeypatch.setattr(qdrant_module, "settings", copy)
    return copy


def _configure(config: Settings, **values: Any) -> None:
    for name in TUNING:
        setattr(config, name, values.get(name))


def test_create_collection_kwargs_map_to_client_models(cfg: Settings) -> None:
    _configure(
        cfg,
        qdrant_hnsw_m=0,
        qdrant_hnsw_payload_m=16,
        qdrant_hnsw_ef_construct=200,
        qdrant_hnsw_on_disk=True,
        qdrant_scalar_quantization=True,
        qdrant_quantization_quantile=0.99,
        qdrant_quantization_always_ram=True,
        qdrant_on_disk_payload=True,
        qdrant_shard_number=2,
        qdrant_replication_factor=2,
        qdrant_write_consistency_factor=2,
        qdrant_vectors_on_disk=True,
    )
    kwargs = qdrant_tuning.create_collection_kwargs(cfg)
    assert kwargs["hnsw_config"] == HnswConfigDiff(
        m=0, payload_m=16, ef_construct=200, on_disk=True
    )
    quantization = kwargs["quantization_config"]
    assert isinstance(quantization, ScalarQuantization)
    assert quantization.scalar.type == ScalarType.INT8
    assert quantization.scalar.quantile == 0.99 and quantization.scalar.always_ram is True
    assert kwargs["on_disk_payload"] is True
    assert kwargs["shard_number"] == 2 and kwargs["replication_factor"] == 2
    assert kwargs["write_consistency_factor"] == 2
    assert qdrant_tuning.vectors_on_disk(cfg) == {"on_disk": True}


class _Collections:
    """Sync client fake for ``ensure_qdrant_collection``."""

    def __init__(self, *, exists: bool, info: Any = None) -> None:
        self.exists, self.info = exists, info
        self.created: list[dict[str, Any]] = []
        self.indexes: list[str] = []

    def collection_exists(self, _: str) -> bool:
        return self.exists

    def create_collection(self, **kwargs: Any) -> None:
        self.created.append(kwargs)

    def get_collection(self, _: str) -> Any:
        return self.info

    def create_payload_index(self, *, field_name: str, **_: Any) -> None:
        self.indexes.append(field_name)


def _info(**hnsw: Any) -> Any:
    vectors = SimpleNamespace(size=settings.qdrant_vector_size, distance=Distance.COSINE)
    return SimpleNamespace(
        config=SimpleNamespace(
            params=SimpleNamespace(
                vectors=vectors, shard_number=1, replication_factor=1, on_disk_payload=True
            ),
            hnsw_config=SimpleNamespace(
                m=hnsw.get("m", 16), ef_construct=100, payload_m=None, on_disk=False
            ),
            quantization_config=None,
        )
    )


def test_tuning_reaches_create_collection_only_for_a_new_collection(
    monkeypatch: pytest.MonkeyPatch, cfg: Settings
) -> None:
    _configure(cfg, qdrant_hnsw_m=32, qdrant_on_disk_payload=False)
    new = _Collections(exists=False)
    monkeypatch.setattr(qdrant_module, "qdrant_client", new)
    qdrant_module.ensure_qdrant_collection()
    (created,) = new.created
    assert created["hnsw_config"] == HnswConfigDiff(m=32)
    assert created["on_disk_payload"] is False
    assert "chunk_hash" in new.indexes

    existing = _Collections(exists=True, info=_info(m=16))
    warnings: list[dict[str, Any]] = []
    monkeypatch.setattr(
        qdrant_tuning.logger, "warning", lambda event, **fields: warnings.append(fields)
    )
    monkeypatch.setattr(qdrant_module, "qdrant_client", existing)
    qdrant_module.ensure_qdrant_collection()
    assert existing.created == []
    (warning,) = warnings
    assert warning["differences"]["qdrant_hnsw_m"] == {"configured": 32, "collection": 16}
    assert warning["differences"]["qdrant_on_disk_payload"] == {
        "configured": False,
        "collection": True,
    }


def test_no_drift_warning_without_configured_values(cfg: Settings) -> None:
    _configure(cfg)
    assert qdrant_tuning.tuning_differences(cfg, _info()) == {}
    _configure(cfg, qdrant_hnsw_m=16, qdrant_scalar_quantization=False)
    assert qdrant_tuning.tuning_differences(cfg, _info(m=16)) == {}


def test_default_collection_has_no_tuning_arguments(
    monkeypatch: pytest.MonkeyPatch, cfg: Settings
) -> None:
    _configure(cfg)
    client = _Collections(exists=False)
    monkeypatch.setattr(qdrant_module, "qdrant_client", client)
    qdrant_module.ensure_qdrant_collection()
    (created,) = client.created
    assert set(created) == {"collection_name", "vectors_config"}
    assert created["vectors_config"].on_disk is None


def test_write_consistency_factor_drift_is_reported(cfg: Settings) -> None:
    """R08-05: a configured write consistency factor that differs from the collection."""
    _configure(cfg, qdrant_write_consistency_factor=2)
    info = _info()
    info.config.params.write_consistency_factor = 1
    assert qdrant_tuning.tuning_differences(cfg, info) == {
        "qdrant_write_consistency_factor": {"configured": 2, "collection": 1}
    }
    assert "write_consistency_factor" not in qdrant_tuning.create_collection_kwargs(_unset(cfg))


def _unset(config: Settings) -> Settings:
    _configure(config)
    return config
