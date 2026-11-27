"""Bounded memory for large files (R06-02).

The stored object is streamed to a temporary file with sized reads, and PDF and TXT are
extracted from that file page by page. ``tracemalloc`` measures Python allocations only
(PyMuPDF's C heap is not traced); the bounds below therefore check that no Python copy of
the whole file or of every page's text is built, which is what the change removes.
"""

from __future__ import annotations

import tracemalloc
from pathlib import Path
from typing import Any

import fitz  # type: ignore[import-untyped]
import pytest

from app.clients import minio_client as minio_module
from app.core.config import settings
from app.domains.documents.extraction.extraction_service import (
    ResultExtractionStream,
    extract_document,
    stream_document,
)
from app.domains.documents.extraction.pdf_engine import PdfExtractionStream, text_blocks_of
from app.domains.documents.services.ocr_service import run_ocr
from app.domains.documents.services.text_extraction import (
    extract_text_sections,
    iter_pdf_sections,
    iter_text_sections,
    iter_txt_sections,
)
from app.workers.base_task import PermanentTaskError, TransientTaskError
from app.workers.ingestion import storage

_MIB = 1024 * 1024
_LINE = b"Travel reimbursement rules apply to every approved business trip.\n"


class _GeneratedBody:
    """A large object produced on the fly; ``read()`` without a size is forbidden."""

    def __init__(self, total: int, *, fail_after: int | None = None) -> None:
        self.total, self.sent, self.reads, self.closed = total, 0, 0, False
        self.fail_after = fail_after
        self.sizes: list[int] = []

    def read(self, amt: int | None = None) -> bytes:
        if amt is None or amt < 0:
            raise AssertionError("read() without a size would load the whole object")
        self.reads += 1
        self.sizes.append(amt)
        if self.fail_after is not None and self.reads > self.fail_after:
            raise OSError("connection reset")
        count = min(amt, self.total - self.sent)
        self.sent += count
        repeats = count // len(_LINE) + 1
        return (_LINE * repeats)[:count]

    def close(self) -> None:
        self.closed = True


class _Minio:
    def __init__(self, body: Any) -> None:
        self.body = body

    def get_object(self, **_: Any) -> dict[str, Any]:
        return {"Body": self.body}


@pytest.fixture
def temp_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    directory = tmp_path / "ingest-tmp"
    directory.mkdir()
    monkeypatch.setattr(settings, "ingest_temp_dir", str(directory))
    return directory


def _use_body(monkeypatch: pytest.MonkeyPatch, body: Any) -> None:
    monkeypatch.setattr(minio_module, "get_minio_client", lambda: _Minio(body))


def test_download_streams_in_sized_reads_and_removes_the_file(
    monkeypatch: pytest.MonkeyPatch, temp_dir: Path
) -> None:
    body = _GeneratedBody(5 * _MIB + 17)
    _use_body(monkeypatch, body)
    monkeypatch.setattr(settings, "ingest_download_chunk_bytes", _MIB)
    with storage.download_to_tempfile("bucket", "key") as path:
        assert path.parent == temp_dir
        assert path.stat().st_size == 5 * _MIB + 17
        assert list(temp_dir.iterdir()) == [path]
    assert not path.exists()
    assert set(body.sizes) == {_MIB}
    assert body.closed


def test_download_removes_the_file_when_the_block_fails(
    monkeypatch: pytest.MonkeyPatch, temp_dir: Path
) -> None:
    _use_body(monkeypatch, _GeneratedBody(1024))
    with pytest.raises(RuntimeError), storage.download_to_tempfile("bucket", "key"):
        raise RuntimeError("extraction failed")
    assert list(temp_dir.iterdir()) == []


@pytest.mark.parametrize(
    ("body", "error"),
    [
        (_GeneratedBody(4 * _MIB, fail_after=2), TransientTaskError),
        (type("Bad", (), {"read": lambda self, amt: "text"})(), TransientTaskError),
    ],
)
def test_download_failures_remove_the_partial_file(
    monkeypatch: pytest.MonkeyPatch, temp_dir: Path, body: Any, error: type[Exception]
) -> None:
    _use_body(monkeypatch, body)
    monkeypatch.setattr(settings, "ingest_download_chunk_bytes", _MIB)
    with pytest.raises(error), storage.download_to_tempfile("bucket", "key"):
        raise AssertionError("not reached")
    assert list(temp_dir.iterdir()) == []


def test_download_reports_storage_errors(monkeypatch: pytest.MonkeyPatch, temp_dir: Path) -> None:
    from botocore.exceptions import ClientError  # type: ignore[import-untyped]

    class _Missing:
        def get_object(self, **_: Any) -> Any:
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")

    monkeypatch.setattr(minio_module, "get_minio_client", lambda: _Missing())
    with pytest.raises(PermanentTaskError), storage.download_to_tempfile("b", "k"):
        pass


def test_download_reports_temp_dir_errors(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    body = _GeneratedBody(10)
    _use_body(monkeypatch, body)
    monkeypatch.setattr(settings, "ingest_temp_dir", str(tmp_path / "missing"))
    with pytest.raises(TransientTaskError), storage.download_to_tempfile("b", "k"):
        pass
    assert body.closed


def test_download_reports_write_errors(monkeypatch: pytest.MonkeyPatch, temp_dir: Path) -> None:
    class _FullDisk:
        name = str(temp_dir / "partial")

        def __init__(self) -> None:
            Path(self.name).write_bytes(b"")

        def write(self, _: bytes) -> int:
            raise OSError("no space left on device")

        def __enter__(self) -> _FullDisk:
            return self

        def __exit__(self, *_: object) -> None:
            return None

    _use_body(monkeypatch, _GeneratedBody(10))
    monkeypatch.setattr(storage.tempfile, "NamedTemporaryFile", lambda **_: _FullDisk())
    with pytest.raises(TransientTaskError), storage.download_to_tempfile("b", "k"):
        pass
    assert list(temp_dir.iterdir()) == []


def test_large_txt_streams_under_the_bound(monkeypatch: pytest.MonkeyPatch, temp_dir: Path) -> None:
    """64 MiB TXT from a streamed object, decoded in 200 000-character sections.

    Bound: 16 MiB of traced Python memory. One read is 1 MiB, the decode buffer holds at
    most one read plus one segment (about 1.2 MiB of text), and a yielded section is one
    segment; a few transient copies of those stay well under 16 MiB, while any whole-file
    copy (bytes or str) would alone be 64 MiB.
    """
    total = 64 * _MIB
    _use_body(monkeypatch, _GeneratedBody(total))
    monkeypatch.setattr(settings, "ingest_download_chunk_bytes", _MIB)
    monkeypatch.setattr(settings, "ingest_text_segment_chars", 200_000)
    bound = 16 * _MIB
    assert bound < total and settings.ingest_memory_ceiling_mb * _MIB > bound

    tracemalloc.start()
    try:
        with storage.download_to_tempfile("bucket", "key") as path:
            sections = 0
            chars = 0
            for section in iter_text_sections(file_type="txt", content=path):
                sections += 1
                chars += len(section.text)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert peak < bound, f"peak {peak} bytes"
    assert sections >= total // 200_000
    assert chars > total * 0.99


def _many_page_pdf(path: Path, pages: int) -> Path:
    document = fitz.open()
    for index in range(pages):
        page = document.new_page()
        for line in range(60):
            text = f"Page {index + 1} line {line}: " + "policy " * 20
            page.insert_text((20, 30 + line * 13), text, fontsize=6)
    document.save(path)
    document.close()
    return path


@pytest.mark.timeout(120)
def test_many_page_pdf_streams_under_the_bound(tmp_path: Path) -> None:
    """300 pages from a file path, advanced and native extraction.

    Bound: 4 MiB of traced Python memory. The pages hold about 2.8 million characters of
    text, so any list of every page's text (or of PyMuPDF block tuples, which 1.28's
    ``get_text("blocks")`` never frees) is far above it; streaming keeps one page plus a
    ``PageSummary`` (a few hundred bytes) per page.
    """
    path = _many_page_pdf(tmp_path / "many.pdf", 300)
    bound = 4 * _MIB

    tracemalloc.start()
    try:
        with PdfExtractionStream(path, enable_table_extraction=False) as stream:
            text_chars = sum(page.char_count for page in stream.pages())
            result = stream.result()
        _, advanced_peak = tracemalloc.get_traced_memory()
        tracemalloc.reset_peak()
        native_chars = sum(section.char_count for section in iter_pdf_sections(path))
        _, native_peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert advanced_peak < bound, f"advanced peak {advanced_peak} bytes"
    assert native_peak < bound, f"native peak {native_peak} bytes"
    assert result.page_count == 300 and result.pages == []
    assert result.page_summaries is not None and len(result.page_summaries) == 300
    assert result.to_snapshot()["pages"][0]["page_number"] == 1
    assert text_chars > 2_500_000 and native_chars > 2_500_000


def test_text_blocks_match_pymupdf_blocks(tmp_path: Path) -> None:
    """The dict-based blocks equal ``get_text("blocks")`` exactly (text and bbox)."""
    document = fitz.open()
    html = (
        "<h1>Travel policy</h1><p>Claims for <b>approved</b> trips. office, café, naïve.</p>"
        "<table border=1><tr><th>Item</th><th>Limit</th></tr><tr><td>Hotel</td>"
        "<td>150</td></tr></table><p>A long paragraph that wraps " + "across lines " * 30
    )
    for _ in range(3):
        page = document.new_page()
        page.insert_htmlbox(fitz.Rect(40, 40, 555, 800), html)
        page.insert_text((50, 820), "Footer", fontsize=8)
    document.new_page()
    for page in document:
        native = [block for block in page.get_text("blocks") if block[6] == 0]
        ours = text_blocks_of(page)
        assert [b[:5] for b in ours] == [b[:5] for b in native]
    document.close()


def test_path_and_bytes_give_the_same_extraction(tmp_path: Path) -> None:
    path = _many_page_pdf(tmp_path / "small.pdf", 3)
    content = path.read_bytes()
    from_path = extract_document(path, file_type="pdf", min_chars_per_page=5)
    from_bytes = extract_document(content, file_type="pdf", min_chars_per_page=5)
    assert from_path.to_sections() == from_bytes.to_sections()
    assert from_path.to_snapshot()["pages"] == from_bytes.to_snapshot()["pages"]
    assert extract_text_sections(file_type="pdf", content=path) == extract_text_sections(
        file_type="pdf", content=content
    )
    # OCR opens the file path the same way (no candidate pages: nothing rendered).
    assert run_ocr(path, []).status == "skipped"
    assert run_ocr(tmp_path / "missing.pdf", [1]).status == "failed"


def test_txt_sections_below_one_segment_are_unchanged(tmp_path: Path) -> None:
    text = "  First line.\nSecond line.  \n"
    path = tmp_path / "a.txt"
    path.write_text(text, encoding="utf-8")
    sections = extract_text_sections(file_type="txt", content=path)
    assert [(s.page_number, s.text) for s in sections] == [(1, text.strip())]
    assert extract_text_sections(file_type="txt", content=text.encode()) == sections


def test_txt_segments_cut_at_line_then_word_boundaries() -> None:
    text = ("alpha beta gamma\n" * 10).encode()
    sections = list(iter_txt_sections(text, segment_chars=40))
    assert [s.page_number for s in sections] == list(range(1, len(sections) + 1))
    assert all(s.text.endswith("gamma") for s in sections)
    words = list(iter_txt_sections(("word " * 40).encode(), segment_chars=30))
    assert all(s.text.endswith("word") for s in words)
    hard = list(iter_txt_sections(b"x" * 95, segment_chars=30))
    assert [len(s.text) for s in hard] == [30, 30, 30, 5]


def test_txt_invalid_utf8_is_replaced_across_reads(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ingest_download_chunk_bytes", 4096)
    data = "é".encode() * 3000 + b"\xff" + b"tail"
    (section,) = list(iter_txt_sections(data, segment_chars=50_000))
    assert section.text == "é" * 3000 + "�tail"


def test_empty_txt_and_unknown_types_raise() -> None:
    with pytest.raises(ValueError, match="no text"):
        list(iter_text_sections(file_type="txt", content=b"  \n"))
    with pytest.raises(ValueError, match="unsupported"):
        stream_document(b"", file_type="xyz")


def test_encrypted_pdf_is_known_before_pages(tmp_path: Path) -> None:
    path = tmp_path / "locked.pdf"
    document = fitz.open()
    document.new_page().insert_text((72, 72), "secret")
    document.save(path, encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw="o", user_pw="u")
    document.close()
    with PdfExtractionStream(path) as stream:
        assert stream.early_profile is not None
        assert list(stream.pages()) == []
        assert stream.result().is_encrypted
    with pytest.raises(ValueError, match="malformed"):
        PdfExtractionStream(b"not a pdf")


def test_result_stream_adapter_passes_pages_through() -> None:
    result = extract_document(b"hello world text", file_type="txt")
    stream = ResultExtractionStream(result)
    assert stream.early_profile is None
    assert list(stream.pages()) == result.pages
    assert stream.result() is result
    stream.close()


def _writer_ctx() -> Any:
    from types import SimpleNamespace

    from app.workers.ingestion.store import MemoryStageStore

    return SimpleNamespace(
        store=MemoryStageStore(),
        parts_since_heartbeat=0,
        options=SimpleNamespace(persist_document_state=False),
        claim_token=None,
    )


async def test_page_writer_keeps_slot_order_and_bounds_fragments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.workers.ingestion import pages
    from app.workers.ingestion.errors import DocumentPipelinePermanentError

    ctx = _writer_ctx()
    writer = pages.PageWriter(ctx, "extract")
    held = writer.reserve()  # an OCR page written after its successors
    for number in range(2, 21):
        await writer.add({"page_number": number, "text": f"p{number}", "char_count": 2})
    await writer.add({"page_number": 1, "text": "ocr", "char_count": 3}, slot=held)
    await writer.flush()
    await writer.flush()  # nothing pending: no second write
    read = await pages.read_pages(ctx, "extract")
    assert [page["page_number"] for page in read] == [1, *range(2, 21)]
    assert writer.parts_written == 20

    monkeypatch.setattr(settings, "ingest_artifact_max_part_bytes", 64 * 1024)
    monkeypatch.setattr(pages, "PAGE_PART_STRIDE", 1)
    import os

    big = {"page_number": 1, "text": os.urandom(200_000).hex(), "char_count": 400_000}
    with pytest.raises(DocumentPipelinePermanentError):
        await pages.PageWriter(_writer_ctx(), "extract").add(big)
