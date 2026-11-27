"""Inline runner and page artifacts (R06-01)."""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import uuid4

import pytest
from ingestion_golden_support import (
    FakeEmbeddings,  # noqa: F401  (sets the strict-settings environment first)
)

from app.core.config import settings
from app.domains.documents.extraction.models import BoundingBox, TableBlock, TableCell
from app.workers.ingestion.context import StageContext
from app.workers.ingestion.deps import current_deps
from app.workers.ingestion.errors import (
    DocumentPipelinePermanentError,
    DocumentPipelineTransientError,
)
from app.workers.ingestion.options import IngestionOptions
from app.workers.ingestion.pages import (
    read_pages,
    table_from_dict,
    table_to_dict,
    to_sections,
    write_pages,
)
from app.workers.ingestion.runner import run_inline
from app.workers.ingestion.stages.base import Stage, StageName, StageOutcome
from app.workers.ingestion.store import COMPLETED, FAILED, RUNNING, MemoryStageStore


class _Recorder:
    async def emit_stage(self, **_: Any) -> None:
        return None


def _ctx(store: Any) -> StageContext:
    return StageContext(
        document_id=uuid4(),
        organization_id=str(uuid4()),
        user_id=str(uuid4()),
        request_id=None,
        run_id="run",
        claim_token="run",
        options=IngestionOptions(),
        deps=current_deps(),
        recorder=_Recorder(),  # type: ignore[arg-type]
        store=store,
    )


def _stage(name: StageName, calls: list[str], **metrics: Any) -> Stage:
    async def _run(ctx: StageContext) -> StageOutcome:
        calls.append(name)
        return StageOutcome(metrics=dict(metrics))

    return Stage(name=name, run=_run)


class _Killed(BaseException):
    pass


def test_completed_stages_are_skipped_and_their_metrics_loaded() -> None:
    async def _run() -> None:
        store = MemoryStageStore()
        await store.mark_completed("extract", metrics={"page_count": 2})
        ctx = _ctx(store)
        calls: list[str] = []
        stages = [
            _stage(StageName.extract, calls),
            _stage(StageName.clean_detect, calls, page_count=2),
        ]
        records = await run_inline(ctx, stages)
        assert calls == [StageName.clean_detect]
        assert ctx.metrics["extract"] == {"page_count": 2}
        assert records["clean_detect"].status == COMPLETED

    asyncio.run(_run())


def test_missing_artifacts_rerun_the_producer() -> None:
    async def _run() -> None:
        store = MemoryStageStore()
        # extract completed with two parts, but its artifacts are gone and clean_detect
        # (a consumer) has not run yet.
        await store.mark_completed("extract", metrics={"artifact_parts": 2})
        ctx = _ctx(store)
        calls: list[str] = []
        stages = [
            _stage(StageName.extract, calls, artifact_parts=2),
            _stage(StageName.clean_detect, calls),
        ]
        await run_inline(ctx, stages)
        assert calls == [StageName.extract, StageName.clean_detect]

        # Once every consumer completed, missing artifacts no longer matter.
        calls.clear()
        await run_inline(ctx, stages)
        assert calls == []

    asyncio.run(_run())


def test_lease_held_by_another_task_is_transient() -> None:
    async def _run() -> None:
        store = MemoryStageStore()
        assert await store.lease("extract", owner="other-task") is not None
        with pytest.raises(DocumentPipelineTransientError) as raised:
            await run_inline(_ctx(store), [_stage(StageName.extract, [])])
        assert raised.value.error_details["code"] == "STAGE_LEASE_HELD"

    asyncio.run(_run())


def test_failure_marks_the_row_failed_with_the_error_code() -> None:
    async def _run() -> None:
        store = MemoryStageStore()

        async def _fail(ctx: StageContext) -> StageOutcome:
            raise DocumentPipelinePermanentError(
                stage="chunk", code="EMPTY_CHUNK_SET", category="validation", message="none"
            )

        with pytest.raises(DocumentPipelinePermanentError):
            await run_inline(_ctx(store), [Stage(name=StageName.chunk, run=_fail)])
        record = (await store.load())["chunk"]
        assert record.status == FAILED and record.error_code == "EMPTY_CHUNK_SET"

    asyncio.run(_run())


def test_failure_is_raised_even_when_marking_it_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _run() -> None:
        store = MemoryStageStore()

        async def _broken_mark(stage: str, *, error_code: str) -> None:
            raise RuntimeError("database gone")

        monkeypatch.setattr(store, "mark_failed", _broken_mark)

        async def _fail(ctx: StageContext) -> StageOutcome:
            raise ValueError("boom")

        with pytest.raises(ValueError, match="boom"):
            await run_inline(_ctx(store), [Stage(name=StageName.dlp, run=_fail)])

    asyncio.run(_run())


def test_base_exception_leaves_the_stage_running() -> None:
    async def _run() -> None:
        store = MemoryStageStore()

        async def _die(ctx: StageContext) -> StageOutcome:
            raise _Killed

        with pytest.raises(_Killed):
            await run_inline(_ctx(store), [Stage(name=StageName.embed, run=_die)])
        assert (await store.load())["embed"].status == RUNNING

    asyncio.run(_run())


def test_oversize_page_text_is_split_and_joined(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ingest_artifact_max_part_bytes", 64 * 1024)

    async def _run() -> None:
        store = MemoryStageStore()
        ctx = _ctx(store)
        # Random-looking text compresses badly, so the page needs several parts.
        big = "".join(uuid4().hex for _ in range(8000))
        pages = [
            {"page_number": 1, "text": "short", "char_count": 5},
            {"page_number": 2, "text": big, "char_count": len(big), "tables": []},
            {"page_number": 3, "text": "tail", "char_count": 4},
        ]
        parts = await write_pages(ctx, "extract", pages)
        assert parts > 3
        read = await read_pages(ctx, "extract")
        assert read == pages
        sections = to_sections(read)
        assert [s.page_number for s in sections] == [1, 2, 3]
        assert sections[1].text == big

    asyncio.run(_run())


def test_page_with_oversize_non_text_fields_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ingest_artifact_max_part_bytes", 64 * 1024)

    async def _run() -> None:
        ctx = _ctx(MemoryStageStore())
        noise = ["".join(uuid4().hex for _ in range(20)) for _ in range(400)]
        page = {"page_number": 1, "text": "t", "char_count": 1, "tables": noise}
        with pytest.raises(DocumentPipelinePermanentError) as raised:
            await write_pages(ctx, "extract", [page])
        assert raised.value.error_details["code"] == "STAGE_ARTIFACT_TOO_LARGE"

    asyncio.run(_run())


@pytest.mark.parametrize("bbox", [None, BoundingBox(1.0, 2.0, 3.0, 4.0)])
def test_table_blocks_round_trip(bbox: BoundingBox | None) -> None:
    table = TableBlock(
        page_number=2,
        table_index=1,
        row_count=2,
        col_count=2,
        cells=(TableCell(0, 0, "a"), TableCell(0, 1, "b")),
        markdown="| a | b |",
        json_data=(("a", "b"), ("1", "2")),
        caption=None,
        confidence=0.8,
        extraction_engine="fake",
        bbox=bbox,
    )
    assert table_from_dict(table_to_dict(table)) == table
