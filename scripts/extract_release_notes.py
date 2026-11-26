#!/usr/bin/env python3
"""Print the docs/CHANGELOG.md section for a release tag (R03-07). Standard library only.

Usage:
    scripts/extract_release_notes.py vX.Y.Z [--changelog PATH]

Prints the body under ``## [X.Y.Z]`` (with or without `` - <date>``) up to the next
``## [`` heading. Exits 1 when the section is missing or empty, so a release cannot be
published without notes.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Sequence
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CHANGELOG = REPO_ROOT / "docs" / "CHANGELOG.md"
TAG_RE = re.compile(r"^v?(\d+\.\d+\.\d+(?:-rc\.?\d+)?)$")
NEXT_SECTION_RE = re.compile(r"^## \[", re.MULTILINE)


def extract_notes(text: str, version: str) -> str | None:
    heading = re.search(rf"^## \[{re.escape(version)}\][^\n]*\n", text, re.MULTILINE)
    if heading is None:
        return None
    next_section = NEXT_SECTION_RE.search(text, heading.end())
    end = next_section.start() if next_section else len(text)
    body = text[heading.end() : end].strip("\n")
    return body or None


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Print the changelog section for a tag.")
    parser.add_argument("tag", help="release tag, e.g. v0.3.0")
    parser.add_argument("--changelog", default=str(DEFAULT_CHANGELOG))
    args = parser.parse_args(argv)

    match = TAG_RE.match(args.tag)
    if match is None:
        print(f"not a release tag: {args.tag!r}", file=sys.stderr)
        return 2
    version = match.group(1)
    try:
        text = Path(args.changelog).read_text()
    except OSError as exc:
        print(f"cannot read changelog: {exc}", file=sys.stderr)
        return 1
    notes = extract_notes(text, version)
    if notes is None:
        print(f"no non-empty CHANGELOG section for [{version}]", file=sys.stderr)
        return 1
    print(notes)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
