#!/usr/bin/env python3
"""Bump, check, and release the Rudix version string (R03-07). Standard library only.

Usage:
    scripts/bump_version.py X.Y.Z [--changelog] [--dry-run] [--date YYYY-MM-DD]
    scripts/bump_version.py --check

The version lives in seven places; every edit is a targeted regex replacement so the
surrounding formatting is preserved:

1. backend/pyproject.toml           [project] version
2. frontend/package.json            "version"
3. frontend/package-lock.json       top-level "version"
4. frontend/package-lock.json       packages[""].version
5. backend/app/core/config.py       api_version Field default
6. .env.example                     API_VERSION
7. frontend/openapi.json            info.version

``--check`` verifies that all seven agree and, when ``GITHUB_REF_TYPE=tag``, that
``GITHUB_REF_NAME`` equals ``v<version>``. ``--changelog`` moves the ``[Unreleased]`` body
of docs/CHANGELOG.md under ``## [X.Y.Z] - <date>`` and leaves an empty ``[Unreleased]``.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CHANGELOG = Path("docs/CHANGELOG.md")
SEMVER_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-rc\.?(0|[1-9]\d*))?$")
UNRELEASED_RE = re.compile(r"^## \[Unreleased\][^\n]*\n", re.MULTILINE)
NEXT_SECTION_RE = re.compile(r"^## \[", re.MULTILINE)


class VersionError(Exception):
    """Raised for invalid versions, missing anchors, or disagreeing files."""


@dataclass(frozen=True)
class Location:
    label: str
    path: Path
    pattern: re.Pattern[str]
    reader: Callable[[str], str] | None = None

    def read(self, root: Path) -> str:
        text = (root / self.path).read_text()
        matches = list(self.pattern.finditer(text))
        if len(matches) != 1:
            raise VersionError(f"{self.label}: expected one version anchor, found {len(matches)}")
        value = matches[0].group("version")
        if self.reader is not None and self.reader(text) != value:
            raise VersionError(f"{self.label}: regex and parsed value disagree")
        return value

    def rewrite(self, text: str, version: str) -> str:
        new_text, count = self.pattern.subn(
            lambda m: f"{m.group('pre')}{version}{m.group('post')}", text, count=1
        )
        if count != 1:
            raise VersionError(f"{self.label}: version anchor not found")
        if self.reader is not None and self.reader(new_text) != version:
            raise VersionError(f"{self.label}: rewrite did not take effect")
        return new_text


def _lock_top(text: str) -> str:
    return str(json.loads(text)["version"])


def _lock_root_package(text: str) -> str:
    return str(json.loads(text)["packages"][""]["version"])


def _package_json(text: str) -> str:
    return str(json.loads(text)["version"])


def _openapi(text: str) -> str:
    return str(json.loads(text)["info"]["version"])


_V = r'(?P<version>[^"\s]+)'
LOCATIONS: tuple[Location, ...] = (
    Location(
        "backend/pyproject.toml version",
        Path("backend/pyproject.toml"),
        re.compile(r'(?P<pre>^version = ")' + _V + r'(?P<post>")', re.MULTILINE),
    ),
    Location(
        "frontend/package.json version",
        Path("frontend/package.json"),
        re.compile(r'(?P<pre>^  "version": ")' + _V + r'(?P<post>")', re.MULTILINE),
        _package_json,
    ),
    Location(
        "frontend/package-lock.json version",
        Path("frontend/package-lock.json"),
        re.compile(r'(?P<pre>^  "version": ")' + _V + r'(?P<post>")', re.MULTILINE),
        _lock_top,
    ),
    Location(
        'frontend/package-lock.json packages[""].version',
        Path("frontend/package-lock.json"),
        re.compile(
            r'(?P<pre>^    "": \{\n(?:      [^\n]*\n)*?      "version": ")' + _V + r'(?P<post>")',
            re.MULTILINE,
        ),
        _lock_root_package,
    ),
    Location(
        "backend/app/core/config.py api_version",
        Path("backend/app/core/config.py"),
        re.compile(r'(?P<pre>api_version: str = Field\(default=")' + _V + r'(?P<post>")'),
    ),
    Location(
        ".env.example API_VERSION",
        Path(".env.example"),
        re.compile(r"(?P<pre>^API_VERSION=)(?P<version>[^\s#]+)(?P<post>)", re.MULTILINE),
    ),
    Location(
        "frontend/openapi.json info.version",
        Path("frontend/openapi.json"),
        re.compile(r'(?P<pre>"info": \{[^{}]*?"version": ")' + _V + r'(?P<post>")', re.DOTALL),
        _openapi,
    ),
)


def parse_semver(version: str) -> tuple[int, int, int, int]:
    """Return a sortable key; a release sorts after its release candidates."""
    match = SEMVER_RE.match(version)
    if match is None:
        raise VersionError(f"not a SemVer version (X.Y.Z or X.Y.Z-rc.N): {version!r}")
    major, minor, patch, rc = match.groups()
    rc_key = int(rc) if rc is not None else sys.maxsize
    return int(major), int(minor), int(patch), rc_key


def read_versions(root: Path) -> dict[str, str]:
    return {location.label: location.read(root) for location in LOCATIONS}


def check(root: Path, env: dict[str, str]) -> list[str]:
    """Return a list of problems; empty means all versions agree (and match the tag)."""
    problems: list[str] = []
    versions = read_versions(root)
    distinct = sorted(set(versions.values()))
    if len(distinct) != 1:
        problems.append("version strings disagree:")
        problems.extend(f"  {label}: {value}" for label, value in versions.items())
        return problems
    version = distinct[0]
    try:
        parse_semver(version)
    except VersionError as exc:
        problems.append(str(exc))
    if env.get("GITHUB_REF_TYPE") == "tag":
        tag = env.get("GITHUB_REF_NAME", "")
        if tag != f"v{version}":
            problems.append(f"tag {tag!r} does not match version v{version}")
    return problems


def move_unreleased(text: str, version: str, release_date: str) -> str:
    """Move the [Unreleased] body under a new ``## [version] - date`` heading."""
    if re.search(rf"^## \[{re.escape(version)}\]", text, re.MULTILINE):
        raise VersionError(f"CHANGELOG already has a section for {version}")
    heading = UNRELEASED_RE.search(text)
    if heading is None:
        raise VersionError("CHANGELOG has no '## [Unreleased]' heading")
    body_start = heading.end()
    next_section = NEXT_SECTION_RE.search(text, body_start)
    body_end = next_section.start() if next_section else len(text)
    body = text[body_start:body_end].strip("\n")
    if not body.strip():
        raise VersionError("CHANGELOG [Unreleased] section is empty; nothing to release")
    tail = text[body_end:]
    released = f"## [{version}] - {release_date}\n\n{body}\n"
    return text[:body_start] + "\n" + released + ("\n" + tail if tail else "")


def bump(
    root: Path,
    version: str,
    *,
    changelog: bool,
    dry_run: bool,
    release_date: str,
) -> list[str]:
    """Rewrite all locations (and optionally the changelog). Returns the touched paths."""
    new_key = parse_semver(version)
    current = read_versions(root)
    for label, value in current.items():
        if parse_semver(value) > new_key:
            raise VersionError(f"refusing downgrade: {label} is {value}, requested {version}")

    texts: dict[Path, str] = {}
    for location in LOCATIONS:
        text = texts.get(location.path)
        if text is None:
            text = (root / location.path).read_text()
        texts[location.path] = location.rewrite(text, version)
    if changelog:
        texts[CHANGELOG] = move_unreleased((root / CHANGELOG).read_text(), version, release_date)

    touched: list[str] = []
    for rel_path, new_text in texts.items():
        path = root / rel_path
        if path.read_text() == new_text:
            continue
        touched.append(str(rel_path))
        if not dry_run:
            path.write_text(new_text)
    return touched


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Bump or check the Rudix version.")
    parser.add_argument("version", nargs="?", help="new version, X.Y.Z or X.Y.Z-rc.N")
    parser.add_argument("--check", action="store_true", help="verify all versions agree")
    parser.add_argument("--changelog", action="store_true", help="release [Unreleased]")
    parser.add_argument("--dry-run", action="store_true", help="print, do not write")
    parser.add_argument("--date", default=None, help="release date (default: today)")
    parser.add_argument("--root", default=str(REPO_ROOT), help=argparse.SUPPRESS)
    return parser


def main(argv: Sequence[str] | None = None, env: dict[str, str] | None = None) -> int:
    args = _parser().parse_args(argv)
    root = Path(args.root)
    environ = dict(os.environ) if env is None else env
    try:
        if args.check:
            if args.version:
                print("--check takes no version argument", file=sys.stderr)
                return 2
            problems = check(root, environ)
            if problems:
                print("\n".join(problems), file=sys.stderr)
                return 1
            print(f"version check passed: {next(iter(read_versions(root).values()))}")
            return 0
        if not args.version:
            print("a version (X.Y.Z) or --check is required", file=sys.stderr)
            return 2
        release_date = args.date or date.today().isoformat()
        date.fromisoformat(release_date)
        touched = bump(
            root,
            args.version,
            changelog=args.changelog,
            dry_run=args.dry_run,
            release_date=release_date,
        )
    except (VersionError, ValueError, KeyError, OSError) as exc:
        print(f"bump_version: {exc}", file=sys.stderr)
        return 1
    verb = "would update" if args.dry_run else "updated"
    for rel_path in touched:
        print(f"{verb} {rel_path}")
    if not touched:
        print(f"already at {args.version}; nothing to change")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
