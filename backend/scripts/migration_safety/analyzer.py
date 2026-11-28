"""Walk a migration's ``upgrade()`` with ``ast`` and report rule events.

Only ``upgrade()`` and the module-level helpers it calls are read: downgrades are never run
automatically (docs/CONTRIBUTING.md). Two pieces of context travel with the walk:

- inside ``with op.get_context().autocommit_block():`` (CONCURRENTLY is allowed there);
- in a branch that runs only on a non-PostgreSQL dialect (``if bind.dialect.name !=
  "postgresql":``, the SQLite path of the test suite), where nothing is reported.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from dataclasses import dataclass, field

from migration_safety import rules
from migration_safety.sql import VOLATILE_DEFAULT_RE, created_tables, sql_events


@dataclass(frozen=True)
class Event:
    rule: str
    line: int
    table: str | None
    column: str | None = None
    referent: str | None = None


@dataclass(frozen=True)
class _Context:
    autocommit: bool = False
    non_postgres: bool = False


@dataclass
class Analysis:
    revision: str | None
    events: list[Event] = field(default_factory=list)
    created: set[str] = field(default_factory=set)


# op.<method>: index of the table argument (op form, batch form) and its keyword.
_TABLE_ARG: dict[str, tuple[int | None, str | None]] = {
    "drop_table": (0, "table_name"),
    "rename_table": (0, "old_table_name"),
    "drop_column": (0, "table_name"),
    "alter_column": (0, "table_name"),
    "add_column": (0, "table_name"),
    "create_index": (1, "table_name"),
    "create_foreign_key": (1, "source_table"),
    "create_check_constraint": (1, "table_name"),
}


def _const_str(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _keyword(call: ast.Call, name: str) -> ast.expr | None:
    for keyword in call.keywords:
        if keyword.arg == name:
            return keyword.value
    return None


def _is_true(node: ast.AST | None) -> bool:
    return isinstance(node, ast.Constant) and node.value is True


def _attr_chain(node: ast.AST) -> list[str]:
    names: list[str] = []
    while True:
        if isinstance(node, ast.Attribute):
            names.append(node.attr)
            node = node.value
        elif isinstance(node, ast.Call):
            node = node.func
        elif isinstance(node, ast.Name):
            names.append(node.id)
            return names
        else:
            return names


class _Walker:
    def __init__(self, tree: ast.Module) -> None:
        self.functions: dict[str, ast.FunctionDef] = {}
        self.strings: dict[str, ast.expr] = {}
        self.analysis = Analysis(revision=None)
        for stmt in tree.body:
            if isinstance(stmt, ast.FunctionDef):
                self.functions[stmt.name] = stmt
            elif isinstance(stmt, (ast.Assign, ast.AnnAssign)):
                targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
                for target in targets:
                    if isinstance(target, ast.Name) and stmt.value is not None:
                        self.strings[target.id] = stmt.value
                        if target.id == "revision":
                            self.analysis.revision = _const_str(stmt.value)
        self._visited: set[tuple[str, _Context]] = set()
        self._dialect_flags: dict[str, bool] = {}
        self._batch_tables: dict[str, str | None] = {}

    # --- values -----------------------------------------------------------------------

    def resolve_str(self, node: ast.AST | None, depth: int = 0) -> str | None:
        if node is None or depth > 5:
            return None
        if (value := _const_str(node)) is not None:
            return value
        if isinstance(node, ast.Name) and node.id in self.strings:
            return self.resolve_str(self.strings[node.id], depth + 1)
        if isinstance(node, ast.JoinedStr):
            parts = [
                _const_str(part) if isinstance(part, ast.Constant) else "{}" for part in node.values
            ]
            return "".join(part or "" for part in parts)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            left = self.resolve_str(node.left, depth + 1)
            right = self.resolve_str(node.right, depth + 1)
            return None if left is None or right is None else left + right
        if isinstance(node, ast.Call) and _attr_chain(node.func)[:1] == ["text"] and node.args:
            return self.resolve_str(node.args[0], depth + 1)
        return None

    def _table(
        self, call: ast.Call, method: str, batch_table: str | None, batch: bool
    ) -> str | None:
        if batch:
            return batch_table
        index, keyword = _TABLE_ARG[method]
        node = _keyword(call, keyword) if keyword else None
        if node is None and index is not None and len(call.args) > index:
            node = call.args[index]
        value = self.resolve_str(node)
        return value.lower() if value else None

    # --- dialect branches -------------------------------------------------------------

    def _dialect_test(self, test: ast.expr) -> bool | None:
        """True: the branch runs only on PostgreSQL; False: only elsewhere; None: unknown."""
        if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
            inner = self._dialect_test(test.operand)
            return None if inner is None else not inner
        if isinstance(test, ast.Name):
            return self._dialect_flags.get(test.id)
        if isinstance(test, ast.Call) and isinstance(test.func, ast.Name) and not test.args:
            # A helper such as ``def _is_postgresql(): return bind.dialect.name == "..."``.
            helper = self.functions.get(test.func.id)
            if helper is not None and len(helper.body) == 1:
                returned = helper.body[0]
                if isinstance(returned, ast.Return) and isinstance(returned.value, ast.Compare):
                    return self._dialect_test(returned.value)
        if isinstance(test, ast.Compare) and len(test.ops) == 1:
            chain = _attr_chain(test.left)
            if "dialect" not in chain or _const_str(test.comparators[0]) != "postgresql":
                return None
            if isinstance(test.ops[0], (ast.Eq, ast.Is)):
                return True
            if isinstance(test.ops[0], (ast.NotEq, ast.IsNot)):
                return False
        return None

    # --- walk -------------------------------------------------------------------------

    def walk_function(self, name: str, ctx: _Context) -> None:
        function = self.functions.get(name)
        if function is None or (name, ctx) in self._visited:
            return
        self._visited.add((name, ctx))
        self.walk_body(function.body, ctx)

    def walk_body(self, body: list[ast.stmt], ctx: _Context) -> None:
        for stmt in body:
            self.walk_stmt(stmt, ctx)

    def walk_stmt(self, stmt: ast.stmt, ctx: _Context) -> None:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            return
        if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
            target = stmt.targets[0]
            flag = self._dialect_test(stmt.value) if isinstance(stmt.value, ast.Compare) else None
            if isinstance(target, ast.Name) and flag is not None:
                self._dialect_flags[target.id] = flag
        if isinstance(stmt, ast.If):
            self.scan_calls(stmt.test, ctx)
            flag = self._dialect_test(stmt.test)
            body_ctx = _Context(ctx.autocommit, ctx.non_postgres or flag is False)
            else_ctx = _Context(ctx.autocommit, ctx.non_postgres or flag is True)
            self.walk_body(stmt.body, body_ctx)
            self.walk_body(stmt.orelse, else_ctx)
            return
        if isinstance(stmt, (ast.With, ast.AsyncWith)):
            inner = ctx
            for item in stmt.items:
                chain = _attr_chain(item.context_expr)
                if chain and chain[0] == "autocommit_block":
                    inner = _Context(True, ctx.non_postgres)
                elif (
                    chain
                    and chain[0] == "batch_alter_table"
                    and isinstance(item.optional_vars, ast.Name)
                ):
                    call = item.context_expr
                    table = (
                        self.resolve_str(call.args[0])
                        if isinstance(call, ast.Call) and call.args
                        else None
                    )
                    self._batch_tables[item.optional_vars.id] = table.lower() if table else None
                else:
                    self.scan_calls(item.context_expr, ctx)
            self.walk_body(stmt.body, inner)
            return
        if isinstance(stmt, (ast.For, ast.AsyncFor, ast.While)):
            self.scan_calls(stmt.iter if not isinstance(stmt, ast.While) else stmt.test, ctx)
            self.walk_body(stmt.body, ctx)
            self.walk_body(stmt.orelse, ctx)
            return
        if isinstance(stmt, ast.Try):
            for part in (stmt.body, *(h.body for h in stmt.handlers), stmt.orelse, stmt.finalbody):
                self.walk_body(part, ctx)
            return
        self.scan_calls(stmt, ctx)

    def scan_calls(self, node: ast.AST, ctx: _Context) -> None:
        for call in _calls(node):
            self.handle_call(call, ctx)

    # --- calls ------------------------------------------------------------------------

    def emit(self, ctx: _Context, event: Event) -> None:
        if not ctx.non_postgres:
            self.analysis.events.append(event)

    def handle_call(self, call: ast.Call, ctx: _Context) -> None:
        func = call.func
        if isinstance(func, ast.Name):
            self.walk_function(func.id, ctx)
            return
        if not isinstance(func, ast.Attribute):
            return
        owner = func.value.id if isinstance(func.value, ast.Name) else None
        method = func.attr
        if method == "execute" and call.args:
            self.handle_sql(call, ctx)
            return
        batch = owner in self._batch_tables
        if owner != "op" and not batch:
            return
        batch_table = self._batch_tables.get(owner or "")
        if method == "create_table":
            name = self.resolve_str(call.args[0] if call.args else _keyword(call, "table_name"))
            if name and not ctx.non_postgres:
                self.analysis.created.add(name.lower())
            return
        if method not in _TABLE_ARG:
            return
        table = self._table(call, method, batch_table, batch)
        self.handle_op(call, method, table, batch, ctx)

    def handle_op(
        self, call: ast.Call, method: str, table: str | None, batch: bool, ctx: _Context
    ) -> None:
        line = call.lineno
        offset = 0 if batch else 1

        def arg(index: int, keyword: str) -> str | None:
            node = _keyword(call, keyword)
            if node is None and len(call.args) > index:
                node = call.args[index]
            value = self.resolve_str(node)
            return value.lower() if value else None

        if method == "drop_table":
            self.emit(ctx, Event(rules.DROP_TABLE, line, table))
        elif method == "rename_table":
            self.emit(ctx, Event(rules.RENAME_TABLE, line, table))
        elif method == "drop_column":
            self.emit(ctx, Event(rules.DROP_COLUMN, line, table, arg(offset, "column_name")))
        elif method == "alter_column":
            column = arg(offset, "column_name")
            if _keyword(call, "new_column_name") is not None:
                self.emit(ctx, Event(rules.RENAME_COLUMN, line, table, column))
            if _keyword(call, "type_") is not None:
                self.emit(ctx, Event(rules.ALTER_COLUMN_TYPE, line, table, column))
            nullable = _keyword(call, "nullable")
            if isinstance(nullable, ast.Constant) and nullable.value is False:
                self.emit(ctx, Event(rules.SET_NOT_NULL, line, table, column))
        elif method == "add_column":
            node = call.args[offset] if len(call.args) > offset else _keyword(call, "column")
            if isinstance(node, ast.Call) and self._volatile_default(node):
                self.emit(ctx, Event(rules.VOLATILE_DEFAULT, line, table))
        elif method == "create_index":
            if _is_true(_keyword(call, "postgresql_concurrently")):
                if not ctx.autocommit:
                    self.emit(ctx, Event(rules.CONCURRENTLY_OUTSIDE_AUTOCOMMIT, line, table))
            else:
                self.emit(ctx, Event(rules.CREATE_INDEX_NON_CONCURRENT, line, table))
        elif method in ("create_foreign_key", "create_check_constraint"):
            if not _is_true(_keyword(call, "postgresql_not_valid")):
                rule = (
                    rules.FOREIGN_KEY_VALIDATING
                    if method == "create_foreign_key"
                    else rules.CHECK_CONSTRAINT_VALIDATING
                )
                referent = (
                    arg(offset + 1, "referent_table")
                    if rule == rules.FOREIGN_KEY_VALIDATING
                    else None
                )
                self.emit(ctx, Event(rule, line, table, referent=referent))

    def _volatile_default(self, column: ast.Call) -> bool:
        default = _keyword(column, "server_default")
        if default is None:
            return False
        text = self.resolve_str(default)
        if text is None:
            text = ast.unparse(default)
        return bool(VOLATILE_DEFAULT_RE.search(text))

    def handle_sql(self, call: ast.Call, ctx: _Context) -> None:
        sql = self.resolve_str(call.args[0])
        if sql is None:
            return
        if not ctx.non_postgres:
            self.analysis.created |= created_tables(sql)
        for event in sql_events(sql):
            if event.rule == rules.CONCURRENTLY_OUTSIDE_AUTOCOMMIT and ctx.autocommit:
                continue
            self.emit(ctx, Event(event.rule, call.lineno, event.table, event.column))


def _calls(node: ast.AST) -> Iterator[ast.Call]:
    """Calls in ``node`` in source order, outermost first, without entering nested defs."""
    stack: list[ast.AST] = [node]
    found: list[ast.Call] = []
    while stack:
        current = stack.pop()
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            continue
        if isinstance(current, ast.Call):
            found.append(current)
        stack.extend(ast.iter_child_nodes(current))
    yield from sorted(found, key=lambda call: (call.lineno, call.col_offset))


def analyze_source(source: str) -> Analysis:
    """Events of one migration file's ``upgrade()``."""
    tree = ast.parse(source)
    walker = _Walker(tree)
    walker.walk_function("upgrade", _Context())
    return walker.analysis
