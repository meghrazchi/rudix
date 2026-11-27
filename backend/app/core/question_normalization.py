"""Question normalisation shared by the chat caches and the verified-answer match (R05-05).

NFKC, casefold, every whitespace run collapsed to one space, stripped. Used only for exact
equality and for hashing; never for display.
"""

import re
import unicodedata

_WHITESPACE = re.compile(r"\s+")


def normalise_question(text: str) -> str:
    return _WHITESPACE.sub(" ", unicodedata.normalize("NFKC", text).casefold()).strip()
