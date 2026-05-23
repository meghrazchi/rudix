from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

ResourceToolExecutor = Callable[
    [str, str, dict[str, Any]],
    Awaitable[dict[str, Any]],
]
