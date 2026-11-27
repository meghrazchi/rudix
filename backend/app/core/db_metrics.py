"""Database pool and per-request query metrics (R03-09).

Two signals feed the load-test baseline:

* ``rudix_db_queries_per_request``: a histogram of SQL statements executed while one HTTP
  request was being handled, labelled by method and route template. The HTTP metrics
  middleware opens a :class:`RequestQueryCounter` per request and stores it in a
  ``ContextVar``. The counter is a mutable object, so tasks spawned with
  ``asyncio.gather``/``create_task`` inherit the same instance and their statements are
  counted too. A ``before_cursor_execute`` listener on the engine increments it; statements
  outside a request (Celery tasks, startup, WebSockets) see no counter and are ignored.
* ``rudix_db_pool_checked_out``, ``rudix_db_pool_size``, ``rudix_db_pool_overflow``: read
  from ``engine.pool`` at scrape time by a custom collector. Pools without these methods
  (``NullPool``, ``StaticPool``) produce no samples instead of raising.
* ``rudix_db_pool_wait_seconds`` and ``rudix_db_pool_timeouts_total`` (R04-01): the engine
  uses :class:`TimedAsyncAdaptedQueuePool`, which times every checkout from the pool queue
  and counts ``TimeoutError`` (pool exhausted for ``DB_POOL_TIMEOUT`` seconds).

Statements carrying the session-context marker (``/* rudix:session-context */``, R04-08) are
not counted as queries.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any

from prometheus_client import CollectorRegistry, Counter, Histogram
from prometheus_client.core import GaugeMetricFamily, Metric
from prometheus_client.registry import Collector
from sqlalchemy import event, exc
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.pool import AsyncAdaptedQueuePool, ConnectionPoolEntry

from app.core.config import settings
from app.core.metrics import registry
from app.db.tenant_context import SESSION_CONTEXT_MARKER

QUERIES_PER_REQUEST_BUCKETS: tuple[float, ...] = (1, 2, 5, 10, 20, 50, 100, 200)

DB_QUERIES_PER_REQUEST = Histogram(
    "rudix_db_queries_per_request",
    "SQL statements executed while handling one HTTP request, by route template",
    ["method", "route"],
    buckets=QUERIES_PER_REQUEST_BUCKETS,
    registry=registry,
)


POOL_WAIT_BUCKETS: tuple[float, ...] = (
    0.0005,
    0.001,
    0.005,
    0.01,
    0.025,
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.5,
    5.0,
    10.0,
    30.0,
)

DB_POOL_WAIT_SECONDS = Histogram(
    "rudix_db_pool_wait_seconds",
    "Time spent waiting to check a connection out of the database pool",
    buckets=POOL_WAIT_BUCKETS,
    registry=registry,
)

DB_POOL_TIMEOUTS_TOTAL = Counter(
    "rudix_db_pool_timeouts_total",
    "Pool checkouts that failed because no connection became free within DB_POOL_TIMEOUT",
    registry=registry,
)


class TimedAsyncAdaptedQueuePool(AsyncAdaptedQueuePool):
    """Async queue pool that records checkout wait time and pool timeouts."""

    def _do_get(self) -> ConnectionPoolEntry:
        started = perf_counter()
        try:
            entry = super()._do_get()
        except exc.TimeoutError as error:
            # ``QueuePool._do_get`` can recurse; count each timeout once.
            if not getattr(error, "_rudix_pool_timeout_counted", False):
                error._rudix_pool_timeout_counted = True  # type: ignore[attr-defined]
                DB_POOL_TIMEOUTS_TOTAL.inc()
                DB_POOL_WAIT_SECONDS.observe(perf_counter() - started)
            raise
        DB_POOL_WAIT_SECONDS.observe(perf_counter() - started)
        return entry


@dataclass
class RequestQueryCounter:
    """Mutable per-request statement counter shared by every task of the request."""

    count: int = 0


@dataclass
class RequestQueryScope:
    """Handle returned by :func:`begin_request_query_count`."""

    counter: RequestQueryCounter
    token: Token[RequestQueryCounter | None] = field(repr=False)


_current_counter: ContextVar[RequestQueryCounter | None] = ContextVar(
    "rudix_db_request_query_counter", default=None
)


def current_query_counter() -> RequestQueryCounter | None:
    return _current_counter.get()


def is_query_counting_enabled() -> bool:
    return bool(settings.metrics_enabled and settings.metrics_db_query_counting_enabled)


def begin_request_query_count() -> RequestQueryScope | None:
    """Start counting statements for the current request; ``None`` when disabled."""
    if not is_query_counting_enabled():
        return None
    counter = RequestQueryCounter()
    token = _current_counter.set(counter)
    return RequestQueryScope(counter=counter, token=token)


def end_request_query_count(scope: RequestQueryScope | None, method: str, route: str) -> None:
    """Observe the request's statement count and clear the context variable."""
    if scope is None:
        return
    try:
        _current_counter.reset(scope.token)
    except ValueError:
        # The token was created in another context (should not happen); clear instead.
        _current_counter.set(None)
    DB_QUERIES_PER_REQUEST.labels(method=method, route=route).observe(scope.counter.count)


def _count_statement(
    _conn: Any = None,
    _cursor: Any = None,
    statement: Any = None,
    *_args: Any,
    **_kwargs: Any,
) -> None:
    counter = _current_counter.get()
    if counter is None:
        return
    if isinstance(statement, str) and SESSION_CONTEXT_MARKER in statement:
        return
    counter.count += 1


def _as_sync_engine(engine: AsyncEngine | Engine) -> Engine:
    return engine.sync_engine if isinstance(engine, AsyncEngine) else engine


def install_query_counter(engine: AsyncEngine | Engine) -> None:
    """Attach the statement-counting listener to ``engine`` (idempotent)."""
    sync_engine = _as_sync_engine(engine)
    if not event.contains(sync_engine, "before_cursor_execute", _count_statement):
        event.listen(sync_engine, "before_cursor_execute", _count_statement)


def remove_query_counter(engine: AsyncEngine | Engine) -> None:
    sync_engine = _as_sync_engine(engine)
    if event.contains(sync_engine, "before_cursor_execute", _count_statement):
        event.remove(sync_engine, "before_cursor_execute", _count_statement)


_POOL_GAUGES: tuple[tuple[str, str, str], ...] = (
    ("rudix_db_pool_checked_out", "Connections currently checked out of the pool", "checkedout"),
    ("rudix_db_pool_size", "Configured pool size (persistent connections)", "size"),
    ("rudix_db_pool_overflow", "Current pool overflow (negative while below size)", "overflow"),
)


class DbPoolCollector(Collector):
    """Reads pool gauges at scrape time from whatever pool ``pool_getter`` returns."""

    def __init__(self, pool_getter: Callable[[], Any]) -> None:
        self._pool_getter = pool_getter

    def describe(self) -> Iterable[Metric]:
        return [GaugeMetricFamily(name, doc) for name, doc, _ in _POOL_GAUGES]

    def collect(self) -> Iterator[Metric]:
        try:
            pool = self._pool_getter()
        except Exception:
            pool = None
        for name, doc, method_name in _POOL_GAUGES:
            family = GaugeMetricFamily(name, doc)
            reader = getattr(pool, method_name, None)
            if callable(reader):
                try:
                    family.add_metric([], float(reader()))
                except Exception:
                    pass
            yield family


_pool_collector: DbPoolCollector | None = None


def install_pool_collector(
    engine: AsyncEngine | Engine, target_registry: CollectorRegistry | None = None
) -> DbPoolCollector:
    """Register one pool collector for ``engine``; later calls retarget the same collector."""
    global _pool_collector
    sync_engine = _as_sync_engine(engine)

    def _getter() -> Any:
        return sync_engine.pool

    if _pool_collector is None:
        _pool_collector = DbPoolCollector(_getter)
        (target_registry or registry).register(_pool_collector)
    else:
        _pool_collector._pool_getter = _getter
    return _pool_collector


def install_db_metrics(engine: AsyncEngine | Engine) -> None:
    """Wire both the statement counter and the pool collector for ``engine``."""
    install_query_counter(engine)
    install_pool_collector(engine)
