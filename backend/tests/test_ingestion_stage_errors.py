"""Stage failure codes and less common stage paths of the staged worker (R06-01)."""

from __future__ import annotations

from typing import Any

import pytest
from botocore.exceptions import ClientError  # type: ignore[import-untyped]
from ingestion_golden_support import (
    EXTRACT_PATCH_TARGET,
    OCR_PATCH_TARGET,
    IngestionEnv,
    Seeded,
    ingestion_env,  # noqa: F401  (fixture)
)
from sqlalchemy import select, update
from test_ingestion_golden import _table_extraction, _two_page_pdf

from app.core.config import settings
from app.domains.documents.extraction.models import DocumentProfile
from app.domains.documents.services.embedding_service import (
    PermanentEmbeddingError,
    TransientEmbeddingError,
)
from app.models.document import Document
from app.workers import document_tasks
from app.workers.ingestion.options import IngestionOptions
from app.workers.ingestion.pipeline import extract_and_store
from app.workers.ingestion.stages import chunk as chunk_stage

TEXT = b"Annual leave is twenty days. Requests go through the people portal in advance."


def _run(env: IngestionEnv, seeded: Seeded, **kwargs: Any) -> Any:
    return env.run_async(
        document_tasks._extract_and_store_document_pages_async(str(seeded.document_id), **kwargs)
    )


def _code(env: IngestionEnv, seeded: Seeded, **kwargs: Any) -> str:
    with pytest.raises(Exception) as raised:
        _run(env, seeded, **kwargs)
    return str(raised.value.error_details["code"])  # type: ignore[attr-defined]


async def _document(env: IngestionEnv, seeded: Seeded) -> Document:
    async with env.factory() as session:
        return (
            await session.execute(select(Document).where(Document.id == seeded.document_id))
        ).scalar_one()


async def _set(env: IngestionEnv, seeded: Seeded, **values: Any) -> None:
    async with env.factory() as session:
        await session.execute(
            update(Document).where(Document.id == seeded.document_id).values(**values)
        )
        await session.commit()


def test_invalid_and_missing_documents(ingestion_env: IngestionEnv) -> None:  # noqa: F811
    with pytest.raises(Exception) as raised:
        ingestion_env.run_async(document_tasks._extract_and_store_document_pages_async("x"))
    assert raised.value.error_details["code"] == "INVALID_DOCUMENT_ID"  # type: ignore[attr-defined]
    with pytest.raises(Exception) as raised:
        ingestion_env.run_async(
            document_tasks._extract_and_store_document_pages_async(
                "00000000-0000-0000-0000-000000000001"
            )
        )
    assert raised.value.error_details["code"] == "DOCUMENT_NOT_FOUND"  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    ("error_code", "expected"),
    [("NoSuchKey", "SOURCE_OBJECT_MISSING"), ("SlowDown", "SOURCE_OBJECT_READ_FAILED")],
)
def test_object_read_failures(
    ingestion_env: IngestionEnv,  # noqa: F811
    error_code: str,
    expected: str,
) -> None:
    def _fail(**_: Any) -> Any:
        raise ClientError({"Error": {"Code": error_code}}, "GetObject")

    ingestion_env.monkeypatch.setattr(ingestion_env.fakes.minio, "get_object", _fail)
    assert _code(ingestion_env, ingestion_env.seed()) == expected


@pytest.mark.parametrize(
    ("profile", "expected"),
    [(DocumentProfile.encrypted, "PDF_ENCRYPTED"), (DocumentProfile.corrupted, "PDF_CORRUPTED")],
)
def test_unreadable_pdf_profiles(
    ingestion_env: IngestionEnv,  # noqa: F811
    profile: DocumentProfile,
    expected: str,
) -> None:
    def _extract(content: bytes, **kwargs: Any) -> Any:
        result = _table_extraction(content)
        result.document_profile = profile
        return result

    ingestion_env.monkeypatch.setattr(*EXTRACT_PATCH_TARGET, _extract)
    assert _code(ingestion_env, ingestion_env.seed(file_type="pdf")) == expected


def test_extraction_value_error(ingestion_env: IngestionEnv) -> None:  # noqa: F811
    def _extract(content: bytes, **_: Any) -> Any:
        raise ValueError("unsupported layout")

    ingestion_env.monkeypatch.setattr(*EXTRACT_PATCH_TARGET, _extract)
    assert _code(ingestion_env, ingestion_env.seed()) == "TEXT_EXTRACTION_FAILED"


@pytest.mark.parametrize("file_type", ["txt", "pdf", "docx"])
def test_legacy_extraction_path(
    ingestion_env: IngestionEnv,  # noqa: F811
    file_type: str,
) -> None:
    env = ingestion_env
    env.monkeypatch.setattr(settings, "feature_enable_advanced_pdf_extraction", False)
    env.set_content(_two_page_pdf() if file_type == "pdf" else TEXT)
    seeded = env.seed(file_type=file_type)
    if file_type == "docx":
        assert _code(env, seeded) == "TEXT_EXTRACTION_FAILED"
        return
    pages, chunks, _, _ = _run(env, seeded)
    assert pages == (2 if file_type == "pdf" else 1) and chunks >= 1
    if file_type == "pdf":
        assert env.fakes.ocr_calls == [[2]]


@pytest.mark.parametrize("failure", ["status", "dependencies"])
def test_ocr_failures(ingestion_env: IngestionEnv, failure: str) -> None:  # noqa: F811
    env = ingestion_env
    from app.domains.documents.services.ocr_service import OcrDocumentResult, OcrPageResult

    def _ocr(content: bytes, pages: list[int], **_: Any) -> Any:
        if failure == "dependencies":
            raise RuntimeError("tesseract missing")
        return OcrDocumentResult(
            status="failed",
            pages=[OcrPageResult(2, "", ["eng"], "failed", warning="blank render")],
            duration_ms=1,
            languages=["eng"],
        )

    env.monkeypatch.setattr(*OCR_PATCH_TARGET, _ocr)
    env.set_content(_two_page_pdf())
    expected = "OCR_DEPENDENCIES_MISSING" if failure == "dependencies" else "OCR_FAILED"
    assert _code(env, env.seed(file_type="pdf")) == expected


@pytest.mark.parametrize("source", ["admin_override", "upload_provided"])
def test_language_sources_are_respected(
    ingestion_env: IngestionEnv,  # noqa: F811
    source: str,
) -> None:
    env = ingestion_env
    env.set_content(b"ok")  # too short to detect
    seeded = env.seed()
    env.run_async(_set(env, seeded, language="de", language_source=source))
    _run(env, seeded)
    document = env.run_async(_document(env, seeded))
    assert document.language == "de" and document.language_source == source


def test_dlp_disabled_skips_the_scan(ingestion_env: IngestionEnv) -> None:  # noqa: F811
    env = ingestion_env
    env.monkeypatch.setattr(settings, "dlp_enabled", False)
    env.set_content(b"IDs: 123-45-6789, 234-56-7890, 345-67-8901, 456-78-9012, 321-54-9876.")
    seeded = env.seed()
    _run(env, seeded)
    assert env.run_async(_document(env, seeded)).dlp_scan_result is None


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (ValueError("bad filter"), "QDRANT_CLEANUP_FILTER_INVALID"),
        (OSError(), "QDRANT_CLEANUP_FAILED"),
    ],
)
def test_vector_cleanup_failures(
    ingestion_env: IngestionEnv,  # noqa: F811
    error: Exception,
    expected: str,
) -> None:
    async def _delete(**_: Any) -> Any:
        raise error

    env = ingestion_env
    env.monkeypatch.setattr(env.fakes.qdrant, "delete_document_points", _delete)
    env.set_content(TEXT)
    assert _code(env, env.seed()) == expected


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (PermanentEmbeddingError("bad input"), "EMBEDDING_FAILED_PERMANENT"),
        (TransientEmbeddingError("timeout"), "EMBEDDING_FAILED_TRANSIENT"),
        ("incomplete", "EMBEDDING_INCOMPLETE"),
        (ValueError("bad payload"), "QDRANT_PAYLOAD_INVALID"),
    ],
)
def test_embed_and_upsert_failures(
    ingestion_env: IngestionEnv,  # noqa: F811
    failure: Any,
    expected: str,
) -> None:
    env = ingestion_env
    real = env.fakes.embeddings.embed_chunks

    async def _embed(*, chunks: list[Any]) -> Any:
        if isinstance(failure, PermanentEmbeddingError | TransientEmbeddingError):
            raise failure
        result = await real(chunks=chunks)
        if failure == "incomplete":
            result.vectors_by_chunk_id = {}
        return result

    async def _upsert(**_: Any) -> Any:
        raise failure

    env.monkeypatch.setattr(env.fakes.embeddings, "embed_chunks", _embed)
    if isinstance(failure, ValueError):
        env.monkeypatch.setattr(env.fakes.qdrant, "upsert_chunks", _upsert)
    env.set_content(TEXT)
    assert _code(env, env.seed()) == expected


def test_finalize_refuses_a_superseded_claim(ingestion_env: IngestionEnv) -> None:  # noqa: F811
    env = ingestion_env
    env.set_content(TEXT)
    seeded = env.seed(status="processing")
    env.run_async(_set(env, seeded, processing_task_id="another-task"))
    assert _code(env, seeded, run_id="mine", claim_token="mine") == "CLAIM_SUPERSEDED"
    document = env.run_async(_document(env, seeded))
    assert document.status == "processing" and document.processing_task_id == "another-task"
    assert env.fakes.qdrant.points  # vectors of the run exist; the holder's run replaces them


def test_status_update_failure_is_transient(ingestion_env: IngestionEnv) -> None:  # noqa: F811
    env = ingestion_env

    async def _none(*_: Any, **__: Any) -> None:
        return None

    env.monkeypatch.setattr(document_tasks._document_repository, "update_document_status", _none)
    env.set_content(TEXT)
    assert _code(env, env.seed()) == "STATUS_INDEXED_UPDATE_FAILED"


def test_vector_collection_reaches_cleanup_and_upserts(
    ingestion_env: IngestionEnv,  # noqa: F811
) -> None:
    env = ingestion_env
    deletes: list[dict[str, Any]] = []
    real_delete = env.fakes.qdrant.delete_document_points

    async def _delete(**kwargs: Any) -> Any:
        deletes.append(kwargs)
        return await real_delete(**kwargs)

    env.monkeypatch.setattr(env.fakes.qdrant, "delete_document_points", _delete)
    env.set_content(TEXT)
    seeded = env.seed()
    service = document_tasks._make_chunking_service(None, index_version="eval-x")
    options = IngestionOptions(
        pipeline_type="evaluation.run",
        chunking_service=service,
        persist_document_state=False,
        persist_document_pages=False,
        record_usage_event=False,
        vector_collection="eval_vectors",
    )
    env.run_async(
        extract_and_store(
            str(seeded.document_id),
            request_id=None,
            organization_id=None,
            user_id=None,
            options=options,
        )
    )
    assert deletes[0]["collection_name"] == "eval_vectors"
    assert {call["collection_name"] for call in env.fakes.qdrant.upserts} == {"eval_vectors"}


def test_adaptive_strategy_snapshot(ingestion_env: IngestionEnv) -> None:  # noqa: F811
    env = ingestion_env
    env.set_content(b"# Leave\n\nTwenty days per year.\n\n# Travel\n\nRail first for short trips.")
    seeded = env.seed()
    env.run_task(
        document_tasks.process_document,
        seeded.document_id,
        task_id="adaptive",
        chunking_profile_config={"strategy": "adaptive_hybrid"},
    )
    snapshot = env.run_async(_document(env, seeded)).chunking_config_snapshot or {}
    assert "adaptive_selected_strategy" in snapshot
    assert "adaptive_signals" in snapshot and "language" not in snapshot["adaptive_signals"]


def test_table_without_text_is_skipped(ingestion_env: IngestionEnv) -> None:  # noqa: F811
    env = ingestion_env
    env.monkeypatch.setattr(*EXTRACT_PATCH_TARGET, _table_extraction)
    real = chunk_stage.build_table_chunk

    def _empty(table: Any, **kwargs: Any) -> Any:
        result = real(table, **kwargs)
        return type(result)(
            text=" ", table_metadata=result.table_metadata, is_valid=result.is_valid
        )

    env.monkeypatch.setattr(chunk_stage, "build_table_chunk", _empty)
    env.set_content(b"%PDF-fake")
    seeded = env.seed(file_type="pdf")
    _run(env, seeded)
    snapshot = env.run_async(_document(env, seeded)).chunking_config_snapshot or {}
    assert "table_chunk_count" not in snapshot


def test_connector_document_without_source_document_writes_no_references(
    ingestion_env: IngestionEnv,  # noqa: F811
) -> None:
    from sqlalchemy import delete

    from app.models.connector_source import SourceDocument, SourceReference

    env = ingestion_env
    env.set_content(TEXT)
    seeded = env.seed(connector=True)

    async def _drop_source() -> None:
        async with env.factory() as session:
            await session.execute(
                delete(SourceDocument).where(SourceDocument.document_id == seeded.document_id)
            )
            await session.commit()

    async def _references() -> int:
        async with env.factory() as session:
            rows = await session.execute(
                select(SourceReference.id).where(SourceReference.document_id == seeded.document_id)
            )
            return len(rows.all())

    env.run_async(_drop_source())
    _run(env, seeded)
    assert env.run_async(_references()) == 0
