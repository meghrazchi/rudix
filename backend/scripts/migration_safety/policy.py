"""Turn analyzer events into findings: large tables, reference models, markers, allowlist."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from migration_safety import rules
from migration_safety.analyzer import Event, analyze_source
from migration_safety.models import ModelSchema


@dataclass(frozen=True)
class Finding:
    revision: str
    path: str
    line: int
    rule: str
    message: str

    def render(self) -> str:
        return f"{self.revision} {self.path}:{self.line} {self.rule}: {self.message}"


@dataclass(frozen=True)
class AllowEntry:
    revision: str
    rule: str
    reason: str


@dataclass(frozen=True)
class Config:
    large_tables: frozenset[str]


def load_config(path: Path) -> Config:
    data = json.loads(path.read_text(encoding="utf-8"))
    return Config(large_tables=frozenset(name.lower() for name in data["large_tables"]))


def load_allowlist(path: Path) -> list[AllowEntry]:
    """Entries ``{revision, rule, reason}``; a missing reason or unknown rule is an error."""
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    entries: list[AllowEntry] = []
    for raw in data.get("entries", []):
        entry = AllowEntry(str(raw["revision"]), str(raw["rule"]), str(raw.get("reason", "")))
        if entry.rule not in rules.OVERRIDABLE_RULES:
            raise ValueError(f"allowlist: unknown rule {entry.rule!r} for {entry.revision}")
        if not entry.reason.strip():
            raise ValueError(f"allowlist: {entry.revision} {entry.rule} needs a reason")
        entries.append(entry)
    return entries


def _describe(event: Event) -> str:
    target = event.table or "<unresolved table>"
    if event.column:
        target = f"{target}.{event.column}"
    if event.referent:
        target = f"{target} -> {event.referent}"
    return f"{rules.DESCRIPTIONS[event.rule]} ({target})"


def _violates(event: Event, config: Config, models: ModelSchema, created: set[str]) -> bool:
    if event.rule in rules.CONTRACT_RULES:
        if event.table is None or event.table in created:
            return False
        if event.rule in (rules.DROP_TABLE, rules.RENAME_TABLE):
            return models.maps_table(event.table)
        return event.column is not None and models.maps_column(event.table, event.column)
    if event.rule == rules.CONCURRENTLY_OUTSIDE_AUTOCOMMIT:
        return True
    tables = [event.table, event.referent] if event.referent else [event.table]
    for table in tables:
        if table is None:
            # Unresolved (a variable or a placeholder): assume large.
            return True
        if table not in created and table in config.large_tables:
            return True
    return False


def check_file(
    path: Path,
    display_path: str,
    config: Config,
    models: ModelSchema,
) -> tuple[str, list[Finding]]:
    """Revision id and the findings of one migration, after its own override markers."""
    source = path.read_text(encoding="utf-8")
    analysis = analyze_source(source)
    revision = analysis.revision or path.stem
    markers, marker_errors = rules.parse_markers(source)
    allowed = frozenset().union(*(marker.rules for marker in markers)) if markers else frozenset()
    findings = [
        Finding(revision, display_path, error.line, rules.INVALID_MARKER, error.message)
        for error in marker_errors
    ]
    seen: set[tuple[int, str, str | None, str | None]] = set()
    for event in analysis.events:
        key = (event.line, event.rule, event.table, event.column)
        if key in seen or event.rule in allowed:
            continue
        if _violates(event, config, models, analysis.created):
            seen.add(key)
            findings.append(
                Finding(revision, display_path, event.line, event.rule, _describe(event))
            )
    return revision, findings


def apply_allowlist(
    findings: list[Finding], entries: list[AllowEntry], checked_revisions: set[str]
) -> tuple[list[Finding], list[AllowEntry]]:
    """Findings left after the allowlist, and entries (of checked revisions) that matched none."""
    keys = {(entry.revision, entry.rule) for entry in entries}
    remaining = [
        finding
        for finding in findings
        if finding.rule == rules.INVALID_MARKER or (finding.revision, finding.rule) not in keys
    ]
    matched = {(finding.revision, finding.rule) for finding in findings}
    stale = [
        entry
        for entry in entries
        if entry.revision in checked_revisions and (entry.revision, entry.rule) not in matched
    ]
    return remaining, stale
