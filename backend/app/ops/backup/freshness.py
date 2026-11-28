"""Backup freshness: marker age per kind, the freshness gauge, and its counter (R08-06).

``check_freshness`` reads ``<prefix>/<kind>/latest.json`` for every configured kind
(``BACKUP_KINDS``) and classifies it as ``fresh``, ``stale`` (older than
``BACKUP_MAX_AGE_HOURS``), ``missing``, or ``invalid``. ``record_freshness`` sets
``rudix_backup_last_success_timestamp_seconds{kind}`` (declared in ``metrics_infra``) for
every kind with a readable marker and counts one check in
``rudix_backup_freshness_checks_total{outcome}``. Alerts: ``infra/observability/prometheus/
rules/backups.yml``.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final, Literal

from prometheus_client import Counter

from app.core.logging import get_logger
from app.core.metrics import is_metrics_enabled, registry
from app.core.metrics_infra import set_backup_last_success_timestamp
from app.ops.backup.markers import MarkerError
from app.ops.backup.store import BackupStore

logger = get_logger("ops.backup.freshness")

KindStatus = Literal["fresh", "stale", "missing", "invalid"]
CheckOutcome = Literal["fresh", "stale", "missing", "error"]
CHECK_OUTCOMES: Final[tuple[str, ...]] = ("fresh", "stale", "missing", "error")

# outcome: fresh (every kind fresh), stale (one or more stale), missing (one or more kinds
# without a readable marker), error (the bucket could not be read). Fixed values only.
BACKUP_FRESHNESS_CHECKS_TOTAL = Counter(
    "rudix_backup_freshness_checks_total",
    "Backup freshness checks by outcome (worst kind wins)",
    ["outcome"],
    registry=registry,
)


@dataclass(frozen=True, slots=True)
class KindFreshness:
    kind: str
    status: KindStatus
    completed_at: datetime | None = None
    age_seconds: float | None = None

    def describe(self) -> str:
        """``kind status age`` for CLI output: no key, path, or bucket name."""
        if self.age_seconds is None:
            return f"{self.kind} {self.status}"
        return f"{self.kind} {self.status} age_hours={self.age_seconds / 3600:.2f}"


def check_freshness(
    store: BackupStore,
    kinds: Sequence[str],
    *,
    max_age_hours: int,
    now: datetime | None = None,
) -> list[KindFreshness]:
    """Freshness of each kind. Bucket errors other than a missing marker propagate."""
    moment = now or datetime.now(UTC)
    limit = max_age_hours * 3600
    results: list[KindFreshness] = []
    for kind in kinds:
        try:
            marker = store.read_marker(kind)
        except MarkerError:
            logger.warning("backup.freshness.marker_invalid", kind=kind)
            results.append(KindFreshness(kind=kind, status="invalid"))
            continue
        if marker is None:
            results.append(KindFreshness(kind=kind, status="missing"))
            continue
        age = max(0.0, (moment - marker.completed_at).total_seconds())
        status: KindStatus = "fresh" if age <= limit else "stale"
        results.append(
            KindFreshness(
                kind=kind, status=status, completed_at=marker.completed_at, age_seconds=age
            )
        )
    return results


def overall_outcome(results: Iterable[KindFreshness]) -> CheckOutcome:
    statuses = {result.status for result in results}
    if statuses & {"missing", "invalid"}:
        return "missing"
    if "stale" in statuses:
        return "stale"
    return "fresh"


def count_check(outcome: CheckOutcome) -> None:
    if is_metrics_enabled():
        BACKUP_FRESHNESS_CHECKS_TOTAL.labels(outcome=outcome).inc()


def record_freshness(results: Sequence[KindFreshness]) -> CheckOutcome:
    """Export the marker times and count the check; returns the overall outcome."""
    for result in results:
        if result.completed_at is not None:
            set_backup_last_success_timestamp(result.kind, result.completed_at.timestamp())
    outcome = overall_outcome(results)
    count_check(outcome)
    return outcome
