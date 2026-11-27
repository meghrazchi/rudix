"""Run extraction LLM batches with a concurrency bound, results in batch order (R06-10)."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence


async def gather_in_order[ItemT, ResultT](
    items: Sequence[ItemT],
    run: Callable[[ItemT], Awaitable[ResultT]],
    *,
    limit: int,
) -> list[ResultT]:
    """Await ``run(item)`` for every item, at most ``limit`` at a time.

    ``limit <= 1`` runs them one after another (the pre-0.6.0 behaviour). Results are
    returned in the order of ``items`` whatever order the calls finish in.
    """
    if limit <= 1 or len(items) <= 1:
        return [await run(item) for item in items]
    semaphore = asyncio.Semaphore(limit)

    async def _bounded(item: ItemT) -> ResultT:
        async with semaphore:
            return await run(item)

    return list(await asyncio.gather(*(_bounded(item) for item in items)))
