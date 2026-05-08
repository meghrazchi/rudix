from __future__ import annotations

from app.services.text_extraction import ExtractedSection
from app.services.text_normalization import clean_extracted_sections, clean_page_text


def test_clean_page_text_removes_null_bytes_and_invalid_control_characters() -> None:
    cleaned, stats = clean_page_text("A\x00B\x07C\x7fD")

    assert cleaned == "ABCD"
    assert stats.null_bytes_removed == 1
    assert stats.invalid_characters_removed == 2
    assert stats.chars_after == 4


def test_clean_page_text_normalizes_whitespace_and_blank_lines() -> None:
    text = "  hello\t\tworld  \r\n\r\n\r\n second   line \n\nthird"
    cleaned, stats = clean_page_text(text)

    assert cleaned == "hello world\n\nsecond line\n\nthird"
    assert stats.whitespace_runs_collapsed > 0
    assert stats.blank_lines_collapsed > 0


def test_clean_extracted_sections_preserves_page_numbers_and_empty_pages() -> None:
    sections = [
        ExtractedSection(page_number=1, text="  first page  ", char_count=14),
        ExtractedSection(page_number=2, text="\x00\t \n\n", char_count=5),
        ExtractedSection(page_number=3, text="third", char_count=5),
    ]

    cleaned, stats = clean_extracted_sections(sections)

    assert [section.page_number for section in cleaned] == [1, 2, 3]
    assert cleaned[0].text == "first page"
    assert cleaned[1].text == ""
    assert cleaned[1].char_count == 0
    assert cleaned[2].text == "third"
    assert stats.pages_total == 3
    assert stats.pages_modified >= 1


def test_clean_extracted_sections_is_deterministic() -> None:
    sections = [
        ExtractedSection(page_number=1, text="a\t\tb", char_count=4),
        ExtractedSection(page_number=2, text=" \n\n c ", char_count=6),
    ]

    first_cleaned, first_stats = clean_extracted_sections(sections)
    second_cleaned, second_stats = clean_extracted_sections(sections)

    assert first_cleaned == second_cleaned
    assert first_stats == second_stats
