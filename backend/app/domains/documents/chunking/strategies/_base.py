from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

import tiktoken
from tiktoken import Encoding


def resolve_encoding(model_name: str) -> Encoding:
    """Return tiktoken encoding for model_name, falling back to cl100k_base."""
    try:
        return tiktoken.encoding_for_model(model_name)
    except KeyError:
        return tiktoken.get_encoding("cl100k_base")


def encode_text(encoding: Encoding, text: str) -> list[int]:
    return encoding.encode(text, disallowed_special=())


def dominant_page_number(token_window: Sequence[tuple[int, int]]) -> int | None:
    """Return the page that contributes the most tokens; earliest page on ties."""
    if not token_window:
        return None
    by_page: dict[int, int] = defaultdict(int)
    for page_number, _token in token_window:
        by_page[page_number] += 1
    return max(by_page.items(), key=lambda kv: (kv[1], -kv[0]))[0]


@dataclass
class TextUnit:
    """A logical text segment (paragraph or sentence) with its encoding cached."""

    page_number: int
    text: str
    token_ids: list[int]

    @property
    def token_count(self) -> int:
        return len(self.token_ids)


def overlap_tail(units: list[TextUnit], overlap_tokens: int) -> list[TextUnit]:
    """Return the suffix of *units* whose combined token count >= *overlap_tokens*.

    If the entire list totals fewer than *overlap_tokens*, returns all units.
    If *overlap_tokens* is 0 or units is empty, returns [].
    """
    if not units or overlap_tokens <= 0:
        return []
    accumulated = 0
    start = len(units)
    while start > 0 and accumulated < overlap_tokens:
        start -= 1
        accumulated += units[start].token_count
    return units[start:]
