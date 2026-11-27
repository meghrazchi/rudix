"""Ingestion behaviour fixtures recorded through the worker with fakes (R06-01).

Each scenario runs the document task body (or the evaluation re-ingest coroutine) and
compares the resulting rows and fake calls with ``tests/fixtures/ingestion_golden``.
``INGESTION_GOLDEN_UPDATE=1`` rewrites the fixtures.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import fitz  # type: ignore[import-untyped]
import pytest
from ingestion_golden_support import (
    EXTRACT_PATCH_TARGET,
    FailingEntityExtraction,
    IngestionEnv,
    Seeded,
    assert_matches_golden,
    ingestion_env,  # noqa: F401  (fixture)
    snapshot,
)

from app.core.config import settings
from app.domains.documents.extraction.models import (
    DocumentProfile,
    ExtractionResult,
    PageExtractionResult,
    TableBlock,
    TableCell,
    TextBlock,
)
from app.workers import document_tasks

POLICY_TEXT = (
    "Annual leave policy. Employees receive twenty days of paid annual leave each year. "
    "Requests are submitted through the people portal at least two weeks in advance.\n\n"
    "Carry over. Up to five unused days carry over into the first quarter of the next "
    "year. Days that are not used by the end of March expire without compensation.\n\n"
    "Sick leave. Sick leave is separate from annual leave and requires a medical note "
    "after three consecutive days. Managers record sick leave in the absence calendar.\n\n"
    "Travel. Business travel is booked through the travel desk. Economy class applies to "
    "flights under six hours and premium economy applies to longer flights."
)
SMALL_CHUNKS = {"strategy": "token_recursive", "chunk_size_tokens": 40, "chunk_overlap_tokens": 5}
HIERARCHICAL = {"strategy": "hierarchical", "chunk_size_tokens": 30, "chunk_overlap_tokens": 5}
PII_TEXT = (
    "IDs: 123-45-6789, 234-56-7890, 345-67-8901, 456-78-9012, 321-54-9876. "
    "Employees receive twenty days of annual leave."
)


def _ids(seeded: Seeded) -> dict[str, str]:
    # Task kwargs as the upload and reindex endpoints send them.
    return {"organization_id": str(seeded.organization_id), "user_id": str(seeded.user_id)}


def _run_process(env: IngestionEnv, seeded: Seeded, task_id: str, **kwargs: Any) -> Any:
    try:
        result = env.run_task(
            document_tasks.process_document,
            seeded.document_id,
            task_id=task_id,
            **_ids(seeded),
            **kwargs,
        )
    except Exception as exc:
        details = getattr(exc, "error_details", {})
        return {"raised": type(exc).__name__, "code": details.get("code")}
    return {key: value for key, value in result.items() if "latency" not in key}


def _upload_text(env: IngestionEnv) -> tuple[Seeded, Any]:
    env.set_content(POLICY_TEXT.encode())
    seeded = env.seed()
    return seeded, _run_process(env, seeded, "task-upload")


def _reindex(env: IngestionEnv) -> tuple[Seeded, Any]:
    env.set_content(POLICY_TEXT.encode())
    seeded = env.seed()
    _run_process(env, seeded, "task-first")
    env.fakes.reset_calls()
    try:
        result = env.run_task(
            document_tasks.reindex_document,
            seeded.document_id,
            task_id="task-reindex",
            chunking_profile_config=SMALL_CHUNKS,
            **_ids(seeded),
        )
    except Exception as exc:  # pragma: no cover - fixture records the failure
        return seeded, {"raised": type(exc).__name__}
    return seeded, {key: value for key, value in result.items() if "latency" not in key}


def _two_page_pdf() -> bytes:
    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_text((72, 72), "Native page one explains the expense approval workflow.")
    pdf.new_page()
    data = pdf.tobytes()
    pdf.close()
    return bytes(data)


def _pdf_ocr(env: IngestionEnv) -> tuple[Seeded, Any]:
    env.set_content(_two_page_pdf())
    seeded = env.seed(filename="scan.pdf", file_type="pdf")
    return seeded, _run_process(env, seeded, "task-ocr")


def _dlp(action: str) -> Callable[[IngestionEnv], tuple[Seeded, Any]]:
    def _scenario(env: IngestionEnv) -> tuple[Seeded, Any]:
        env.monkeypatch.setattr(settings, "dlp_enabled", True)
        env.monkeypatch.setattr(settings, "dlp_action", action)
        env.set_content(PII_TEXT.encode())
        seeded = env.seed()
        return seeded, _run_process(env, seeded, f"task-dlp-{action}")

    return _scenario


def _hierarchical(env: IngestionEnv) -> tuple[Seeded, Any]:
    env.set_content(POLICY_TEXT.encode())
    seeded = env.seed()
    return seeded, _run_process(
        env, seeded, "task-hierarchical", chunking_profile_config=HIERARCHICAL
    )


def _table_extraction(content: bytes, **_: Any) -> ExtractionResult:
    cells = tuple(
        TableCell(row=row, col=col, text=text)
        for row, values in enumerate((("Plan", "Days"), ("Basic", "20"), ("Plus", "25")))
        for col, text in enumerate(values)
    )
    table = TableBlock(
        page_number=1,
        table_index=0,
        row_count=3,
        col_count=2,
        cells=cells,
        markdown="| Plan | Days |\n|---|---|\n| Basic | 20 |\n| Plus | 25 |",
        json_data=(("Plan", "Days"), ("Basic", "20"), ("Plus", "25")),
        caption="Leave days by plan",
        confidence=0.9,
        extraction_engine="fake",
        bbox=None,
    )
    text = TextBlock(
        page_number=1,
        text="Annual leave allowance depends on the plan the employee is enrolled in.",
        bbox=None,
        block_type="paragraph",
    )
    page = PageExtractionResult(
        page_number=1,
        text_blocks=[text],
        table_blocks=[table],
        image_blocks=[],
        char_count=200,
        page_width=600.0,
        page_height=800.0,
        text_coverage_ratio=0.5,
        image_coverage_ratio=0.0,
        requires_ocr=False,
    )
    return ExtractionResult(
        document_profile=DocumentProfile.table_heavy,
        page_count=1,
        pages=[page],
        total_text_blocks=1,
        total_table_blocks=1,
        total_image_blocks=0,
        warnings=[],
        extraction_engine="fake",
        extraction_confidence=0.95,
        duration_ms=4,
    )


def _table_chunks(env: IngestionEnv) -> tuple[Seeded, Any]:
    env.monkeypatch.setattr(*EXTRACT_PATCH_TARGET, _table_extraction)
    env.set_content(b"%PDF-fake")
    seeded = env.seed(filename="tables.pdf", file_type="pdf")
    return seeded, _run_process(env, seeded, "task-table")


def _connector(env: IngestionEnv) -> tuple[Seeded, Any]:
    env.set_content(POLICY_TEXT.encode())
    seeded = env.seed(connector=True)
    return seeded, _run_process(env, seeded, "task-connector", chunking_profile_config=SMALL_CHUNKS)


def _graph(strict: bool) -> Callable[[IngestionEnv], tuple[Seeded, Any]]:
    def _scenario(env: IngestionEnv) -> tuple[Seeded, Any]:
        env.monkeypatch.setattr(settings, "enterprise_graph_enabled", True)
        env.monkeypatch.setattr(settings, "feature_enable_entity_extraction", True)
        env.monkeypatch.setattr(settings, "entity_extraction_strict_mode", strict)
        env.monkeypatch.setattr(
            document_tasks, "_entity_extraction_service", FailingEntityExtraction()
        )
        env.set_content(POLICY_TEXT.encode())
        seeded = env.seed()
        return seeded, _run_process(env, seeded, f"task-graph-{strict}")

    return _scenario


def _evaluation_reingest(env: IngestionEnv) -> tuple[Seeded, Any]:
    env.set_content(POLICY_TEXT.encode())
    seeded = env.seed()
    _run_process(env, seeded, "task-production")
    env.fakes.reset_calls()
    service = document_tasks._make_chunking_service(SMALL_CHUNKS, index_version="eval-golden")
    pages, chunks, stats, embedding = env.run_async(
        document_tasks._extract_and_store_document_pages_async(
            str(seeded.document_id),
            request_id="req-eval",
            **_ids(seeded),
            pipeline_type="evaluation.run",
            chunking_service=service,
            profile_source="custom_profile",
            persist_document_state=False,
            persist_document_pages=False,
            record_usage_event=False,
        )
    )
    return seeded, {
        "page_count": pages,
        "chunk_count": chunks,
        "cleaning": stats.as_log_fields(),
        "input_tokens": embedding.input_tokens,
        "batch_count": embedding.batch_count,
    }


SCENARIOS: dict[str, Callable[[IngestionEnv], tuple[Seeded, Any]]] = {
    "upload_text": _upload_text,
    "reindex": _reindex,
    "pdf_ocr": _pdf_ocr,
    "dlp_warn": _dlp("warn"),
    "dlp_quarantine": _dlp("quarantine"),
    "hierarchical_chunks": _hierarchical,
    "table_chunks": _table_chunks,
    "connector_document": _connector,
    "graph_lenient_failure": _graph(strict=False),
    "graph_strict_failure": _graph(strict=True),
    "evaluation_reingest": _evaluation_reingest,
}


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_ingestion_matches_golden(ingestion_env: IngestionEnv, name: str) -> None:  # noqa: F811
    seeded, outcome = SCENARIOS[name](ingestion_env)
    assert_matches_golden(name, snapshot(ingestion_env, seeded, outcome=outcome))
