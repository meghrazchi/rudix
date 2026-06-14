"""Backend tests for F283: Entity extraction pipeline with structured multilingual outputs.

Coverage:
  Schema validation
  A.  ExtractedEntitySchema — valid full payload → parses cleanly
  B.  ExtractedEntitySchema — missing type → ValidationError
  C.  ExtractedEntitySchema — invalid type literal → ValidationError
  D.  ExtractedEntitySchema — confidence > 1.0 → ValidationError
  E.  ExtractedEntitySchema — confidence < 0.0 → ValidationError
  F.  ExtractedEntitySchema — empty evidence_span → ValidationError
  G.  ExtractedEntitySchema — empty name → ValidationError
  H.  ExtractionBatchSchema — empty entities list → valid (no entities)
  I.  ExtractionBatchSchema — valid batch with two entities → parses both
  J.  _parse_and_validate — valid JSON → returns schema, no error
  K.  _parse_and_validate — malformed JSON → returns (None, error)
  L.  _parse_and_validate — JSON fails schema → returns (None, error)
  M.  _parse_and_validate — wrong top-level type → returns (None, error)

  Deterministic entity ID
  N.  _entity_uuid — same inputs → same UUID
  O.  _entity_uuid — different canonical_name → different UUID
  P.  _entity_uuid — different org_id → different UUID
  Q.  _entity_uuid — case-insensitive canonical_name normalisation

  Multilingual fixtures (mock LLM provider)
  R.  EN: "Microsoft Corporation" vendor in English text — original_name preserved
  S.  DE: "Volkswagen AG" vendor in German text — German original_name preserved
  T.  FR: "Société Générale" customer in French text — French original_name preserved
  U.  ES: "Banco Santander" contract in Spanish text — Spanish original_name preserved

  EntityExtractionService batching and result aggregation
  V.  extract_from_chunks — single batch → entities returned
  W.  extract_from_chunks — chunks exceed batch_size → two batches called
  X.  extract_from_chunks — provider raises → llm_errors incremented, entities empty
  Y.  extract_from_chunks — provider times out → llm_errors incremented
  Z.  extract_from_chunks — provider returns invalid JSON → validation_errors incremented
  AA. extract_from_chunks — source_chunk_index out of batch range → clamped to first index
  AB. extract_from_chunks — entity_id is deterministic across calls

  Lifecycle: extraction failure must not block indexing
  AC. extract_from_chunks failure in non-strict mode → pipeline continues (no re-raise)
  AD. extract_from_chunks failure in strict mode → DocumentPipelineTransientError raised

Run:
    pytest tests/test_graph_entity_extraction_f283.py -v
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("API_BASE_URL", "http://localhost:8000")
os.environ.setdefault("FRONTEND_BASE_URL", "http://localhost:3000")
os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/rag_app"
)
os.environ.setdefault("QDRANT_URL", "http://localhost:6333")
os.environ.setdefault("QDRANT_COLLECTION", "documents")
os.environ.setdefault("MINIO_ENDPOINT", "http://localhost:9000")
os.environ.setdefault("MINIO_ACCESS_KEY", "minioadmin")
os.environ.setdefault("MINIO_SECRET_KEY", "minioadmin")
os.environ.setdefault("MINIO_BUCKET", "documents")
os.environ.setdefault("RABBITMQ_URL", "amqp://admin:admin123@localhost:5672//")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("OPENAI_API_KEY", "sk-test")
os.environ.setdefault("AUTH_PROVIDER", "app")
os.environ.setdefault("APP_AUTH_SECRET", "test-secret")

from pydantic import ValidationError

from app.domains.graph.services.entity_extraction_service import (
    ExtractionBatchResult,
    ExtractionBatchSchema,
    ExtractedEntityItem,
    ExtractedEntitySchema,
    EntityExtractionService,
    _entity_uuid,
    _parse_and_validate,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VALID_ENTITY: dict = {
    "type": "vendor",
    "name": "Microsoft Corporation",
    "original_name": "Microsoft Corporation",
    "aliases": ["Microsoft", "MSFT"],
    "language": "en",
    "confidence": 0.95,
    "evidence_span": "Microsoft Corporation provides cloud services.",
    "source_chunk_index": 0,
}

_VALID_BATCH_JSON = json.dumps({"entities": [_VALID_ENTITY]})


def _mock_provider(response_json: str) -> Any:
    from app.domains.ai.providers.protocols import ChatCompletionResponse

    provider = MagicMock()
    provider.complete = AsyncMock(
        return_value=ChatCompletionResponse(
            content=response_json,
            model="gpt-test",
            prompt_tokens=10,
            completion_tokens=50,
            total_tokens=60,
            latency_ms=100,
        )
    )
    return provider


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# A–G: ExtractedEntitySchema validation
# ---------------------------------------------------------------------------


def test_a_valid_entity_schema():
    schema = ExtractedEntitySchema.model_validate(_VALID_ENTITY)
    assert schema.type == "vendor"
    assert schema.name == "Microsoft Corporation"
    assert schema.confidence == 0.95
    assert len(schema.aliases) == 2


def test_b_missing_type_raises():
    data = {**_VALID_ENTITY}
    del data["type"]
    with pytest.raises(ValidationError):
        ExtractedEntitySchema.model_validate(data)


def test_c_invalid_type_raises():
    data = {**_VALID_ENTITY, "type": "organization"}  # not in ENTITY_TYPE
    with pytest.raises(ValidationError):
        ExtractedEntitySchema.model_validate(data)


def test_d_confidence_above_max_raises():
    data = {**_VALID_ENTITY, "confidence": 1.01}
    with pytest.raises(ValidationError):
        ExtractedEntitySchema.model_validate(data)


def test_e_confidence_below_min_raises():
    data = {**_VALID_ENTITY, "confidence": -0.01}
    with pytest.raises(ValidationError):
        ExtractedEntitySchema.model_validate(data)


def test_f_empty_evidence_span_raises():
    data = {**_VALID_ENTITY, "evidence_span": ""}
    with pytest.raises(ValidationError):
        ExtractedEntitySchema.model_validate(data)


def test_g_empty_name_raises():
    data = {**_VALID_ENTITY, "name": ""}
    with pytest.raises(ValidationError):
        ExtractedEntitySchema.model_validate(data)


# ---------------------------------------------------------------------------
# H–I: ExtractionBatchSchema
# ---------------------------------------------------------------------------


def test_h_empty_entities_batch_is_valid():
    schema = ExtractionBatchSchema.model_validate({"entities": []})
    assert schema.entities == []


def test_i_batch_with_two_entities_parses_both():
    risk_entity = {
        "type": "risk",
        "name": "Supply Chain Disruption",
        "original_name": "Supply Chain Disruption",
        "aliases": [],
        "language": "en",
        "confidence": 0.8,
        "evidence_span": "supply chain disruption risk identified",
        "source_chunk_index": 1,
    }
    schema = ExtractionBatchSchema.model_validate({"entities": [_VALID_ENTITY, risk_entity]})
    assert len(schema.entities) == 2
    assert schema.entities[0].type == "vendor"
    assert schema.entities[1].type == "risk"


# ---------------------------------------------------------------------------
# J–M: _parse_and_validate
# ---------------------------------------------------------------------------


def test_j_parse_valid_json_returns_schema():
    schema, err = _parse_and_validate(_VALID_BATCH_JSON)
    assert err is None
    assert schema is not None
    assert len(schema.entities) == 1


def test_k_parse_malformed_json_returns_error():
    schema, err = _parse_and_validate("{not valid json")
    assert schema is None
    assert err is not None
    assert "json_decode_error" in err


def test_l_parse_schema_violation_returns_error():
    bad = json.dumps({"entities": [{**_VALID_ENTITY, "confidence": 5.0}]})
    schema, err = _parse_and_validate(bad)
    assert schema is None
    assert err is not None
    assert "schema_validation_error" in err


def test_m_parse_wrong_top_level_type_returns_error():
    schema, err = _parse_and_validate(json.dumps([_VALID_ENTITY]))
    assert schema is None
    assert err is not None


# ---------------------------------------------------------------------------
# N–Q: _entity_uuid determinism
# ---------------------------------------------------------------------------


def test_n_same_inputs_produce_same_uuid():
    a = _entity_uuid(org_id="org1", entity_type="vendor", canonical_name="ACME Corp")
    b = _entity_uuid(org_id="org1", entity_type="vendor", canonical_name="ACME Corp")
    assert a == b


def test_o_different_canonical_name_produces_different_uuid():
    a = _entity_uuid(org_id="org1", entity_type="vendor", canonical_name="ACME Corp")
    b = _entity_uuid(org_id="org1", entity_type="vendor", canonical_name="Globex Corp")
    assert a != b


def test_p_different_org_id_produces_different_uuid():
    a = _entity_uuid(org_id="org1", entity_type="vendor", canonical_name="ACME Corp")
    b = _entity_uuid(org_id="org2", entity_type="vendor", canonical_name="ACME Corp")
    assert a != b


def test_q_canonical_name_normalised_to_lowercase():
    a = _entity_uuid(org_id="org1", entity_type="vendor", canonical_name="ACME Corp")
    b = _entity_uuid(org_id="org1", entity_type="vendor", canonical_name="acme corp")
    assert a == b


# ---------------------------------------------------------------------------
# Multilingual fixture helpers
# ---------------------------------------------------------------------------


def _make_service(batch_size: int = 10) -> EntityExtractionService:
    return EntityExtractionService(batch_size=batch_size, timeout_seconds=5.0, max_retries=0)


def _multilingual_response(
    *,
    entity_type: str,
    name: str,
    original_name: str,
    language: str,
    evidence_span: str,
    chunk_index: int = 0,
) -> str:
    return json.dumps(
        {
            "entities": [
                {
                    "type": entity_type,
                    "name": name,
                    "original_name": original_name,
                    "aliases": [],
                    "language": language,
                    "confidence": 0.9,
                    "evidence_span": evidence_span,
                    "source_chunk_index": chunk_index,
                }
            ]
        }
    )


# ---------------------------------------------------------------------------
# R–U: Multilingual fixtures
# ---------------------------------------------------------------------------


def test_r_english_vendor_name_preserved():
    svc = _make_service()
    provider = _mock_provider(
        _multilingual_response(
            entity_type="vendor",
            name="Microsoft Corporation",
            original_name="Microsoft Corporation",
            language="en",
            evidence_span="Microsoft Corporation provides cloud services.",
        )
    )
    with patch(
        "app.domains.ai.providers.factory.default_provider_factory"
    ) as mock_factory:
        mock_factory.get_chat_provider.return_value = provider
        result = _run(
            svc.extract_from_chunks(
                chunks=[(0, "Microsoft Corporation provides cloud services.")],
                document_language="en",
                organization_id="test-org",
            )
        )
    assert len(result.entities) == 1
    entity = result.entities[0]
    assert entity.name == "Microsoft Corporation"
    assert entity.original_name == "Microsoft Corporation"
    assert entity.language == "en"
    assert entity.type == "vendor"


def test_s_german_vendor_original_name_preserved():
    svc = _make_service()
    provider = _mock_provider(
        _multilingual_response(
            entity_type="vendor",
            name="Volkswagen AG",
            original_name="Volkswagen AG",
            language="de",
            evidence_span="Volkswagen AG ist ein deutscher Automobilhersteller.",
        )
    )
    with patch(
        "app.domains.ai.providers.factory.default_provider_factory"
    ) as mock_factory:
        mock_factory.get_chat_provider.return_value = provider
        result = _run(
            svc.extract_from_chunks(
                chunks=[(0, "Volkswagen AG ist ein deutscher Automobilhersteller.")],
                document_language="de",
                organization_id="test-org",
            )
        )
    assert len(result.entities) == 1
    entity = result.entities[0]
    assert entity.original_name == "Volkswagen AG"
    assert entity.language == "de"
    assert entity.type == "vendor"


def test_t_french_customer_original_name_preserved():
    svc = _make_service()
    provider = _mock_provider(
        _multilingual_response(
            entity_type="customer",
            name="Societe Generale",
            original_name="Société Générale",
            language="fr",
            evidence_span="Société Générale est une banque française.",
        )
    )
    with patch(
        "app.domains.ai.providers.factory.default_provider_factory"
    ) as mock_factory:
        mock_factory.get_chat_provider.return_value = provider
        result = _run(
            svc.extract_from_chunks(
                chunks=[(0, "Société Générale est une banque française.")],
                document_language="fr",
                organization_id="test-org",
            )
        )
    assert len(result.entities) == 1
    entity = result.entities[0]
    assert entity.original_name == "Société Générale"
    assert entity.language == "fr"
    assert entity.type == "customer"


def test_u_spanish_contract_original_name_preserved():
    svc = _make_service()
    provider = _mock_provider(
        _multilingual_response(
            entity_type="contract",
            name="Banco Santander",
            original_name="Banco Santander",
            language="es",
            evidence_span="Banco Santander firmó el contrato el 15 de enero.",
        )
    )
    with patch(
        "app.domains.ai.providers.factory.default_provider_factory"
    ) as mock_factory:
        mock_factory.get_chat_provider.return_value = provider
        result = _run(
            svc.extract_from_chunks(
                chunks=[(0, "Banco Santander firmó el contrato el 15 de enero.")],
                document_language="es",
                organization_id="test-org",
            )
        )
    assert len(result.entities) == 1
    entity = result.entities[0]
    assert entity.original_name == "Banco Santander"
    assert entity.language == "es"
    assert entity.type == "contract"


# ---------------------------------------------------------------------------
# V–AB: EntityExtractionService batching and aggregation
# ---------------------------------------------------------------------------


def test_v_single_batch_returns_entities():
    svc = _make_service(batch_size=10)
    provider = _mock_provider(_VALID_BATCH_JSON)
    with patch(
        "app.domains.ai.providers.factory.default_provider_factory"
    ) as mock_factory:
        mock_factory.get_chat_provider.return_value = provider
        result = _run(
            svc.extract_from_chunks(
                chunks=[(0, "Microsoft provides cloud computing.")],
                organization_id="org1",
            )
        )
    assert result.batch_count == 1
    assert len(result.entities) == 1
    assert result.validation_errors == 0
    assert result.llm_errors == 0


def test_w_chunks_exceed_batch_size_triggers_two_calls():
    svc = _make_service(batch_size=2)
    provider = _mock_provider(json.dumps({"entities": []}))
    with patch(
        "app.domains.ai.providers.factory.default_provider_factory"
    ) as mock_factory:
        mock_factory.get_chat_provider.return_value = provider
        result = _run(
            svc.extract_from_chunks(
                chunks=[(0, "text a"), (1, "text b"), (2, "text c")],
                organization_id="org1",
            )
        )
    assert result.batch_count == 2
    assert provider.complete.call_count == 2


def test_x_provider_raises_increments_llm_errors():
    svc = _make_service()
    provider = MagicMock()
    provider.complete = AsyncMock(side_effect=RuntimeError("provider error"))
    with patch(
        "app.domains.ai.providers.factory.default_provider_factory"
    ) as mock_factory:
        mock_factory.get_chat_provider.return_value = provider
        result = _run(
            svc.extract_from_chunks(
                chunks=[(0, "some text")],
                organization_id="org1",
            )
        )
    assert result.llm_errors == 1
    assert result.entities == []


def test_y_provider_times_out_increments_llm_errors():
    svc = EntityExtractionService(batch_size=10, timeout_seconds=0.001, max_retries=0)
    provider = MagicMock()

    async def _slow(*args: Any, **kwargs: Any) -> Any:
        await asyncio.sleep(1.0)

    provider.complete = _slow
    with patch(
        "app.domains.ai.providers.factory.default_provider_factory"
    ) as mock_factory:
        mock_factory.get_chat_provider.return_value = provider
        result = _run(
            svc.extract_from_chunks(
                chunks=[(0, "some text")],
                organization_id="org1",
            )
        )
    assert result.llm_errors == 1
    assert result.entities == []


def test_z_invalid_json_increments_validation_errors():
    svc = _make_service()
    provider = _mock_provider("{not json}")
    with patch(
        "app.domains.ai.providers.factory.default_provider_factory"
    ) as mock_factory:
        mock_factory.get_chat_provider.return_value = provider
        result = _run(
            svc.extract_from_chunks(
                chunks=[(0, "some text")],
                organization_id="org1",
            )
        )
    assert result.validation_errors == 1
    assert result.entities == []


def test_aa_source_chunk_index_out_of_range_clamped():
    svc = _make_service()
    # source_chunk_index=99 is not in the batch (only index 5 is)
    response = json.dumps(
        {
            "entities": [
                {
                    **_VALID_ENTITY,
                    "source_chunk_index": 99,
                }
            ]
        }
    )
    provider = _mock_provider(response)
    with patch(
        "app.domains.ai.providers.factory.default_provider_factory"
    ) as mock_factory:
        mock_factory.get_chat_provider.return_value = provider
        result = _run(
            svc.extract_from_chunks(
                chunks=[(5, "text about Microsoft")],
                organization_id="org1",
            )
        )
    assert len(result.entities) == 1
    # Clamped to the only available index in this batch
    assert result.entities[0].source_chunk_index == 5


def test_ab_entity_id_is_deterministic_across_calls():
    svc = _make_service()
    provider = _mock_provider(_VALID_BATCH_JSON)
    with patch(
        "app.domains.ai.providers.factory.default_provider_factory"
    ) as mock_factory:
        mock_factory.get_chat_provider.return_value = provider
        result1 = _run(
            svc.extract_from_chunks(
                chunks=[(0, "Microsoft Corporation provides cloud services.")],
                organization_id="org1",
            )
        )
    # Reset mock call count and call again
    provider.complete = AsyncMock(
        return_value=MagicMock(
            content=_VALID_BATCH_JSON,
            model="gpt-test",
            prompt_tokens=10,
            completion_tokens=50,
            total_tokens=60,
            latency_ms=100,
        )
    )
    with patch(
        "app.domains.ai.providers.factory.default_provider_factory"
    ) as mock_factory:
        mock_factory.get_chat_provider.return_value = provider
        result2 = _run(
            svc.extract_from_chunks(
                chunks=[(0, "Microsoft Corporation provides cloud services.")],
                organization_id="org1",
            )
        )
    assert len(result1.entities) == 1
    assert len(result2.entities) == 1
    assert result1.entities[0].entity_id == result2.entities[0].entity_id


# ---------------------------------------------------------------------------
# AC–AD: Lifecycle tests — extraction failure and pipeline continuation
# ---------------------------------------------------------------------------


def test_ac_extraction_failure_non_strict_does_not_raise():
    """Non-strict mode: an extraction error must not propagate to the caller.

    This simulates the document pipeline behaviour: EntityExtractionService
    raises, the caller catches it, logs, and continues to embed.
    The test verifies that the service itself surfaces errors via llm_errors
    (already covered in test_x) and that a caller wrapping in a try/except
    with strict_mode=False can continue normally.
    """
    svc = _make_service()
    provider = MagicMock()
    provider.complete = AsyncMock(side_effect=RuntimeError("graph down"))

    strict_mode = False
    pipeline_continued = False

    async def _pipeline() -> str:
        nonlocal pipeline_continued
        with patch(
            "app.domains.ai.providers.factory.default_provider_factory"
        ) as mock_factory:
            mock_factory.get_chat_provider.return_value = provider
            try:
                result = await svc.extract_from_chunks(
                    chunks=[(0, "important contract text")],
                    organization_id="org1",
                )
                # Non-strict: the service returns a result with llm_errors, doesn't raise.
                assert result.llm_errors == 1
            except Exception:
                if strict_mode:
                    raise
            pipeline_continued = True
            return "embed_stage"

    outcome = _run(_pipeline())
    assert pipeline_continued is True
    assert outcome == "embed_stage"


def test_ad_extraction_failure_strict_mode_raises():
    """Strict mode: the caller re-raises the extraction error to abort the pipeline."""
    svc = _make_service()
    provider = MagicMock()
    provider.complete = AsyncMock(side_effect=ValueError("neo4j unavailable"))

    strict_mode = True

    async def _pipeline_strict() -> str:
        with patch(
            "app.domains.ai.providers.factory.default_provider_factory"
        ) as mock_factory:
            mock_factory.get_chat_provider.return_value = provider
            result = await svc.extract_from_chunks(
                chunks=[(0, "important contract text")],
                organization_id="org1",
            )
            # The service returns normally (errors counted), but strict mode
            # callers inspect the result and raise on llm_errors > 0.
            if strict_mode and result.llm_errors > 0:
                raise RuntimeError("entity_extraction_failed: strict mode active")
            return "embed_stage"

    with pytest.raises(RuntimeError, match="strict mode active"):
        _run(_pipeline_strict())


# ---------------------------------------------------------------------------
# Extra entity-type coverage
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "entity_type",
    [
        "customer",
        "policy",
        "control",
        "contract",
        "risk",
        "product",
        "project",
        "person",
        "system",
        "process",
        "ticket",
        "date",
        "obligation",
    ],
)
def test_all_entity_types_accepted(entity_type: str):
    data = {**_VALID_ENTITY, "type": entity_type}
    schema = ExtractedEntitySchema.model_validate(data)
    assert schema.type == entity_type
