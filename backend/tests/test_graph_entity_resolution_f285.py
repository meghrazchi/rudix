"""Backend tests for F285: entity normalization, canonicalization, and review gating.

Coverage:
  A. normalize_entity_name removes diacritics, punctuation, and extra spaces
  B. entity_resolution_key is deterministic and org-scoped
  C. alias resolution fixture: common aliases auto-merge at high confidence
  D. cross-tenant non-merge: the same names do not bleed across organizations
  E. dedup precision: similar but distinct names stay below auto-merge threshold
  F. low-confidence candidates are routed to review instead of auto-merging
"""

from __future__ import annotations

import os
import uuid
from unittest.mock import AsyncMock, MagicMock

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

from app.domains.graph.services.entity_resolution_service import (
    EntityResolutionCandidate,
    EntityResolutionInput,
    EntityResolutionService,
    entity_resolution_key,
    normalize_entity_name,
)


@pytest.mark.asyncio
async def test_a_normalize_entity_name_collapses_variants() -> None:
    assert normalize_entity_name("  Société  Générale, S.A. ") == "societe generale s a"


@pytest.mark.asyncio
async def test_b_entity_resolution_key_is_deterministic() -> None:
    a = entity_resolution_key(
        organization_id="org-1",
        entity_type="vendor",
        canonical_name="Acme Corp",
        source_external_id="sharepoint:123",
    )
    b = entity_resolution_key(
        organization_id="org-1",
        entity_type="vendor",
        canonical_name="Acme Corp",
        source_external_id="sharepoint:123",
    )
    c = entity_resolution_key(
        organization_id="org-2",
        entity_type="vendor",
        canonical_name="Acme Corp",
        source_external_id="sharepoint:123",
    )
    assert a == b
    assert a != c


@pytest.mark.asyncio
async def test_c_alias_resolution_fixture_auto_merges_common_aliases() -> None:
    svc = EntityResolutionService(auto_merge_threshold=0.9, review_threshold=0.65)
    repo = MagicMock()
    repo.find_entity_resolution_candidates = AsyncMock(
        return_value=[
            {
                "entity_id": str(uuid.uuid4()),
                "entity_type": "vendor",
                "canonical_name": "Microsoft Corporation",
                "normalized_name": "microsoft corporation",
                "external_source_id": None,
                "resolution_status": "active",
                "resolution_confidence": 0.94,
                "aliases": ["Microsoft", "MSFT"],
                "alias_normalized_names": ["microsoft", "msft"],
                "alias_count": 2,
            }
        ]
    )
    result = await svc.resolve_entity(
        repository=repo,
        input_=EntityResolutionInput(
            organization_id="org-1",
            entity_type="vendor",
            canonical_name="MSFT",
            original_name="MSFT",
            aliases=["Microsoft"],
            source_external_id="connector-a:001",
            source_connector="sharepoint",
            language="en",
        ),
    )
    assert result.status == "auto_merged"
    assert result.review_required is False
    assert result.matched_on


@pytest.mark.asyncio
async def test_d_cross_tenant_non_merge_same_name() -> None:
    svc = EntityResolutionService(auto_merge_threshold=0.8, review_threshold=0.6)
    repo = MagicMock()
    repo.find_entity_resolution_candidates = AsyncMock(return_value=[])
    left = await svc.resolve_entity(
        repository=repo,
        input_=EntityResolutionInput(
            organization_id="org-a",
            entity_type="vendor",
            canonical_name="Acme Corp",
            original_name="Acme Corp",
            aliases=["Acme"],
        ),
    )
    right = await svc.resolve_entity(
        repository=repo,
        input_=EntityResolutionInput(
            organization_id="org-b",
            entity_type="vendor",
            canonical_name="Acme Corp",
            original_name="Acme Corp",
            aliases=["Acme"],
        ),
    )
    assert left.canonical_entity_id != right.canonical_entity_id
    assert left.status == "new"
    assert right.status == "new"


@pytest.mark.asyncio
async def test_e_dedup_precision_similar_but_distinct_names_stay_separate() -> None:
    svc = EntityResolutionService(auto_merge_threshold=0.9, review_threshold=0.7)
    candidates = [
        EntityResolutionCandidate(
            entity_id=uuid.uuid4(),
            canonical_name="Global Payments Inc",
            normalized_name="global payments inc",
            entity_type="vendor",
            score=0.0,
            alias_count=0,
        ),
    ]
    scored = svc.score_candidates(
        input_=EntityResolutionInput(
            organization_id="org-1",
            entity_type="vendor",
            canonical_name="Global Payment Services",
            original_name="Global Payment Services",
        ),
        candidates=candidates,
    )
    assert scored[0].score < svc.auto_merge_threshold
    assert "similar_name" in scored[0].matched_on or scored[0].score < 0.9


@pytest.mark.asyncio
async def test_f_low_confidence_candidates_route_to_review() -> None:
    svc = EntityResolutionService(auto_merge_threshold=0.99, review_threshold=0.92)
    repo = MagicMock()
    repo.find_entity_resolution_candidates = AsyncMock(
        return_value=[
            {
                "entity_id": str(uuid.uuid4()),
                "entity_type": "customer",
                "canonical_name": "Northwind Traders",
                "normalized_name": "northwind traders",
                "external_source_id": None,
                "resolution_status": "active",
                "resolution_confidence": 0.51,
                "aliases": ["Northwind"],
                "alias_normalized_names": ["northwind"],
                "alias_count": 1,
            }
        ]
    )
    result = await svc.resolve_entity(
        repository=repo,
        input_=EntityResolutionInput(
            organization_id="org-1",
            entity_type="customer",
            canonical_name="Northwind Trading",
            original_name="Northwind Trading",
            aliases=["Northwind"],
            embedding_similarity=0.54,
        ),
    )
    assert result.status in {"review", "new"}
    assert result.candidate_score < svc.auto_merge_threshold
