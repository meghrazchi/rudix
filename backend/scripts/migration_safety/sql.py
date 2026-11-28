"""Findings in raw SQL strings (``op.execute``, ``connection.execute``, ``sa.text``).

Pattern based, not a parser: it reads the statements migrations actually write. A table name
that comes from a placeholder (``{}`` from an f-string) is unknown (``None``); the policy
treats an unknown table as large for lock rules and skips it for contract rules.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from migration_safety import rules

_PART = r'(?:"[^"]+"|[A-Za-z0-9_{}]+)'
_IDENT = rf"(?:{_PART}(?:\.{_PART})*)"
_COMMENT_RE = re.compile(r"--[^\n]*|/\*.*?\*/", re.DOTALL)
_ALTER_TABLE_RE = re.compile(
    rf"\bALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?(?:ONLY\s+)?(?P<table>{_IDENT})\s+(?P<rest>.*)",
    re.IGNORECASE | re.DOTALL,
)
_DROP_TABLE_RE = re.compile(
    rf"\bDROP\s+TABLE\s+(?:IF\s+EXISTS\s+)?(?P<tables>{_IDENT}(?:\s*,\s*{_IDENT})*)",
    re.IGNORECASE,
)
_CREATE_TABLE_RE = re.compile(
    rf"\bCREATE\s+(?:UNLOGGED\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?P<table>{_IDENT})",
    re.IGNORECASE,
)
_CREATE_INDEX_RE = re.compile(
    r"\bCREATE\s+(?:UNIQUE\s+)?INDEX\s+(?P<concurrently>CONCURRENTLY\s+)?"
    rf"(?:IF\s+NOT\s+EXISTS\s+)?(?:{_IDENT}\s+)?ON\s+(?:ONLY\s+)?(?P<table>{_IDENT})",
    re.IGNORECASE,
)
_LOCK_RE = re.compile(rf"\bLOCK\s+(?:TABLE\s+)?(?:ONLY\s+)?(?P<table>{_IDENT})", re.IGNORECASE)
_VACUUM_FULL_RE = re.compile(
    r"\bVACUUM\s*(?:\([^)]*\bFULL\b[^)]*\)|FULL\b)(?:\s+(?:VERBOSE|ANALYZE|FREEZE)\b)*"
    rf"(?:\s+(?P<table>{_IDENT}))?",
    re.IGNORECASE,
)
_CLUSTER_RE = re.compile(rf"^\s*CLUSTER\b(?:\s+VERBOSE)?(?:\s+(?P<table>{_IDENT}))?", re.IGNORECASE)
_CONCURRENTLY_RE = re.compile(r"\bCONCURRENTLY\b", re.IGNORECASE)
_DROP_COLUMN_RE = re.compile(
    rf"\bDROP\s+(?:COLUMN\s+)?(?:IF\s+EXISTS\s+)?(?P<column>{_IDENT})", re.IGNORECASE
)
_RENAME_TABLE_RE = re.compile(rf"^\s*RENAME\s+TO\s+{_IDENT}", re.IGNORECASE)
_RENAME_COLUMN_RE = re.compile(
    rf"^\s*RENAME\s+(?:COLUMN\s+)?(?P<column>{_IDENT})\s+TO\s+{_IDENT}", re.IGNORECASE
)
_ALTER_TYPE_RE = re.compile(
    rf"\bALTER\s+(?:COLUMN\s+)?{_IDENT}\s+(?:SET\s+DATA\s+)?TYPE\b", re.IGNORECASE
)
_SET_NOT_NULL_RE = re.compile(rf"\bALTER\s+(?:COLUMN\s+)?{_IDENT}\s+SET\s+NOT\s+NULL\b", re.I)
_ADD_CONSTRAINT_RE = re.compile(r"\bADD\s+CONSTRAINT\b", re.IGNORECASE)
_ADD_COLUMN_RE = re.compile(r"^\s*ADD\s+(?!CONSTRAINT\b)", re.IGNORECASE)
_NOT_VALID_RE = re.compile(r"\bNOT\s+VALID\b", re.IGNORECASE)
_USING_INDEX_RE = re.compile(r"\bUSING\s+INDEX\b", re.IGNORECASE)
VOLATILE_DEFAULT_RE = re.compile(
    r"\b(?:random|gen_random_uuid|uuid_generate_v[14]|clock_timestamp|timeofday|nextval)\s*\(",
    re.IGNORECASE,
)
_DEFAULT_RE = re.compile(r"\bDEFAULT\b", re.IGNORECASE)


@dataclass(frozen=True)
class SqlEvent:
    rule: str
    table: str | None
    column: str | None = None
    concurrently: bool = False


def clean_name(raw: str | None) -> str | None:
    """Unquoted, unqualified identifier; None when it comes from a placeholder."""
    if raw is None:
        return None
    name = raw.strip().strip('"')
    if "{" in name or "}" in name or not name:
        return None
    name = name.split(".")[-1].strip('"')
    return name.lower()


def _split_top_level(text: str) -> list[str]:
    """Comma-separated ALTER TABLE actions, ignoring commas inside parentheses."""
    parts: list[str] = []
    depth = 0
    current: list[str] = []
    for char in text:
        if char == "(":
            depth += 1
        elif char == ")":
            depth = max(0, depth - 1)
        if char == "," and depth == 0:
            parts.append("".join(current))
            current = []
            continue
        current.append(char)
    parts.append("".join(current))
    return parts


def _alter_table_events(table: str | None, rest: str) -> list[SqlEvent]:
    events: list[SqlEvent] = []
    for action in _split_top_level(rest):
        stripped = action.strip()
        upper = stripped.upper()
        if upper.startswith("DROP") and not upper.startswith("DROP CONSTRAINT"):
            if upper.startswith(("DROP DEFAULT", "DROP NOT NULL", "DROP IDENTITY")):
                continue
            found = _DROP_COLUMN_RE.match(stripped)
            if found:
                events.append(SqlEvent(rules.DROP_COLUMN, table, clean_name(found["column"])))
        elif _RENAME_TABLE_RE.match(stripped):
            events.append(SqlEvent(rules.RENAME_TABLE, table))
        elif upper.startswith("RENAME CONSTRAINT"):
            continue
        elif found := _RENAME_COLUMN_RE.match(stripped):
            events.append(SqlEvent(rules.RENAME_COLUMN, table, clean_name(found["column"])))
        elif _ALTER_TYPE_RE.search(stripped):
            events.append(SqlEvent(rules.ALTER_COLUMN_TYPE, table))
        elif _SET_NOT_NULL_RE.search(stripped):
            events.append(SqlEvent(rules.SET_NOT_NULL, table))
        elif _ADD_CONSTRAINT_RE.search(stripped):
            if not _NOT_VALID_RE.search(stripped) and not _USING_INDEX_RE.search(stripped):
                events.append(SqlEvent(rules.ADD_CONSTRAINT_VALIDATING, table))
        elif _ADD_COLUMN_RE.match(stripped) and _DEFAULT_RE.search(stripped):
            if VOLATILE_DEFAULT_RE.search(stripped):
                events.append(SqlEvent(rules.VOLATILE_DEFAULT, table))
    return events


def _statement_events(statement: str) -> list[SqlEvent]:
    events: list[SqlEvent] = []
    concurrently = bool(_CONCURRENTLY_RE.search(statement))
    if concurrently:
        events.append(SqlEvent(rules.CONCURRENTLY_OUTSIDE_AUTOCOMMIT, None, concurrently=True))
    for found in _DROP_TABLE_RE.finditer(statement):
        for raw in found["tables"].split(","):
            events.append(SqlEvent(rules.DROP_TABLE, clean_name(raw)))
    if alter := _ALTER_TABLE_RE.search(statement):
        events.extend(_alter_table_events(clean_name(alter["table"]), alter["rest"]))
    for index in _CREATE_INDEX_RE.finditer(statement):
        if not index["concurrently"]:
            events.append(SqlEvent(rules.CREATE_INDEX_NON_CONCURRENT, clean_name(index["table"])))
    single = (
        (rules.LOCK_TABLE, _LOCK_RE),
        (rules.VACUUM_FULL, _VACUUM_FULL_RE),
        (rules.CLUSTER, _CLUSTER_RE),
    )
    for rule, pattern in single:
        if match := pattern.search(statement):
            events.append(SqlEvent(rule, clean_name(match["table"])))
    return events


def created_tables(sql: str) -> set[str]:
    return {
        name
        for found in _CREATE_TABLE_RE.finditer(_COMMENT_RE.sub(" ", sql))
        if (name := clean_name(found["table"])) is not None
    }


def sql_events(sql: str) -> list[SqlEvent]:
    """Every rule event in a SQL string (one or more statements)."""
    text = _COMMENT_RE.sub(" ", sql)
    events: list[SqlEvent] = []
    for statement in text.split(";"):
        if statement.strip():
            events.extend(_statement_events(statement))
    return events
