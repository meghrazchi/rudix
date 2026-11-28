"""Authenticated Prometheus metrics server for Celery workers (R08-09, contract 5.2.8).

The worker's main process serves ``GET /metrics`` on ``WORKER_METRICS_PORT`` from a daemon
thread (``wsgiref`` with one thread per request). In multiprocess mode
(``PROMETHEUS_MULTIPROC_DIR`` set by ``app/workers/pools.py``) every request aggregates the
files written by the main process and every prefork child through a ``MultiProcessCollector``
on a fresh registry; otherwise it serves the application registry of this process.

With ``METRICS_REQUIRE_AUTH=true`` a request needs ``Authorization: Bearer
<METRICS_BEARER_TOKEN>``, with the same answers as the API route
(``app/interfaces/http/metrics.py``): 401 when the header is missing or not a bearer token,
or when no token is configured; 403 when the token is wrong. Tokens are compared with
``hmac.compare_digest`` and never logged.
"""

from __future__ import annotations

import hmac
import logging
import os
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from socketserver import ThreadingMixIn
from typing import TYPE_CHECKING, Any
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, generate_latest
from prometheus_client import multiprocess as prometheus_multiprocess
from prometheus_client.metrics import MetricWrapperBase
from prometheus_client.metrics_core import Metric
from prometheus_client.registry import Collector

if TYPE_CHECKING:
    from app.core.config import Settings

logger = logging.getLogger("observability.metrics")

MULTIPROC_DIR_ENV = "PROMETHEUS_MULTIPROC_DIR"
METRICS_SCRAPE_PATH = "/metrics"
# Environments where unauthenticated metrics get a startup warning.
_PROTECTED_ENVIRONMENTS = frozenset({"staging", "production"})

StartResponse = Callable[..., Any]
WsgiApp = Callable[[dict[str, Any], StartResponse], Iterable[bytes]]


@dataclass(frozen=True)
class MetricsAuthFailure:
    status_code: int
    detail: str


def check_metrics_authorization(
    authorization: str | None,
    *,
    require_auth: bool,
    expected_token: str | None,
) -> MetricsAuthFailure | None:
    """``None`` when the request may read metrics, else the status and safe detail."""
    if not require_auth:
        return None
    if not expected_token:
        return MetricsAuthFailure(401, "Metrics authentication required but no token is configured")
    if not authorization or not authorization.startswith("Bearer "):
        return MetricsAuthFailure(401, "Missing or invalid Authorization header")
    token = authorization[7:].strip()
    if not hmac.compare_digest(token.encode(), expected_token.encode()):
        return MetricsAuthFailure(403, "Invalid metrics token")
    return None


def multiprocess_dir() -> str | None:
    """The multiprocess directory when this process collects in multiprocess mode."""
    return os.environ.get(MULTIPROC_DIR_ENV) or None


class _ProcessLocalCollectors(Collector):
    """Custom collectors of the application registry (the database pool gauges), which read
    live objects of this process at scrape time and have no multiprocess files."""

    def __init__(self, app_registry: CollectorRegistry) -> None:
        self._app_registry = app_registry

    def _custom(self) -> list[Collector]:
        collectors = list(getattr(self._app_registry, "_collector_to_names", {}))
        return [item for item in collectors if not isinstance(item, MetricWrapperBase)]

    def describe(self) -> Iterable[Metric]:
        return []

    def collect(self) -> Iterable[Metric]:
        for collector in self._custom():
            yield from collector.collect()


def build_scrape_registry(
    app_registry: CollectorRegistry, multiproc_dir: str | None
) -> CollectorRegistry:
    """A fresh registry over the multiprocess files plus the process-local custom
    collectors, or the application registry in single-process mode."""
    if not multiproc_dir:
        return app_registry
    scrape_registry = CollectorRegistry()
    prometheus_multiprocess.MultiProcessCollector(scrape_registry, path=multiproc_dir)
    scrape_registry.register(_ProcessLocalCollectors(app_registry))
    return scrape_registry


def make_metrics_app(
    registry: CollectorRegistry,
    *,
    require_auth: bool,
    expected_token: str | None,
) -> WsgiApp:
    def app(environ: dict[str, Any], start_response: StartResponse) -> Iterable[bytes]:
        if environ.get("PATH_INFO") != METRICS_SCRAPE_PATH:
            return _plain(start_response, "404 Not Found", b"Not found\n")
        if environ.get("REQUEST_METHOD") not in ("GET", "HEAD"):
            return _plain(start_response, "405 Method Not Allowed", b"Method not allowed\n")
        failure = check_metrics_authorization(
            environ.get("HTTP_AUTHORIZATION"),
            require_auth=require_auth,
            expected_token=expected_token,
        )
        if failure is not None:
            status = "401 Unauthorized" if failure.status_code == 401 else "403 Forbidden"
            headers = [("WWW-Authenticate", "Bearer")] if failure.status_code == 401 else []
            return _plain(start_response, status, f"{failure.detail}\n".encode(), headers)
        body = generate_latest(registry)
        start_response(
            "200 OK", [("Content-Type", CONTENT_TYPE_LATEST), ("Content-Length", str(len(body)))]
        )
        return [b""] if environ.get("REQUEST_METHOD") == "HEAD" else [body]

    return app


def _plain(
    start_response: StartResponse,
    status: str,
    body: bytes,
    extra_headers: list[tuple[str, str]] | None = None,
) -> list[bytes]:
    headers = [("Content-Type", "text/plain; charset=utf-8"), ("Content-Length", str(len(body)))]
    start_response(status, headers + (extra_headers or []))
    return [body]


class _ThreadingWSGIServer(ThreadingMixIn, WSGIServer):
    daemon_threads = True
    allow_reuse_address = True


class _QuietHandler(WSGIRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:
        """Scrapes every few seconds would flood the worker log; nothing is logged."""


@dataclass
class MetricsServer:
    server: WSGIServer
    thread: threading.Thread
    multiprocess: bool

    @property
    def port(self) -> int:
        return int(self.server.server_port)

    def shutdown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


def start_metrics_server(
    port: int,
    *,
    config: Settings,
    app_registry: CollectorRegistry,
    addr: str = "0.0.0.0",
) -> MetricsServer:
    """Serve ``/metrics`` on ``addr:port`` (0 picks a free port) from a daemon thread."""
    multiproc_dir = multiprocess_dir() if config.worker_metrics_multiprocess else None
    token = config.metrics_bearer_token.get_secret_value() if config.metrics_bearer_token else None
    app = make_metrics_app(
        build_scrape_registry(app_registry, multiproc_dir),
        require_auth=config.metrics_require_auth,
        expected_token=token,
    )
    server = make_server(
        addr, port, app, server_class=_ThreadingWSGIServer, handler_class=_QuietHandler
    )
    thread = threading.Thread(target=server.serve_forever, name="rudix-worker-metrics", daemon=True)
    thread.start()
    logger.info(
        "worker.metrics_server.started",
        extra={
            "port": server.server_port,
            "multiprocess": multiproc_dir is not None,
            "require_auth": config.metrics_require_auth,
        },
    )
    return MetricsServer(server=server, thread=thread, multiprocess=multiproc_dir is not None)


def warn_if_metrics_auth_disabled(config: Settings, *, runtime: str) -> bool:
    """Log ``metrics.auth_disabled`` when metrics are served without auth in staging or
    production. A warning, not a failure, so existing deployments keep starting."""
    enabled = config.worker_metrics_enabled if runtime == "worker" else config.metrics_enabled
    environment = str(getattr(config.environment, "value", config.environment))
    if not enabled or config.metrics_require_auth or environment not in _PROTECTED_ENVIRONMENTS:
        return False
    logger.warning(
        "metrics.auth_disabled",
        extra={"runtime": runtime, "environment": environment, "setting": "METRICS_REQUIRE_AUTH"},
    )
    return True


def mark_current_process_dead() -> bool:
    """Remove this process's live gauge files in multiprocess mode (worker child exit)."""
    path = multiprocess_dir()
    if path is None:
        return False
    prometheus_multiprocess.mark_process_dead(os.getpid(), path=path)
    return True
