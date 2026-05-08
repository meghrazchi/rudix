from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from app.services.text_extraction import ExtractedSection

_HORIZONTAL_WHITESPACE_RE = re.compile(r"[ \t\f\v]+")


@dataclass
class TextCleaningStats:
    pages_total: int = 0
    pages_modified: int = 0
    null_bytes_removed: int = 0
    invalid_characters_removed: int = 0
    whitespace_runs_collapsed: int = 0
    blank_lines_collapsed: int = 0
    chars_before: int = 0
    chars_after: int = 0

    def as_log_fields(self) -> dict[str, int]:
        return {
            "cleaning_pages_total": self.pages_total,
            "cleaning_pages_modified": self.pages_modified,
            "cleaning_null_bytes_removed": self.null_bytes_removed,
            "cleaning_invalid_characters_removed": self.invalid_characters_removed,
            "cleaning_whitespace_runs_collapsed": self.whitespace_runs_collapsed,
            "cleaning_blank_lines_collapsed": self.blank_lines_collapsed,
            "cleaning_chars_before": self.chars_before,
            "cleaning_chars_after": self.chars_after,
        }


def _strip_invalid_characters(text: str) -> tuple[str, int]:
    cleaned_chars: list[str] = []
    removed = 0
    for char in text:
        if char == "\n" or char == "\t":
            cleaned_chars.append(char)
            continue
        codepoint = ord(char)
        category = unicodedata.category(char)
        if category == "Cs":
            removed += 1
            continue
        if (codepoint < 32) or (127 <= codepoint <= 159):
            removed += 1
            continue
        cleaned_chars.append(char)
    return "".join(cleaned_chars), removed


def _normalize_whitespace(text: str) -> tuple[str, int, int]:
    lines = text.split("\n")
    collapsed_runs = 0
    normalized_lines: list[str] = []
    for line in lines:
        runs = _HORIZONTAL_WHITESPACE_RE.findall(line)
        collapsed_runs += sum(1 for run in runs if run != " ")
        normalized = _HORIZONTAL_WHITESPACE_RE.sub(" ", line).strip()
        normalized_lines.append(normalized)

    blank_lines_collapsed = 0
    collapsed_lines: list[str] = []
    blank_streak = 0
    for line in normalized_lines:
        if line == "":
            blank_streak += 1
            if blank_streak == 1:
                collapsed_lines.append("")
            else:
                blank_lines_collapsed += 1
            continue
        blank_streak = 0
        collapsed_lines.append(line)

    return "\n".join(collapsed_lines).strip(), collapsed_runs, blank_lines_collapsed


def clean_page_text(text: str) -> tuple[str, TextCleaningStats]:
    stats = TextCleaningStats(pages_total=1, chars_before=len(text))
    without_nulls = text.replace("\x00", "")
    stats.null_bytes_removed = len(text) - len(without_nulls)

    newline_normalized = without_nulls.replace("\r\n", "\n").replace("\r", "\n")
    without_invalid_chars, invalid_removed = _strip_invalid_characters(newline_normalized)
    stats.invalid_characters_removed = invalid_removed

    cleaned_text, whitespace_collapsed, blank_lines_collapsed = _normalize_whitespace(without_invalid_chars)
    stats.whitespace_runs_collapsed = whitespace_collapsed
    stats.blank_lines_collapsed = blank_lines_collapsed
    stats.chars_after = len(cleaned_text)
    if cleaned_text != text:
        stats.pages_modified = 1

    return cleaned_text, stats


def clean_extracted_sections(
    sections: list[ExtractedSection],
) -> tuple[list[ExtractedSection], TextCleaningStats]:
    aggregated = TextCleaningStats(pages_total=len(sections))
    cleaned_sections: list[ExtractedSection] = []
    for section in sections:
        cleaned_text, stats = clean_page_text(section.text)
        cleaned_sections.append(
            ExtractedSection(
                page_number=section.page_number,
                text=cleaned_text,
                char_count=len(cleaned_text),
            )
        )
        aggregated.pages_modified += stats.pages_modified
        aggregated.null_bytes_removed += stats.null_bytes_removed
        aggregated.invalid_characters_removed += stats.invalid_characters_removed
        aggregated.whitespace_runs_collapsed += stats.whitespace_runs_collapsed
        aggregated.blank_lines_collapsed += stats.blank_lines_collapsed
        aggregated.chars_before += stats.chars_before
        aggregated.chars_after += stats.chars_after
    return cleaned_sections, aggregated
