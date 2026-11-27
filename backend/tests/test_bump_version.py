"""Tests for scripts/bump_version.py (R03-07).

The script is loaded from the repo path and always runs against copies of the real
files in tmp_path; the real tree is never bumped.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "bump_version.py"
VERSION_FILES = (
    "backend/pyproject.toml",
    "frontend/package.json",
    "frontend/package-lock.json",
    "backend/app/core/settings/app.py",
    ".env.example",
    "frontend/openapi.json",
    "docs/CHANGELOG.md",
)


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("bump_version", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


bv = _load()


@pytest.fixture()
def tree(tmp_path: Path) -> Path:
    for rel in VERSION_FILES:
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO_ROOT / rel, target)
    return tmp_path


def _current(root: Path) -> str:
    values = set(bv.read_versions(root).values())
    assert len(values) == 1
    return values.pop()


def _next_minor(version: str) -> str:
    major, minor, _patch, _rc = bv.parse_semver(version)
    return f"{major}.{minor + 1}.0"


def test_real_tree_versions_agree() -> None:
    assert bv.check(REPO_ROOT, {}) == []


def test_bump_rewrites_all_seven_locations_and_preserves_format(tree: Path) -> None:
    old = _current(tree)
    new = _next_minor(old)
    before = {rel: (tree / rel).read_text() for rel in VERSION_FILES}

    touched = bv.bump(tree, new, changelog=False, dry_run=False, release_date="2026-11-26")

    assert sorted(touched) == sorted(VERSION_FILES[:-1])
    assert set(bv.read_versions(tree).values()) == {new}
    lock = json.loads((tree / "frontend/package-lock.json").read_text())
    assert lock["version"] == new and lock["packages"][""]["version"] == new
    assert json.loads((tree / "frontend/openapi.json").read_text())["info"]["version"] == new
    for rel in VERSION_FILES[:-1]:
        old_lines = before[rel].splitlines()
        new_lines = (tree / rel).read_text().splitlines()
        assert len(old_lines) == len(new_lines), rel
        changed = [i for i, (a, b) in enumerate(zip(old_lines, new_lines, strict=True)) if a != b]
        expected = 2 if rel == "frontend/package-lock.json" else 1
        assert len(changed) == expected, (rel, changed)
        for index in changed:
            assert old_lines[index].replace(old, new) == new_lines[index]
    assert (tree / "docs/CHANGELOG.md").read_text() == before["docs/CHANGELOG.md"]


def test_dry_run_writes_nothing(tree: Path) -> None:
    before = {rel: (tree / rel).read_text() for rel in VERSION_FILES}
    touched = bv.bump(tree, "9.0.0", changelog=True, dry_run=True, release_date="2026-11-26")
    assert "docs/CHANGELOG.md" in touched
    assert {rel: (tree / rel).read_text() for rel in VERSION_FILES} == before


def test_refuses_downgrade(tree: Path) -> None:
    bv.bump(tree, "5.0.0", changelog=False, dry_run=False, release_date="2026-11-26")
    with pytest.raises(bv.VersionError, match="downgrade"):
        bv.bump(tree, "4.9.9", changelog=False, dry_run=False, release_date="2026-11-26")
    with pytest.raises(bv.VersionError, match="downgrade"):
        bv.bump(tree, "5.0.0-rc.1", changelog=False, dry_run=False, release_date="2026-11-26")


def test_same_version_is_a_noop(tree: Path) -> None:
    current = _current(tree)
    assert bv.bump(tree, current, changelog=False, dry_run=False, release_date="x") == []


@pytest.mark.parametrize("bad", ["1.2", "v1.2.3", "01.2.3", "1.2.3-beta", "1.2.3.4", ""])
def test_rejects_invalid_semver(bad: str) -> None:
    with pytest.raises(bv.VersionError):
        bv.parse_semver(bad)


def test_rc_sorts_before_release() -> None:
    assert bv.parse_semver("1.0.0-rc.1") < bv.parse_semver("1.0.0-rc2") < bv.parse_semver("1.0.0")


def test_check_detects_disagreement(tree: Path) -> None:
    env_example = tree / ".env.example"
    env_example.write_text(env_example.read_text().replace("API_VERSION=", "API_VERSION=9", 1))
    problems = bv.check(tree, {})
    assert problems and problems[0] == "version strings disagree:"
    assert bv.main(["--check", "--root", str(tree)], env={}) == 1


def test_check_matches_tag(tree: Path, capsys: pytest.CaptureFixture) -> None:
    current = _current(tree)
    ok_env = {"GITHUB_REF_TYPE": "tag", "GITHUB_REF_NAME": f"v{current}"}
    assert bv.main(["--check", "--root", str(tree)], env=ok_env) == 0
    assert "version check passed" in capsys.readouterr().out
    bad_env = {"GITHUB_REF_TYPE": "tag", "GITHUB_REF_NAME": "v99.0.0"}
    assert bv.main(["--check", "--root", str(tree)], env=bad_env) == 1
    assert "does not match" in capsys.readouterr().err
    branch_env = {"GITHUB_REF_TYPE": "branch", "GITHUB_REF_NAME": "main"}
    assert bv.main(["--check", "--root", str(tree)], env=branch_env) == 0


def test_changelog_moves_unreleased_body(tree: Path) -> None:
    original = (tree / "docs/CHANGELOG.md").read_text()
    unreleased_body = original.split("## [Unreleased]\n", 1)[1].split("\n## [", 1)[0].strip()

    bv.bump(tree, "9.1.0", changelog=True, dry_run=False, release_date="2026-12-01")

    text = (tree / "docs/CHANGELOG.md").read_text()
    assert "## [Unreleased]\n\n## [9.1.0] - 2026-12-01\n\n" in text
    released = text.split("## [9.1.0] - 2026-12-01\n\n", 1)[1].split("\n## [", 1)[0].strip()
    assert released == unreleased_body
    assert text.count("## [Unreleased]") == 1
    assert text.startswith(original.split("## [Unreleased]", 1)[0])
    with pytest.raises(bv.VersionError, match="already has a section"):
        bv.move_unreleased(text, "9.1.0", "2026-12-02")
    with pytest.raises(bv.VersionError, match="empty"):
        bv.move_unreleased(text, "9.2.0", "2026-12-02")


def test_changelog_without_unreleased_heading_fails() -> None:
    with pytest.raises(bv.VersionError, match="no '## \\[Unreleased\\]'"):
        bv.move_unreleased("# Changelog\n", "1.0.0", "2026-01-01")


def test_changelog_with_unreleased_as_last_section() -> None:
    text = bv.move_unreleased("# C\n\n## [Unreleased]\n\n- a\n", "1.0.0", "2026-01-01")
    assert text == "# C\n\n## [Unreleased]\n\n## [1.0.0] - 2026-01-01\n\n- a\n"


def test_missing_anchor_is_reported(tree: Path) -> None:
    config = tree / "backend/app/core/settings/app.py"
    config.write_text(config.read_text().replace("api_version: str", "api_ver: str"))
    with pytest.raises(bv.VersionError, match="api_version"):
        bv.read_versions(tree)
    location = next(loc for loc in bv.LOCATIONS if "settings/app.py" in loc.label)
    with pytest.raises(bv.VersionError, match="not found"):
        location.rewrite(config.read_text(), "1.0.0")


def test_main_cli_paths(tree: Path, capsys: pytest.CaptureFixture) -> None:
    assert bv.main(["--root", str(tree)], env={}) == 2
    assert bv.main(["--check", "1.0.0", "--root", str(tree)], env={}) == 2
    assert bv.main(["bogus", "--root", str(tree)], env={}) == 1
    assert bv.main(["9.9.9", "--date", "not-a-date", "--root", str(tree)], env={}) == 1
    capsys.readouterr()
    assert bv.main(["9.9.9", "--dry-run", "--root", str(tree)], env={}) == 0
    assert "would update frontend/openapi.json" in capsys.readouterr().out
    assert bv.main(["9.9.9", "--root", str(tree)], env={}) == 0
    assert bv.main(["9.9.9", "--root", str(tree)], env={}) == 0
    assert "nothing to change" in capsys.readouterr().out


def test_script_runs_as_subprocess(tree: Path) -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--check", "--root", str(tree)],
        capture_output=True,
        text=True,
        check=False,
        env={"PATH": "/usr/bin:/bin"},
    )
    assert result.returncode == 0, result.stderr
