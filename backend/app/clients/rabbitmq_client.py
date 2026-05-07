import asyncio
import socket
from urllib.parse import urlsplit

from app.core.config import settings


def _rabbitmq_host_port() -> tuple[str, int]:
    parsed = urlsplit(str(settings.rabbitmq_url))
    host = parsed.hostname
    if host is None:
        raise ValueError("rabbitmq_url is missing host")
    port = parsed.port
    if port is None:
        port = 5671 if parsed.scheme == "amqps" else 5672
    return host, port


def _check_rabbitmq_tcp_connection(timeout_seconds: float) -> bool:
    host, port = _rabbitmq_host_port()
    with socket.create_connection((host, port), timeout=timeout_seconds):
        return True


async def check_rabbitmq_health(timeout_seconds: float = 2.0) -> bool:
    try:
        return await asyncio.to_thread(_check_rabbitmq_tcp_connection, timeout_seconds)
    except Exception:
        return False
