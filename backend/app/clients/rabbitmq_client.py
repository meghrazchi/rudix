import asyncio
import socket
from urllib.parse import urlsplit, urlunsplit

from app.clients.factory import get_rabbitmq_host_port
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("clients.rabbitmq")
_rabbitmq_endpoint: tuple[str, int] | None = None


def _sanitize_url(url: str) -> str:
    parsed = urlsplit(url)
    host = parsed.hostname or ""
    if parsed.port is not None:
        host = f"{host}:{parsed.port}"
    return urlunsplit((parsed.scheme, host, parsed.path, parsed.query, parsed.fragment))


def init_rabbitmq() -> None:
    global _rabbitmq_endpoint
    try:
        _rabbitmq_endpoint = get_rabbitmq_host_port(settings)
        logger.info(
            "rabbitmq.init.success",
            url=_sanitize_url(str(settings.rabbitmq_url)),
            connect_timeout_seconds=settings.rabbitmq_connect_timeout_seconds,
        )
    except Exception as exc:
        logger.error(
            "rabbitmq.init.failed",
            url=_sanitize_url(str(settings.rabbitmq_url)),
            error=exc.__class__.__name__,
            exc_info=exc,
        )
        _rabbitmq_endpoint = None
        raise


def close_rabbitmq() -> None:
    global _rabbitmq_endpoint
    _rabbitmq_endpoint = None


def rabbitmq_broker_url() -> str:
    get_rabbitmq_host_port(settings)
    return str(settings.rabbitmq_url)


def redis_result_backend_url() -> str:
    return str(settings.redis_url)


def _rabbitmq_host_port() -> tuple[str, int]:
    if _rabbitmq_endpoint is not None:
        return _rabbitmq_endpoint
    return get_rabbitmq_host_port(settings)


def _check_rabbitmq_tcp_connection(timeout_seconds: float) -> bool:
    host, port = _rabbitmq_host_port()
    with socket.create_connection((host, port), timeout=timeout_seconds):
        return True


async def check_rabbitmq_health(timeout_seconds: float | None = None) -> bool:
    effective_timeout = timeout_seconds or settings.rabbitmq_connect_timeout_seconds
    try:
        return await asyncio.to_thread(_check_rabbitmq_tcp_connection, effective_timeout)
    except Exception:
        return False
