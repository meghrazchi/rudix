"""Report and purge evaluation (eval-) index versions from PostgreSQL and Qdrant.

Dry run is the default: it prints counts per organization and index version and
deletes nothing. Pass --apply to delete eligible eval- chunk rows and vectors.
Versions belonging to queued or running evaluation runs are always skipped.

With QDRANT_EVALUATION_COLLECTION set (R06-12) the evaluation collection is scanned and
purged as well as QDRANT_COLLECTION.

Non-eval versions outside DOCUMENT_INDEX_VERSION + DOCUMENT_ACTIVE_INDEX_VERSIONS
are reported as "inactive: hidden from retrieval" and are never deleted. When any
are found the script exits with code 2, so it can gate a deploy.

Usage:
    python scripts/purge_eval_index_versions.py [--apply]
        [--organization-id <uuid>] [--batch-size 256]
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence
from uuid import UUID

from app.clients.factory import create_qdrant_client
from app.core.config import settings
from app.db.session import SessionLocal
from app.domains.evaluations.services.eval_index_purge_service import (
    EvalIndexPurgeService,
    PurgeReport,
)

_LABELS = {
    "active": "active",
    "inactive": "inactive: hidden from retrieval",
    "eval": "eval: eligible for purge",
    "eval_in_progress": "eval: run in progress, skipped",
}


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--apply", action="store_true", help="delete eligible eval versions")
    parser.add_argument("--organization-id", type=UUID, default=None)
    parser.add_argument("--batch-size", type=int, default=256)
    args = parser.parse_args(argv)
    if args.batch_size < 1:
        parser.error("--batch-size must be at least 1")
    return args


def format_report(report: PurgeReport) -> list[str]:
    mode = "APPLY" if report.applied else "DRY RUN"
    lines = [f"mode={mode} active_versions={','.join(settings.active_index_versions)}"]
    for item in report.versions:
        lines.append(
            f"org={item.organization_id} version={item.index_version} "
            f"chunks={item.chunk_count} points={item.point_count} "
            f"chunks_deleted={item.chunks_deleted} points_deleted={item.points_deleted} "
            f"[{_LABELS[item.classification]}]"
        )
    lines.append(
        f"total chunks_deleted={report.chunks_deleted} points_deleted={report.points_deleted} "
        f"points_without_version={report.points_without_version} "
        f"inactive_versions={len(report.inactive_versions)}"
    )
    return lines


async def run(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    service = EvalIndexPurgeService(
        qdrant_client=create_qdrant_client(settings),
        collection=settings.qdrant_collection,
        batch_size=args.batch_size,
        evaluation_collection=settings.qdrant_evaluation_collection,
    )
    async with SessionLocal() as session:
        report = await service.run(session, apply=args.apply, organization_id=args.organization_id)
    for line in format_report(report):
        print(line)
    return report.exit_code


def main(argv: Sequence[str] | None = None) -> int:
    return asyncio.run(run(argv))


if __name__ == "__main__":
    sys.exit(main())
