"""Fail on Alembic migrations that break the previous release or lock large tables (R08-08).

    python scripts/check_migration_safety.py --all
    python scripts/check_migration_safety.py --base-ref origin/develop

``--all`` checks every file in ``alembic/versions`` against the working-tree models and
honours ``scripts/migration_safety_allowlist.json`` (a stale entry fails). ``--base-ref``
checks only migrations added or changed since the merge base with the ref (plus untracked
ones) and compares drops and renames with the models at the ref, which the previous release
runs during a rolling deploy. Rules, the override marker, and the allowlist are described
in docs/CONTRIBUTING.md ("Database migrations").

Output: one line per finding (``<revision> <file>:<line> <rule>: <message>``); exit 0 when
clean, 1 on findings or stale allowlist entries, 2 on usage or git errors.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from migration_safety.models import (
    ModelSchema,
    load_ref_models,
    load_worktree_models,
    run_git,
)
from migration_safety.policy import (
    AllowEntry,
    Finding,
    apply_allowlist,
    check_file,
    load_allowlist,
    load_config,
)

SCRIPTS_DIR = Path(__file__).resolve().parent
DEFAULT_BACKEND_DIR = SCRIPTS_DIR.parent


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--all", action="store_true", help="check every migration")
    mode.add_argument("--base-ref", help="check migrations changed since this git ref")
    parser.add_argument("--backend-dir", type=Path, default=DEFAULT_BACKEND_DIR)
    parser.add_argument("--config", type=Path, default=SCRIPTS_DIR / "migration_safety_config.json")
    parser.add_argument(
        "--allowlist", type=Path, default=SCRIPTS_DIR / "migration_safety_allowlist.json"
    )
    return parser.parse_args(argv)


def _versions(backend_dir: Path) -> Path:
    return backend_dir / "alembic" / "versions"


def _repo_paths(backend_dir: Path) -> tuple[Path, str]:
    """Repository root and the backend directory relative to it (``git`` paths)."""
    root = Path(run_git(backend_dir, "rev-parse", "--show-toplevel").strip()).resolve()
    relative = backend_dir.resolve().relative_to(root).as_posix()
    return root, "" if relative == "." else relative


def _join(prefix: str, path: str) -> str:
    return f"{prefix}/{path}" if prefix else path


def changed_migrations(backend_dir: Path, ref: str) -> list[Path]:
    """Migrations added or modified since the merge base with ``ref``, plus untracked ones."""
    root, prefix = _repo_paths(backend_dir)
    versions_rel = _join(prefix, "alembic/versions")
    base = run_git(root, "merge-base", ref, "HEAD").strip()
    changed = run_git(root, "diff", "--name-only", "--diff-filter=AMR", base, "--", versions_rel)
    untracked = run_git(root, "ls-files", "--others", "--exclude-standard", "--", versions_rel)
    names = {line for line in (changed + untracked).splitlines() if line.endswith(".py")}
    return sorted(root / name for name in names if (root / name).is_file())


def run_check(
    files: list[Path],
    backend_dir: Path,
    models: ModelSchema,
    config_path: Path,
    allowlist: list[AllowEntry],
    *,
    every_revision_checked: bool,
) -> tuple[list[Finding], list[AllowEntry]]:
    config = load_config(config_path)
    findings: list[Finding] = []
    revisions: set[str] = set()
    for path in files:
        try:
            display = path.resolve().relative_to(backend_dir.resolve()).as_posix()
        except ValueError:
            display = str(path)
        revision, file_findings = check_file(path, display, config, models)
        revisions.add(revision)
        findings.extend(file_findings)
    remaining, stale = apply_allowlist(findings, allowlist, revisions)
    if every_revision_checked:
        stale.extend(entry for entry in allowlist if entry.revision not in revisions)
    return remaining, stale


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    backend_dir: Path = args.backend_dir.resolve()
    try:
        allowlist = load_allowlist(args.allowlist)
        if args.all:
            files = sorted(_versions(backend_dir).glob("*.py"))
            models = load_worktree_models(backend_dir / "app" / "models")
        else:
            files = changed_migrations(backend_dir, args.base_ref)
            root, prefix = _repo_paths(backend_dir)
            models = load_ref_models(root, args.base_ref, _join(prefix, "app/models"))
    except (RuntimeError, ValueError, OSError) as exc:
        print(f"check_migration_safety: {exc}", file=sys.stderr)
        return 2
    findings, stale = run_check(
        files,
        backend_dir,
        models,
        args.config,
        allowlist,
        every_revision_checked=bool(args.all),
    )
    for finding in findings:
        print(finding.render())
    for entry in stale:
        print(f"{entry.revision} allowlist: stale entry for {entry.rule} (no matching finding)")
    scope = "all migrations" if args.all else f"migrations changed since {args.base_ref}"
    if findings or stale:
        print(
            f"check_migration_safety: {len(findings)} finding(s), {len(stale)} stale allowlist "
            f"entr{'y' if len(stale) == 1 else 'ies'} in {len(files)} file(s) ({scope}); "
            "see docs/CONTRIBUTING.md, Database migrations",
            file=sys.stderr,
        )
        return 1
    print(f"check_migration_safety: OK, {len(files)} file(s) ({scope})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
