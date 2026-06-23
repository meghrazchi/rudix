"""Tests for evidence quality warnings: OCR, table extraction, document lifecycle (F315).

Covers:
- ConfidenceService: table_quality_multiplier and extraction_quality_multiplier
- _compute_table_quality_multiplier and _compute_extraction_quality_multiplier helpers
- _build_evidence_quality_record aggregation
- _with_table_metadata: populates table_extraction_confidence and table_low_confidence_warning
- _with_extraction_quality: populates doc_extraction_quality, doc_extraction_warning,
  doc_processing_warning
- CitationTrustRecord and EvidenceQualityRecord schema validation
- Trust level emits "warning" when table or extraction quality multipliers degrade confidence
"""

from __future__ import annotations

import os

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

from app.domains.chat.schemas.chat import ChatCitationResponse
from app.domains.chat.schemas.trust_metadata import (
    CitationTrustRecord,
    ConfidenceTrustRecord,
    EvidenceQualityRecord,
)
from app.domains.chat.services.confidence_service import (
    ConfidenceChunkSignal,
    ConfidenceService,
    ConfidenceWeights,
)
from app.interfaces.http.chat import (
    _TABLE_CONFIDENCE_LOW_THRESHOLD,
    _EXTRACTION_WARNING_PROFILES,
    _PROCESSING_INCOMPLETE_STATUSES,
    _build_evidence_quality_record,
    _compute_extraction_quality_multiplier,
    _compute_table_quality_multiplier,
    _with_extraction_quality,
    _with_table_metadata,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_citation(**kwargs: object) -> ChatCitationResponse:
    defaults = {
        "document_id": "doc-1",
        "chunk_id": "chunk-1",
        "filename": "report.pdf",
        "score": 0.9,
        "similarity_score": 0.9,
    }
    defaults.update(kwargs)
    return ChatCitationResponse(**defaults)


def _make_service(**kwargs: object) -> ConfidenceService:
    return ConfidenceService(
        weights=ConfidenceWeights(
            top_similarity=1.0,
            average_similarity=0.0,
            rerank_score=0.0,
            citation_support=0.0,
            agreement=0.0,
        ),
        medium_threshold=kwargs.pop("medium_threshold", 0.45),
        high_threshold=kwargs.pop("high_threshold", 0.75),
        **kwargs,
    )


# ---------------------------------------------------------------------------
# EvidenceQualityRecord schema
# ---------------------------------------------------------------------------


class TestEvidenceQualityRecord:
    def test_defaults(self) -> None:
        rec = EvidenceQualityRecord()
        assert rec.table_low_confidence_count == 0
        assert rec.extraction_warning_count == 0
        assert rec.processing_warning_count == 0
        assert rec.any_incomplete_documents is False
        assert rec.warning_reasons == []

    def test_with_values(self) -> None:
        rec = EvidenceQualityRecord(
            table_low_confidence_count=2,
            extraction_warning_count=1,
            processing_warning_count=1,
            any_incomplete_documents=True,
            warning_reasons=["Table data may be inaccurate.", "Processing incomplete."],
        )
        assert rec.table_low_confidence_count == 2
        assert rec.any_incomplete_documents is True
        assert len(rec.warning_reasons) == 2

    def test_round_trip_json(self) -> None:
        rec = EvidenceQualityRecord(
            table_low_confidence_count=1,
            extraction_warning_count=0,
            processing_warning_count=0,
            any_incomplete_documents=False,
            warning_reasons=["1 cited table has low extraction confidence."],
        )
        data = rec.model_dump(mode="json")
        restored = EvidenceQualityRecord.model_validate(data)
        assert restored == rec


# ---------------------------------------------------------------------------
# CitationTrustRecord — F315 fields
# ---------------------------------------------------------------------------


class TestCitationTrustRecordF315Fields:
    def test_defaults(self) -> None:
        rec = CitationTrustRecord(document_id="d", chunk_id="c")
        assert rec.table_extraction_confidence is None
        assert rec.table_low_confidence_warning is False
        assert rec.doc_extraction_quality is None
        assert rec.doc_extraction_warning is False
        assert rec.doc_processing_warning is False

    def test_set_table_low_confidence(self) -> None:
        rec = CitationTrustRecord(
            document_id="d",
            chunk_id="c",
            is_table_chunk=True,
            table_extraction_confidence=0.25,
            table_low_confidence_warning=True,
        )
        assert rec.table_extraction_confidence == 0.25
        assert rec.table_low_confidence_warning is True

    def test_set_extraction_warning(self) -> None:
        rec = CitationTrustRecord(
            document_id="d",
            chunk_id="c",
            doc_extraction_quality="corrupted",
            doc_extraction_warning=True,
        )
        assert rec.doc_extraction_quality == "corrupted"
        assert rec.doc_extraction_warning is True

    def test_set_processing_warning(self) -> None:
        rec = CitationTrustRecord(
            document_id="d",
            chunk_id="c",
            doc_processing_warning=True,
        )
        assert rec.doc_processing_warning is True


# ---------------------------------------------------------------------------
# _with_table_metadata — F315 confidence annotation
# ---------------------------------------------------------------------------


class TestWithTableMetadataF315:
    def test_no_metadata_returns_unchanged(self) -> None:
        citation = _make_citation()
        result = _with_table_metadata(citation, {})
        assert result.is_table_chunk is False
        assert result.table_extraction_confidence is None
        assert result.table_low_confidence_warning is False

    def test_high_confidence_no_warning(self) -> None:
        citation = _make_citation(chunk_id="chunk-t")
        meta_map = {
            "chunk-t": {
                "caption": "Revenue",
                "row_count": 5,
                "col_count": 3,
                "headers": ["Year", "Revenue", "Growth"],
                "section_context": None,
                "confidence": 0.90,
                "extraction_engine": "camelot",
                "is_valid": True,
            }
        }
        result = _with_table_metadata(citation, meta_map)
        assert result.is_table_chunk is True
        assert result.table_extraction_confidence == pytest.approx(0.90)
        assert result.table_low_confidence_warning is False

    def test_low_confidence_triggers_warning(self) -> None:
        citation = _make_citation(chunk_id="chunk-t")
        meta_map = {
            "chunk-t": {
                "caption": None,
                "row_count": 3,
                "col_count": 2,
                "headers": [],
                "section_context": None,
                "confidence": 0.30,
                "extraction_engine": "camelot",
                "is_valid": False,
            }
        }
        result = _with_table_metadata(citation, meta_map)
        assert result.is_table_chunk is True
        assert result.table_extraction_confidence == pytest.approx(0.30)
        assert result.table_low_confidence_warning is True

    def test_boundary_at_threshold_not_low(self) -> None:
        citation = _make_citation(chunk_id="chunk-t")
        conf = _TABLE_CONFIDENCE_LOW_THRESHOLD  # exactly at threshold, not below
        meta_map = {
            "chunk-t": {
                "caption": None,
                "row_count": 2,
                "col_count": 2,
                "headers": [],
                "section_context": None,
                "confidence": conf,
                "extraction_engine": "camelot",
                "is_valid": True,
            }
        }
        result = _with_table_metadata(citation, meta_map)
        assert result.table_low_confidence_warning is False

    def test_zero_confidence_is_warning(self) -> None:
        citation = _make_citation(chunk_id="chunk-t")
        meta_map = {
            "chunk-t": {
                "confidence": 0.0,
                "row_count": 1,
                "col_count": 1,
                "headers": [],
                "section_context": None,
                "caption": None,
                "extraction_engine": "camelot",
                "is_valid": False,
            }
        }
        result = _with_table_metadata(citation, meta_map)
        assert result.table_low_confidence_warning is True

    def test_missing_confidence_no_warning(self) -> None:
        citation = _make_citation(chunk_id="chunk-t")
        meta_map = {
            "chunk-t": {
                "row_count": 3,
                "col_count": 2,
                "headers": [],
                "section_context": None,
                "caption": None,
                # No 'confidence' key
            }
        }
        result = _with_table_metadata(citation, meta_map)
        assert result.table_extraction_confidence is None
        assert result.table_low_confidence_warning is False


# ---------------------------------------------------------------------------
# _with_extraction_quality
# ---------------------------------------------------------------------------


class TestWithExtractionQuality:
    def _build_map(
        self,
        doc_id: str,
        profile: str | None,
        conf: float | None,
        status: str,
    ) -> dict[str, tuple[str | None, float | None, str]]:
        return {doc_id: (profile, conf, status)}

    def test_no_entry_returns_unchanged(self) -> None:
        citation = _make_citation(document_id="doc-a")
        result = _with_extraction_quality(citation, {})
        assert result.doc_extraction_quality is None
        assert result.doc_extraction_warning is False
        assert result.doc_processing_warning is False

    def test_healthy_profile_no_warning(self) -> None:
        citation = _make_citation(document_id="doc-a")
        quality_map = self._build_map("doc-a", "text_based", 0.95, "indexed")
        result = _with_extraction_quality(citation, quality_map)
        assert result.doc_extraction_quality == "text_based"
        assert result.doc_extraction_warning is False
        assert result.doc_processing_warning is False

    @pytest.mark.parametrize("profile", list(_EXTRACTION_WARNING_PROFILES))
    def test_warning_profiles_trigger_extraction_warning(self, profile: str) -> None:
        citation = _make_citation(document_id="doc-a")
        quality_map = self._build_map("doc-a", profile, 0.95, "indexed")
        result = _with_extraction_quality(citation, quality_map)
        assert result.doc_extraction_warning is True

    def test_low_extraction_confidence_triggers_warning(self) -> None:
        citation = _make_citation(document_id="doc-a")
        quality_map = self._build_map("doc-a", "scanned", 0.30, "indexed")
        result = _with_extraction_quality(citation, quality_map)
        assert result.doc_extraction_warning is True

    def test_borderline_extraction_confidence_no_warning(self) -> None:
        citation = _make_citation(document_id="doc-a")
        quality_map = self._build_map("doc-a", "mixed", 0.50, "indexed")
        result = _with_extraction_quality(citation, quality_map)
        assert result.doc_extraction_warning is False

    @pytest.mark.parametrize("status", list(_PROCESSING_INCOMPLETE_STATUSES))
    def test_incomplete_statuses_trigger_processing_warning(self, status: str) -> None:
        citation = _make_citation(document_id="doc-a")
        quality_map = self._build_map("doc-a", "text_based", 0.95, status)
        result = _with_extraction_quality(citation, quality_map)
        assert result.doc_processing_warning is True

    def test_indexed_status_no_processing_warning(self) -> None:
        citation = _make_citation(document_id="doc-a")
        quality_map = self._build_map("doc-a", "text_based", 0.95, "indexed")
        result = _with_extraction_quality(citation, quality_map)
        assert result.doc_processing_warning is False

    def test_none_extraction_confidence_with_healthy_profile_no_warning(self) -> None:
        citation = _make_citation(document_id="doc-a")
        quality_map = self._build_map("doc-a", "text_based", None, "indexed")
        result = _with_extraction_quality(citation, quality_map)
        assert result.doc_extraction_warning is False

    def test_preserves_existing_ocr_and_freshness_fields(self) -> None:
        citation = _make_citation(
            document_id="doc-a",
            doc_ocr_quality_status="low",
            doc_ocr_low_confidence_warning=True,
            doc_stale_warning=True,
        )
        quality_map = self._build_map("doc-a", "text_based", 0.95, "indexed")
        result = _with_extraction_quality(citation, quality_map)
        assert result.doc_ocr_quality_status == "low"
        assert result.doc_ocr_low_confidence_warning is True
        assert result.doc_stale_warning is True

    def test_both_extraction_and_processing_warnings(self) -> None:
        citation = _make_citation(document_id="doc-a")
        quality_map = self._build_map("doc-a", "corrupted", 0.10, "failed")
        result = _with_extraction_quality(citation, quality_map)
        assert result.doc_extraction_warning is True
        assert result.doc_processing_warning is True


# ---------------------------------------------------------------------------
# _compute_table_quality_multiplier
# ---------------------------------------------------------------------------


class TestComputeTableQualityMultiplier:
    def test_no_citations(self) -> None:
        assert _compute_table_quality_multiplier([]) == 1.0

    def test_no_table_chunks(self) -> None:
        citations = [_make_citation(is_table_chunk=False)]
        assert _compute_table_quality_multiplier(citations) == 1.0

    def test_high_confidence_table_no_penalty(self) -> None:
        citation = _make_citation(is_table_chunk=True, table_extraction_confidence=0.90)
        assert _compute_table_quality_multiplier([citation]) == pytest.approx(1.0)

    def test_low_confidence_table_penalty(self) -> None:
        citation = _make_citation(is_table_chunk=True, table_extraction_confidence=0.30)
        result = _compute_table_quality_multiplier([citation])
        assert result == pytest.approx(0.85)

    def test_very_low_confidence_table_heavy_penalty(self) -> None:
        citation = _make_citation(is_table_chunk=True, table_extraction_confidence=0.10)
        result = _compute_table_quality_multiplier([citation])
        assert result == pytest.approx(0.70)

    def test_mixed_citations_averaged(self) -> None:
        citations = [
            _make_citation(is_table_chunk=True, table_extraction_confidence=0.90),  # 1.0
            _make_citation(is_table_chunk=True, table_extraction_confidence=0.30),  # 0.85
        ]
        result = _compute_table_quality_multiplier(citations)
        assert result == pytest.approx((1.0 + 0.85) / 2, rel=1e-4)

    def test_table_chunk_without_confidence_excluded(self) -> None:
        citation = _make_citation(is_table_chunk=True, table_extraction_confidence=None)
        assert _compute_table_quality_multiplier([citation]) == 1.0

    def test_text_and_table_chunks_only_tables_counted(self) -> None:
        citations = [
            _make_citation(is_table_chunk=False),
            _make_citation(is_table_chunk=True, table_extraction_confidence=0.10),  # 0.70
        ]
        result = _compute_table_quality_multiplier(citations)
        assert result == pytest.approx(0.70)


# ---------------------------------------------------------------------------
# _compute_extraction_quality_multiplier
# ---------------------------------------------------------------------------


class TestComputeExtractionQualityMultiplier:
    def test_no_citations(self) -> None:
        assert _compute_extraction_quality_multiplier([]) == 1.0

    def test_no_extraction_warnings(self) -> None:
        citations = [_make_citation(doc_extraction_warning=False)]
        assert _compute_extraction_quality_multiplier(citations) == 1.0

    def test_any_extraction_warning_returns_penalty(self) -> None:
        citations = [
            _make_citation(doc_extraction_warning=False),
            _make_citation(doc_extraction_warning=True),
        ]
        assert _compute_extraction_quality_multiplier(citations) == pytest.approx(0.85)

    def test_all_extraction_warnings_same_penalty(self) -> None:
        citations = [
            _make_citation(doc_extraction_warning=True),
            _make_citation(doc_extraction_warning=True),
        ]
        assert _compute_extraction_quality_multiplier(citations) == pytest.approx(0.85)


# ---------------------------------------------------------------------------
# _build_evidence_quality_record
# ---------------------------------------------------------------------------


class TestBuildEvidenceQualityRecord:
    def test_no_citations(self) -> None:
        rec = _build_evidence_quality_record([])
        assert rec.table_low_confidence_count == 0
        assert rec.extraction_warning_count == 0
        assert rec.processing_warning_count == 0
        assert rec.any_incomplete_documents is False
        assert rec.warning_reasons == []

    def test_single_table_low_confidence(self) -> None:
        citations = [
            CitationTrustRecord(
                document_id="d",
                chunk_id="c",
                is_table_chunk=True,
                table_low_confidence_warning=True,
            )
        ]
        rec = _build_evidence_quality_record(citations)
        assert rec.table_low_confidence_count == 1
        assert rec.extraction_warning_count == 0
        assert len(rec.warning_reasons) == 1
        assert "table" in rec.warning_reasons[0].lower()

    def test_multiple_extraction_warnings(self) -> None:
        citations = [
            CitationTrustRecord(document_id="d1", chunk_id="c1", doc_extraction_warning=True),
            CitationTrustRecord(document_id="d2", chunk_id="c2", doc_extraction_warning=True),
        ]
        rec = _build_evidence_quality_record(citations)
        assert rec.extraction_warning_count == 2
        assert "extraction quality" in rec.warning_reasons[0].lower()
        assert "2 source documents" in rec.warning_reasons[0]

    def test_processing_warning_sets_incomplete_flag(self) -> None:
        citations = [
            CitationTrustRecord(document_id="d", chunk_id="c", doc_processing_warning=True)
        ]
        rec = _build_evidence_quality_record(citations)
        assert rec.processing_warning_count == 1
        assert rec.any_incomplete_documents is True
        assert "processing" in rec.warning_reasons[0].lower()

    def test_all_three_warning_types(self) -> None:
        citations = [
            CitationTrustRecord(
                document_id="d1",
                chunk_id="c1",
                is_table_chunk=True,
                table_low_confidence_warning=True,
            ),
            CitationTrustRecord(
                document_id="d2", chunk_id="c2", doc_extraction_warning=True
            ),
            CitationTrustRecord(
                document_id="d3", chunk_id="c3", doc_processing_warning=True
            ),
        ]
        rec = _build_evidence_quality_record(citations)
        assert rec.table_low_confidence_count == 1
        assert rec.extraction_warning_count == 1
        assert rec.processing_warning_count == 1
        assert rec.any_incomplete_documents is True
        assert len(rec.warning_reasons) == 3

    def test_clean_citations_no_warnings(self) -> None:
        citations = [
            CitationTrustRecord(
                document_id="d1",
                chunk_id="c1",
                is_table_chunk=True,
                table_low_confidence_warning=False,
                doc_extraction_warning=False,
                doc_processing_warning=False,
            )
        ]
        rec = _build_evidence_quality_record(citations)
        assert rec.warning_reasons == []


# ---------------------------------------------------------------------------
# ConfidenceService — table and extraction multipliers
# ---------------------------------------------------------------------------


class TestConfidenceServiceF315Multipliers:
    _chunks = [ConfidenceChunkSignal(similarity_score=0.5, rerank_score=None)]

    def test_default_multipliers_no_change(self) -> None:
        svc = _make_service()
        result = svc.score(
            chunks=self._chunks,
            citation_count=1,
            citation_validation_score=1.0,
            not_found_signal=False,
        )
        assert result.explanation.table_quality_multiplier == pytest.approx(1.0)
        assert result.explanation.extraction_quality_multiplier == pytest.approx(1.0)

    def test_low_table_quality_reduces_score(self) -> None:
        svc = _make_service()
        result_clean = svc.score(
            chunks=self._chunks,
            citation_count=1,
            citation_validation_score=1.0,
            not_found_signal=False,
            table_quality_multiplier=1.0,
        )
        result_low = svc.score(
            chunks=self._chunks,
            citation_count=1,
            citation_validation_score=1.0,
            not_found_signal=False,
            table_quality_multiplier=0.85,
        )
        assert result_low.score < result_clean.score
        assert result_low.explanation.table_quality_multiplier == pytest.approx(0.85)

    def test_low_extraction_quality_reduces_score(self) -> None:
        svc = _make_service()
        result_clean = svc.score(
            chunks=self._chunks,
            citation_count=1,
            citation_validation_score=1.0,
            not_found_signal=False,
            extraction_quality_multiplier=1.0,
        )
        result_low = svc.score(
            chunks=self._chunks,
            citation_count=1,
            citation_validation_score=1.0,
            not_found_signal=False,
            extraction_quality_multiplier=0.85,
        )
        assert result_low.score < result_clean.score
        assert result_low.explanation.extraction_quality_multiplier == pytest.approx(0.85)

    def test_table_quality_reason_emitted(self) -> None:
        svc = _make_service()
        result = svc.score(
            chunks=self._chunks,
            citation_count=1,
            citation_validation_score=1.0,
            not_found_signal=False,
            table_quality_multiplier=0.85,
        )
        codes = [r.code for r in result.explanation.reasons]
        assert "low_table_extraction" in codes

    def test_extraction_quality_reason_emitted(self) -> None:
        svc = _make_service()
        result = svc.score(
            chunks=self._chunks,
            citation_count=1,
            citation_validation_score=1.0,
            not_found_signal=False,
            extraction_quality_multiplier=0.85,
        )
        codes = [r.code for r in result.explanation.reasons]
        assert "low_extraction_quality" in codes

    def test_trust_level_warning_from_low_table_quality(self) -> None:
        svc = _make_service(medium_threshold=0.80)
        result = svc.score(
            chunks=self._chunks,
            citation_count=1,
            citation_validation_score=1.0,
            not_found_signal=False,
            table_quality_multiplier=0.70,
        )
        assert result.trust_level == "warning"
        assert result.explanation.table_quality_multiplier == pytest.approx(0.70)

    def test_trust_level_warning_from_low_extraction_quality(self) -> None:
        svc = _make_service(medium_threshold=0.80)
        result = svc.score(
            chunks=self._chunks,
            citation_count=1,
            citation_validation_score=1.0,
            not_found_signal=False,
            extraction_quality_multiplier=0.85,
        )
        assert result.trust_level == "warning"

    def test_high_score_not_degraded_to_warning_by_mild_table_quality(self) -> None:
        svc = _make_service(high_threshold=0.60)
        result = svc.score(
            chunks=[ConfidenceChunkSignal(similarity_score=0.95)],
            citation_count=3,
            citation_validation_score=1.0,
            not_found_signal=False,
            table_quality_multiplier=0.95,
        )
        assert result.trust_level == "high"

    def test_no_chunks_explanation_includes_new_multipliers(self) -> None:
        svc = _make_service()
        result = svc.score(
            chunks=[],
            citation_count=0,
            citation_validation_score=1.0,
            not_found_signal=False,
            table_quality_multiplier=0.80,
            extraction_quality_multiplier=0.85,
        )
        assert result.explanation.table_quality_multiplier == pytest.approx(0.80)
        assert result.explanation.extraction_quality_multiplier == pytest.approx(0.85)


# ---------------------------------------------------------------------------
# ConfidenceTrustRecord — F315 fields present in schema
# ---------------------------------------------------------------------------


class TestConfidenceTrustRecordF315:
    def test_new_multiplier_fields_default_to_1(self) -> None:
        rec = ConfidenceTrustRecord(
            score=0.8,
            category="high",
            trust_level="high",
            citation_support_score=0.8,
            citation_validation_score=0.9,
            citation_coverage_score=0.75,
            retrieval_agreement_score=0.9,
            top_similarity=0.85,
            average_similarity=0.82,
            top_rerank_score=0.83,
            raw_score=0.80,
            citation_validation_multiplier=0.9,
            not_found_penalty_multiplier=1.0,
            not_found_signal=False,
            no_context=False,
        )
        assert rec.table_quality_multiplier == pytest.approx(1.0)
        assert rec.extraction_quality_multiplier == pytest.approx(1.0)

    def test_can_set_low_multipliers(self) -> None:
        rec = ConfidenceTrustRecord(
            score=0.55,
            category="medium",
            trust_level="warning",
            citation_support_score=0.6,
            citation_validation_score=0.7,
            citation_coverage_score=0.5,
            retrieval_agreement_score=0.8,
            top_similarity=0.7,
            average_similarity=0.65,
            top_rerank_score=0.68,
            raw_score=0.65,
            citation_validation_multiplier=0.7,
            not_found_penalty_multiplier=1.0,
            table_quality_multiplier=0.85,
            extraction_quality_multiplier=0.85,
            not_found_signal=False,
            no_context=False,
        )
        assert rec.table_quality_multiplier == pytest.approx(0.85)
        assert rec.extraction_quality_multiplier == pytest.approx(0.85)
        assert rec.trust_level == "warning"
