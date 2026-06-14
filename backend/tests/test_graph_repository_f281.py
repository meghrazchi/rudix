"""Backend tests for F281: Neo4j repository layer and graph service abstraction.

Covers:
  A.  EntityRepository.upsert_entity — graph disabled → no-op
  B.  EntityRepository.upsert_entity — driver None → no-op
  C.  EntityRepository.upsert_entity — success → execute_write called with org scope
  D.  EntityRepository.get_entity — graph disabled → None
  E.  EntityRepository.get_entity — driver None → None
  F.  EntityRepository.get_entity — not found → None
  G.  EntityRepository.get_entity — found → dict with org scope
  H.  EntityRepository.list_entities — with entity_type filter
  I.  EntityRepository.list_entities — with workspace_id filter
  J.  EntityRepository.delete_entity — removes entity, returns True
  K.  EntityRepository.delete_entity — missing entity, returns False

  L.  DocumentGraphRepository.upsert_document_node — graph disabled → no-op
  M.  DocumentGraphRepository.get_document_node — found → dict
  N.  DocumentGraphRepository.delete_document_node — removed → True

  O.  RelationRepository.create_relation — unknown rel_type → ValueError
  P.  RelationRepository.create_relation — valid rel_type → execute_write called
  Q.  RelationRepository.get_entity_relations — direction=out → correct edge pattern
  R.  RelationRepository.delete_relation — unknown rel_type → ValueError
  S.  RelationRepository.delete_relation — removed → True

  T.  EvidenceRepository.link_evidence — graph disabled → no-op
  U.  EvidenceRepository.link_evidence — success → execute_write called
  V.  EvidenceRepository.get_entity_evidence — returns list
  W.  EvidenceRepository.delete_evidence_for_chunk — returns count

  X.  ExtractionRunRepository.create_extraction_run — graph disabled → no-op
  Y.  ExtractionRunRepository.create_extraction_run — success → execute_write called
  Z.  ExtractionRunRepository.update_extraction_run — updates status
  AA. ExtractionRunRepository.get_extraction_runs — returns list

  AB. GraphRAGRepository.find_related_entities — empty ids → []
  AC. GraphRAGRepository.find_related_entities — driver None → []
  AD. GraphRAGRepository.find_related_entities — depth clamped to 1-5
  AE. GraphRAGRepository.find_entities_by_name — driver None → []
  AF. GraphRAGRepository.find_entities_by_name — with entity_type filter
  AG. GraphRAGRepository.get_evidence_for_entities — empty ids → []
  AH. GraphRAGRepository.get_evidence_for_entities — returns list

  AI. GraphService.is_available — disabled → False
  AJ. GraphService.is_available — enabled + driver None → False
  AK. GraphService.is_available — enabled + driver active → True
  AL. GraphService delegates upsert_entity to EntityRepository
  AM. GraphService delegates list_entities to EntityRepository
  AN. GraphService delegates create_relation (valid type) to RelationRepository
  AO. GraphService delegates link_evidence to EvidenceRepository
  AP. GraphService delegates start_extraction_run to ExtractionRunRepository
  AQ. GraphService delegates find_related_entities to GraphRAGRepository

  AR. GET /admin/graph/entities — graph disabled → 503
  AS. GET /admin/graph/entities — member role → 403
  AT. GET /admin/graph/entities — owner role → 200 list
  AU. POST /admin/graph/entities — graph disabled → 503
  AV. POST /admin/graph/entities — owner role → 200 entity dict
  AW. GET /admin/graph/entities/{id} — not found → 404
  AX. GET /admin/graph/entities/{id} — found → 200
  AY. DELETE /admin/graph/entities/{id} — owner → 200 {deleted:true}
  AZ. GET /admin/graph/entities/{id}/evidence — returns evidence list
  BA. GET /admin/graph/entities/{id}/relations — bad rel_type → 422
  BB. GET /admin/graph/entities/{id}/relations — valid → 200
  BC. GET /admin/graph/documents/{id}/extraction-runs — returns list

  Security:
  BD. EntityRepository.list_entities WHERE clause always includes organization_id
  BE. EntityRepository.get_entity always binds org param
  BF. RelationRepository blocks unknown rel_type strings (injection guard)
  BG. GraphRAGRepository.find_related_entities always binds org param
  BH. GraphRAGRepository depth clamped — never unbounded traversal

Run:
    pytest tests/test_graph_repository_f281.py -v
"""

from __future__ import annotations

import os
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

from fastapi.testclient import TestClient

from app.auth.dependencies import get_current_principal
from app.auth.models import AuthenticatedPrincipal
from app.core.config import settings
from app.domains.graph.repositories.entity_repository import EntityRepository
from app.domains.graph.repositories.document_repository import DocumentGraphRepository
from app.domains.graph.repositories.relation_repository import RelationRepository
from app.domains.graph.repositories.evidence_repository import EvidenceRepository
from app.domains.graph.repositories.extraction_run_repository import ExtractionRunRepository
from app.domains.graph.repositories.graphrag_repository import GraphRAGRepository
from app.domains.graph.services.graph_service import GraphService
from app.main import app

import app.clients.neo4j_client as neo4j_module

_ORG = "org-test-f281"
_WS = "ws-test-f281"
_DB = "neo4j"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _reset_driver() -> None:
    neo4j_module._neo4j_driver = None


def _mock_driver(records: list[dict] | None = None) -> MagicMock:
    """Return a mock driver whose session returns parameterized records."""
    record_data = records if records is not None else []

    result_mock = AsyncMock()
    result_mock.data = AsyncMock(return_value=record_data)
    result_mock.consume = AsyncMock()

    session_mock = AsyncMock()
    session_mock.run = AsyncMock(return_value=result_mock)
    session_mock.execute_write = AsyncMock(return_value=None)
    session_mock.execute_read = AsyncMock(return_value=None)
    session_mock.__aenter__ = AsyncMock(return_value=session_mock)
    session_mock.__aexit__ = AsyncMock(return_value=False)

    driver_mock = MagicMock()
    driver_mock.session = MagicMock(return_value=session_mock)
    return driver_mock


def _principal_override(role: str = "owner"):
    async def _dep() -> AuthenticatedPrincipal:
        return AuthenticatedPrincipal(
            user_id="test-user",
            organization_id=_ORG,
            roles=[role],
            auth_provider="app",
        )

    return _dep



# ---------------------------------------------------------------------------
# A. EntityRepository.upsert_entity — graph disabled → no-op
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_entity_upsert_disabled():
    _reset_driver()
    with patch.object(settings, "enterprise_graph_enabled", False):
        repo = EntityRepository()
        # Should not raise and should not call any driver
        await repo.upsert_entity(
            organization_id=_ORG,
            entity_id="e-001",
            entity_type="Organization",
            canonical_name="Acme",
        )


# ---------------------------------------------------------------------------
# B. EntityRepository.upsert_entity — driver None → no-op
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_b_entity_upsert_driver_none():
    _reset_driver()
    with patch.object(settings, "enterprise_graph_enabled", True):
        repo = EntityRepository()
        await repo.upsert_entity(
            organization_id=_ORG,
            entity_id="e-001",
            entity_type="Organization",
            canonical_name="Acme",
        )


# ---------------------------------------------------------------------------
# C. EntityRepository.upsert_entity — success → execute_write called with org scope
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_c_entity_upsert_success():
    driver = _mock_driver()
    with patch.object(settings, "enterprise_graph_enabled", True), patch.object(
        settings, "neo4j_database", _DB
    ), patch.object(neo4j_module, "_neo4j_driver", driver):
        repo = EntityRepository()
        await repo.upsert_entity(
            organization_id=_ORG,
            entity_id="e-001",
            entity_type="Organization",
            canonical_name="Acme",
        )
        session = driver.session.return_value.__aenter__.return_value
        session.execute_write.assert_called_once()
        # Verify the transaction function receives org-scoped params
        tx_fn = session.execute_write.call_args[0][0]
        tx_mock = AsyncMock()
        await tx_fn(tx_mock)
        call_kwargs = tx_mock.run.call_args[1]
        assert call_kwargs["organization_id"] == _ORG
        assert call_kwargs["entity_id"] == "e-001"


# ---------------------------------------------------------------------------
# D–F. EntityRepository.get_entity edge cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_d_entity_get_disabled():
    _reset_driver()
    with patch.object(settings, "enterprise_graph_enabled", False):
        result = await EntityRepository().get_entity(organization_id=_ORG, entity_id="e-001")
        assert result is None


@pytest.mark.asyncio
async def test_e_entity_get_driver_none():
    _reset_driver()
    with patch.object(settings, "enterprise_graph_enabled", True):
        result = await EntityRepository().get_entity(organization_id=_ORG, entity_id="e-001")
        assert result is None


@pytest.mark.asyncio
async def test_f_entity_get_not_found():
    driver = _mock_driver(records=[])
    with patch.object(settings, "enterprise_graph_enabled", True), patch.object(
        settings, "neo4j_database", _DB
    ), patch.object(settings, "neo4j_query_timeout_seconds", 5.0), patch.object(
        neo4j_module, "_neo4j_driver", driver
    ):
        result = await EntityRepository().get_entity(organization_id=_ORG, entity_id="missing")
        assert result is None


# ---------------------------------------------------------------------------
# G. EntityRepository.get_entity — found → dict scoped to org
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_g_entity_get_found():
    entity_data = {
        "organization_id": _ORG,
        "entity_id": "e-001",
        "entity_type": "Organization",
        "canonical_name": "Acme",
    }
    driver = _mock_driver(records=[{"entity": entity_data}])
    with patch.object(settings, "enterprise_graph_enabled", True), patch.object(
        settings, "neo4j_database", _DB
    ), patch.object(settings, "neo4j_query_timeout_seconds", 5.0), patch.object(
        neo4j_module, "_neo4j_driver", driver
    ):
        result = await EntityRepository().get_entity(organization_id=_ORG, entity_id="e-001")
        assert result is not None
        assert result["entity_id"] == "e-001"
        assert result["organization_id"] == _ORG

        # Verify the query used org-scoped params
        session = driver.session.return_value.__aenter__.return_value
        call_kwargs = session.run.call_args[1]
        assert call_kwargs["organization_id"] == _ORG


# ---------------------------------------------------------------------------
# H. EntityRepository.list_entities — entity_type filter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_h_entity_list_entity_type_filter():
    entity_data = {
        "organization_id": _ORG,
        "entity_id": "e-002",
        "entity_type": "Policy",
        "canonical_name": "Privacy Policy",
    }
    driver = _mock_driver(records=[{"entity": entity_data}])
    with patch.object(settings, "enterprise_graph_enabled", True), patch.object(
        settings, "neo4j_database", _DB
    ), patch.object(settings, "neo4j_query_timeout_seconds", 5.0), patch.object(
        neo4j_module, "_neo4j_driver", driver
    ):
        results = await EntityRepository().list_entities(
            organization_id=_ORG,
            entity_type="Policy",
        )
        assert len(results) == 1

        # Confirm entity_type param is in the call
        session = driver.session.return_value.__aenter__.return_value
        call_kwargs = session.run.call_args[1]
        assert call_kwargs["organization_id"] == _ORG
        assert call_kwargs["entity_type"] == "Policy"


# ---------------------------------------------------------------------------
# I. EntityRepository.list_entities — workspace_id filter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_i_entity_list_workspace_filter():
    driver = _mock_driver(records=[])
    with patch.object(settings, "enterprise_graph_enabled", True), patch.object(
        settings, "neo4j_database", _DB
    ), patch.object(settings, "neo4j_query_timeout_seconds", 5.0), patch.object(
        neo4j_module, "_neo4j_driver", driver
    ):
        await EntityRepository().list_entities(
            organization_id=_ORG,
            workspace_id=_WS,
        )
        session = driver.session.return_value.__aenter__.return_value
        call_kwargs = session.run.call_args[1]
        assert call_kwargs["workspace_id"] == _WS


# ---------------------------------------------------------------------------
# J–K. EntityRepository.delete_entity
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_j_entity_delete_found():
    async def _write_fn(tx_fn):
        tx = AsyncMock()
        result = AsyncMock()
        result.data = AsyncMock(return_value=[{"cnt": 1}])
        tx.run = AsyncMock(return_value=result)
        return await tx_fn(tx)

    driver = MagicMock()
    session_mock = AsyncMock()
    session_mock.execute_write = AsyncMock(side_effect=_write_fn)
    session_mock.__aenter__ = AsyncMock(return_value=session_mock)
    session_mock.__aexit__ = AsyncMock(return_value=False)
    driver.session = MagicMock(return_value=session_mock)

    with patch.object(settings, "enterprise_graph_enabled", True), patch.object(
        settings, "neo4j_database", _DB
    ), patch.object(neo4j_module, "_neo4j_driver", driver):
        deleted = await EntityRepository().delete_entity(organization_id=_ORG, entity_id="e-001")
        assert deleted is True


@pytest.mark.asyncio
async def test_k_entity_delete_missing():
    async def _write_fn(tx_fn):
        tx = AsyncMock()
        result = AsyncMock()
        result.data = AsyncMock(return_value=[{"cnt": 0}])
        tx.run = AsyncMock(return_value=result)
        return await tx_fn(tx)

    driver = MagicMock()
    session_mock = AsyncMock()
    session_mock.execute_write = AsyncMock(side_effect=_write_fn)
    session_mock.__aenter__ = AsyncMock(return_value=session_mock)
    session_mock.__aexit__ = AsyncMock(return_value=False)
    driver.session = MagicMock(return_value=session_mock)

    with patch.object(settings, "enterprise_graph_enabled", True), patch.object(
        settings, "neo4j_database", _DB
    ), patch.object(neo4j_module, "_neo4j_driver", driver):
        deleted = await EntityRepository().delete_entity(organization_id=_ORG, entity_id="missing")
        assert deleted is False


# ---------------------------------------------------------------------------
# L–N. DocumentGraphRepository
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_l_document_upsert_disabled():
    _reset_driver()
    with patch.object(settings, "enterprise_graph_enabled", False):
        await DocumentGraphRepository().upsert_document_node(
            organization_id=_ORG, document_id="doc-001"
        )


@pytest.mark.asyncio
async def test_m_document_get_found():
    doc_data = {"organization_id": _ORG, "document_id": "doc-001", "title": "Test"}
    driver = _mock_driver(records=[{"doc": doc_data}])
    with patch.object(settings, "enterprise_graph_enabled", True), patch.object(
        settings, "neo4j_database", _DB
    ), patch.object(settings, "neo4j_query_timeout_seconds", 5.0), patch.object(
        neo4j_module, "_neo4j_driver", driver
    ):
        result = await DocumentGraphRepository().get_document_node(
            organization_id=_ORG, document_id="doc-001"
        )
        assert result is not None
        assert result["document_id"] == "doc-001"


@pytest.mark.asyncio
async def test_n_document_delete():
    async def _write_fn(tx_fn):
        tx = AsyncMock()
        result = AsyncMock()
        result.data = AsyncMock(return_value=[{"cnt": 1}])
        tx.run = AsyncMock(return_value=result)
        return await tx_fn(tx)

    driver = MagicMock()
    session_mock = AsyncMock()
    session_mock.execute_write = AsyncMock(side_effect=_write_fn)
    session_mock.__aenter__ = AsyncMock(return_value=session_mock)
    session_mock.__aexit__ = AsyncMock(return_value=False)
    driver.session = MagicMock(return_value=session_mock)

    with patch.object(settings, "enterprise_graph_enabled", True), patch.object(
        settings, "neo4j_database", _DB
    ), patch.object(neo4j_module, "_neo4j_driver", driver):
        deleted = await DocumentGraphRepository().delete_document_node(
            organization_id=_ORG, document_id="doc-001"
        )
        assert deleted is True


# ---------------------------------------------------------------------------
# O–S. RelationRepository
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_o_relation_unknown_type_raises():
    with pytest.raises(ValueError, match="Unknown relationship type"):
        await RelationRepository().create_relation(
            organization_id=_ORG,
            from_entity_id="e-001",
            to_entity_id="e-002",
            rel_type="INVENTED_RELATION",
        )


@pytest.mark.asyncio
async def test_p_relation_create_valid():
    driver = _mock_driver()
    with patch.object(settings, "enterprise_graph_enabled", True), patch.object(
        settings, "neo4j_database", _DB
    ), patch.object(neo4j_module, "_neo4j_driver", driver):
        await RelationRepository().create_relation(
            organization_id=_ORG,
            from_entity_id="e-001",
            to_entity_id="e-002",
            rel_type="RELATES_TO",
        )
        session = driver.session.return_value.__aenter__.return_value
        session.execute_write.assert_called_once()


@pytest.mark.asyncio
async def test_q_relation_get_out_direction():
    driver = _mock_driver(records=[])
    with patch.object(settings, "enterprise_graph_enabled", True), patch.object(
        settings, "neo4j_database", _DB
    ), patch.object(settings, "neo4j_query_timeout_seconds", 5.0), patch.object(
        neo4j_module, "_neo4j_driver", driver
    ):
        await RelationRepository().get_entity_relations(
            organization_id=_ORG,
            entity_id="e-001",
            direction="out",
        )
        session = driver.session.return_value.__aenter__.return_value
        cypher_call = session.run.call_args[0][0]
        assert "-[r]->" in cypher_call


@pytest.mark.asyncio
async def test_r_relation_delete_unknown_type_raises():
    with pytest.raises(ValueError, match="Unknown relationship type"):
        await RelationRepository().delete_relation(
            organization_id=_ORG,
            from_entity_id="e-001",
            to_entity_id="e-002",
            rel_type="EVIL_TYPE",
        )


@pytest.mark.asyncio
async def test_s_relation_delete_success():
    async def _write_fn(tx_fn):
        tx = AsyncMock()
        result = AsyncMock()
        result.data = AsyncMock(return_value=[{"cnt": 1}])
        tx.run = AsyncMock(return_value=result)
        return await tx_fn(tx)

    driver = MagicMock()
    session_mock = AsyncMock()
    session_mock.execute_write = AsyncMock(side_effect=_write_fn)
    session_mock.__aenter__ = AsyncMock(return_value=session_mock)
    session_mock.__aexit__ = AsyncMock(return_value=False)
    driver.session = MagicMock(return_value=session_mock)

    with patch.object(settings, "enterprise_graph_enabled", True), patch.object(
        settings, "neo4j_database", _DB
    ), patch.object(neo4j_module, "_neo4j_driver", driver):
        deleted = await RelationRepository().delete_relation(
            organization_id=_ORG,
            from_entity_id="e-001",
            to_entity_id="e-002",
            rel_type="RELATES_TO",
        )
        assert deleted is True


# ---------------------------------------------------------------------------
# T–W. EvidenceRepository
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_t_evidence_link_disabled():
    _reset_driver()
    with patch.object(settings, "enterprise_graph_enabled", False):
        await EvidenceRepository().link_evidence(
            organization_id=_ORG,
            entity_id="e-001",
            chunk_id="c-001",
            source_document_id="doc-001",
        )


@pytest.mark.asyncio
async def test_u_evidence_link_success():
    driver = _mock_driver()
    with patch.object(settings, "enterprise_graph_enabled", True), patch.object(
        settings, "neo4j_database", _DB
    ), patch.object(neo4j_module, "_neo4j_driver", driver):
        await EvidenceRepository().link_evidence(
            organization_id=_ORG,
            entity_id="e-001",
            chunk_id="c-001",
            source_document_id="doc-001",
            confidence=0.9,
            evidence_text="Acme Corp provides services.",
        )
        session = driver.session.return_value.__aenter__.return_value
        session.execute_write.assert_called_once()
        tx_fn = session.execute_write.call_args[0][0]
        tx_mock = AsyncMock()
        await tx_fn(tx_mock)
        call_kwargs = tx_mock.run.call_args[1]
        assert call_kwargs["organization_id"] == _ORG
        assert call_kwargs["confidence"] == 0.9


@pytest.mark.asyncio
async def test_v_evidence_get_list():
    ev_records = [
        {
            "chunk_id": "c-001",
            "source_document_id": "doc-001",
            "confidence": 0.9,
            "evidence_text": "...",
            "created_at": "2026-06-14T00:00:00+00:00",
        }
    ]
    driver = _mock_driver(records=ev_records)
    with patch.object(settings, "enterprise_graph_enabled", True), patch.object(
        settings, "neo4j_database", _DB
    ), patch.object(settings, "neo4j_query_timeout_seconds", 5.0), patch.object(
        neo4j_module, "_neo4j_driver", driver
    ):
        results = await EvidenceRepository().get_entity_evidence(
            organization_id=_ORG, entity_id="e-001"
        )
        assert len(results) == 1
        assert results[0]["chunk_id"] == "c-001"


@pytest.mark.asyncio
async def test_w_evidence_delete_for_chunk():
    async def _write_fn(tx_fn):
        tx = AsyncMock()
        result = AsyncMock()
        result.data = AsyncMock(return_value=[{"cnt": 3}])
        tx.run = AsyncMock(return_value=result)
        return await tx_fn(tx)

    driver = MagicMock()
    session_mock = AsyncMock()
    session_mock.execute_write = AsyncMock(side_effect=_write_fn)
    session_mock.__aenter__ = AsyncMock(return_value=session_mock)
    session_mock.__aexit__ = AsyncMock(return_value=False)
    driver.session = MagicMock(return_value=session_mock)

    with patch.object(settings, "enterprise_graph_enabled", True), patch.object(
        settings, "neo4j_database", _DB
    ), patch.object(neo4j_module, "_neo4j_driver", driver):
        cnt = await EvidenceRepository().delete_evidence_for_chunk(
            organization_id=_ORG, chunk_id="c-001"
        )
        assert cnt == 3


# ---------------------------------------------------------------------------
# X–AA. ExtractionRunRepository
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_x_extraction_run_disabled():
    _reset_driver()
    with patch.object(settings, "enterprise_graph_enabled", False):
        await ExtractionRunRepository().create_extraction_run(
            organization_id=_ORG,
            document_id="doc-001",
            run_id="run-001",
            strategy="default",
        )


@pytest.mark.asyncio
async def test_y_extraction_run_create():
    driver = _mock_driver()
    with patch.object(settings, "enterprise_graph_enabled", True), patch.object(
        settings, "neo4j_database", _DB
    ), patch.object(neo4j_module, "_neo4j_driver", driver):
        await ExtractionRunRepository().create_extraction_run(
            organization_id=_ORG,
            document_id="doc-001",
            run_id="run-001",
            strategy="default",
        )
        session = driver.session.return_value.__aenter__.return_value
        session.execute_write.assert_called_once()
        tx_fn = session.execute_write.call_args[0][0]
        tx_mock = AsyncMock()
        await tx_fn(tx_mock)
        call_kwargs = tx_mock.run.call_args[1]
        assert call_kwargs["organization_id"] == _ORG
        assert call_kwargs["status"] == "running"


@pytest.mark.asyncio
async def test_z_extraction_run_update():
    driver = _mock_driver()
    with patch.object(settings, "enterprise_graph_enabled", True), patch.object(
        settings, "neo4j_database", _DB
    ), patch.object(neo4j_module, "_neo4j_driver", driver):
        await ExtractionRunRepository().update_extraction_run(
            organization_id=_ORG,
            run_id="run-001",
            status="completed",
            entity_count=42,
        )
        session = driver.session.return_value.__aenter__.return_value
        session.execute_write.assert_called_once()
        tx_fn = session.execute_write.call_args[0][0]
        tx_mock = AsyncMock()
        await tx_fn(tx_mock)
        call_kwargs = tx_mock.run.call_args[1]
        assert call_kwargs["status"] == "completed"
        assert call_kwargs["entity_count"] == 42


@pytest.mark.asyncio
async def test_aa_extraction_run_list():
    run_data = [
        {
            "run": {
                "run_id": "run-001",
                "document_id": "doc-001",
                "strategy": "default",
                "status": "completed",
                "entity_count": 5,
            }
        }
    ]
    driver = _mock_driver(records=run_data)
    with patch.object(settings, "enterprise_graph_enabled", True), patch.object(
        settings, "neo4j_database", _DB
    ), patch.object(settings, "neo4j_query_timeout_seconds", 5.0), patch.object(
        neo4j_module, "_neo4j_driver", driver
    ):
        results = await ExtractionRunRepository().get_extraction_runs(
            organization_id=_ORG, document_id="doc-001"
        )
        assert len(results) == 1
        assert results[0]["status"] == "completed"


# ---------------------------------------------------------------------------
# AB–AH. GraphRAGRepository
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ab_graphrag_empty_ids():
    result = await GraphRAGRepository().find_related_entities(
        organization_id=_ORG, entity_ids=[]
    )
    assert result == []


@pytest.mark.asyncio
async def test_ac_graphrag_driver_none():
    _reset_driver()
    with patch.object(settings, "enterprise_graph_enabled", True):
        result = await GraphRAGRepository().find_related_entities(
            organization_id=_ORG, entity_ids=["e-001"]
        )
        assert result == []


@pytest.mark.asyncio
async def test_ad_graphrag_depth_clamped():
    """depth > 5 must be clamped to 5; depth < 1 clamped to 1."""
    driver = _mock_driver(records=[])
    with patch.object(settings, "enterprise_graph_enabled", True), patch.object(
        settings, "neo4j_database", _DB
    ), patch.object(settings, "neo4j_query_timeout_seconds", 5.0), patch.object(
        neo4j_module, "_neo4j_driver", driver
    ):
        # depth=99 → safe_depth should be 5
        await GraphRAGRepository().find_related_entities(
            organization_id=_ORG, entity_ids=["e-001"], depth=99
        )
        session = driver.session.return_value.__aenter__.return_value
        cypher = session.run.call_args[0][0]
        assert "[*1..5]" in cypher

        # depth=0 → safe_depth should be 1
        await GraphRAGRepository().find_related_entities(
            organization_id=_ORG, entity_ids=["e-001"], depth=0
        )
        cypher2 = session.run.call_args[0][0]
        assert "[*1..1]" in cypher2


@pytest.mark.asyncio
async def test_ae_graphrag_name_search_driver_none():
    _reset_driver()
    with patch.object(settings, "enterprise_graph_enabled", True):
        result = await GraphRAGRepository().find_entities_by_name(
            organization_id=_ORG, name_query="acme"
        )
        assert result == []


@pytest.mark.asyncio
async def test_af_graphrag_name_search_entity_type_filter():
    driver = _mock_driver(records=[])
    with patch.object(settings, "enterprise_graph_enabled", True), patch.object(
        settings, "neo4j_database", _DB
    ), patch.object(settings, "neo4j_query_timeout_seconds", 5.0), patch.object(
        neo4j_module, "_neo4j_driver", driver
    ):
        await GraphRAGRepository().find_entities_by_name(
            organization_id=_ORG, name_query="acme", entity_type="Organization"
        )
        session = driver.session.return_value.__aenter__.return_value
        call_kwargs = session.run.call_args[1]
        assert call_kwargs["organization_id"] == _ORG
        assert call_kwargs["entity_type"] == "Organization"


@pytest.mark.asyncio
async def test_ag_graphrag_evidence_empty_ids():
    result = await GraphRAGRepository().get_evidence_for_entities(
        organization_id=_ORG, entity_ids=[]
    )
    assert result == []


@pytest.mark.asyncio
async def test_ah_graphrag_evidence_returns_list():
    ev_records = [
        {
            "entity_id": "e-001",
            "chunk_id": "c-001",
            "source_document_id": "doc-001",
            "confidence": 0.85,
            "evidence_text": "Acme",
        }
    ]
    driver = _mock_driver(records=ev_records)
    with patch.object(settings, "enterprise_graph_enabled", True), patch.object(
        settings, "neo4j_database", _DB
    ), patch.object(settings, "neo4j_query_timeout_seconds", 5.0), patch.object(
        neo4j_module, "_neo4j_driver", driver
    ):
        results = await GraphRAGRepository().get_evidence_for_entities(
            organization_id=_ORG, entity_ids=["e-001"]
        )
        assert len(results) == 1
        assert results[0]["entity_id"] == "e-001"
        call_kwargs = driver.session.return_value.__aenter__.return_value.run.call_args[1]
        assert call_kwargs["organization_id"] == _ORG


# ---------------------------------------------------------------------------
# AI–AQ. GraphService
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ai_service_not_available_disabled():
    _reset_driver()
    with patch.object(settings, "enterprise_graph_enabled", False):
        svc = GraphService()
        assert svc.is_available() is False


@pytest.mark.asyncio
async def test_aj_service_not_available_driver_none():
    _reset_driver()
    with patch.object(settings, "enterprise_graph_enabled", True):
        svc = GraphService()
        assert svc.is_available() is False


@pytest.mark.asyncio
async def test_ak_service_available():
    driver = _mock_driver()
    with patch.object(settings, "enterprise_graph_enabled", True), patch.object(
        neo4j_module, "_neo4j_driver", driver
    ):
        svc = GraphService()
        assert svc.is_available() is True


@pytest.mark.asyncio
async def test_al_service_delegates_upsert_entity():
    upsert_mock = AsyncMock()
    svc = GraphService()
    svc._entities.upsert_entity = upsert_mock
    await svc.upsert_entity(
        organization_id=_ORG, entity_id="e-001", entity_type="Policy", canonical_name="P1"
    )
    upsert_mock.assert_awaited_once()
    kwargs = upsert_mock.call_args[1]
    assert kwargs["organization_id"] == _ORG


@pytest.mark.asyncio
async def test_am_service_delegates_list_entities():
    list_mock = AsyncMock(return_value=[])
    svc = GraphService()
    svc._entities.list_entities = list_mock
    result = await svc.list_entities(organization_id=_ORG, entity_type="Policy")
    list_mock.assert_awaited_once()
    assert result == []


@pytest.mark.asyncio
async def test_an_service_delegates_create_relation_valid():
    create_mock = AsyncMock()
    svc = GraphService()
    svc._relations.create_relation = create_mock
    await svc.create_relation(
        organization_id=_ORG,
        from_entity_id="e-001",
        to_entity_id="e-002",
        rel_type="RELATES_TO",
    )
    create_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_ao_service_delegates_link_evidence():
    link_mock = AsyncMock()
    svc = GraphService()
    svc._evidence.link_evidence = link_mock
    await svc.link_evidence(
        organization_id=_ORG,
        entity_id="e-001",
        chunk_id="c-001",
        source_document_id="doc-001",
    )
    link_mock.assert_awaited_once()
    assert link_mock.call_args[1]["organization_id"] == _ORG


@pytest.mark.asyncio
async def test_ap_service_delegates_start_extraction_run():
    create_mock = AsyncMock()
    svc = GraphService()
    svc._extraction_runs.create_extraction_run = create_mock
    await svc.start_extraction_run(
        organization_id=_ORG, document_id="doc-001", run_id="run-001", strategy="default"
    )
    create_mock.assert_awaited_once()
    assert create_mock.call_args[1]["status"] == "running"


@pytest.mark.asyncio
async def test_aq_service_delegates_find_related_entities():
    find_mock = AsyncMock(return_value=[])
    svc = GraphService()
    svc._graphrag.find_related_entities = find_mock
    result = await svc.find_related_entities(organization_id=_ORG, entity_ids=["e-001"])
    find_mock.assert_awaited_once()
    assert result == []


# ---------------------------------------------------------------------------
# AR–BC. HTTP endpoint tests
# ---------------------------------------------------------------------------

_BASE = "/api/v1/admin/graph"


def _svc_mock(**overrides: Any) -> MagicMock:
    """Build a GraphService mock with safe defaults."""
    svc = MagicMock(spec=GraphService)
    svc.list_entities = AsyncMock(return_value=[])
    svc.upsert_entity = AsyncMock()
    svc.get_entity = AsyncMock(return_value=None)
    svc.delete_entity = AsyncMock(return_value=False)
    svc.get_entity_evidence = AsyncMock(return_value=[])
    svc.get_entity_relations = AsyncMock(return_value=[])
    svc.get_document_extraction_runs = AsyncMock(return_value=[])
    for k, v in overrides.items():
        setattr(svc, k, v)
    return svc


def test_ar_list_entities_graph_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "enterprise_graph_enabled", False)
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    app.dependency_overrides[get_current_principal] = _principal_override("owner")
    try:
        client = TestClient(app)
        resp = client.get(f"{_BASE}/entities")
        assert resp.status_code == 503
        assert "enterprise_graph_disabled" in resp.json()["detail"]
    finally:
        app.dependency_overrides.pop(get_current_principal, None)


def test_as_list_entities_member_forbidden(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "enterprise_graph_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    app.dependency_overrides[get_current_principal] = _principal_override("member")
    try:
        client = TestClient(app)
        resp = client.get(f"{_BASE}/entities")
        assert resp.status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_principal, None)


def test_at_list_entities_owner_success(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.interfaces.http.admin_graph_entities as ent_module

    monkeypatch.setattr(settings, "enterprise_graph_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    svc = _svc_mock(list_entities=AsyncMock(return_value=[{"entity_id": "e-001"}]))
    monkeypatch.setattr(ent_module, "_graph_service", lambda: svc)
    app.dependency_overrides[get_current_principal] = _principal_override("owner")
    try:
        client = TestClient(app)
        resp = client.get(f"{_BASE}/entities")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["entity_id"] == "e-001"
    finally:
        app.dependency_overrides.pop(get_current_principal, None)


def test_au_upsert_entity_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "enterprise_graph_enabled", False)
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    app.dependency_overrides[get_current_principal] = _principal_override("owner")
    try:
        client = TestClient(app)
        resp = client.post(
            f"{_BASE}/entities",
            json={"entity_id": "e-001", "entity_type": "Organization", "canonical_name": "Acme"},
        )
        assert resp.status_code == 503
    finally:
        app.dependency_overrides.pop(get_current_principal, None)


def test_av_upsert_entity_success(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.interfaces.http.admin_graph_entities as ent_module

    entity = {"entity_id": "e-001", "entity_type": "Organization", "canonical_name": "Acme", "organization_id": _ORG}
    monkeypatch.setattr(settings, "enterprise_graph_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    svc = _svc_mock(get_entity=AsyncMock(return_value=entity))
    monkeypatch.setattr(ent_module, "_graph_service", lambda: svc)
    app.dependency_overrides[get_current_principal] = _principal_override("owner")
    try:
        client = TestClient(app)
        resp = client.post(
            f"{_BASE}/entities",
            json={"entity_id": "e-001", "entity_type": "Organization", "canonical_name": "Acme"},
        )
        assert resp.status_code == 200
        assert resp.json()["entity_id"] == "e-001"
    finally:
        app.dependency_overrides.pop(get_current_principal, None)


def test_aw_get_entity_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.interfaces.http.admin_graph_entities as ent_module

    monkeypatch.setattr(settings, "enterprise_graph_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    svc = _svc_mock()
    monkeypatch.setattr(ent_module, "_graph_service", lambda: svc)
    app.dependency_overrides[get_current_principal] = _principal_override("owner")
    try:
        client = TestClient(app)
        resp = client.get(f"{_BASE}/entities/missing-id")
        assert resp.status_code == 404
    finally:
        app.dependency_overrides.pop(get_current_principal, None)


def test_ax_get_entity_found(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.interfaces.http.admin_graph_entities as ent_module

    entity = {"entity_id": "e-001", "organization_id": _ORG}
    monkeypatch.setattr(settings, "enterprise_graph_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    svc = _svc_mock(get_entity=AsyncMock(return_value=entity))
    monkeypatch.setattr(ent_module, "_graph_service", lambda: svc)
    app.dependency_overrides[get_current_principal] = _principal_override("owner")
    try:
        client = TestClient(app)
        resp = client.get(f"{_BASE}/entities/e-001")
        assert resp.status_code == 200
        assert resp.json()["entity_id"] == "e-001"
    finally:
        app.dependency_overrides.pop(get_current_principal, None)


def test_ay_delete_entity_success(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.interfaces.http.admin_graph_entities as ent_module

    monkeypatch.setattr(settings, "enterprise_graph_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    svc = _svc_mock(delete_entity=AsyncMock(return_value=True))
    monkeypatch.setattr(ent_module, "_graph_service", lambda: svc)
    app.dependency_overrides[get_current_principal] = _principal_override("owner")
    try:
        client = TestClient(app)
        resp = client.delete(f"{_BASE}/entities/e-001")
        assert resp.status_code == 200
        assert resp.json()["deleted"] is True
    finally:
        app.dependency_overrides.pop(get_current_principal, None)


def test_az_get_entity_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.interfaces.http.admin_graph_entities as ent_module

    evidence = [
        {"chunk_id": "c-001", "source_document_id": "doc-001", "confidence": 0.9, "evidence_text": "...", "created_at": None}
    ]
    monkeypatch.setattr(settings, "enterprise_graph_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    svc = _svc_mock(get_entity_evidence=AsyncMock(return_value=evidence))
    monkeypatch.setattr(ent_module, "_graph_service", lambda: svc)
    app.dependency_overrides[get_current_principal] = _principal_override("owner")
    try:
        client = TestClient(app)
        resp = client.get(f"{_BASE}/entities/e-001/evidence")
        assert resp.status_code == 200
        data = resp.json()
        assert data["entity_id"] == "e-001"
        assert len(data["items"]) == 1
    finally:
        app.dependency_overrides.pop(get_current_principal, None)


def test_ba_get_entity_relations_bad_type(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.interfaces.http.admin_graph_entities as ent_module

    monkeypatch.setattr(settings, "enterprise_graph_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    svc = _svc_mock()
    monkeypatch.setattr(ent_module, "_graph_service", lambda: svc)
    app.dependency_overrides[get_current_principal] = _principal_override("owner")
    try:
        client = TestClient(app)
        resp = client.get(f"{_BASE}/entities/e-001/relations?rel_type=INVALID_TYPE")
        assert resp.status_code == 422
    finally:
        app.dependency_overrides.pop(get_current_principal, None)


def test_bb_get_entity_relations_valid(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.interfaces.http.admin_graph_entities as ent_module

    relations = [{"from_entity_id": "e-001", "rel_type": "RELATES_TO", "to_entity_id": "e-002", "properties": {}}]
    monkeypatch.setattr(settings, "enterprise_graph_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    svc = _svc_mock(get_entity_relations=AsyncMock(return_value=relations))
    monkeypatch.setattr(ent_module, "_graph_service", lambda: svc)
    app.dependency_overrides[get_current_principal] = _principal_override("owner")
    try:
        client = TestClient(app)
        resp = client.get(f"{_BASE}/entities/e-001/relations?rel_type=RELATES_TO")
        assert resp.status_code == 200
        data = resp.json()
        assert data["entity_id"] == "e-001"
        assert data["items"][0]["rel_type"] == "RELATES_TO"
    finally:
        app.dependency_overrides.pop(get_current_principal, None)


def test_bc_get_extraction_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.interfaces.http.admin_graph_entities as ent_module

    runs = [
        {
            "run_id": "run-001",
            "document_id": "doc-001",
            "strategy": "default",
            "status": "completed",
            "entity_count": 5,
            "error": None,
            "created_at": None,
            "updated_at": None,
        }
    ]
    monkeypatch.setattr(settings, "enterprise_graph_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    svc = _svc_mock(get_document_extraction_runs=AsyncMock(return_value=runs))
    monkeypatch.setattr(ent_module, "_graph_service", lambda: svc)
    app.dependency_overrides[get_current_principal] = _principal_override("owner")
    try:
        client = TestClient(app)
        resp = client.get(f"{_BASE}/documents/doc-001/extraction-runs")
        assert resp.status_code == 200
        data = resp.json()
        assert data["document_id"] == "doc-001"
        assert data["items"][0]["run_id"] == "run-001"
    finally:
        app.dependency_overrides.pop(get_current_principal, None)


# ---------------------------------------------------------------------------
# Security tests: BD–BH
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bd_entity_list_where_always_includes_org():
    """list_entities Cypher always binds organization_id — verify WHERE clause."""
    driver = _mock_driver(records=[])
    with patch.object(settings, "enterprise_graph_enabled", True), patch.object(
        settings, "neo4j_database", _DB
    ), patch.object(settings, "neo4j_query_timeout_seconds", 5.0), patch.object(
        neo4j_module, "_neo4j_driver", driver
    ):
        await EntityRepository().list_entities(organization_id=_ORG)
        session = driver.session.return_value.__aenter__.return_value
        call_kwargs = session.run.call_args[1]
        assert "organization_id" in call_kwargs
        assert call_kwargs["organization_id"] == _ORG
        cypher = session.run.call_args[0][0]
        assert "organization_id" in cypher


@pytest.mark.asyncio
async def test_be_entity_get_always_binds_org():
    """get_entity Cypher always binds organization_id param."""
    driver = _mock_driver(records=[])
    with patch.object(settings, "enterprise_graph_enabled", True), patch.object(
        settings, "neo4j_database", _DB
    ), patch.object(settings, "neo4j_query_timeout_seconds", 5.0), patch.object(
        neo4j_module, "_neo4j_driver", driver
    ):
        await EntityRepository().get_entity(organization_id=_ORG, entity_id="e-001")
        session = driver.session.return_value.__aenter__.return_value
        call_kwargs = session.run.call_args[1]
        assert call_kwargs["organization_id"] == _ORG


@pytest.mark.asyncio
async def test_bf_relation_type_injection_guard():
    """RelationRepository rejects any rel_type not in schema vocabulary."""
    injection_attempts = [
        "RELATES_TO} MATCH (x) DETACH DELETE x //",
        "RELATES_TO\nMATCH",
        "'; DROP TABLE users; --",
        "",
        "relates_to",  # lowercase — not in vocabulary
    ]
    for bad_type in injection_attempts:
        with pytest.raises((ValueError, Exception)):
            await RelationRepository().create_relation(
                organization_id=_ORG,
                from_entity_id="e-001",
                to_entity_id="e-002",
                rel_type=bad_type,
            )


@pytest.mark.asyncio
async def test_bg_graphrag_always_binds_org():
    """find_related_entities Cypher always binds organization_id."""
    driver = _mock_driver(records=[])
    with patch.object(settings, "enterprise_graph_enabled", True), patch.object(
        settings, "neo4j_database", _DB
    ), patch.object(settings, "neo4j_query_timeout_seconds", 5.0), patch.object(
        neo4j_module, "_neo4j_driver", driver
    ):
        await GraphRAGRepository().find_related_entities(
            organization_id=_ORG, entity_ids=["e-001"]
        )
        session = driver.session.return_value.__aenter__.return_value
        call_kwargs = session.run.call_args[1]
        assert call_kwargs["organization_id"] == _ORG


@pytest.mark.asyncio
async def test_bh_graphrag_depth_never_unbounded():
    """depth is always clamped — no [*] unbounded pattern ever reaches Neo4j."""
    driver = _mock_driver(records=[])
    with patch.object(settings, "enterprise_graph_enabled", True), patch.object(
        settings, "neo4j_database", _DB
    ), patch.object(settings, "neo4j_query_timeout_seconds", 5.0), patch.object(
        neo4j_module, "_neo4j_driver", driver
    ):
        for depth in [0, 1, 3, 5, 10, 100, -1]:
            await GraphRAGRepository().find_related_entities(
                organization_id=_ORG, entity_ids=["e-001"], depth=depth
            )
            session = driver.session.return_value.__aenter__.return_value
            cypher = session.run.call_args[0][0]
            assert "[*]" not in cypher
            assert "[*1.." in cypher
