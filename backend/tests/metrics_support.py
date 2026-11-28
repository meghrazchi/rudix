"""Shared helpers for the multiprocess metrics tests (R08-09).

``run_child`` simulates one prefork worker process: a fresh interpreter with
``PROMETHEUS_MULTIPROC_DIR`` set imports every metric module and touches every metric once
(counter +1, gauge set to ``value``, histogram observes ``value``), then prints its pid.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]


def _discover_metric_modules() -> tuple[str, ...]:
    """Every app module that builds a metric with prometheus_client and names a rudix_*
    series (a new metric module is covered without editing this list)."""
    modules: list[str] = []
    for path in sorted((BACKEND_DIR / "app").rglob("*.py")):
        source = path.read_text()
        if "from prometheus_client import" in source and '"rudix_' in source:
            relative = path.relative_to(BACKEND_DIR).with_suffix("")
            modules.append(".".join(relative.parts))
    return tuple(modules)


METRIC_MODULES = _discover_metric_modules()
BASE_ENV = {
    "ENVIRONMENT": "test",
    "API_BASE_URL": "http://localhost:8000",
    "FRONTEND_BASE_URL": "http://localhost:3000",
    "DATABASE_URL": "postgresql+asyncpg://postgres:postgres@localhost:5432/rag_app",
    "QDRANT_URL": "http://localhost:6333",
    "QDRANT_COLLECTION": "documents",
    "MINIO_ENDPOINT": "http://localhost:9000",
    "MINIO_ACCESS_KEY": "minioadmin",
    "MINIO_SECRET_KEY": "minioadmin",
    "MINIO_BUCKET": "documents",
    "RABBITMQ_URL": "amqp://admin:admin123@localhost:5672//",
    "REDIS_URL": "redis://localhost:6379/0",
    "OPENAI_API_KEY": "sk-test",
    "AUTH_PROVIDER": "app",
    "APP_AUTH_SECRET": "test-secret",
}

_CHILD = """
import importlib, json, os, sys
from prometheus_client.metrics import Counter, Gauge, Histogram, MetricWrapperBase
modules, value = json.loads(sys.argv[1]), float(sys.argv[2])
for module in modules:
    importlib.import_module(module)
from app.core.metrics import registry
for collector in list(registry._collector_to_names):
    if not isinstance(collector, MetricWrapperBase):
        continue
    names = collector._labelnames
    metric = collector.labels(*["v"] * len(names)) if names else collector
    if isinstance(collector, Counter):
        metric.inc()
    elif isinstance(collector, Gauge):
        metric.set(value)
    elif isinstance(collector, Histogram):
        metric.observe(value)
    else:
        raise SystemExit("unsupported metric type " + type(collector).__name__)
print(os.getpid())
"""


def ensure_env() -> None:
    """Settings need these variables; existing values win."""
    for key, value in BASE_ENV.items():
        os.environ.setdefault(key, value)


def run_child(directory: Path, value: float) -> int:
    env = {**BASE_ENV, **os.environ, "PROMETHEUS_MULTIPROC_DIR": str(directory)}
    result = subprocess.run(
        [sys.executable, "-c", _CHILD, json.dumps(list(METRIC_MODULES)), str(value)],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    return int(result.stdout.strip().splitlines()[-1])
