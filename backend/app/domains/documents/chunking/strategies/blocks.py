"""Intermediate block representation and text-to-blocks parser.

Parses raw page text into typed blocks (heading, paragraph, table, code, list)
without using external NLP dependencies.  The parser is intentionally simple and
conservative — ambiguous content defaults to "paragraph" rather than crashing or
misclassifying.

Block text is never logged; callers must redact before emitting to observability.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Block types
# ---------------------------------------------------------------------------

BLOCK_PARAGRAPH = "paragraph"
BLOCK_HEADING = "heading"
BLOCK_TABLE = "table"
BLOCK_CODE = "code"
BLOCK_LIST = "list"

# ---------------------------------------------------------------------------
# Regex patterns (compiled once at import time)
# ---------------------------------------------------------------------------

# ATX-style Markdown headings: # H1  ## H2 … ###### H6
_ATX_HEADING = re.compile(r"^(#{1,6})\s+(.+?)(?:\s+#+)?\s*$")

# Short ALL-CAPS lines used as headings in plain-text DOCX exports.
# Require: 2-80 chars, all uppercase letters/digits/spaces/basic punct.
_CAPS_HEADING = re.compile(r"^[A-Z][A-Z0-9 ,.:;/&()\-]{1,79}$")

# Setext headings (underline style): text\n===== or text\n-----
_SETEXT_H1 = re.compile(r"^=+\s*$")
_SETEXT_H2 = re.compile(r"^-+\s*$")

# Opening fence for code blocks: ``` or ~~~, optionally followed by lang tag
_CODE_FENCE_OPEN = re.compile(r"^(`{3,}|~{3,})")

# Table row: line that contains at least one | surrounded by non-empty content
_TABLE_ROW = re.compile(r"\S.*\|.*\S")

# Bullet list items: -, *, +, •  (possibly indented)
_BULLET = re.compile(r"^\s*[-*+•]\s+")

# Numbered list items: 1. 1) 1:
_NUMBERED = re.compile(r"^\s*\d+[.):\s]\s+")


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class Block:
    """One logical unit of text from a document page."""

    page_number: int
    text: str
    block_type: str  # one of the BLOCK_* constants above
    heading_level: int | None = None  # 1-6 for BLOCK_HEADING, else None


# ---------------------------------------------------------------------------
# Section-path tracker
# ---------------------------------------------------------------------------


class SectionTracker:
    """Maintains a stack of heading (level, text) pairs as the parser scans blocks.

    Only heading blocks should be passed to :meth:`update`.
    """

    def __init__(self) -> None:
        self._stack: list[tuple[int, str]] = []

    def update(self, level: int, heading_text: str) -> None:
        """Incorporate a new heading at *level*, trimming any deeper entries."""
        self._stack = [(lvl, h) for lvl, h in self._stack if lvl < level]
        self._stack.append((level, heading_text.strip()))

    def reset(self) -> None:
        self._stack = []

    @property
    def path(self) -> str:
        """Current section path, e.g. 'Policy > Leave > Annual Leave'."""
        return " > ".join(h for _, h in self._stack)

    @property
    def empty(self) -> bool:
        return not self._stack


# ---------------------------------------------------------------------------
# Block parser
# ---------------------------------------------------------------------------


def parse_blocks(page_number: int, text: str) -> list[Block]:
    """Parse *text* into an ordered list of :class:`Block` objects.

    The algorithm is a single-pass line-by-line state machine.  It recognises:

    * ATX Markdown headings (``# H1`` … ``###### H6``)
    * Setext headings (underline ``=====`` or ``-----``)
    * Short ALL-CAPS lines as headings (common in DOCX plain-text exports)
    * Fenced code blocks (`` ``` `` / ``~~~``)
    * Table rows (lines containing ``|``)
    * Bullet and numbered list items (grouped into a single list block)
    * Everything else: paragraphs
    """
    lines = text.splitlines()
    blocks: list[Block] = []

    # ---- mutable state ----
    state: str = "normal"  # normal | code_fence | table | list
    buffer: list[str] = []
    fence_marker: str = ""

    def flush_buffer(btype: str, level: int | None = None) -> None:
        joined = "\n".join(buffer).strip()
        if joined:
            blocks.append(Block(page_number, joined, btype, level))
        buffer.clear()

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # ------------------------------------------------------------------
        # State: inside a fenced code block
        # ------------------------------------------------------------------
        if state == "code_fence":
            if _CODE_FENCE_OPEN.match(stripped) and stripped.startswith(fence_marker):
                buffer.append(line)
                flush_buffer(BLOCK_CODE)
                state = "normal"
                fence_marker = ""
            else:
                buffer.append(line)
            i += 1
            continue

        # ------------------------------------------------------------------
        # State: inside a table
        # ------------------------------------------------------------------
        if state == "table":
            if _TABLE_ROW.search(stripped) or (stripped.startswith("|") and stripped.endswith("|")):
                buffer.append(line)
                i += 1
                continue
            else:
                flush_buffer(BLOCK_TABLE)
                state = "normal"
                # fall through to process current line

        # ------------------------------------------------------------------
        # State: inside a list
        # ------------------------------------------------------------------
        if state == "list":
            if _BULLET.match(line) or _NUMBERED.match(line) or (stripped and line[0] == " "):
                # continuation or new list item
                buffer.append(line)
                i += 1
                continue
            else:
                flush_buffer(BLOCK_LIST)
                state = "normal"
                # fall through to process current line

        # ------------------------------------------------------------------
        # State: normal — detect block type for this line
        # ------------------------------------------------------------------

        # Blank line: flush current paragraph-ish buffer
        if not stripped:
            if buffer:
                flush_buffer(BLOCK_PARAGRAPH)
            i += 1
            continue

        # Fenced code block opening
        m_fence = _CODE_FENCE_OPEN.match(stripped)
        if m_fence:
            if buffer:
                flush_buffer(BLOCK_PARAGRAPH)
            state = "code_fence"
            fence_marker = m_fence.group(1)[:3]
            buffer.append(line)
            i += 1
            continue

        # Setext headings — look ahead one line
        if i + 1 < len(lines):
            next_stripped = lines[i + 1].strip()
            if _SETEXT_H1.match(next_stripped) and stripped:
                if buffer:
                    flush_buffer(BLOCK_PARAGRAPH)
                blocks.append(Block(page_number, stripped, BLOCK_HEADING, 1))
                i += 2
                continue
            if _SETEXT_H2.match(next_stripped) and stripped:
                if buffer:
                    flush_buffer(BLOCK_PARAGRAPH)
                blocks.append(Block(page_number, stripped, BLOCK_HEADING, 2))
                i += 2
                continue

        # ATX heading
        m_atx = _ATX_HEADING.match(stripped)
        if m_atx:
            if buffer:
                flush_buffer(BLOCK_PARAGRAPH)
            level = len(m_atx.group(1))
            heading_text = m_atx.group(2).strip()
            blocks.append(Block(page_number, heading_text, BLOCK_HEADING, level))
            i += 1
            continue

        # Short ALL-CAPS line — treat as heading level 2 when it looks like a title
        if _CAPS_HEADING.match(stripped) and len(stripped) <= 80:
            if buffer:
                flush_buffer(BLOCK_PARAGRAPH)
            blocks.append(Block(page_number, stripped, BLOCK_HEADING, 2))
            i += 1
            continue

        # Table row
        if _TABLE_ROW.search(stripped):
            if buffer:
                flush_buffer(BLOCK_PARAGRAPH)
            state = "table"
            buffer.append(line)
            i += 1
            continue

        # Bullet or numbered list
        if _BULLET.match(line) or _NUMBERED.match(line):
            if buffer:
                flush_buffer(BLOCK_PARAGRAPH)
            state = "list"
            buffer.append(line)
            i += 1
            continue

        # Default: accumulate as paragraph
        buffer.append(line)
        i += 1

    # Flush any remaining buffer
    if state == "code_fence":
        flush_buffer(BLOCK_CODE)
    elif state == "table":
        flush_buffer(BLOCK_TABLE)
    elif state == "list":
        flush_buffer(BLOCK_LIST)
    elif buffer:
        flush_buffer(BLOCK_PARAGRAPH)

    return blocks


def dominant_block_type(blocks: list[Block]) -> str:
    """Return the 'most significant' block type found in *blocks*.

    Priority: code > table > list > heading > paragraph.
    """
    types = {b.block_type for b in blocks}
    for btype in (BLOCK_CODE, BLOCK_TABLE, BLOCK_LIST, BLOCK_HEADING):
        if btype in types:
            return btype
    return BLOCK_PARAGRAPH
