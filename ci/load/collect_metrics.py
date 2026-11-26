#!/usr/bin/env python3
"""Scrape the API's Prometheus ``/metrics`` around a load run and summarise DB usage.

Standard library only. Subcommands:

* ``snapshot URL --out FILE``: save one scrape (Prometheus text format).
* ``run URL --duration S --out metrics.json``: scrape before, sample the pool gauge every
  ``--interval`` seconds for ``--duration`` seconds, scrape after, write the summary.
* ``diff --before B --after A --out metrics.json [--pool-max N]``: summarise two saved
  snapshots offline.

The summary JSON holds ``rudix_db_queries_per_request`` p50/p95/mean/count per
``METHOD route`` (from the histogram delta between the two scrapes) and the maximum
``rudix_db_pool_checked_out`` seen. Set ``RUDIX_LOAD_METRICS_TOKEN`` when the API runs with
``METRICS_REQUIRE_AUTH=true``. Quantiles use Prometheus' ``histogram_quantile`` linear
interpolation, so they are bucket estimates, not exact values.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import time
import urllib.request
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

QUERIES_METRIC = "rudix_db_queries_per_request"
POOL_CHECKED_OUT = "rudix_db_pool_checked_out"
POOL_SIZE = "rudix_db_pool_size"
POOL_OVERFLOW = "rudix_db_pool_overflow"

SampleKey = tuple[str, tuple[tuple[str, str], ...]]
Samples = dict[SampleKey, float]

_SAMPLE_RE = re.compile(
    r"^(?P<name>[a-zA-Z_:][a-zA-Z0-9_:]*)(?:\{(?P<labels>.*)\})?\s+(?P<value>\S+)(?:\s+\S+)?$"
)
_LABEL_RE = re.compile(r'([a-zA-Z_][a-zA-Z0-9_]*)="((?:[^"\\]|\\.)*)"')


def _unescape(value: str) -> str:
    return value.replace(r"\"", '"').replace(r"\n", "\n").replace("\\\\", "\\")


def parse_prometheus_text(text: str) -> Samples:
    """Parse Prometheus text exposition into ``{(name, sorted labels): value}``."""
    samples: Samples = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = _SAMPLE_RE.match(line)
        if match is None:
            continue
        labels = tuple(
            sorted((key, _unescape(val)) for key, val in _LABEL_RE.findall(match["labels"] or ""))
        )
        try:
            value = float(match["value"])
        except ValueError:
            continue
        samples[(match["name"], labels)] = value
    return samples


def diff_samples(before: Samples, after: Samples) -> Samples:
    """``after - before`` for cumulative series (missing in ``before`` counts as 0)."""
    return {key: value - before.get(key, 0.0) for key, value in after.items()}


def histogram_quantile(quantile: float, buckets: Iterable[tuple[float, float]]) -> float | None:
    """Prometheus-style quantile from cumulative ``(upper_bound, count)`` buckets."""
    ordered = sorted(buckets)
    if not ordered or ordered[-1][1] <= 0:
        return None
    total = ordered[-1][1]
    rank = quantile * total
    lower_bound, lower_count = 0.0, 0.0
    for upper_bound, count in ordered:
        if count >= rank:
            if math.isinf(upper_bound):
                # Above the highest finite bucket: report that bucket's bound.
                return lower_bound
            in_bucket = count - lower_count
            if in_bucket <= 0:
                return upper_bound
            return lower_bound + (upper_bound - lower_bound) * (rank - lower_count) / in_bucket
        lower_bound, lower_count = upper_bound, count
    return ordered[-1][0]


def _route_key(labels: dict[str, str]) -> str:
    method = labels.get("method", "")
    route = labels.get("route", "")
    return f"{method} {route}".strip()


def summarise_queries(delta: Samples) -> dict[str, dict[str, float | int | None]]:
    """Per-route p50/p95/mean/count of ``rudix_db_queries_per_request`` from a delta."""
    buckets: dict[str, list[tuple[float, float]]] = {}
    counts: dict[str, float] = {}
    sums: dict[str, float] = {}
    for (name, label_items), value in delta.items():
        labels = dict(label_items)
        if name == f"{QUERIES_METRIC}_bucket":
            le = labels.pop("le", "+Inf")
            bound = math.inf if le in {"+Inf", "Inf"} else float(le)
            buckets.setdefault(_route_key(labels), []).append((bound, value))
        elif name == f"{QUERIES_METRIC}_count":
            counts[_route_key(labels)] = value
        elif name == f"{QUERIES_METRIC}_sum":
            sums[_route_key(labels)] = value
    summary: dict[str, dict[str, float | int | None]] = {}
    for route in sorted(buckets):
        count = counts.get(route, 0.0)
        if count <= 0:
            continue
        summary[route] = {
            "count": int(count),
            "mean": round(sums.get(route, 0.0) / count, 3),
            "p50": _round(histogram_quantile(0.5, buckets[route])),
            "p95": _round(histogram_quantile(0.95, buckets[route])),
        }
    return summary


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 3)


def gauge_value(samples: Samples, name: str) -> float | None:
    values = [value for (sample_name, _), value in samples.items() if sample_name == name]
    return max(values) if values else None


def build_summary(
    before: Samples, after: Samples, pool_checked_out_samples: Iterable[float] = ()
) -> dict[str, Any]:
    observed = [v for v in pool_checked_out_samples]
    for snapshot in (before, after):
        value = gauge_value(snapshot, POOL_CHECKED_OUT)
        if value is not None:
            observed.append(value)
    return {
        "queries_per_request": summarise_queries(diff_samples(before, after)),
        "pool": {
            "max_checked_out": max(observed) if observed else None,
            "size": gauge_value(after, POOL_SIZE),
            "overflow_after": gauge_value(after, POOL_OVERFLOW),
            "samples": len(observed),
        },
    }


def scrape(url: str, token: str | None = None, timeout: float = 10.0) -> str:
    request = urllib.request.Request(url, headers={"Accept": "text/plain"})
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return str(response.read().decode("utf-8"))


def sample_pool(
    fetch: Callable[[], str],
    *,
    duration: float,
    interval: float,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> list[float]:
    """Poll ``rudix_db_pool_checked_out`` until ``duration`` elapses; skip failed scrapes."""
    values: list[float] = []
    deadline = clock() + duration
    while clock() < deadline:
        try:
            value = gauge_value(parse_prometheus_text(fetch()), POOL_CHECKED_OUT)
        except OSError:
            value = None
        if value is not None:
            values.append(value)
        sleep(interval)
    return values


def _write_json(path: str, payload: dict[str, Any]) -> None:
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if path == "-":
        sys.stdout.write(text)
    else:
        Path(path).write_text(text, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    snap = sub.add_parser("snapshot", help="save one /metrics scrape")
    snap.add_argument("url")
    snap.add_argument("--out", required=True)

    run = sub.add_parser("run", help="scrape before, sample during, scrape after")
    run.add_argument("url")
    run.add_argument("--duration", type=float, required=True, help="seconds to sample")
    run.add_argument("--interval", type=float, default=2.0)
    run.add_argument("--out", default="-")

    dif = sub.add_parser("diff", help="summarise two saved snapshots")
    dif.add_argument("--before", required=True)
    dif.add_argument("--after", required=True)
    dif.add_argument("--pool-max", type=float, default=None, help="max checked_out seen")
    dif.add_argument("--out", default="-")

    args = parser.parse_args(argv)
    token = os.environ.get("RUDIX_LOAD_METRICS_TOKEN") or None

    if args.command == "snapshot":
        Path(args.out).write_text(scrape(args.url, token), encoding="utf-8")
        return 0
    if args.command == "run":
        before = parse_prometheus_text(scrape(args.url, token))
        pool = sample_pool(
            lambda: scrape(args.url, token), duration=args.duration, interval=args.interval
        )
        after = parse_prometheus_text(scrape(args.url, token))
        _write_json(args.out, build_summary(before, after, pool))
        return 0
    before = parse_prometheus_text(Path(args.before).read_text(encoding="utf-8"))
    after = parse_prometheus_text(Path(args.after).read_text(encoding="utf-8"))
    extra = [args.pool_max] if args.pool_max is not None else []
    _write_json(args.out, build_summary(before, after, extra))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
