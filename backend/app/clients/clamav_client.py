from __future__ import annotations

import socket
import struct
from dataclasses import dataclass

from app.core.config import settings
from app.core.logging import get_logger


class ClamAVClientError(RuntimeError):
    """Base class for ClamAV client failures with safe, non-sensitive messaging."""


class ClamAVUnavailableError(ClamAVClientError):
    """Raised when the ClamAV daemon cannot be reached."""


class ClamAVProtocolError(ClamAVClientError):
    """Raised when the ClamAV daemon returns an unexpected response."""


@dataclass(frozen=True)
class ClamAVScanResponse:
    status: str
    signature: str | None = None


class ClamAVClient:
    """Minimal clamd INSTREAM client for scanning in-memory upload bytes."""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        timeout_seconds: float,
        chunk_size: int = 64 * 1024,
    ) -> None:
        self._host = host
        self._port = port
        self._timeout_seconds = timeout_seconds
        self._chunk_size = chunk_size

    def scan_bytes(self, content: bytes) -> ClamAVScanResponse:
        if not content:
            raise ClamAVProtocolError("scan content must not be empty")

        try:
            with socket.create_connection(
                (self._host, self._port),
                timeout=self._timeout_seconds,
            ) as sock:
                sock.settimeout(self._timeout_seconds)
                sock.sendall(b"zINSTREAM\0")
                for start in range(0, len(content), self._chunk_size):
                    chunk = content[start : start + self._chunk_size]
                    sock.sendall(struct.pack(">I", len(chunk)))
                    sock.sendall(chunk)
                sock.sendall(struct.pack(">I", 0))
                raw_response = self._read_response(sock)
        except TimeoutError as exc:
            raise ClamAVUnavailableError("clamav scan timed out") from exc
        except OSError as exc:
            raise ClamAVUnavailableError("clamav daemon unavailable") from exc

        return self._parse_response(raw_response)

    @staticmethod
    def _read_response(sock: socket.socket) -> str:
        buffer = bytearray()
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            buffer.extend(chunk)
            if b"\0" in chunk or b"\n" in chunk:
                break

        response = bytes(buffer).replace(b"\0", b"").decode("utf-8", errors="replace").strip()
        if not response:
            raise ClamAVProtocolError("empty clamav response")
        return response

    @staticmethod
    def _parse_response(response: str) -> ClamAVScanResponse:
        upper = response.upper()
        if upper.endswith("OK"):
            return ClamAVScanResponse(status="clean")

        if "FOUND" in upper:
            signature = response
            marker = ":"
            if marker in response:
                signature = response.split(marker, maxsplit=1)[1].strip()
            signature = signature.rsplit(" FOUND", maxsplit=1)[0].strip()
            return ClamAVScanResponse(status="infected", signature=signature or None)

        if "ERROR" in upper:
            raise ClamAVProtocolError("clamav error response")

        raise ClamAVProtocolError("unexpected clamav response")


clamav_client: ClamAVClient | None = None
logger = get_logger("clients.clamav")


def init_clamav() -> None:
    global clamav_client
    if not settings.malware_scan_enabled:
        clamav_client = None
        logger.info("clamav.init.skipped", reason="malware_scan_disabled")
        return
    clamav_client = ClamAVClient(
        host=settings.malware_scan_clamav_host,
        port=settings.malware_scan_clamav_port,
        timeout_seconds=settings.malware_scan_timeout_seconds,
        chunk_size=settings.malware_scan_stream_chunk_size_bytes,
    )
    logger.info(
        "clamav.init.success",
        host=settings.malware_scan_clamav_host,
        port=settings.malware_scan_clamav_port,
        timeout_seconds=settings.malware_scan_timeout_seconds,
    )


def close_clamav() -> None:
    global clamav_client
    clamav_client = None
    logger.info("clamav.close")


def get_clamav_client(*, lazy_init: bool = True) -> ClamAVClient | None:
    if clamav_client is not None:
        return clamav_client
    if not lazy_init:
        return None
    try:
        init_clamav()
    except Exception as exc:
        logger.warning(
            "clamav.lazy_init.failed",
            error=exc.__class__.__name__,
        )
        return None
    return clamav_client
