#!/usr/bin/env python3
"""Merge Locust ``--csv`` stats and ``collect_metrics.py`` JSON into baseline tables.

Standard library only::

    python ci/load/report.py --scenario chat_ws \\
        --stats ci/load/results/chat_ws_stats.csv \\
        --metrics ci/load/results/chat_ws_metrics.json \\
        --update docs/roadmap/V0_3_0_LOAD_BASELINE.md

Without ``--update`` the table is printed. With it, the block between
``<!-- load-report:<scenario>:start -->`` and ``<!-- load-report:<scenario>:end -->`` in
the baseline document is replaced; nothing else in the file changes.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

NOT_MEASURED = "not yet measured"
TABLE_HEADER = (
    "| Request | Requests | p50 (ms) | p95 (ms) | Error rate "
    "| Queries/request p50 | Queries/request p95 | Max pool checked out |\n"
    "|---|---|---|---|---|---|---|---|"
)


def start_marker(scenario: str) -> str:
    return f"<!-- load-report:{scenario}:start -->"


def end_marker(scenario: str) -> str:
    return f"<!-- load-report:{scenario}:end -->"


def read_locust_stats(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _number(value: str | None) -> float | None:
    if value is None or value.strip() in {"", "N/A"}:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _fmt(value: float | int | None, digits: int = 0) -> str:
    if value is None:
        return "n/a"
    return f"{value:.{digits}f}"


def display_name(row: dict[str, str]) -> str:
    kind = (row.get("Type") or "").strip()
    name = (row.get("Name") or "").strip()
    if not kind or name == "Aggregated":
        return "All requests"
    return name if name.startswith(f"{kind} ") else f"{kind} {name}"


def error_rate(row: dict[str, str]) -> float | None:
    requests = _number(row.get("Request Count"))
    failures = _number(row.get("Failure Count"))
    if not requests:
        return None
    return (failures or 0.0) / requests


def build_rows(stats: list[dict[str, str]], metrics: dict[str, Any]) -> list[str]:
    queries: dict[str, dict[str, Any]] = metrics.get("queries_per_request", {})
    pool_max = metrics.get("pool", {}).get("max_checked_out")
    rows: list[str] = []
    for row in sorted(stats, key=lambda r: (display_name(r) == "All requests", display_name(r))):
        name = display_name(row)
        is_total = name == "All requests"
        query_stats = queries.get(name)
        if query_stats is not None:
            q50, q95 = _fmt(query_stats.get("p50"), 1), _fmt(query_stats.get("p95"), 1)
        elif name.startswith(("WS ", "INGEST ")):
            q50 = q95 = "n/a (not HTTP)"
        else:
            q50 = q95 = "n/a"
        rate = error_rate(row)
        cells = [
            f"**{name}**" if is_total else f"`{name}`",
            _fmt(_number(row.get("Request Count"))),
            _fmt(_number(row.get("50%"))),
            _fmt(_number(row.get("95%"))),
            "n/a" if rate is None else f"{rate * 100:.2f}%",
            "" if is_total else q50,
            "" if is_total else q95,
            _fmt(pool_max) if is_total else "",
        ]
        rows.append("| " + " | ".join(cells) + " |")
    return rows


def render_table(stats: list[dict[str, str]], metrics: dict[str, Any]) -> str:
    rows = build_rows(stats, metrics)
    if not rows:
        rows = ["| " + " | ".join([NOT_MEASURED] * 8) + " |"]
    return TABLE_HEADER + "\n" + "\n".join(rows)


def replace_block(document: str, scenario: str, table: str) -> str:
    start, end = start_marker(scenario), end_marker(scenario)
    head, found_start, rest = document.partition(start)
    if not found_start:
        raise ValueError(f"marker {start} not found")
    _, found_end, tail = rest.partition(end)
    if not found_end:
        raise ValueError(f"marker {end} not found")
    return f"{head}{start}\n{table}\n{end}{tail}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render a load baseline table.")
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--stats", required=True, help="Locust <prefix>_stats.csv")
    parser.add_argument("--metrics", help="collect_metrics.py JSON (optional)")
    parser.add_argument("--update", help="baseline markdown file to update in place")
    args = parser.parse_args(argv)

    stats = read_locust_stats(Path(args.stats))
    metrics: dict[str, Any] = {}
    if args.metrics:
        metrics = json.loads(Path(args.metrics).read_text(encoding="utf-8"))
    table = render_table(stats, metrics)

    if not args.update:
        sys.stdout.write(table + "\n")
        return 0
    target = Path(args.update)
    try:
        updated = replace_block(target.read_text(encoding="utf-8"), args.scenario, table)
    except ValueError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 2
    target.write_text(updated, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
