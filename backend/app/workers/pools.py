"""Worker pools per queue (R06-04; C1).

``python -m app.workers.pools <name>`` replaces itself (``execvpe``) with::

    celery -A app.workers.celery_app:celery_app worker -Q <queues> --concurrency <n>
        --pool <pool> -n <name>@%h [--max-tasks-per-child <n>] --loglevel=INFO

so compose files need no knowledge of queue names: they come from settings. Pools:

=========  =================================================  ==========================
Pool       Queues (defaults from CELERY_QUEUE_*)              Load
=========  =================================================  ==========================
ingest     documents.processing, .deletion, .reindex          CPU-bound (OCR, parsing)
graph      documents.graph                                    I/O-bound (LLM, Neo4j)
sync       connectors.sync                                    I/O-bound (provider APIs)
eval       evaluations                                        mixed, isolated
default    default, email, agents (C2), dead-letter consumer  light, I/O-bound
=========  =================================================  ==========================

The ``threads`` pool is accepted only with concurrency 1: ``run_async`` drives one event
loop per process (``app/workers/async_runtime.py``), which two threads cannot share, and
Celery enforces time limits only in the prefork pool. Size I/O-bound pools with more prefork
processes instead (docs/10).

Metrics (R08-09): with ``WORKER_METRICS_ENABLED`` and ``WORKER_METRICS_MULTIPROCESS`` (default
true) the pool exports the counters of every prefork child. Before ``execvpe`` (so before the
worker imports ``prometheus_client``) this module points ``PROMETHEUS_MULTIPROC_DIR`` at a
directory (default ``/tmp/rudix-prometheus``; a value already in the environment wins),
removes stale ``*.db`` files left by an earlier run, and creates it. The worker metrics server
(``app/core/metrics_server.py``) aggregates the files. The development command
``celery -A app.workers.celery_app:celery_app worker`` does not go through this module and
stays single-process: only the main process's metrics are exported there.
"""

from __future__ import annotations

import glob
import os
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.core.settings.worker_platform import parse_queue_list

if TYPE_CHECKING:
    from app.core.config import Settings

CELERY_APP = "app.workers.celery_app:celery_app"
POOL_NAMES = ("ingest", "graph", "sync", "eval", "default")
# Main-process bootsteps that run only in the default pool.
_DEFAULT_POOL_ENV = {"WORKER_CONSUME_DEAD_LETTER": "true", "WORKER_SAMPLE_QUEUE_DEPTH": "true"}
_OTHER_POOL_ENV = {"WORKER_CONSUME_DEAD_LETTER": "false", "WORKER_SAMPLE_QUEUE_DEPTH": "false"}
MULTIPROC_DIR_ENV = "PROMETHEUS_MULTIPROC_DIR"
# Per container: the chart mounts an emptyDir at /tmp, Compose containers have their own /tmp.
DEFAULT_MULTIPROC_DIR = "/tmp/rudix-prometheus"


class PoolConfigError(ValueError):
    """The pool name or its settings cannot start a worker."""


@dataclass(frozen=True)
class PoolSpec:
    name: str
    queues: tuple[str, ...]
    concurrency: int
    pool: str
    max_tasks_per_child: int | None


def default_pool_queues(config: Settings) -> dict[str, list[str]]:
    """Queues per pool derived from the CELERY_QUEUE_* settings."""
    default = [config.celery_task_default_queue, config.celery_queue_email]
    agents = getattr(config, "celery_queue_agents", None)  # C2
    if isinstance(agents, str) and agents:
        default.append(agents)
    return {
        "ingest": [
            config.celery_queue_documents_processing,
            config.celery_queue_documents_embedding,
            config.celery_queue_documents_deletion,
            config.celery_queue_documents_reindex,
        ],
        "graph": [config.celery_queue_documents_graph],
        "sync": [config.celery_queue_connector_sync],
        "eval": [config.celery_queue_evaluations],
        "default": default,
    }


def pool_spec(name: str, config: Settings) -> PoolSpec:
    if name not in POOL_NAMES:
        raise PoolConfigError(f"unknown worker pool {name!r}; expected one of {POOL_NAMES}")
    configured = parse_queue_list(getattr(config, f"worker_pool_{name}_queues"))
    queues = configured or list(dict.fromkeys(default_pool_queues(config)[name]))
    concurrency = int(getattr(config, f"worker_pool_{name}_concurrency"))
    pool = str(getattr(config, f"worker_pool_{name}_pool"))
    if pool == "threads" and concurrency > 1:
        raise PoolConfigError(
            f"WORKER_POOL_{name.upper()}_POOL=threads needs concurrency 1: worker tasks share "
            "one event loop per process; use prefork with more processes"
        )
    override = getattr(config, f"worker_pool_{name}_max_tasks_per_child")
    max_tasks = config.celery_worker_max_tasks_per_child if override is None else int(override)
    return PoolSpec(
        name=name,
        queues=tuple(queues),
        concurrency=concurrency,
        pool=pool,
        max_tasks_per_child=max_tasks or None,
    )


def build_worker_argv(spec: PoolSpec, loglevel: str = "INFO") -> list[str]:
    """The ``celery worker`` argv for one pool (pure; unit-tested)."""
    argv = [
        "celery",
        "-A",
        CELERY_APP,
        "worker",
        "-Q",
        ",".join(spec.queues),
        "--concurrency",
        str(spec.concurrency),
        "--pool",
        spec.pool,
        "-n",
        f"{spec.name}@%h",
        f"--loglevel={loglevel}",
    ]
    if spec.max_tasks_per_child:
        argv.extend(["--max-tasks-per-child", str(spec.max_tasks_per_child)])
    return argv


def build_worker_env(
    name: str, environ: Mapping[str, str], multiproc_dir: str | None = None
) -> dict[str, str]:
    """Environment for the pool: only the default pool runs the dead-letter consumer and the
    queue depth sampler, unless the environment sets the flags explicitly.

    With ``multiproc_dir`` the worker collects metrics in multiprocess mode from that
    directory; without it the variable is removed so the worker stays single-process.
    """
    env = dict(environ)
    for key, value in (_DEFAULT_POOL_ENV if name == "default" else _OTHER_POOL_ENV).items():
        env.setdefault(key, value)
    if multiproc_dir:
        env[MULTIPROC_DIR_ENV] = multiproc_dir
    else:
        env.pop(MULTIPROC_DIR_ENV, None)
    return env


def multiprocess_metrics_enabled(config: Settings) -> bool:
    """Multiprocess collection applies only when the worker metrics server runs."""
    return bool(config.worker_metrics_enabled and config.worker_metrics_multiprocess)


def prepare_multiprocess_dir(environ: Mapping[str, str]) -> str:
    """Create the metrics directory and remove stale ``*.db`` files of an earlier run.

    Files from a previous start belong to dead processes; left in place they would add old
    counter values to the new worker's export.
    """
    path = environ.get(MULTIPROC_DIR_ENV) or DEFAULT_MULTIPROC_DIR
    os.makedirs(path, exist_ok=True)
    for stale in glob.glob(os.path.join(path, "*.db")):
        os.remove(stale)
    return path


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print(f"usage: python -m app.workers.pools <{'|'.join(POOL_NAMES)}>", file=sys.stderr)
        return 2
    from app.core.config import settings

    try:
        spec = pool_spec(args[0], settings)
    except PoolConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    command = build_worker_argv(spec, loglevel=os.environ.get("WORKER_LOG_LEVEL", "INFO"))
    # ``python -m celery`` from this interpreter: works without the venv on PATH.
    multiproc_dir = (
        prepare_multiprocess_dir(os.environ) if multiprocess_metrics_enabled(settings) else None
    )
    env = build_worker_env(spec.name, os.environ, multiproc_dir)
    executable = sys.executable
    os.execvpe(executable, [executable, "-m", *command], env)
    return 0  # pragma: no cover - execvpe does not return


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
