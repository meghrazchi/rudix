"""Non-blocking Celery task dispatch for request paths (R04-11)."""

from __future__ import annotations

import asyncio
from typing import Any


async def enqueue(task: Any, *args: Any, **kwargs: Any) -> Any:
    """Run ``task.delay`` in a worker thread so broker I/O never blocks the loop.

    Exceptions raised by the broker client propagate unchanged to the caller.
    Returns the ``AsyncResult``.
    """
    return await asyncio.to_thread(task.delay, *args, **kwargs)
