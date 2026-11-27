"""Vector index generations: adoption, registry, verify, swap, rollback, drop (R06-08)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from ingestion_golden_support import (
    IngestionEnv,
    ingestion_env,  # noqa: F401  (fixture)
)
from qdrant_client.http.models import CreateAliasOperation, DeleteAliasOperation
from sqlalchemy import delete
from vector_index_support import (
    ALIAS,
    NEW_MODEL,
    NEW_SIZE,
    OLD_MODEL,
    VectorIndexEnv,
    make_vector_index_env,
)

from app.clients import qdrant_client as qdrant_module
from app.core.config import settings
from app.domains.chat.services.query_embedding_cache import embed_query_cached
from app.domains.chat.services.query_retrieval_service import QueryRetrievalService
from app.domains.documents.services.qdrant_service import QdrantService, resolve_write_targets
from app.domains.vector_index.services import generation_service, lifecycle_service
from app.domains.vector_index.services.generation_service import (
    generation_collection_name,
    model_slug,
    registry,
)
from app.domains.vector_index.services.lifecycle_service import VectorIndexLifecycleError
from app.domains.vector_index.services.startup import reconcile_on_startup
from app.models.vector_index import VectorIndexGenerationDocument


@pytest.fixture
def vi(
    ingestion_env: IngestionEnv,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> Any:
    yield from make_vector_index_env(ingestion_env, monkeypatch)


def _expect_error(vi: VectorIndexEnv, coro: Any, code: str) -> None:
    with pytest.raises(VectorIndexLifecycleError) as excinfo:
        vi.run(coro)
    assert excinfo.value.code == code


def test_model_slug_and_collection_names(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "qdrant_collection", "documents")
    assert model_slug("Embed-New/Large v2") == "embed_new_large_v2"
    assert model_slug("text-embedding-3-small") == "text_embedding_3_small"
    assert len(model_slug("x" * 90)) == 40
    assert model_slug("---") == "model"
    assert generation_collection_name("text-embedding-3-large", 2) == (
        "documents_text_embedding_3_large_v2"
    )


def test_alias_equal_to_collection_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "qdrant_collection_alias", settings.qdrant_collection)
    with pytest.raises(ValueError):
        generation_service.configured_alias()


def test_legacy_mode_reads_and_writes_the_configured_collection(vi: VectorIndexEnv) -> None:
    seeded = vi.seed_indexed("legacy")
    assert vi.points(settings.qdrant_collection, seeded)
    assert resolve_write_targets() == [settings.qdrant_collection]
    assert vi.run(QdrantService().resolve_write_targets()) == [settings.qdrant_collection]
    assert vi.run(generation_service.resolve_active_generation()) is None
    service = QueryRetrievalService()
    assert service.embedding_model == OLD_MODEL
    assert service.qdrant_collection == settings.qdrant_collection
    assert vi.client.alias_calls == []
    assert vi.generations() == {}
    _expect_error(vi, lifecycle_service.adopt(), "legacy_mode")
    _expect_error(vi, lifecycle_service.drop_retired(dry_run=False), "legacy_mode")


def test_adopt_registers_the_legacy_collection_without_copying(vi: VectorIndexEnv) -> None:
    seeded = vi.seed_indexed("before-adopt")
    before = dict(vi.points(settings.qdrant_collection))
    vi.enable_alias()

    row = vi.run(lifecycle_service.adopt())

    assert (row.generation, row.state, row.collection_name) == (
        1,
        "active",
        settings.qdrant_collection,
    )
    assert (row.embedding_model, row.vector_size) == (OLD_MODEL, settings.qdrant_vector_size)
    assert vi.client.aliases == {ALIAS: settings.qdrant_collection}
    assert len(vi.client.alias_calls) == 1
    assert isinstance(vi.client.alias_calls[0][0], CreateAliasOperation)
    assert vi.client.points(settings.qdrant_collection) == before
    assert vi.client.calls["upsert"] == 0 or set(vi.client.collections) == {
        settings.qdrant_collection
    }
    # Idempotent: a second adopt returns generation 1 and makes no alias call.
    assert vi.run(lifecycle_service.adopt()).generation == 1
    assert len(vi.client.alias_calls) == 1
    active = vi.run(generation_service.resolve_active_generation())
    assert active is not None and active.generation == 1
    assert QueryRetrievalService().qdrant_collection == settings.qdrant_collection
    # New ingestion after adoption writes to generation 1 as before.
    other = vi.seed_indexed("after-adopt")
    assert vi.points(settings.qdrant_collection, other)
    assert vi.points(settings.qdrant_collection, seeded)


def test_adopt_refuses_unsafe_states(vi: VectorIndexEnv) -> None:
    vi.enable_alias()
    vi.client.add_collection(ALIAS, size=4)
    _expect_error(vi, lifecycle_service.adopt(), "alias_conflict")
    vi.client.delete_collection(collection_name=ALIAS)
    vi.client.add_collection("elsewhere", size=4)
    vi.client.aliases[ALIAS] = "elsewhere"
    _expect_error(vi, lifecycle_service.adopt(), "alias_points_elsewhere")
    vi.client.aliases.clear()
    vi.client.delete_collection(collection_name=settings.qdrant_collection)
    _expect_error(vi, lifecycle_service.adopt(), "collection_missing")
    _expect_error(vi, lifecycle_service.register_building(), "not_adopted")


def test_register_building_creates_the_collection_and_dual_targets(vi: VectorIndexEnv) -> None:
    row = vi.adopt_and_register()

    name = f"{settings.qdrant_collection}_embed_new_large_v2_v2"
    assert (row.generation, row.state, row.collection_name) == (2, "building", name)
    assert vi.client.vector_configs[name] == (NEW_SIZE, settings.qdrant_distance.value)
    indexed = {field for coll, field in vi.client.__dict__["payload_indexes"] if coll == name}
    assert {"organization_id", "document_id", "index_version", "chunk_hash"} <= indexed
    targets = vi.run(generation_service.resolve_write_targets())
    assert [t.collection_name for t in targets] == [settings.qdrant_collection, name]
    assert [t.embedding_model for t in targets] == [OLD_MODEL, NEW_MODEL]
    assert resolve_write_targets() == [settings.qdrant_collection, name]
    # Same model again returns the building one; another model is refused while building.
    assert vi.run(lifecycle_service.register_building()).id == row.id
    _expect_error(
        vi,
        lifecycle_service.register_building(embedding_model="other", vector_size=4),
        "building_exists",
    )


def test_verify_mismatch_blocks_swap(vi: VectorIndexEnv) -> None:
    vi.seed_indexed("doc")
    vi.adopt_and_register()
    # Nothing built yet: the new collection is empty.
    result = vi.run(lifecycle_service.verify())
    assert not result.passed and result.error_code == "point_count_mismatch"
    assert result.actual_points == 0 and result.expected_points > 0
    assert vi.generations()[2].state == "failed"
    assert vi.generations()[2].error_code == "point_count_mismatch"
    _expect_error(vi, lifecycle_service.swap(dry_run=False), "not_verified")
    assert vi.client.aliases == {ALIAS: settings.qdrant_collection}
    # A failed generation takes no dual writes.
    assert len(vi.run(generation_service.resolve_write_targets())) == 1


def test_verify_detects_missing_documents(vi: VectorIndexEnv) -> None:
    vi.seed_indexed("doc")
    gen2 = vi.adopt_and_register()
    assert vi.build().verify.passed

    async def _drop_rows() -> None:
        async with vi.env.factory() as session:
            await session.execute(delete(VectorIndexGenerationDocument))
            await session.commit()

    vi.run(_drop_rows())
    result = vi.run(lifecycle_service.verify(generation=gen2.generation))
    assert result.error_code == "documents_missing"
    assert (result.documents_total, result.documents_done) == (1, 0)
    assert result.actual_points == result.expected_points
    _expect_error(vi, lifecycle_service.verify(generation=1), "nothing_to_verify")


def test_swap_is_one_alias_call_then_rollback_and_drop(vi: VectorIndexEnv) -> None:
    seeded = vi.seed_indexed("doc")
    gen2 = vi.adopt_and_register()
    progress = vi.build()
    assert progress.finished and progress.verify is not None and progress.verify.passed

    plan = vi.run(lifecycle_service.swap())
    assert not plan.applied and (plan.from_generation, plan.to_generation) == (1, 2)
    assert vi.client.aliases == {ALIAS: settings.qdrant_collection}
    calls_before = len(vi.client.alias_calls)

    applied = vi.run(lifecycle_service.swap(dry_run=False))

    assert applied.applied
    assert len(vi.client.alias_calls) == calls_before + 1
    operations = vi.client.alias_calls[-1]
    assert [type(op) for op in operations] == [DeleteAliasOperation, CreateAliasOperation]
    assert vi.client.aliases == {ALIAS: gen2.collection_name}
    rows = vi.generations()
    assert rows[2].state == "active" and rows[1].state == "retired"
    retire_after = rows[1].retire_after
    assert retire_after is not None
    retire_after = retire_after.replace(tzinfo=retire_after.tzinfo or UTC)
    expected = datetime.now(UTC) + timedelta(hours=settings.qdrant_retired_grace_hours)
    assert abs((retire_after - expected).total_seconds()) < 120

    # Retrieval follows the active generation's model and collection.
    service = QueryRetrievalService()
    vi.run(service.refresh_index_target())
    assert (service.embedding_model, service.vector_size) == (NEW_MODEL, NEW_SIZE)
    assert service.qdrant_collection == gen2.collection_name
    assert vi.points(gen2.collection_name, seeded)

    # Drop respects the grace period and never drops the active generation.
    assert vi.run(lifecycle_service.drop_retired(dry_run=False)) == []
    later = datetime.now(UTC) + timedelta(hours=settings.qdrant_retired_grace_hours + 1)
    assert vi.run(lifecycle_service.drop_retired(now=later)) == [1]
    assert settings.qdrant_collection in vi.client.vector_configs  # dry run

    # Rollback before the drop: the alias returns to generation 1.
    rollback = vi.run(lifecycle_service.rollback(dry_run=False))
    assert (rollback.from_generation, rollback.to_generation) == (2, 1)
    assert vi.client.aliases == {ALIAS: settings.qdrant_collection}
    assert [type(op) for op in vi.client.alias_calls[-1]] == [
        DeleteAliasOperation,
        CreateAliasOperation,
    ]
    rows = vi.generations()
    assert rows[1].state == "active" and rows[2].state == "retired"
    vi.run(service.refresh_index_target())
    assert service.embedding_model == OLD_MODEL

    # Generation 2 is now retired; after its grace it is dropped, the active one is kept.
    later = datetime.now(UTC) + timedelta(hours=settings.qdrant_retired_grace_hours + 1)
    assert vi.run(lifecycle_service.drop_retired(dry_run=False, now=later)) == [2]
    assert gen2.collection_name in vi.client.deleted_collections
    assert settings.qdrant_collection in vi.client.vector_configs
    assert vi.generations()[2].state == "dropped"
    _expect_error(vi, lifecycle_service.rollback(dry_run=False), "nothing_to_roll_back")


def test_swap_moves_the_alias_back_when_the_state_commit_fails(
    vi: VectorIndexEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    vi.seed_indexed("doc")
    vi.adopt_and_register()
    vi.build()
    calls: list[Any] = []

    async def _broken(session: Any, generation_id: Any) -> Any:
        calls.append(generation_id)
        raise RuntimeError("database down")

    monkeypatch.setattr(lifecycle_service.repo, "get_by_id", _broken)
    with pytest.raises(RuntimeError):
        vi.run(
            lifecycle_service._move_alias(
                alias=ALIAS, to_row=vi.generations()[2], from_row=vi.generations()[1]
            )
        )
    assert vi.client.aliases == {ALIAS: settings.qdrant_collection}
    assert calls


def test_startup_model_change_registers_a_generation_instead_of_raising(
    vi: VectorIndexEnv,
) -> None:
    vi.enable_alias()
    vi.run(lifecycle_service.adopt())
    assert vi.run(reconcile_on_startup()) == "current"
    vi.configure_model(NEW_MODEL, NEW_SIZE)

    qdrant_module.ensure_qdrant_collection()  # no RuntimeError on the size mismatch
    outcome = vi.run(reconcile_on_startup())

    assert outcome == "registered"
    rows = vi.generations()
    assert rows[2].state == "building" and rows[2].embedding_model == NEW_MODEL
    assert vi.client.aliases == {ALIAS: settings.qdrant_collection}
    # Queries keep the active generation's model meanwhile.
    service = QueryRetrievalService()
    vi.run(service.refresh_index_target())
    assert (service.embedding_model, service.vector_size) == (OLD_MODEL, 1536)
    # A second start finds the pending generation and registers nothing new.
    assert vi.run(reconcile_on_startup()) == "pending"
    vi.configure_model("third-model", 4)
    assert vi.run(reconcile_on_startup()) == "building_other"
    assert set(vi.generations()) == {1, 2}


def test_startup_reconcile_outcomes_without_adoption(vi: VectorIndexEnv) -> None:
    assert vi.run(reconcile_on_startup()) == "legacy"
    vi.enable_alias()
    assert vi.run(reconcile_on_startup()) == "not_adopted"


def test_legacy_mode_keeps_the_startup_mismatch_error(vi: VectorIndexEnv) -> None:
    vi.configure_model(NEW_MODEL, NEW_SIZE)
    with pytest.raises(RuntimeError):
        qdrant_module.ensure_qdrant_collection()
    # Alias configured but not adopted yet: the legacy check still applies.
    vi.enable_alias()
    with pytest.raises(RuntimeError):
        qdrant_module.ensure_qdrant_collection()


def test_query_embedding_cache_key_follows_the_active_generation(
    vi: VectorIndexEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.domains.chat.services import query_embedding_cache

    keys: list[str] = []

    async def _get_or_load(*, key_id: str, loader: Any, **_: Any) -> Any:
        keys.append(key_id)
        return await loader()

    monkeypatch.setattr(query_embedding_cache, "get_or_load", _get_or_load)
    vi.seed_indexed("doc")
    vi.adopt_and_register()
    service = QueryRetrievalService(embedding_provider=vi.provider)  # type: ignore[arg-type]
    first = vi.run(embed_query_cached(service, organization_id=uuid4(), question="leave?"))
    assert len(first.vector) == 1536 and vi.provider.models()[-1] == OLD_MODEL
    vi.build()
    vi.run(lifecycle_service.swap(dry_run=False))
    second = vi.run(embed_query_cached(service, organization_id=uuid4(), question="leave?"))
    assert len(second.vector) == NEW_SIZE and vi.provider.models()[-1] == NEW_MODEL
    assert keys[0] != keys[1]


def test_registry_cache_ttl_and_refresh_failure(
    vi: VectorIndexEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    vi.enable_alias()
    vi.run(lifecycle_service.adopt())
    monkeypatch.setattr(settings, "vector_index_registry_cache_seconds", 3600.0)
    first = vi.run(registry.snapshot())
    loads: list[str] = []

    async def _load(alias: str) -> Any:
        loads.append(alias)
        raise RuntimeError("database down")

    monkeypatch.setattr(registry, "_load", _load)
    assert vi.run(registry.snapshot()) is first  # cached
    assert vi.run(registry.snapshot(force=True)) is first  # failure keeps the last one
    assert loads == [ALIAS]
    registry.invalidate()
    with pytest.raises(RuntimeError):
        vi.run(registry.snapshot())
    assert generation_service.cached_read_target()[0] == settings.qdrant_collection
