"""Async wrappers around the sync boto3 S3 client (R04-11).

Every blocking call runs in a worker thread so request handlers never stall the
event loop. Workers keep using the sync client directly. Callers obtain the
client via ``app.clients.minio_client.get_minio_client`` (lazy_init semantics
unchanged) and pass it in.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

DEFAULT_CHUNK_SIZE = 64 * 1024


async def put_object(client: Any, **kwargs: Any) -> Any:
    return await asyncio.to_thread(client.put_object, **kwargs)


async def delete_object(client: Any, **kwargs: Any) -> Any:
    return await asyncio.to_thread(client.delete_object, **kwargs)


async def head_object(client: Any, **kwargs: Any) -> Any:
    return await asyncio.to_thread(client.head_object, **kwargs)


async def generate_presigned_url(client: Any, *args: Any, **kwargs: Any) -> str:
    return str(await asyncio.to_thread(client.generate_presigned_url, *args, **kwargs))


class StoredObject:
    """Result of ``get_object``: metadata plus an async chunk iterator over the body."""

    def __init__(self, response: dict[str, Any]) -> None:
        self._response = response
        self._body = response["Body"]

    @property
    def response(self) -> dict[str, Any]:
        return self._response

    async def iter_chunks(self, chunk_size: int = DEFAULT_CHUNK_SIZE) -> AsyncIterator[bytes]:
        while True:
            chunk = await asyncio.to_thread(self._body.read, chunk_size)
            if not chunk:
                break
            yield chunk

    async def read_all(self, chunk_size: int = DEFAULT_CHUNK_SIZE) -> bytes:
        return b"".join([chunk async for chunk in self.iter_chunks(chunk_size)])

    async def close(self) -> None:
        close = getattr(self._body, "close", None)
        if callable(close):
            await asyncio.to_thread(close)


async def get_object(client: Any, **kwargs: Any) -> StoredObject:
    response = await asyncio.to_thread(client.get_object, **kwargs)
    return StoredObject(response)
