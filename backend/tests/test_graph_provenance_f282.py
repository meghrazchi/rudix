"""Backend tests for F282: Graph source model and evidence-first provenance contract.

Covers:
  A.  EvidenceRepository.link_evidence — no citation fields → ValueError
  B.  EvidenceRepository.link_evidence — only evidence_text → valid (backward compat)
  C.  EvidenceRepository.link_evidence — only citation_text → valid
  D.  EvidenceRepository.link_evidence — only citation_reference → valid
  E.  EvidenceRepository.link_evidence — full provenance payload → execute_write called
  F.  EvidenceRepository.link_evidence — all new fields sent to Cypher
  G.  EvidenceRepository.link_evidence — graph disabled → no-op (no ValueError)
  H.  EvidenceRepository.get_entity_evidence — returns full provenance fields
  I.  EvidenceRepository.get_entity_evidence — driver None → []
  J.  EvidenceRepository.get_document_provenance — returns multi-entity provenance
  K.  EvidenceRepository.get_document_provenance — driver None → []
  L.  EvidenceRepository.get_document_provenance — query scoped by organization_id

  M.  GraphRAGRepository.get_evidence_for_entities — returns new provenance fields
  N.  GraphRAGRepository.get_evidence_for_entities — citation_text present in return

  O.  GraphService.link_evidence — delegates full provenance to repository
  P.  GraphService.get_document_provenance — delegates to evidence repository

  Q.  POST /admin/graph/evidence — graph disabled → 503
  R.  POST /admin/graph/evidence — member role → 403
  S.  POST /admin/graph/evidence — missing citation → 422
  T.  POST /admin/graph/evidence — valid full provenance → 201
  U.  POST /admin/graph/evidence — only citation_reference → 201
  V.  GET /admin/graph/documents/{id}/provenance — graph disabled → 503
  W.  GET /admin/graph/documents/{id}/provenance — returns provenance list
  X.  GET /admin/graph/documents/{id}/provenance — member role → 403
  Y.  GET /admin/graph/entities/{id}/citations — graph disabled → 503
  Z.  GET /admin/graph/entities/{id}/citations — returns citation DTOs
  AA. GET /admin/graph/entities/{id}/citations — citation_text falls back to evidence_text

  Security:
  AB. EvidenceRepository.get_document_provenance — org always bound in WHERE
  AC. link_evidence — ValueError before reaching Neo4j (no injection path)
  AD. EvidenceRepository.get_entity_evidence — Cypher includes organization_id in WHERE

Run:
    pytest tests/test_graph_provenance_f282.py -v
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
from app.domains.graph.repositories.evidence_repository import EvidenceRepository
from app.domains.graph.repositories.graphrag_repository import GraphRAGRepository
from app.domains.graph.services.graph_service import GraphService
from app.main import app

import app.clients.neo4j_client as neo4j_module

_ORG = "org-test-f282"
_WS = "ws-test-f282"
_DB = "neo4j"
_DOC = "doc-f282-001"
_CHUNK = "chunk-f282-001"
_ENTITY = "entity-f282-001"
_RUN = "run-f282-001"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _reset_driver() -> None:
    neo4j_module._neo4j_driver = None


def _mock_driver(records: list[dict] | None = None) -> MagicMock:
    record_data = records if records is not None else []

    result_mock = AsyncMock()
    result_mock.data = AsyncMock(return_value=record_data)
    result_mock.consume = AsyncMock()

    session_mock = AsyncMock()
    session_mock.run = AsyncMock(return_value=result_mock)
    session_mock.execute_write = AsyncMock(return_value=None)
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
# A. link_evidence — no citation fields → ValueError
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_link_evidence_no_citation_raises():
    repo = EvidenceRepository()
    with pytest.raises(ValueError, match="provenance_required"):
        await repo.link_evidence(
            organization_id=_ORG,
            entity_id=_ENTITY,
            chunk_id=_CHUNK,
            source_document_id=_DOC,
            confidence=0.9,
            # no evidence_text, citation_text, or citation_reference
        )


# ---------------------------------------------------------------------------
# B. link_evidence — only evidence_text → valid (backward compat)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_b_link_evidence_evidence_text_valid():
    driver = _mock_driver()
    with patch.object(settings, "enterprise_graph_enabled", True), patch.object(
        settings, "neo4j_database", _DB
    ), patch.object(neo4j_module, "_neo4j_driver", driver):
        await EvidenceRepository().link_evidence(
            organization_id=_ORG,
            entity_id=_ENTITY,
            chunk_id=_CHUNK,
            source_document_id=_DOC,
            evidence_text="Acme Corp provides services.",
        )
        session = driver.session.return_value.__aenter__.return_value
        session.execute_write.assert_called_once()


# ---------------------------------------------------------------------------
# C. link_evidence — only citation_text → valid
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_c_link_evidence_citation_text_valid():
    driver = _mock_driver()
    with patch.object(settings, "enterprise_graph_enabled", True), patch.object(
        settings, "neo4j_database", _DB
    ), patch.object(neo4j_module, "_neo4j_driver", driver):
        await EvidenceRepository().link_evidence(
            organization_id=_ORG,
            entity_id=_ENTITY,
            chunk_id=_CHUNK,
            source_document_id=_DOC,
            citation_text="The vendor shall maintain ISO 27001 certification.",
        )
        session = driver.session.return_value.__aenter__.return_value
        session.execute_write.assert_called_once()


# ---------------------------------------------------------------------------
# D. link_evidence — only citation_reference → valid
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_d_link_evidence_citation_reference_valid():
    driver = _mock_driver()
    with patch.object(settings, "enterprise_graph_enabled", True), patch.object(
        settings, "neo4j_database", _DB
    ), patch.object(neo4j_module, "_neo4j_driver", driver):
        await EvidenceRepository().link_evidence(
            organization_id=_ORG,
            entity_id=_ENTITY,
            chunk_id=_CHUNK,
            source_document_id=_DOC,
            citation_reference="Privacy Policy v2, Section 3.1, p. 8",
        )
        session = driver.session.return_value.__aenter__.return_value
        session.execute_write.assert_called_once()


# ---------------------------------------------------------------------------
# E. link_evidence — full provenance payload → execute_write called
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_e_link_evidence_full_provenance():
    driver = _mock_driver()
    with patch.object(settings, "enterprise_graph_enabled", True), patch.object(
        settings, "neo4j_database", _DB
    ), patch.object(neo4j_module, "_neo4j_driver", driver):
        await EvidenceRepository().link_evidence(
            organization_id=_ORG,
            entity_id=_ENTITY,
            chunk_id=_CHUNK,
            source_document_id=_DOC,
            confidence=0.95,
            workspace_id=_WS,
            document_version_id="v2",
            page_number=4,
            source_connector="confluence",
            external_url="https://confluence.example.com/page/123",
            extraction_run_id=_RUN,
            citation_text="Acme Corp is headquartered in Berlin.",
            citation_reference="Vendor Agreement, p. 4",
        )
        session = driver.session.return_value.__aenter__.return_value
        session.execute_write.assert_called_once()


# ---------------------------------------------------------------------------
# F. link_evidence — all new fields sent to Cypher
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_f_link_evidence_all_fields_passed_to_cypher():
    driver = _mock_driver()
    with patch.object(settings, "enterprise_graph_enabled", True), patch.object(
        settings, "neo4j_database", _DB
    ), patch.object(neo4j_module, "_neo4j_driver", driver):
        await EvidenceRepository().link_evidence(
            organization_id=_ORG,
            entity_id=_ENTITY,
            chunk_id=_CHUNK,
            source_document_id=_DOC,
            workspace_id=_WS,
            document_version_id="v3",
            page_number=12,
            source_connector="google_drive",
            external_url="https://drive.google.com/file/d/abc",
            extraction_run_id=_RUN,
            citation_text="Quoted span from the source.",
            citation_reference="Doc Title, p. 12",
        )
        session = driver.session.return_value.__aenter__.return_value
        tx_fn = session.execute_write.call_args[0][0]
        tx_mock = AsyncMock()
        await tx_fn(tx_mock)
        kwargs = tx_mock.run.call_args[1]
        assert kwargs["organization_id"] == _ORG
        assert kwargs["workspace_id"] == _WS
        assert kwargs["document_version_id"] == "v3"
        assert kwargs["page_number"] == 12
        assert kwargs["source_connector"] == "google_drive"
        assert kwargs["external_url"] == "https://drive.google.com/file/d/abc"
        assert kwargs["extraction_run_id"] == _RUN
        assert kwargs["citation_text"] == "Quoted span from the source."
        assert kwargs["citation_reference"] == "Doc Title, p. 12"


# ---------------------------------------------------------------------------
# G. link_evidence — graph disabled → no-op (ValueError fires before driver check)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_g_link_evidence_disabled_no_op_no_citation():
    """When graph is disabled AND no citation, ValueError fires before driver check."""
    _reset_driver()
    with patch.object(settings, "enterprise_graph_enabled", False):
        with pytest.raises(ValueError, match="provenance_required"):
            await EvidenceRepository().link_evidence(
                organization_id=_ORG,
                entity_id=_ENTITY,
                chunk_id=_CHUNK,
                source_document_id=_DOC,
            )


@pytest.mark.asyncio
async def test_g2_link_evidence_disabled_with_citation_noop():
    """When graph is disabled but citation is present → silent no-op."""
    _reset_driver()
    with patch.object(settings, "enterprise_graph_enabled", False):
        # Should not raise — driver is None so we get a no-op
        await EvidenceRepository().link_evidence(
            organization_id=_ORG,
            entity_id=_ENTITY,
            chunk_id=_CHUNK,
            source_document_id=_DOC,
            citation_text="Some text",
        )


# ---------------------------------------------------------------------------
# H. get_entity_evidence — returns full provenance fields
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_h_get_entity_evidence_full_fields():
    ev_records = [
        {
            "chunk_id": _CHUNK,
            "source_document_id": _DOC,
            "workspace_id": _WS,
            "document_version_id": "v2",
            "page_number": 4,
            "source_connector": "confluence",
            "external_url": "https://example.com",
            "extraction_run_id": _RUN,
            "confidence": 0.9,
            "evidence_text": None,
            "citation_text": "Acme Corp is headquartered in Berlin.",
            "citation_reference": "Vendor Agreement, p. 4",
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
            organization_id=_ORG, entity_id=_ENTITY
        )
        assert len(results) == 1
        r = results[0]
        assert r["chunk_id"] == _CHUNK
        assert r["workspace_id"] == _WS
        assert r["document_version_id"] == "v2"
        assert r["page_number"] == 4
        assert r["source_connector"] == "confluence"
        assert r["external_url"] == "https://example.com"
        assert r["extraction_run_id"] == _RUN
        assert r["citation_text"] == "Acme Corp is headquartered in Berlin."
        assert r["citation_reference"] == "Vendor Agreement, p. 4"


# ---------------------------------------------------------------------------
# I. get_entity_evidence — driver None → []
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_i_get_entity_evidence_driver_none():
    _reset_driver()
    with patch.object(settings, "enterprise_graph_enabled", True):
        result = await EvidenceRepository().get_entity_evidence(
            organization_id=_ORG, entity_id=_ENTITY
        )
        assert result == []


# ---------------------------------------------------------------------------
# J. get_document_provenance — returns multi-entity provenance
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_j_get_document_provenance_returns_list():
    prov_records = [
        {
            "entity_id": "e-001",
            "entity_type": "Organization",
            "canonical_name": "Acme Corp",
            "chunk_id": _CHUNK,
            "source_document_id": _DOC,
            "workspace_id": _WS,
            "document_version_id": None,
            "page_number": 2,
            "source_connector": None,
            "external_url": None,
            "extraction_run_id": _RUN,
            "confidence": 0.88,
            "evidence_text": None,
            "citation_text": "Acme Corp",
            "citation_reference": "Contract, p. 2",
            "created_at": "2026-06-14T00:00:00+00:00",
        },
        {
            "entity_id": "e-002",
            "entity_type": "Policy",
            "canonical_name": "ISO 27001",
            "chunk_id": _CHUNK,
            "source_document_id": _DOC,
            "workspace_id": _WS,
            "document_version_id": None,
            "page_number": 5,
            "source_connector": None,
            "external_url": None,
            "extraction_run_id": _RUN,
            "confidence": 0.75,
            "evidence_text": None,
            "citation_text": "ISO 27001 certified",
            "citation_reference": "Contract, p. 5",
            "created_at": "2026-06-14T00:00:00+00:00",
        },
    ]
    driver = _mock_driver(records=prov_records)
    with patch.object(settings, "enterprise_graph_enabled", True), patch.object(
        settings, "neo4j_database", _DB
    ), patch.object(settings, "neo4j_query_timeout_seconds", 5.0), patch.object(
        neo4j_module, "_neo4j_driver", driver
    ):
        results = await EvidenceRepository().get_document_provenance(
            organization_id=_ORG, document_id=_DOC
        )
        assert len(results) == 2
        assert results[0]["entity_id"] == "e-001"
        assert results[1]["entity_id"] == "e-002"
        assert results[0]["citation_text"] == "Acme Corp"
        assert results[1]["extraction_run_id"] == _RUN


# ---------------------------------------------------------------------------
# K. get_document_provenance — driver None → []
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_k_get_document_provenance_driver_none():
    _reset_driver()
    with patch.object(settings, "enterprise_graph_enabled", True):
        result = await EvidenceRepository().get_document_provenance(
            organization_id=_ORG, document_id=_DOC
        )
        assert result == []


# ---------------------------------------------------------------------------
# L. get_document_provenance — query scoped by organization_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_l_get_document_provenance_org_scoped():
    driver = _mock_driver(records=[])
    with patch.object(settings, "enterprise_graph_enabled", True), patch.object(
        settings, "neo4j_database", _DB
    ), patch.object(settings, "neo4j_query_timeout_seconds", 5.0), patch.object(
        neo4j_module, "_neo4j_driver", driver
    ):
        await EvidenceRepository().get_document_provenance(
            organization_id=_ORG, document_id=_DOC
        )
        session = driver.session.return_value.__aenter__.return_value
        call_kwargs = session.run.call_args[1]
        assert call_kwargs["organization_id"] == _ORG
        assert call_kwargs["document_id"] == _DOC
        cypher = session.run.call_args[0][0]
        assert "organization_id" in cypher


# ---------------------------------------------------------------------------
# M. GraphRAGRepository.get_evidence_for_entities — returns new provenance fields
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_m_graphrag_evidence_returns_provenance_fields():
    ev_records = [
        {
            "entity_id": _ENTITY,
            "chunk_id": _CHUNK,
            "source_document_id": _DOC,
            "workspace_id": _WS,
            "source_connector": "jira",
            "document_version_id": None,
            "page_number": 1,
            "external_url": "https://jira.example.com/issue/123",
            "extraction_run_id": _RUN,
            "confidence": 0.8,
            "evidence_text": None,
            "citation_text": "JQL query results",
            "citation_reference": "JIRA-123",
        }
    ]
    driver = _mock_driver(records=ev_records)
    with patch.object(settings, "enterprise_graph_enabled", True), patch.object(
        settings, "neo4j_database", _DB
    ), patch.object(settings, "neo4j_query_timeout_seconds", 5.0), patch.object(
        neo4j_module, "_neo4j_driver", driver
    ):
        results = await GraphRAGRepository().get_evidence_for_entities(
            organization_id=_ORG, entity_ids=[_ENTITY]
        )
        assert len(results) == 1
        r = results[0]
        assert r["workspace_id"] == _WS
        assert r["source_connector"] == "jira"
        assert r["extraction_run_id"] == _RUN
        assert r["citation_text"] == "JQL query results"
        assert r["citation_reference"] == "JIRA-123"


# ---------------------------------------------------------------------------
# N. GraphRAGRepository — citation_text present in RETURN clause
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_n_graphrag_cypher_includes_citation_text():
    driver = _mock_driver(records=[])
    with patch.object(settings, "enterprise_graph_enabled", True), patch.object(
        settings, "neo4j_database", _DB
    ), patch.object(settings, "neo4j_query_timeout_seconds", 5.0), patch.object(
        neo4j_module, "_neo4j_driver", driver
    ):
        await GraphRAGRepository().get_evidence_for_entities(
            organization_id=_ORG, entity_ids=[_ENTITY]
        )
        session = driver.session.return_value.__aenter__.return_value
        cypher = session.run.call_args[0][0]
        assert "citation_text" in cypher
        assert "citation_reference" in cypher
        assert "extraction_run_id" in cypher


# ---------------------------------------------------------------------------
# O. GraphService.link_evidence — delegates full provenance to repository
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_o_service_link_evidence_full_provenance():
    link_mock = AsyncMock()
    svc = GraphService()
    svc._evidence.link_evidence = link_mock
    await svc.link_evidence(
        organization_id=_ORG,
        entity_id=_ENTITY,
        chunk_id=_CHUNK,
        source_document_id=_DOC,
        confidence=0.9,
        workspace_id=_WS,
        document_version_id="v2",
        page_number=4,
        source_connector="confluence",
        external_url="https://confluence.example.com",
        extraction_run_id=_RUN,
        citation_text="Quoted text",
        citation_reference="Policy, p. 4",
    )
    link_mock.assert_awaited_once()
    kwargs = link_mock.call_args[1]
    assert kwargs["organization_id"] == _ORG
    assert kwargs["workspace_id"] == _WS
    assert kwargs["extraction_run_id"] == _RUN
    assert kwargs["citation_text"] == "Quoted text"
    assert kwargs["citation_reference"] == "Policy, p. 4"


# ---------------------------------------------------------------------------
# P. GraphService.get_document_provenance — delegates to evidence repository
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_p_service_get_document_provenance():
    prov_mock = AsyncMock(return_value=[{"entity_id": "e-001"}])
    svc = GraphService()
    svc._evidence.get_document_provenance = prov_mock
    result = await svc.get_document_provenance(organization_id=_ORG, document_id=_DOC)
    prov_mock.assert_awaited_once()
    assert prov_mock.call_args[1]["organization_id"] == _ORG
    assert prov_mock.call_args[1]["document_id"] == _DOC
    assert result == [{"entity_id": "e-001"}]


# ---------------------------------------------------------------------------
# HTTP endpoint tests: Q–AA
# ---------------------------------------------------------------------------

_BASE = "/api/v1/admin/graph"


def _svc_mock(**overrides: Any) -> MagicMock:
    svc = MagicMock(spec=GraphService)
    svc.link_evidence = AsyncMock()
    svc.get_entity_evidence = AsyncMock(return_value=[])
    svc.get_document_provenance = AsyncMock(return_value=[])
    for k, v in overrides.items():
        setattr(svc, k, v)
    return svc


# Q. POST /admin/graph/evidence — graph disabled → 503

def test_q_create_evidence_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "enterprise_graph_enabled", False)
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    app.dependency_overrides[get_current_principal] = _principal_override("owner")
    try:
        client = TestClient(app)
        resp = client.post(
            f"{_BASE}/evidence",
            json={
                "entity_id": _ENTITY,
                "chunk_id": _CHUNK,
                "source_document_id": _DOC,
                "citation_text": "Some text",
            },
        )
        assert resp.status_code == 503
        assert "enterprise_graph_disabled" in resp.json()["detail"]
    finally:
        app.dependency_overrides.pop(get_current_principal, None)


# R. POST /admin/graph/evidence — member role → 403

def test_r_create_evidence_member_forbidden(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "enterprise_graph_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    app.dependency_overrides[get_current_principal] = _principal_override("member")
    try:
        client = TestClient(app)
        resp = client.post(
            f"{_BASE}/evidence",
            json={
                "entity_id": _ENTITY,
                "chunk_id": _CHUNK,
                "source_document_id": _DOC,
                "citation_text": "Some text",
            },
        )
        assert resp.status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_principal, None)


# S. POST /admin/graph/evidence — missing citation → 422

def test_s_create_evidence_no_citation_422(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "enterprise_graph_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    app.dependency_overrides[get_current_principal] = _principal_override("owner")
    try:
        client = TestClient(app)
        resp = client.post(
            f"{_BASE}/evidence",
            json={
                "entity_id": _ENTITY,
                "chunk_id": _CHUNK,
                "source_document_id": _DOC,
                "confidence": 0.9,
                # no citation fields
            },
        )
        assert resp.status_code == 422
        body = resp.json()
        assert "provenance_required" in str(body)
    finally:
        app.dependency_overrides.pop(get_current_principal, None)


# T. POST /admin/graph/evidence — valid full provenance → 201

def test_t_create_evidence_full_provenance_201(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.interfaces.http.admin_graph_provenance as prov_module

    monkeypatch.setattr(settings, "enterprise_graph_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    svc = _svc_mock()
    monkeypatch.setattr(prov_module, "_graph_service", lambda: svc)
    app.dependency_overrides[get_current_principal] = _principal_override("owner")
    try:
        client = TestClient(app)
        resp = client.post(
            f"{_BASE}/evidence",
            json={
                "entity_id": _ENTITY,
                "chunk_id": _CHUNK,
                "source_document_id": _DOC,
                "confidence": 0.95,
                "workspace_id": _WS,
                "document_version_id": "v2",
                "page_number": 4,
                "source_connector": "confluence",
                "external_url": "https://confluence.example.com/page/1",
                "extraction_run_id": _RUN,
                "citation_text": "Vendor maintains ISO 27001.",
                "citation_reference": "Vendor Agreement, p. 4",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["linked"] is True
        assert data["entity_id"] == _ENTITY
        assert data["chunk_id"] == _CHUNK
        svc.link_evidence.assert_awaited_once()
    finally:
        app.dependency_overrides.pop(get_current_principal, None)


# U. POST /admin/graph/evidence — only citation_reference → 201

def test_u_create_evidence_only_citation_reference(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.interfaces.http.admin_graph_provenance as prov_module

    monkeypatch.setattr(settings, "enterprise_graph_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    svc = _svc_mock()
    monkeypatch.setattr(prov_module, "_graph_service", lambda: svc)
    app.dependency_overrides[get_current_principal] = _principal_override("owner")
    try:
        client = TestClient(app)
        resp = client.post(
            f"{_BASE}/evidence",
            json={
                "entity_id": _ENTITY,
                "chunk_id": _CHUNK,
                "source_document_id": _DOC,
                "citation_reference": "Policy v3, §5.2",
            },
        )
        assert resp.status_code == 201
        assert resp.json()["linked"] is True
    finally:
        app.dependency_overrides.pop(get_current_principal, None)


# V. GET /admin/graph/documents/{id}/provenance — graph disabled → 503

def test_v_document_provenance_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "enterprise_graph_enabled", False)
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    app.dependency_overrides[get_current_principal] = _principal_override("owner")
    try:
        client = TestClient(app)
        resp = client.get(f"{_BASE}/documents/{_DOC}/provenance")
        assert resp.status_code == 503
    finally:
        app.dependency_overrides.pop(get_current_principal, None)


# W. GET /admin/graph/documents/{id}/provenance — returns provenance list

def test_w_document_provenance_returns_list(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.interfaces.http.admin_graph_provenance as prov_module

    prov_data = [
        {
            "entity_id": "e-001",
            "entity_type": "Organization",
            "canonical_name": "Acme Corp",
            "chunk_id": _CHUNK,
            "source_document_id": _DOC,
            "workspace_id": _WS,
            "document_version_id": "v2",
            "page_number": 3,
            "source_connector": None,
            "external_url": None,
            "extraction_run_id": _RUN,
            "confidence": 0.9,
            "evidence_text": None,
            "citation_text": "Acme Corp",
            "citation_reference": "Contract, p. 3",
            "created_at": None,
        }
    ]
    monkeypatch.setattr(settings, "enterprise_graph_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    svc = _svc_mock(get_document_provenance=AsyncMock(return_value=prov_data))
    monkeypatch.setattr(prov_module, "_graph_service", lambda: svc)
    app.dependency_overrides[get_current_principal] = _principal_override("owner")
    try:
        client = TestClient(app)
        resp = client.get(f"{_BASE}/documents/{_DOC}/provenance")
        assert resp.status_code == 200
        data = resp.json()
        assert data["document_id"] == _DOC
        assert data["total"] == 1
        item = data["items"][0]
        assert item["entity_id"] == "e-001"
        assert item["citation_text"] == "Acme Corp"
        assert item["page_number"] == 3
        assert item["extraction_run_id"] == _RUN
    finally:
        app.dependency_overrides.pop(get_current_principal, None)


# X. GET /admin/graph/documents/{id}/provenance — member role → 403

def test_x_document_provenance_member_forbidden(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "enterprise_graph_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    app.dependency_overrides[get_current_principal] = _principal_override("member")
    try:
        client = TestClient(app)
        resp = client.get(f"{_BASE}/documents/{_DOC}/provenance")
        assert resp.status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_principal, None)


# Y. GET /admin/graph/entities/{id}/citations — graph disabled → 503

def test_y_entity_citations_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "enterprise_graph_enabled", False)
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    app.dependency_overrides[get_current_principal] = _principal_override("owner")
    try:
        client = TestClient(app)
        resp = client.get(f"{_BASE}/entities/{_ENTITY}/citations")
        assert resp.status_code == 503
    finally:
        app.dependency_overrides.pop(get_current_principal, None)


# Z. GET /admin/graph/entities/{id}/citations — returns citation DTOs

def test_z_entity_citations_returns_dtos(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.interfaces.http.admin_graph_provenance as prov_module

    ev_data = [
        {
            "chunk_id": _CHUNK,
            "source_document_id": _DOC,
            "workspace_id": _WS,
            "document_version_id": "v2",
            "page_number": 7,
            "source_connector": "google_drive",
            "external_url": "https://drive.google.com/file/d/xyz",
            "extraction_run_id": _RUN,
            "confidence": 0.92,
            "evidence_text": None,
            "citation_text": "ISO 27001 certified since 2023.",
            "citation_reference": "Security Policy, p. 7",
        }
    ]
    monkeypatch.setattr(settings, "enterprise_graph_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    svc = _svc_mock(get_entity_evidence=AsyncMock(return_value=ev_data))
    monkeypatch.setattr(prov_module, "_graph_service", lambda: svc)
    app.dependency_overrides[get_current_principal] = _principal_override("owner")
    try:
        client = TestClient(app)
        resp = client.get(f"{_BASE}/entities/{_ENTITY}/citations")
        assert resp.status_code == 200
        data = resp.json()
        assert data["entity_id"] == _ENTITY
        assert len(data["items"]) == 1
        item = data["items"][0]
        assert item["entity_id"] == _ENTITY
        assert item["chunk_id"] == _CHUNK
        assert item["page_number"] == 7
        assert item["source_connector"] == "google_drive"
        assert item["extraction_run_id"] == _RUN
        assert item["citation_text"] == "ISO 27001 certified since 2023."
        assert item["citation_reference"] == "Security Policy, p. 7"
    finally:
        app.dependency_overrides.pop(get_current_principal, None)


# AA. GET /admin/graph/entities/{id}/citations — citation_text falls back to evidence_text

def test_aa_citations_fallback_to_evidence_text(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.interfaces.http.admin_graph_provenance as prov_module

    ev_data = [
        {
            "chunk_id": _CHUNK,
            "source_document_id": _DOC,
            "workspace_id": None,
            "document_version_id": None,
            "page_number": None,
            "source_connector": None,
            "external_url": None,
            "extraction_run_id": None,
            "confidence": 0.7,
            "evidence_text": "Legacy text from F281 pipeline",
            "citation_text": None,
            "citation_reference": None,
        }
    ]
    monkeypatch.setattr(settings, "enterprise_graph_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    svc = _svc_mock(get_entity_evidence=AsyncMock(return_value=ev_data))
    monkeypatch.setattr(prov_module, "_graph_service", lambda: svc)
    app.dependency_overrides[get_current_principal] = _principal_override("owner")
    try:
        client = TestClient(app)
        resp = client.get(f"{_BASE}/entities/{_ENTITY}/citations")
        assert resp.status_code == 200
        item = resp.json()["items"][0]
        # citation_text falls back to evidence_text when citation_text is None
        assert item["citation_text"] == "Legacy text from F281 pipeline"
    finally:
        app.dependency_overrides.pop(get_current_principal, None)


# ---------------------------------------------------------------------------
# Security tests: AB–AD
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ab_document_provenance_org_always_bound():
    """get_document_provenance Cypher always binds organization_id."""
    driver = _mock_driver(records=[])
    with patch.object(settings, "enterprise_graph_enabled", True), patch.object(
        settings, "neo4j_database", _DB
    ), patch.object(settings, "neo4j_query_timeout_seconds", 5.0), patch.object(
        neo4j_module, "_neo4j_driver", driver
    ):
        await EvidenceRepository().get_document_provenance(
            organization_id=_ORG, document_id=_DOC
        )
        session = driver.session.return_value.__aenter__.return_value
        call_kwargs = session.run.call_args[1]
        assert "organization_id" in call_kwargs
        assert call_kwargs["organization_id"] == _ORG
        cypher = session.run.call_args[0][0]
        assert "organization_id" in cypher


@pytest.mark.asyncio
async def test_ac_link_evidence_validation_fires_before_driver():
    """ValueError from validation fires before any Neo4j call — no injection path."""
    driver = _mock_driver()
    with patch.object(settings, "enterprise_graph_enabled", True), patch.object(
        settings, "neo4j_database", _DB
    ), patch.object(neo4j_module, "_neo4j_driver", driver):
        with pytest.raises(ValueError, match="provenance_required"):
            await EvidenceRepository().link_evidence(
                organization_id=_ORG,
                entity_id=_ENTITY,
                chunk_id=_CHUNK,
                source_document_id=_DOC,
                # no citation
            )
        session = driver.session.return_value.__aenter__.return_value
        session.execute_write.assert_not_called()


@pytest.mark.asyncio
async def test_ad_get_entity_evidence_cypher_includes_org():
    """get_entity_evidence Cypher always includes organization_id in WHERE."""
    driver = _mock_driver(records=[])
    with patch.object(settings, "enterprise_graph_enabled", True), patch.object(
        settings, "neo4j_database", _DB
    ), patch.object(settings, "neo4j_query_timeout_seconds", 5.0), patch.object(
        neo4j_module, "_neo4j_driver", driver
    ):
        await EvidenceRepository().get_entity_evidence(
            organization_id=_ORG, entity_id=_ENTITY
        )
        session = driver.session.return_value.__aenter__.return_value
        call_kwargs = session.run.call_args[1]
        assert call_kwargs["organization_id"] == _ORG
        cypher = session.run.call_args[0][0]
        assert "organization_id" in cypher
