"""Tables and columns the SQLAlchemy models map, read with ``ast`` (no imports run).

``--all`` reads ``app/models`` from the working tree; ``--base-ref`` reads it from the git
ref with ``git show`` (the previous release's models, which must keep working against the
new schema during a rolling deploy).
"""

from __future__ import annotations

import ast
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

_COLUMN_FACTORIES = frozenset({"mapped_column", "Column", "column_property"})


@dataclass
class ModelSchema:
    tables: set[str] = field(default_factory=set)
    columns: dict[str, set[str]] = field(default_factory=dict)

    def maps_table(self, table: str) -> bool:
        return table in self.tables

    def maps_column(self, table: str, column: str) -> bool:
        return column in self.columns.get(table, set())


def _call_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Name):
            return func.id
        if isinstance(func, ast.Attribute):
            return func.attr
    return None


def _first_str_arg(call: ast.Call) -> str | None:
    if call.args and isinstance(call.args[0], ast.Constant) and isinstance(call.args[0].value, str):
        return call.args[0].value
    return None


def _class_columns(node: ast.ClassDef) -> tuple[str | None, set[str]]:
    table: str | None = None
    columns: set[str] = set()
    for stmt in node.body:
        target: ast.expr | None = None
        value: ast.expr | None = None
        if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
            target, value = stmt.targets[0], stmt.value
        elif isinstance(stmt, ast.AnnAssign):
            target, value = stmt.target, stmt.value
        if not isinstance(target, ast.Name) or value is None:
            continue
        if target.id == "__tablename__":
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                table = value.value
            continue
        if isinstance(value, ast.Call) and _call_name(value) in _COLUMN_FACTORIES:
            columns.add(_first_str_arg(value) or target.id)
    return table, columns


def _table_calls(tree: ast.AST) -> Iterable[tuple[str, set[str]]]:
    """``Table("name", metadata, Column("col", ...), ...)`` declarations."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _call_name(node) == "Table":
            name = _first_str_arg(node)
            if name is None:
                continue
            columns = {
                column
                for arg in node.args[1:]
                if isinstance(arg, ast.Call) and _call_name(arg) == "Column"
                for column in [_first_str_arg(arg)]
                if column is not None
            }
            yield name, columns


def schema_from_sources(sources: Iterable[str]) -> ModelSchema:
    """Merge every mapped class (with mixin and base-class columns) and ``Table`` call."""
    classes: dict[str, tuple[str | None, set[str], list[str]]] = {}
    schema = ModelSchema()
    for source in sources:
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                table, columns = _class_columns(node)
                bases = [base.id for base in node.bases if isinstance(base, ast.Name)]
                classes[node.name] = (table, columns, bases)
        for name, columns in _table_calls(tree):
            schema.tables.add(name)
            schema.columns.setdefault(name, set()).update(columns)

    def inherited(name: str, seen: frozenset[str]) -> set[str]:
        if name not in classes or name in seen:
            return set()
        _, columns, bases = classes[name]
        result = set(columns)
        for base in bases:
            result |= inherited(base, seen | {name})
        return result

    for name, (table, _, _) in classes.items():
        if table is not None:
            schema.tables.add(table)
            schema.columns.setdefault(table, set()).update(inherited(name, frozenset()))
    return schema


def load_worktree_models(models_dir: Path) -> ModelSchema:
    paths = sorted(models_dir.rglob("*.py"))
    return schema_from_sources(path.read_text(encoding="utf-8") for path in paths)


def run_git(repo_root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=repo_root, capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def load_ref_models(repo_root: Path, ref: str, models_rel: str) -> ModelSchema:
    """The models as they are at ``ref`` (``git ls-tree`` + ``git show``)."""
    listing = run_git(repo_root, "ls-tree", "-r", "--name-only", ref, "--", models_rel)
    paths = [line for line in listing.splitlines() if line.endswith(".py")]
    return schema_from_sources(run_git(repo_root, "show", f"{ref}:{path}") for path in paths)
