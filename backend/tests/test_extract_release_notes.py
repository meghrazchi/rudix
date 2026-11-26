"""Tests for scripts/extract_release_notes.py (R03-07), on copies of the real changelog."""

from __future__ import annotations

import importlib.util
import shutil
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "extract_release_notes.py"
BUMP_SCRIPT = REPO_ROOT / "scripts" / "bump_version.py"


def _load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


notes = _load("extract_release_notes", SCRIPT)
bump = _load("bump_version_for_notes", BUMP_SCRIPT)

SAMPLE = """# Changelog

## [Unreleased]

## [1.2.0] - 2026-12-01

### Added

- feature one

## [1.1.0] - 2026-11-01

- older
"""


def test_extracts_section_between_headings() -> None:
    assert notes.extract_notes(SAMPLE, "1.2.0") == "### Added\n\n- feature one"
    assert notes.extract_notes(SAMPLE, "1.1.0") == "- older"


def test_missing_or_empty_section_returns_none() -> None:
    assert notes.extract_notes(SAMPLE, "0.0.0") is None
    assert notes.extract_notes("## [2.0.0]\n\n## [1.0.0]\n- x\n", "2.0.0") is None


def test_version_is_matched_exactly() -> None:
    assert notes.extract_notes("## [1.2.10]\n- ten\n", "1.2.1") is None


def test_cli_prints_notes(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(SAMPLE)
    assert notes.main(["v1.2.0", "--changelog", str(changelog)]) == 0
    assert capsys.readouterr().out == "### Added\n\n- feature one\n"
    assert notes.main(["v0.0.0", "--changelog", str(changelog)]) == 1
    assert notes.main(["release-1", "--changelog", str(changelog)]) == 2
    assert notes.main(["v1.2.0", "--changelog", str(tmp_path / "none.md")]) == 1


def test_round_trip_with_bump_on_real_changelog_copy(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    changelog = tmp_path / "CHANGELOG.md"
    shutil.copyfile(REPO_ROOT / "docs" / "CHANGELOG.md", changelog)
    original = changelog.read_text()
    body = original.split("## [Unreleased]\n", 1)[1].split("\n## [", 1)[0].strip()

    changelog.write_text(bump.move_unreleased(original, "9.0.0", "2026-12-01"))

    assert notes.main(["v9.0.0", "--changelog", str(changelog)]) == 0
    assert capsys.readouterr().out.strip() == body
