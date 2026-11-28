"""Rule names, descriptions, and the override marker (docs/CONTRIBUTING.md, migrations)."""

from __future__ import annotations

import re
from dataclasses import dataclass

# Contract changes: fail while the previous release's models still reference the object.
DROP_COLUMN = "drop-column"
DROP_TABLE = "drop-table"
RENAME_COLUMN = "rename-column"
RENAME_TABLE = "rename-table"
# Long ACCESS EXCLUSIVE (or SHARE) locks: fail on a large table unless overridden.
ALTER_COLUMN_TYPE = "alter-column-type"
SET_NOT_NULL = "set-not-null"
CREATE_INDEX_NON_CONCURRENT = "create-index-non-concurrent"
FOREIGN_KEY_VALIDATING = "foreign-key-validating"
CHECK_CONSTRAINT_VALIDATING = "check-constraint-validating"
ADD_CONSTRAINT_VALIDATING = "add-constraint-validating"
VOLATILE_DEFAULT = "volatile-default"
LOCK_TABLE = "lock-table"
VACUUM_FULL = "vacuum-full"
CLUSTER = "cluster"
# CREATE/DROP INDEX CONCURRENTLY cannot run inside a transaction block.
CONCURRENTLY_OUTSIDE_AUTOCOMMIT = "concurrently-outside-autocommit"
# A marker without a reason or with an unknown rule; never overridable.
INVALID_MARKER = "invalid-marker"

CONTRACT_RULES = frozenset({DROP_COLUMN, DROP_TABLE, RENAME_COLUMN, RENAME_TABLE})
LOCK_RULES = frozenset(
    {
        ALTER_COLUMN_TYPE,
        SET_NOT_NULL,
        CREATE_INDEX_NON_CONCURRENT,
        FOREIGN_KEY_VALIDATING,
        CHECK_CONSTRAINT_VALIDATING,
        ADD_CONSTRAINT_VALIDATING,
        VOLATILE_DEFAULT,
        LOCK_TABLE,
        VACUUM_FULL,
        CLUSTER,
    }
)
OVERRIDABLE_RULES = CONTRACT_RULES | LOCK_RULES | {CONCURRENTLY_OUTSIDE_AUTOCOMMIT}

DESCRIPTIONS: dict[str, str] = {
    DROP_COLUMN: "drops a column the reference models still map",
    DROP_TABLE: "drops a table the reference models still map",
    RENAME_COLUMN: "renames a column the reference models still map",
    RENAME_TABLE: "renames a table the reference models still map",
    ALTER_COLUMN_TYPE: "changes a column type on a large table (table rewrite, ACCESS EXCLUSIVE)",
    SET_NOT_NULL: "sets NOT NULL on a large table (full scan under ACCESS EXCLUSIVE)",
    CREATE_INDEX_NON_CONCURRENT: "creates an index on a large table without CONCURRENTLY",
    FOREIGN_KEY_VALIDATING: "adds a foreign key on a large table without NOT VALID",
    CHECK_CONSTRAINT_VALIDATING: "adds a check constraint on a large table without NOT VALID",
    ADD_CONSTRAINT_VALIDATING: "ALTER TABLE ... ADD CONSTRAINT on a large table without NOT VALID",
    VOLATILE_DEFAULT: "adds a column with a volatile default to a large table (table rewrite)",
    LOCK_TABLE: "takes an explicit LOCK TABLE on a large table",
    VACUUM_FULL: "runs VACUUM FULL (table rewrite under ACCESS EXCLUSIVE)",
    CLUSTER: "runs CLUSTER (table rewrite under ACCESS EXCLUSIVE)",
    CONCURRENTLY_OUTSIDE_AUTOCOMMIT: "uses CONCURRENTLY outside op.get_context().autocommit_block()",
    INVALID_MARKER: "migration-safety marker needs known rules and a non-empty reason",
}

MARKER_RE = re.compile(r"#\s*migration-safety:\s*(?P<body>.*)$")
_MARKER_BODY_RE = re.compile(
    r'^allow=(?P<rules>[a-z0-9,\-]+)(?:\s+reason="(?P<reason>[^"]*)")?\s*$'
)


@dataclass(frozen=True)
class Marker:
    line: int
    rules: frozenset[str]
    reason: str


@dataclass(frozen=True)
class MarkerError:
    line: int
    message: str


def parse_markers(source: str) -> tuple[list[Marker], list[MarkerError]]:
    """``# migration-safety: allow=<rule>[,<rule>] reason="..."`` lines of a migration."""
    markers: list[Marker] = []
    errors: list[MarkerError] = []
    for number, text in enumerate(source.splitlines(), start=1):
        found = MARKER_RE.search(text)
        if found is None:
            continue
        body = _MARKER_BODY_RE.match(found.group("body").strip())
        if body is None:
            errors.append(MarkerError(number, 'expected allow=<rule>[,<rule>] reason="..."'))
            continue
        rules = frozenset(rule for rule in body.group("rules").split(",") if rule)
        unknown = sorted(rules - OVERRIDABLE_RULES)
        reason = (body.group("reason") or "").strip()
        if unknown:
            errors.append(MarkerError(number, f"unknown rule(s): {', '.join(unknown)}"))
        elif not reason:
            errors.append(MarkerError(number, "a non-empty reason is required"))
        else:
            markers.append(Marker(number, rules, reason))
    return markers, errors
