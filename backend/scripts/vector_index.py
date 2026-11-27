#!/usr/bin/env python3
"""Operate vector index generations behind QDRANT_COLLECTION_ALIAS (R06-08).

Operator commands; they act across organisations, so run them with
``DATABASE_MAINTENANCE_URL`` set to the BYPASSRLS role (docs/27 "Reindex and alias swap").

    adopt [--embedding-model M]   register QDRANT_COLLECTION as generation 1, create the alias
    plan                          show what a build for the configured model would create
    build [--enqueue] [--max-pages N] [--generation N]
                                  register a building generation for the configured model
                                  (if none) and fill it; verifies when the walk completes
    status                        list generations and where the alias points
    swap [--yes]                  point the alias at the verified generation (one call)
    rollback [--yes]              point the alias back at the newest retired generation
    drop-retired [--yes]          delete collections of retired generations past the grace

swap, rollback and drop-retired are dry runs unless ``--yes`` is given.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
from typing import Any, TextIO

from app.core.config import settings
from app.domains.vector_index.repositories import generations as repo
from app.domains.vector_index.services import lifecycle_service, qdrant_ops
from app.domains.vector_index.services.generation_service import generation_collection_name
from app.domains.vector_index.services.lifecycle_service import VectorIndexLifecycleError

COMMANDS = ("adopt", "plan", "build", "status", "swap", "rollback", "drop-retired")


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("command", choices=COMMANDS)
    parser.add_argument("--yes", action="store_true", help="act (swap, rollback, drop-retired)")
    parser.add_argument("--embedding-model", default=None, help="adopt: model of the collection")
    parser.add_argument("--generation", type=int, default=None)
    parser.add_argument("--max-pages", type=int, default=None)
    parser.add_argument("--enqueue", action="store_true", help="build: run as a Celery task")
    args = parser.parse_args(argv)
    if args.max_pages is not None and args.max_pages < 1:
        parser.error("--max-pages must be at least 1")
    return args


def _print(out: TextIO, payload: Any) -> None:
    print(json.dumps(payload, default=str, sort_keys=True), file=out, flush=True)


async def _status(out: TextIO) -> None:
    alias = lifecycle_service.require_alias()
    rows = await lifecycle_service.list_rows(alias)
    _print(
        out,
        {
            "alias": alias,
            "alias_target": await qdrant_ops.alias_target(alias),
            "generations": [lifecycle_service.describe(row) for row in rows],
        },
    )


async def _plan(out: TextIO) -> None:
    alias = lifecycle_service.require_alias()
    rows = await lifecycle_service.list_rows(alias)
    active = repo.pick(rows, ("active",))
    building = repo.pick(rows, repo.BUILDING_STATES)
    number = max((row.generation for row in rows), default=0) + 1
    model = settings.openai_embedding_model.strip()
    _print(
        out,
        {
            "alias": alias,
            "active": lifecycle_service.describe(active) if active else None,
            "building": lifecycle_service.describe(building) if building else None,
            "would_create": None
            if building is not None or active is None
            else {
                "generation": number,
                "collection": generation_collection_name(model, number),
                "embedding_model": model,
                "vector_size": settings.qdrant_vector_size,
            },
        },
    )


async def _build(args: argparse.Namespace, out: TextIO) -> None:
    if args.generation is None:
        row = await lifecycle_service.register_building(reason="operator")
        generation = row.generation
    else:
        generation = args.generation
    from app.workers import vector_index_tasks

    if args.enqueue:
        vector_index_tasks.build_vector_index.apply_async(
            kwargs={"generation": generation, "max_pages": args.max_pages}
        )
        _print(out, {"enqueued": True, "generation": generation})
        return
    progress = await vector_index_tasks.run_build(generation=generation, max_pages=args.max_pages)
    _print(out, progress.as_dict())


async def run(argv: Sequence[str] | None = None, *, out: TextIO = sys.stdout) -> int:
    args = _parse_args(argv)
    try:
        if args.command == "adopt":
            row = await lifecycle_service.adopt(embedding_model=args.embedding_model)
            _print(out, lifecycle_service.describe(row))
        elif args.command == "plan":
            await _plan(out)
        elif args.command == "build":
            await _build(args, out)
        elif args.command == "status":
            await _status(out)
        elif args.command in ("swap", "rollback"):
            action = (
                lifecycle_service.swap if args.command == "swap" else lifecycle_service.rollback
            )
            plan = await action(dry_run=not args.yes)
            _print(out, {**plan.__dict__, "mode": "APPLY" if args.yes else "DRY RUN"})
        else:
            dropped = await lifecycle_service.drop_retired(dry_run=not args.yes)
            _print(out, {"generations": dropped, "mode": "APPLY" if args.yes else "DRY RUN"})
    except VectorIndexLifecycleError as exc:
        _print(out, {"error": exc.code, "message": str(exc)})
        return 2
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    return asyncio.run(run(argv))


if __name__ == "__main__":
    raise SystemExit(main())
