"""Celery queue declarations (R06-05; C1).

``classic`` (the default) returns the 0.5.0 declarations unchanged: one classic queue per
configured name, bound to the default ``rudix`` direct exchange by Celery.

``quorum`` declares every task queue as a quorum queue with ``x-delivery-limit`` and a
dead-letter exchange, bound to a topic exchange, plus the dead-letter exchange and queue.
Celery 5.7 behaviour this relies on (read from the installed source):

- ``worker_detect_quorum_queues`` (default on) turns global QoS off when any declared queue
  has ``x-queue-type: quorum`` (``celery/worker/consumer/tasks.py::qos_global``); quorum
  queues reject global QoS.
- The ``DelayedDelivery`` consumer bootstep is included when quorum queues are detected and
  declares the ``celery_delayed_*`` exchanges and queues; ``app.send_task`` routes a
  ``countdown``/``eta`` message through them instead of holding it unacknowledged in the
  worker. It skips direct exchanges (warning that ETA tasks then block the worker), so quorum
  mode publishes through ``CELERY_QUORUM_EXCHANGE`` (topic).

A classic queue cannot be redeclared as quorum (``PRECONDITION_FAILED``), and the ``rudix``
direct exchange cannot become a topic exchange, so a cut-over uses new queue names and the
new exchange, then drains the old classic queues (docs/27).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from kombu import Exchange, Queue  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from app.core.config import Settings

CLASSIC_EXCHANGE = "rudix"


def task_queue_names(config: Settings) -> list[str]:
    """Every task queue name in declaration order; a name configured twice appears once."""
    names = [
        config.celery_task_default_queue,
        config.celery_queue_documents_processing,
        config.celery_queue_documents_deletion,
        config.celery_queue_documents_reindex,
        config.celery_queue_evaluations,
        config.celery_queue_connector_sync,
        config.celery_queue_email,
        config.celery_queue_documents_embedding,
        config.celery_queue_documents_graph,
    ]
    # C2 adds CELERY_QUEUE_AGENTS (default ``default``); read it when present.
    agents = getattr(config, "celery_queue_agents", None)
    if isinstance(agents, str) and agents:
        names.append(agents)
    return list(dict.fromkeys(names))


def quorum_queue_arguments(config: Settings) -> dict[str, Any]:
    return {
        "x-queue-type": "quorum",
        "x-delivery-limit": config.celery_delivery_limit,
        "x-dead-letter-exchange": config.celery_dead_letter_exchange,
        "x-dead-letter-routing-key": config.celery_dead_letter_queue,
    }


def dead_letter_exchange(config: Settings) -> Exchange:
    return Exchange(config.celery_dead_letter_exchange, type="direct", durable=True)


def dead_letter_queue(config: Settings) -> Queue:
    """The dead-letter queue: quorum, no delivery limit or dead-lettering of its own."""
    return Queue(
        config.celery_dead_letter_queue,
        exchange=dead_letter_exchange(config),
        routing_key=config.celery_dead_letter_queue,
        durable=True,
        queue_arguments={"x-queue-type": "quorum"},
    )


def build_task_queues(config: Settings) -> tuple[Queue, ...]:
    """``task_queues`` for the configured queue type (dead-letter queue last in quorum)."""
    names = task_queue_names(config)
    if config.celery_queue_type != "quorum":
        return tuple(Queue(name, routing_key=name) for name in names)
    exchange = Exchange(config.celery_quorum_exchange, type="topic", durable=True)
    arguments = quorum_queue_arguments(config)
    queues = [
        Queue(
            name,
            exchange=exchange,
            routing_key=name,
            durable=True,
            queue_arguments=dict(arguments),
        )
        for name in names
    ]
    return (*queues, dead_letter_queue(config))


def queue_conf(config: Settings) -> dict[str, Any]:
    """Celery configuration keys that depend on the queue type.

    Classic returns today's exchange keys only, so the 0.5.0 configuration is unchanged.
    """
    if config.celery_queue_type != "quorum":
        return {
            "task_default_exchange": CLASSIC_EXCHANGE,
            "task_default_exchange_type": "direct",
        }
    return {
        "task_default_exchange": config.celery_quorum_exchange,
        "task_default_exchange_type": "topic",
        "task_default_queue_type": "quorum",
        "task_create_missing_queue_type": "quorum",
        "task_create_missing_queue_exchange_type": "topic",
        "worker_detect_quorum_queues": True,
        "broker_native_delayed_delivery_queue_type": "quorum",
    }


def sampled_queue_names(config: Settings) -> list[str]:
    """Queues whose depth the sampler reports (dead-letter queue in quorum mode)."""
    names = task_queue_names(config)
    if config.celery_queue_type == "quorum":
        names.append(config.celery_dead_letter_queue)
    return names


def current_queue_for_task(task_name: str, stored_queue: str | None, default_queue: str) -> str:
    """The queue a re-dispatch of ``task_name`` should use: its current route when it has one.

    A FailedJob stores the queue of its failed delivery. After a queue rename (the quorum
    cut-over uses new names) that queue is drained and deleted, so a retry follows the current
    route; a task without a route keeps the stored queue.
    """
    from app.workers.celery_app import TASK_ROUTES

    route = TASK_ROUTES.get(task_name)
    if route:
        return route["queue"]
    return stored_queue or default_queue
