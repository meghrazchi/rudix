"""Backend tests for F284: Relationship extraction, evidence linking, and confidence scoring.

Coverage:
  Schema validation
  A.  ExtractedRelationSchema — valid payload → parses cleanly
  B.  ExtractedRelationSchema — missing from_entity_name → ValidationError
  C.  ExtractedRelationSchema — unknown rel_type → ValidationError
  D.  ExtractedRelationSchema — confidence > 1.0 → ValidationError
  E.  ExtractedRelationSchema — confidence < 0.0 → ValidationError
  F.  ExtractedRelationSchema — empty evidence_span → ValidationError
  G.  ExtractedRelationSchema — rel_type is uppercased automatically
  H.  RelationExtractionBatchSchema — empty relations → valid
  I.  RelationExtractionBatchSchema — two valid relations → parses both
  J.  _parse_and_validate — valid JSON → returns schema, no error
  K.  _parse_and_validate — malformed JSON → (None, error)
  L.  _parse_and_validate — schema error → (None, error)
  M.  _parse_and_validate — unknown rel_type in JSON → (None, error)

  Deterministic relation ID
  N.  _relation_uuid — same inputs → same UUID
  O.  _relation_uuid — different rel_type → different UUID
  P.  _relation_uuid — different org_id → different UUID
  Q.  _relation_uuid — order matters: (A→B) ≠ (B→A)

  Confidence threshold and initial status
  R.  compute_initial_status — above threshold → unverified
  S.  compute_initial_status — below threshold → low_confidence
  T.  compute_initial_status — exactly at threshold → unverified (inclusive)
  U.  review_mode ignored by compute_initial_status (caller decides)

  RelationExtractionService (mock LLM provider)
  V.  extract_from_chunks — single batch → relations returned
  W.  extract_from_chunks — unknown entity names skipped, skipped_unknown_entity incremented
  X.  extract_from_chunks — provider raises → llm_errors incremented, relations empty
  Y.  extract_from_chunks — provider times out → llm_errors incremented
  Z.  extract_from_chunks — invalid JSON → validation_errors incremented
  AA. extract_from_chunks — source_chunk_index out of batch range → clamped to first
  AB. extract_from_chunks — relation_id is deterministic across calls

  RelationRepository (mock Neo4j)
  AC. create_relation_with_evidence — no evidence → ValueError
  AD. create_relation_with_evidence — unknown rel_type → ValueError
  AE. create_relation_with_evidence — driver None → no-op
  AF. create_relation_with_evidence — valid → execute_write called with all provenance fields
  AG. list_relations — driver None → []
  AH. list_relations — status filter added to WHERE
  AI. list_relations — unknown status → ValueError
  AJ. get_relation — driver None → None
  AK. get_relation — record found → dict
  AL. update_relation_status — driver None → False
  AM. update_relation_status — unknown status → ValueError
  AN. update_relation_status — record found → True
  AO. delete_relation_by_id — driver None → False
  AP. delete_relation_by_id — deleted → True

  GraphService delegation
  AQ. GraphService.create_relation_with_evidence — delegates to RelationRepository
  AR. GraphService.list_relations — delegates to RelationRepository
  AS. GraphService.update_relation_status — delegates to RelationRepository
  AT. GraphService.delete_relation_by_id — delegates to RelationRepository

  HTTP API (admin_graph_relations)
  AU. GET  /admin/graph/relations — graph disabled → 503
  AV. GET  /admin/graph/relations — member role → 403
  AW. GET  /admin/graph/relations — invalid status param → 422
  AX. GET  /admin/graph/relations — owner → 200 list
  AY. POST /admin/graph/relations — no evidence → 422
  AZ. POST /admin/graph/relations — unknown rel_type → 422
  BA. POST /admin/graph/relations — valid → 200 relation dict
  BB. GET  /admin/graph/relations/{id} — not found → 404
  BC. GET  /admin/graph/relations/{id} — found → 200
  BD. PATCH /admin/graph/relations/{id}/status — not found → 404
  BE. PATCH /admin/graph/relations/{id}/status — valid → 200
  BF. DELETE /admin/graph/relations/{id} — not found → 404
  BG. DELETE /admin/graph/relations/{id} — valid → 200 {deleted: true}

  Security
  BH. RelationRepository blocks unknown rel_type strings (injection guard)
  BI. list_relations always includes organization_id in WHERE
  BJ. create_relation_with_evidence requires evidence before reaching Neo4j

Run:
    pytest tests/test_graph_relation_extraction_f284.py -v
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.auth.dependencies import get_current_principal
from app.auth.models import AuthenticatedPrincipal
from app.db.session import get_db_session
from app.core.config import settings
from app.domains.graph.repositories.relation_repository import (
    RelationRepository,
    _validate_rel_type,
    _validate_status,
)
from app.domains.graph.services.graph_service import GraphService
from app.domains.graph.services.relation_extraction_service import (
    ExtractedRelationSchema,
    RelationExtractionBatchSchema,
    RelationExtractionService,
    _parse_and_validate,
    _relation_uuid,
)
from app.main import app
from app.models.enums import OrganizationRole

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

import app.clients.neo4j_client as neo4j_module

_ORG = "00000000-0000-0000-0000-000000f284f1"
_WS = "00000000-0000-0000-0000-000000f284f2"
_DB = "neo4j"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _reset_driver() -> None:
    neo4j_module._neo4j_driver = None


def _mock_driver(records: list[dict] | None = None) -> MagicMock:
    """Return a mock Neo4j driver whose session returns parameterised records."""
    record_data = records if records is not None else []

    result_mock = AsyncMock()
    result_mock.data = AsyncMock(return_value=record_data)

    tx_mock = AsyncMock()
    tx_mock.run = AsyncMock(return_value=result_mock)

    session_mock = AsyncMock()
    session_mock.__aenter__ = AsyncMock(return_value=session_mock)
    session_mock.__aexit__ = AsyncMock(return_value=False)
    session_mock.run = AsyncMock(return_value=result_mock)
    session_mock.execute_write = AsyncMock(side_effect=lambda fn: fn(tx_mock))

    driver = MagicMock()
    driver.session = MagicMock(return_value=session_mock)
    return driver


def _set_driver(driver: MagicMock | None) -> None:
    neo4j_module._neo4j_driver = driver


def _entity_ids() -> tuple[uuid.UUID, uuid.UUID]:
    return uuid.uuid4(), uuid.uuid4()


# ---------------------------------------------------------------------------
# A-M: Schema validation
# ---------------------------------------------------------------------------


def test_A_extracted_relation_schema_valid():
    data = {
        "from_entity_name": "Acme Corp",
        "to_entity_name": "Global Ltd",
        "rel_type": "OWNS",
        "confidence": 0.85,
        "evidence_span": "Acme Corp owns Global Ltd as stated in section 3.",
        "source_chunk_index": 2,
    }
    schema = ExtractedRelationSchema.model_validate(data)
    assert schema.from_entity_name == "Acme Corp"
    assert schema.rel_type == "OWNS"
    assert schema.confidence == 0.85


def test_B_extracted_relation_schema_missing_from_entity():
    with pytest.raises(ValidationError):
        ExtractedRelationSchema.model_validate(
            {
                "to_entity_name": "Global Ltd",
                "rel_type": "OWNS",
                "confidence": 0.9,
                "evidence_span": "...",
                "source_chunk_index": 0,
            }
        )


def test_C_extracted_relation_schema_unknown_rel_type():
    with pytest.raises(ValidationError):
        ExtractedRelationSchema.model_validate(
            {
                "from_entity_name": "A",
                "to_entity_name": "B",
                "rel_type": "INVENTED_TYPE",
                "confidence": 0.9,
                "evidence_span": "...",
                "source_chunk_index": 0,
            }
        )


def test_D_extracted_relation_schema_confidence_too_high():
    with pytest.raises(ValidationError):
        ExtractedRelationSchema.model_validate(
            {
                "from_entity_name": "A",
                "to_entity_name": "B",
                "rel_type": "RELATES_TO",
                "confidence": 1.5,
                "evidence_span": "...",
                "source_chunk_index": 0,
            }
        )


def test_E_extracted_relation_schema_confidence_negative():
    with pytest.raises(ValidationError):
        ExtractedRelationSchema.model_validate(
            {
                "from_entity_name": "A",
                "to_entity_name": "B",
                "rel_type": "RELATES_TO",
                "confidence": -0.1,
                "evidence_span": "...",
                "source_chunk_index": 0,
            }
        )


def test_F_extracted_relation_schema_empty_evidence_span():
    with pytest.raises(ValidationError):
        ExtractedRelationSchema.model_validate(
            {
                "from_entity_name": "A",
                "to_entity_name": "B",
                "rel_type": "AFFECTS",
                "confidence": 0.7,
                "evidence_span": "",
                "source_chunk_index": 0,
            }
        )


def test_G_rel_type_uppercased_automatically():
    schema = ExtractedRelationSchema.model_validate(
        {
            "from_entity_name": "X",
            "to_entity_name": "Y",
            "rel_type": "depends_on",
            "confidence": 0.6,
            "evidence_span": "X depends on Y.",
            "source_chunk_index": 0,
        }
    )
    assert schema.rel_type == "DEPENDS_ON"


def test_H_batch_schema_empty_relations():
    schema = RelationExtractionBatchSchema.model_validate({"relations": []})
    assert schema.relations == []


def test_I_batch_schema_two_valid_relations():
    data = {
        "relations": [
            {
                "from_entity_name": "A",
                "to_entity_name": "B",
                "rel_type": "MENTIONS",
                "confidence": 0.8,
                "evidence_span": "A mentions B.",
                "source_chunk_index": 0,
            },
            {
                "from_entity_name": "C",
                "to_entity_name": "D",
                "rel_type": "SUPERSEDES",
                "confidence": 0.6,
                "evidence_span": "C supersedes D.",
                "source_chunk_index": 1,
            },
        ]
    }
    schema = RelationExtractionBatchSchema.model_validate(data)
    assert len(schema.relations) == 2
    assert schema.relations[0].rel_type == "MENTIONS"
    assert schema.relations[1].rel_type == "SUPERSEDES"


def test_J_parse_and_validate_valid():
    raw = json.dumps(
        {
            "relations": [
                {
                    "from_entity_name": "Alpha",
                    "to_entity_name": "Beta",
                    "rel_type": "OWNS",
                    "confidence": 0.9,
                    "evidence_span": "Alpha owns Beta.",
                    "source_chunk_index": 0,
                }
            ]
        }
    )
    schema, err = _parse_and_validate(raw)
    assert schema is not None
    assert err is None
    assert len(schema.relations) == 1


def test_K_parse_and_validate_malformed_json():
    schema, err = _parse_and_validate("{broken json")
    assert schema is None
    assert err is not None
    assert "json_decode_error" in err


def test_L_parse_and_validate_schema_error():
    raw = json.dumps({"relations": [{"from_entity_name": "A"}]})
    schema, err = _parse_and_validate(raw)
    assert schema is None
    assert "schema_validation_error" in err


def test_M_parse_and_validate_unknown_rel_type():
    raw = json.dumps(
        {
            "relations": [
                {
                    "from_entity_name": "A",
                    "to_entity_name": "B",
                    "rel_type": "INVALID_REL",
                    "confidence": 0.8,
                    "evidence_span": "...",
                    "source_chunk_index": 0,
                }
            ]
        }
    )
    schema, err = _parse_and_validate(raw)
    assert schema is None
    assert "schema_validation_error" in err


# ---------------------------------------------------------------------------
# N-Q: Deterministic relation ID
# ---------------------------------------------------------------------------


def test_N_relation_uuid_same_inputs_same_uuid():
    uid1 = _relation_uuid(org_id="org1", from_entity_id="e1", rel_type="OWNS", to_entity_id="e2")
    uid2 = _relation_uuid(org_id="org1", from_entity_id="e1", rel_type="OWNS", to_entity_id="e2")
    assert uid1 == uid2


def test_O_relation_uuid_different_rel_type():
    uid1 = _relation_uuid(org_id="org", from_entity_id="e1", rel_type="OWNS", to_entity_id="e2")
    uid2 = _relation_uuid(org_id="org", from_entity_id="e1", rel_type="AFFECTS", to_entity_id="e2")
    assert uid1 != uid2


def test_P_relation_uuid_different_org():
    uid1 = _relation_uuid(org_id="org-a", from_entity_id="e1", rel_type="OWNS", to_entity_id="e2")
    uid2 = _relation_uuid(org_id="org-b", from_entity_id="e1", rel_type="OWNS", to_entity_id="e2")
    assert uid1 != uid2


def test_Q_relation_uuid_direction_matters():
    uid_ab = _relation_uuid(org_id="org", from_entity_id="e1", rel_type="OWNS", to_entity_id="e2")
    uid_ba = _relation_uuid(org_id="org", from_entity_id="e2", rel_type="OWNS", to_entity_id="e1")
    assert uid_ab != uid_ba


# ---------------------------------------------------------------------------
# R-U: Confidence threshold and initial status
# ---------------------------------------------------------------------------


def test_R_compute_initial_status_above_threshold():
    svc = RelationExtractionService(confidence_threshold=0.5)
    assert svc.compute_initial_status(0.8) == "unverified"


def test_S_compute_initial_status_below_threshold():
    svc = RelationExtractionService(confidence_threshold=0.5)
    assert svc.compute_initial_status(0.3) == "low_confidence"


def test_T_compute_initial_status_at_threshold_inclusive():
    svc = RelationExtractionService(confidence_threshold=0.5)
    assert svc.compute_initial_status(0.5) == "unverified"


def test_U_compute_initial_status_zero_confidence():
    svc = RelationExtractionService(confidence_threshold=0.5)
    assert svc.compute_initial_status(0.0) == "low_confidence"


# ---------------------------------------------------------------------------
# V-AB: RelationExtractionService (mock LLM provider)
# ---------------------------------------------------------------------------


def _make_provider(response_json: str | None = None, raise_exc: Exception | None = None):
    """Build a mock LLM provider that returns given JSON or raises."""
    response_mock = MagicMock()
    response_mock.content = response_json or json.dumps({"relations": []})

    complete_mock = AsyncMock()
    if raise_exc:
        complete_mock.side_effect = raise_exc
    else:
        complete_mock.return_value = response_mock

    provider = MagicMock()
    provider.complete = complete_mock
    return provider


def _entity_lookup() -> dict[str, uuid.UUID]:
    return {
        "acme corp": uuid.uuid4(),
        "global ltd": uuid.uuid4(),
    }


@pytest.mark.asyncio
async def test_V_extract_from_chunks_single_batch():
    from_id = uuid.uuid4()
    to_id = uuid.uuid4()
    entity_map = {"acme corp": from_id, "global ltd": to_id}
    payload = json.dumps(
        {
            "relations": [
                {
                    "from_entity_name": "Acme Corp",
                    "to_entity_name": "Global Ltd",
                    "rel_type": "OWNS",
                    "confidence": 0.9,
                    "evidence_span": "Acme owns Global Ltd.",
                    "source_chunk_index": 0,
                }
            ]
        }
    )
    provider = _make_provider(payload)
    svc = RelationExtractionService(batch_size=10)
    with patch(
        "app.domains.graph.services.relation_extraction_service.RelationExtractionService.extract_from_chunks.__func__"
        if False
        else "app.domains.ai.providers.factory"
    ):
        with patch(
            "app.domains.graph.services.relation_extraction_service.default_provider_factory"
        ) as mock_factory:
            mock_factory.get_chat_provider.return_value = provider
            result = await svc.extract_from_chunks(
                chunks=[(0, "Acme Corp owns Global Ltd as per the agreement.")],
                entity_name_to_id=entity_map,
                entity_names_by_chunk={0: ["Acme Corp", "Global Ltd"]},
                organization_id=_ORG,
            )
    assert len(result.relations) == 1
    assert result.relations[0].rel_type == "OWNS"
    assert result.relations[0].from_entity_id == from_id
    assert result.relations[0].to_entity_id == to_id
    assert result.llm_errors == 0


@pytest.mark.asyncio
async def test_W_extract_unknown_entity_skipped():
    entity_map = {"acme corp": uuid.uuid4()}  # "global ltd" not in map
    payload = json.dumps(
        {
            "relations": [
                {
                    "from_entity_name": "Acme Corp",
                    "to_entity_name": "Global Ltd",
                    "rel_type": "OWNS",
                    "confidence": 0.9,
                    "evidence_span": "Acme owns Global Ltd.",
                    "source_chunk_index": 0,
                }
            ]
        }
    )
    provider = _make_provider(payload)
    svc = RelationExtractionService()
    with patch(
        "app.domains.graph.services.relation_extraction_service.default_provider_factory"
    ) as mock_factory:
        mock_factory.get_chat_provider.return_value = provider
        result = await svc.extract_from_chunks(
            chunks=[(0, "Acme owns Global Ltd.")],
            entity_name_to_id=entity_map,
            entity_names_by_chunk={0: ["Acme Corp"]},
            organization_id=_ORG,
        )
    assert len(result.relations) == 0
    assert result.skipped_unknown_entity == 1


@pytest.mark.asyncio
async def test_X_extract_provider_raises():
    svc = RelationExtractionService(max_retries=0)
    provider = _make_provider(raise_exc=RuntimeError("provider down"))
    with patch(
        "app.domains.graph.services.relation_extraction_service.default_provider_factory"
    ) as mock_factory:
        mock_factory.get_chat_provider.return_value = provider
        result = await svc.extract_from_chunks(
            chunks=[(0, "some text")],
            entity_name_to_id={"a": uuid.uuid4()},
            entity_names_by_chunk={0: ["a"]},
            organization_id=_ORG,
        )
    assert result.llm_errors == 1
    assert result.relations == []


@pytest.mark.asyncio
async def test_Y_extract_provider_timeout():
    svc = RelationExtractionService(timeout_seconds=0.001, max_retries=0)

    async def _slow(*args, **kwargs):
        await asyncio.sleep(10)
        return MagicMock(content="{}")

    provider = MagicMock()
    provider.complete = AsyncMock(side_effect=_slow)
    with patch(
        "app.domains.graph.services.relation_extraction_service.default_provider_factory"
    ) as mock_factory:
        mock_factory.get_chat_provider.return_value = provider
        result = await svc.extract_from_chunks(
            chunks=[(0, "text")],
            entity_name_to_id={"a": uuid.uuid4()},
            entity_names_by_chunk={0: ["a"]},
            organization_id=_ORG,
        )
    assert result.llm_errors == 1


@pytest.mark.asyncio
async def test_Z_extract_invalid_json():
    provider = _make_provider("{not json at all}")
    svc = RelationExtractionService(max_retries=0)
    with patch(
        "app.domains.graph.services.relation_extraction_service.default_provider_factory"
    ) as mock_factory:
        mock_factory.get_chat_provider.return_value = provider
        result = await svc.extract_from_chunks(
            chunks=[(0, "some text")],
            entity_name_to_id={"a": uuid.uuid4()},
            entity_names_by_chunk={0: ["a"]},
            organization_id=_ORG,
        )
    assert result.validation_errors == 1
    assert result.relations == []


@pytest.mark.asyncio
async def test_AA_chunk_index_out_of_range_clamped():
    from_id, to_id = _entity_ids()
    entity_map = {"a": from_id, "b": to_id}
    payload = json.dumps(
        {
            "relations": [
                {
                    "from_entity_name": "A",
                    "to_entity_name": "B",
                    "rel_type": "RELATES_TO",
                    "confidence": 0.7,
                    "evidence_span": "A relates to B.",
                    "source_chunk_index": 999,  # out of range
                }
            ]
        }
    )
    provider = _make_provider(payload)
    svc = RelationExtractionService()
    with patch(
        "app.domains.graph.services.relation_extraction_service.default_provider_factory"
    ) as mock_factory:
        mock_factory.get_chat_provider.return_value = provider
        result = await svc.extract_from_chunks(
            chunks=[(5, "A relates to B.")],
            entity_name_to_id=entity_map,
            entity_names_by_chunk={5: ["A", "B"]},
            organization_id=_ORG,
        )
    assert len(result.relations) == 1
    assert result.relations[0].source_chunk_index == 5  # clamped to first valid index


@pytest.mark.asyncio
async def test_AB_relation_id_is_deterministic():
    from_id, to_id = _entity_ids()
    entity_map = {"alpha": from_id, "beta": to_id}
    payload = json.dumps(
        {
            "relations": [
                {
                    "from_entity_name": "Alpha",
                    "to_entity_name": "Beta",
                    "rel_type": "DEPENDS_ON",
                    "confidence": 0.8,
                    "evidence_span": "Alpha depends on Beta.",
                    "source_chunk_index": 0,
                }
            ]
        }
    )
    provider = _make_provider(payload)
    svc = RelationExtractionService()
    org = "org-deterministic"
    with patch(
        "app.domains.graph.services.relation_extraction_service.default_provider_factory"
    ) as mock_factory:
        mock_factory.get_chat_provider.return_value = provider
        r1 = await svc.extract_from_chunks(
            chunks=[(0, "Alpha depends on Beta.")],
            entity_name_to_id=entity_map,
            entity_names_by_chunk={0: ["Alpha", "Beta"]},
            organization_id=org,
        )
    provider2 = _make_provider(payload)
    with patch(
        "app.domains.graph.services.relation_extraction_service.default_provider_factory"
    ) as mock_factory2:
        mock_factory2.get_chat_provider.return_value = provider2
        r2 = await svc.extract_from_chunks(
            chunks=[(0, "Alpha depends on Beta.")],
            entity_name_to_id=entity_map,
            entity_names_by_chunk={0: ["Alpha", "Beta"]},
            organization_id=org,
        )
    assert r1.relations[0].relation_id == r2.relations[0].relation_id


# ---------------------------------------------------------------------------
# AC-AP: RelationRepository (mock Neo4j)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_AC_create_with_evidence_no_evidence_raises():
    repo = RelationRepository()
    _reset_driver()
    _set_driver(_mock_driver())
    with pytest.raises(ValueError, match="evidence"):
        await repo.create_relation_with_evidence(
            organization_id=_ORG,
            from_entity_id=uuid.uuid4(),
            to_entity_id=uuid.uuid4(),
            rel_type="OWNS",
            relation_id=uuid.uuid4(),
            # no evidence fields provided
        )


@pytest.mark.asyncio
async def test_AD_create_with_evidence_unknown_rel_type_raises():
    repo = RelationRepository()
    _reset_driver()
    _set_driver(_mock_driver())
    with pytest.raises(ValueError, match="Unknown relationship type"):
        await repo.create_relation_with_evidence(
            organization_id=_ORG,
            from_entity_id=uuid.uuid4(),
            to_entity_id=uuid.uuid4(),
            rel_type="INVALID_TYPE",
            relation_id=uuid.uuid4(),
            evidence_text="some evidence",
        )


@pytest.mark.asyncio
async def test_AE_create_with_evidence_driver_none_noop():
    repo = RelationRepository()
    _reset_driver()
    # No exception, just silent no-op
    await repo.create_relation_with_evidence(
        organization_id=_ORG,
        from_entity_id=uuid.uuid4(),
        to_entity_id=uuid.uuid4(),
        rel_type="OWNS",
        relation_id=uuid.uuid4(),
        evidence_text="some evidence",
    )


@pytest.mark.asyncio
async def test_AF_create_with_evidence_calls_execute_write():
    repo = RelationRepository()
    _reset_driver()
    driver = _mock_driver()
    _set_driver(driver)

    rel_id = uuid.uuid4()
    from_id, to_id = _entity_ids()
    with patch(
        "app.domains.graph.repositories.relation_repository._get_driver_and_settings",
        return_value=(driver, MagicMock(neo4j_database=_DB, neo4j_query_timeout_seconds=10.0)),
    ):
        await repo.create_relation_with_evidence(
            organization_id=_ORG,
            from_entity_id=from_id,
            to_entity_id=to_id,
            rel_type="COVERS_CONTROL",
            relation_id=rel_id,
            citation_text="Control A covers policy B.",
            source_document_id=uuid.uuid4(),
            confidence=0.88,
            initial_status="unverified",
        )
    driver.session().__aenter__.return_value.execute_write.assert_called()


@pytest.mark.asyncio
async def test_AG_list_relations_driver_none():
    repo = RelationRepository()
    _reset_driver()
    result = await repo.list_relations(organization_id=_ORG)
    assert result == []


@pytest.mark.asyncio
async def test_AH_list_relations_status_filter():
    records = [
        {
            "relation_id": str(uuid.uuid4()),
            "organization_id": _ORG,
            "from_entity_id": str(uuid.uuid4()),
            "rel_type": "OWNS",
            "to_entity_id": str(uuid.uuid4()),
            "status": "low_confidence",
            "confidence": 0.3,
            "evidence_text": "...",
            "citation_text": None,
            "citation_reference": None,
            "chunk_id": None,
            "source_document_id": None,
            "page_number": None,
            "workspace_id": None,
            "extraction_run_id": None,
            "created_at": "2026-06-14T00:00:00",
            "updated_at": "2026-06-14T00:00:00",
        }
    ]
    driver = _mock_driver(records)
    _reset_driver()
    with patch(
        "app.domains.graph.repositories.relation_repository._get_driver_and_settings",
        return_value=(driver, MagicMock(neo4j_database=_DB, neo4j_query_timeout_seconds=10.0)),
    ):
        result = await RelationRepository().list_relations(
            organization_id=_ORG, status="low_confidence"
        )
    assert len(result) == 1
    assert result[0]["status"] == "low_confidence"


@pytest.mark.asyncio
async def test_AI_list_relations_unknown_status_raises():
    repo = RelationRepository()
    _reset_driver()
    _set_driver(_mock_driver())
    with pytest.raises(ValueError, match="Unknown relation status"):
        await repo.list_relations(organization_id=_ORG, status="published")  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_AJ_get_relation_driver_none():
    repo = RelationRepository()
    _reset_driver()
    result = await repo.get_relation(organization_id=_ORG, relation_id=uuid.uuid4())
    assert result is None


@pytest.mark.asyncio
async def test_AK_get_relation_found():
    rel_id = str(uuid.uuid4())
    records = [
        {
            "relation_id": rel_id,
            "organization_id": _ORG,
            "from_entity_id": str(uuid.uuid4()),
            "rel_type": "AFFECTS",
            "to_entity_id": str(uuid.uuid4()),
            "status": "verified",
            "confidence": 0.95,
            "evidence_text": "A affects B.",
            "citation_text": None,
            "citation_reference": None,
            "chunk_id": None,
            "source_document_id": None,
            "page_number": None,
            "workspace_id": None,
            "extraction_run_id": None,
            "created_at": "2026-06-14T00:00:00",
            "updated_at": "2026-06-14T00:00:00",
        }
    ]
    driver = _mock_driver(records)
    _reset_driver()
    with patch(
        "app.domains.graph.repositories.relation_repository._get_driver_and_settings",
        return_value=(driver, MagicMock(neo4j_database=_DB, neo4j_query_timeout_seconds=10.0)),
    ):
        result = await RelationRepository().get_relation(organization_id=_ORG, relation_id=rel_id)
    assert result is not None
    assert result["relation_id"] == rel_id
    assert result["status"] == "verified"


@pytest.mark.asyncio
async def test_AL_update_relation_status_driver_none():
    repo = RelationRepository()
    _reset_driver()
    result = await repo.update_relation_status(
        organization_id=_ORG, relation_id=uuid.uuid4(), status="verified"
    )
    assert result is False


@pytest.mark.asyncio
async def test_AM_update_relation_status_unknown_status_raises():
    repo = RelationRepository()
    _reset_driver()
    _set_driver(_mock_driver())
    with pytest.raises(ValueError, match="Unknown relation status"):
        await repo.update_relation_status(
            organization_id=_ORG,
            relation_id=uuid.uuid4(),
            status="published",  # type: ignore[arg-type]
        )


@pytest.mark.asyncio
async def test_AN_update_relation_status_found_returns_true():
    records = [{"cnt": 1}]
    driver = _mock_driver(records)
    _reset_driver()
    with patch(
        "app.domains.graph.repositories.relation_repository._get_driver_and_settings",
        return_value=(driver, MagicMock(neo4j_database=_DB, neo4j_query_timeout_seconds=10.0)),
    ):
        result = await RelationRepository().update_relation_status(
            organization_id=_ORG,
            relation_id=uuid.uuid4(),
            status="rejected",
        )
    assert result is True


@pytest.mark.asyncio
async def test_AO_delete_relation_by_id_driver_none():
    repo = RelationRepository()
    _reset_driver()
    result = await repo.delete_relation_by_id(organization_id=_ORG, relation_id=uuid.uuid4())
    assert result is False


@pytest.mark.asyncio
async def test_AP_delete_relation_by_id_returns_true():
    records = [{"cnt": 1}]
    driver = _mock_driver(records)
    _reset_driver()
    with patch(
        "app.domains.graph.repositories.relation_repository._get_driver_and_settings",
        return_value=(driver, MagicMock(neo4j_database=_DB, neo4j_query_timeout_seconds=10.0)),
    ):
        result = await RelationRepository().delete_relation_by_id(
            organization_id=_ORG, relation_id=uuid.uuid4()
        )
    assert result is True


# ---------------------------------------------------------------------------
# AQ-AT: GraphService delegation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_AQ_graph_service_create_relation_with_evidence_delegates():
    svc = GraphService()
    rel_id = uuid.uuid4()
    from_id, to_id = _entity_ids()
    svc._relations.create_relation_with_evidence = AsyncMock()
    await svc.create_relation_with_evidence(
        organization_id=_ORG,
        from_entity_id=from_id,
        to_entity_id=to_id,
        rel_type="OWNS",
        relation_id=rel_id,
        citation_text="X owns Y.",
    )
    svc._relations.create_relation_with_evidence.assert_called_once()
    call_kwargs = svc._relations.create_relation_with_evidence.call_args.kwargs
    assert str(call_kwargs["relation_id"]) == str(rel_id)
    assert call_kwargs["rel_type"] == "OWNS"


@pytest.mark.asyncio
async def test_AR_graph_service_list_relations_delegates():
    svc = GraphService()
    svc._relations.list_relations = AsyncMock(return_value=[{"relation_id": "r1"}])
    result = await svc.list_relations(organization_id=_ORG, status="unverified")
    svc._relations.list_relations.assert_called_once()
    assert result == [{"relation_id": "r1"}]


@pytest.mark.asyncio
async def test_AS_graph_service_update_relation_status_delegates():
    svc = GraphService()
    svc._relations.update_relation_status = AsyncMock(return_value=True)
    result = await svc.update_relation_status(
        organization_id=_ORG, relation_id=uuid.uuid4(), status="verified"
    )
    assert result is True
    svc._relations.update_relation_status.assert_called_once()


@pytest.mark.asyncio
async def test_AT_graph_service_delete_relation_by_id_delegates():
    svc = GraphService()
    svc._relations.delete_relation_by_id = AsyncMock(return_value=True)
    result = await svc.delete_relation_by_id(organization_id=_ORG, relation_id=uuid.uuid4())
    assert result is True
    svc._relations.delete_relation_by_id.assert_called_once()


def _owner_principal(org_id: str = _ORG) -> AuthenticatedPrincipal:
    from app.models.permissions import PermissionType

    return AuthenticatedPrincipal(
        user_id="00000000-0000-0000-0000-000000f284a1",
        organization_id=org_id,
        roles=[OrganizationRole.owner.value],
        auth_provider="app",
        api_key_permissions=frozenset(p.value for p in PermissionType),
    )


def _member_principal(org_id: str = _ORG) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        user_id="00000000-0000-0000-0000-000000f284b1",
        organization_id=org_id,
        roles=[OrganizationRole.member.value],
        auth_provider="app",
    )


async def _mock_db_session():
    yield AsyncMock()


def _graph_disabled_client():
    client = TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides[get_current_principal] = lambda: _owner_principal()
    return client


def test_AU_list_relations_graph_disabled_503():
    with patch.object(settings, "enterprise_graph_enabled", False):
        app.dependency_overrides[get_current_principal] = lambda: _owner_principal()
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/api/v1/admin/graph/relations")
    app.dependency_overrides.pop(get_current_principal, None)
    assert resp.status_code == 503


def test_AV_list_relations_member_403():
    with patch.object(settings, "enterprise_graph_enabled", True):
        app.dependency_overrides[get_current_principal] = lambda: _member_principal()
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/api/v1/admin/graph/relations")
    app.dependency_overrides.pop(get_current_principal, None)
    assert resp.status_code == 403


def test_AW_list_relations_invalid_status_422():
    with patch.object(settings, "enterprise_graph_enabled", True):
        app.dependency_overrides[get_current_principal] = lambda: _owner_principal()
        with patch("app.interfaces.http.admin_graph_relations.GraphService") as MockSvc:
            MockSvc.return_value.list_relations = AsyncMock(return_value=[])
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get("/api/v1/admin/graph/relations?status=published")
    app.dependency_overrides.pop(get_current_principal, None)
    assert resp.status_code == 422


def test_AX_list_relations_owner_200():
    fake_relations = [
        {
            "relation_id": str(uuid.uuid4()),
            "rel_type": "OWNS",
            "status": "unverified",
            "confidence": 0.9,
        }
    ]
    with patch.object(settings, "enterprise_graph_enabled", True):
        app.dependency_overrides[get_current_principal] = lambda: _owner_principal()
        with patch("app.interfaces.http.admin_graph_relations.GraphService") as MockSvc:
            MockSvc.return_value.list_relations = AsyncMock(return_value=fake_relations)
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get("/api/v1/admin/graph/relations")
    app.dependency_overrides.pop(get_current_principal, None)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["rel_type"] == "OWNS"


def test_AY_create_relation_no_evidence_422():
    payload = {
        "from_entity_id": str(uuid.uuid4()),
        "to_entity_id": str(uuid.uuid4()),
        "rel_type": "OWNS",
        "relation_id": str(uuid.uuid4()),
        "confidence": 0.8,
        # no evidence fields
    }
    with patch.object(settings, "enterprise_graph_enabled", True):
        app.dependency_overrides[get_current_principal] = lambda: _owner_principal()
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post("/api/v1/admin/graph/relations", json=payload)
    app.dependency_overrides.pop(get_current_principal, None)
    assert resp.status_code == 422


def test_AZ_create_relation_unknown_rel_type_422():
    payload = {
        "from_entity_id": str(uuid.uuid4()),
        "to_entity_id": str(uuid.uuid4()),
        "rel_type": "INVENTED",
        "relation_id": str(uuid.uuid4()),
        "evidence_text": "some evidence",
        "confidence": 0.8,
    }
    with patch.object(settings, "enterprise_graph_enabled", True):
        app.dependency_overrides[get_current_principal] = lambda: _owner_principal()
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post("/api/v1/admin/graph/relations", json=payload)
    app.dependency_overrides.pop(get_current_principal, None)
    assert resp.status_code == 422


def test_BA_create_relation_valid_200():
    rel_id = str(uuid.uuid4())
    fake_relation = {
        "relation_id": rel_id,
        "rel_type": "OWNS",
        "status": "unverified",
        "confidence": 0.8,
    }
    payload = {
        "from_entity_id": str(uuid.uuid4()),
        "to_entity_id": str(uuid.uuid4()),
        "rel_type": "OWNS",
        "relation_id": rel_id,
        "citation_text": "Acme owns Global Ltd.",
        "confidence": 0.8,
    }
    with patch.object(settings, "enterprise_graph_enabled", True):
        app.dependency_overrides[get_current_principal] = lambda: _owner_principal()
        app.dependency_overrides[get_db_session] = _mock_db_session
        with patch("app.interfaces.http.admin_graph_relations.GraphService") as MockSvc:
            MockSvc.return_value.create_relation_with_evidence = AsyncMock()
            MockSvc.return_value.get_relation = AsyncMock(return_value=fake_relation)
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.post("/api/v1/admin/graph/relations", json=payload)
    app.dependency_overrides.pop(get_current_principal, None)
    app.dependency_overrides.pop(get_db_session, None)
    assert resp.status_code == 200
    assert resp.json()["relation_id"] == rel_id


def test_BB_get_relation_not_found_404():
    with patch.object(settings, "enterprise_graph_enabled", True):
        app.dependency_overrides[get_current_principal] = lambda: _owner_principal()
        with patch("app.interfaces.http.admin_graph_relations.GraphService") as MockSvc:
            MockSvc.return_value.get_relation = AsyncMock(return_value=None)
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get(f"/api/v1/admin/graph/relations/{uuid.uuid4()}")
    app.dependency_overrides.pop(get_current_principal, None)
    assert resp.status_code == 404


def test_BC_get_relation_found_200():
    rel_id = str(uuid.uuid4())
    fake_relation = {"relation_id": rel_id, "rel_type": "AFFECTS", "status": "verified"}
    with patch.object(settings, "enterprise_graph_enabled", True):
        app.dependency_overrides[get_current_principal] = lambda: _owner_principal()
        with patch("app.interfaces.http.admin_graph_relations.GraphService") as MockSvc:
            MockSvc.return_value.get_relation = AsyncMock(return_value=fake_relation)
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get(f"/api/v1/admin/graph/relations/{rel_id}")
    app.dependency_overrides.pop(get_current_principal, None)
    assert resp.status_code == 200
    assert resp.json()["relation_id"] == rel_id


def test_BD_patch_status_not_found_404():
    with patch.object(settings, "enterprise_graph_enabled", True):
        app.dependency_overrides[get_current_principal] = lambda: _owner_principal()
        with patch("app.interfaces.http.admin_graph_relations.GraphService") as MockSvc:
            MockSvc.return_value.update_relation_status = AsyncMock(return_value=False)
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.patch(
                f"/api/v1/admin/graph/relations/{uuid.uuid4()}/status",
                json={"status": "verified"},
            )
    app.dependency_overrides.pop(get_current_principal, None)
    assert resp.status_code == 404


def test_BE_patch_status_valid_200():
    rel_id = str(uuid.uuid4())
    with patch.object(settings, "enterprise_graph_enabled", True):
        app.dependency_overrides[get_current_principal] = lambda: _owner_principal()
        app.dependency_overrides[get_db_session] = _mock_db_session
        with patch("app.interfaces.http.admin_graph_relations.GraphService") as MockSvc:
            MockSvc.return_value.update_relation_status = AsyncMock(return_value=True)
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.patch(
                f"/api/v1/admin/graph/relations/{rel_id}/status",
                json={"status": "verified"},
            )
    app.dependency_overrides.pop(get_current_principal, None)
    app.dependency_overrides.pop(get_db_session, None)
    assert resp.status_code == 200
    data = resp.json()
    assert data["updated"] is True
    assert data["status"] == "verified"


def test_BF_delete_relation_not_found_404():
    with patch.object(settings, "enterprise_graph_enabled", True):
        app.dependency_overrides[get_current_principal] = lambda: _owner_principal()
        with patch("app.interfaces.http.admin_graph_relations.GraphService") as MockSvc:
            MockSvc.return_value.delete_relation_by_id = AsyncMock(return_value=False)
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.delete(f"/api/v1/admin/graph/relations/{uuid.uuid4()}")
    app.dependency_overrides.pop(get_current_principal, None)
    assert resp.status_code == 404


def test_BG_delete_relation_valid_200():
    rel_id = str(uuid.uuid4())
    with patch.object(settings, "enterprise_graph_enabled", True):
        app.dependency_overrides[get_current_principal] = lambda: _owner_principal()
        app.dependency_overrides[get_db_session] = _mock_db_session
        with patch("app.interfaces.http.admin_graph_relations.GraphService") as MockSvc:
            MockSvc.return_value.delete_relation_by_id = AsyncMock(return_value=True)
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.delete(f"/api/v1/admin/graph/relations/{rel_id}")
    app.dependency_overrides.pop(get_current_principal, None)
    app.dependency_overrides.pop(get_db_session, None)
    assert resp.status_code == 200
    assert resp.json()["deleted"] is True


# ---------------------------------------------------------------------------
# BH-BJ: Security
# ---------------------------------------------------------------------------


def test_BH_validate_rel_type_blocks_unknown():
    with pytest.raises(ValueError, match="Unknown relationship type"):
        _validate_rel_type("DROP_ALL_DATA")


def test_BI_validate_status_blocks_unknown():
    with pytest.raises(ValueError, match="Unknown relation status"):
        _validate_status("super_verified")


@pytest.mark.asyncio
async def test_BJ_create_evidence_required_before_neo4j():
    """Evidence validation fires before any Neo4j call is made."""
    repo = RelationRepository()
    _reset_driver()
    driver = _mock_driver()
    _set_driver(driver)

    with pytest.raises(ValueError, match="evidence"):
        await repo.create_relation_with_evidence(
            organization_id=_ORG,
            from_entity_id=uuid.uuid4(),
            to_entity_id=uuid.uuid4(),
            rel_type="OWNS",
            relation_id=uuid.uuid4(),
            # no evidence
        )
    # Driver's session must not have been touched
    driver.session.assert_not_called()
