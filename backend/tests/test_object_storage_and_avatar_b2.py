"""R04-11: async object-storage wrappers, loop-lag monitor lifecycle, avatar handlers."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients import minio_client as minio_module
from app.clients import object_storage
from app.core import loop_lag
from app.core.config import settings
from app.core.loop_lag import LoopLagMonitor
from app.interfaces.http import profile as profile_api
from app.models.enums import OrganizationRole
from tests.list_endpoint_seed import api_client, configure_app_auth, seed_document, seed_tenant


class RecordingBody:
    def __init__(self, content: bytes) -> None:
        self.content = content
        self.pos = 0
        self.closed = False

    def read(self, amt: int | None = None) -> bytes:
        end = len(self.content) if amt is None else self.pos + amt
        chunk = self.content[self.pos : end]
        self.pos += len(chunk)
        return chunk

    def close(self) -> None:
        self.closed = True


class RecordingClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.body = RecordingBody(b"abcdefgh")

    def put_object(self, **kwargs: Any) -> str:
        self.calls.append(("put", kwargs))
        return "put"

    def delete_object(self, **kwargs: Any) -> str:
        self.calls.append(("delete", kwargs))
        return "delete"

    def head_object(self, **kwargs: Any) -> str:
        self.calls.append(("head", kwargs))
        return "head"

    def get_object(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("get", kwargs))
        return {"Body": self.body, "ContentLength": 8}

    def generate_presigned_url(self, *args: Any, **kwargs: Any) -> str:
        self.calls.append(("presign", {"args": args, **kwargs}))
        return "https://signed.example/avatar"


@pytest.mark.asyncio
async def test_wrappers_forward_to_sync_client() -> None:
    client = RecordingClient()

    assert await object_storage.put_object(client, Bucket="b", Key="k") == "put"
    assert await object_storage.delete_object(client, Bucket="b", Key="k") == "delete"
    assert await object_storage.head_object(client, Bucket="b", Key="k") == "head"
    url = await object_storage.generate_presigned_url(client, "get_object", ExpiresIn=5)

    assert url == "https://signed.example/avatar"
    assert [name for name, _ in client.calls] == ["put", "delete", "head", "presign"]


@pytest.mark.asyncio
async def test_get_object_streams_chunks_and_closes() -> None:
    client = RecordingClient()

    stored = await object_storage.get_object(client, Bucket="b", Key="k")
    chunks = [chunk async for chunk in stored.iter_chunks(chunk_size=3)]
    await stored.close()

    assert chunks == [b"abc", b"def", b"gh"]
    assert stored.response["ContentLength"] == 8
    assert client.body.closed is True


@pytest.mark.asyncio
async def test_read_all_and_close_without_close_method() -> None:
    client = RecordingClient()
    stored = await object_storage.get_object(client, Bucket="b", Key="k")
    assert await stored.read_all(chunk_size=5) == b"abcdefgh"

    class NoClose:
        def read(self, amt: int | None = None) -> bytes:
            return b""

    bare = object_storage.StoredObject({"Body": NoClose()})
    await bare.close()
    assert await bare.read_all() == b""


@pytest.mark.asyncio
async def test_loop_lag_monitor_lifecycle_and_reset() -> None:
    monitor = LoopLagMonitor(interval_ms=5)
    assert monitor.running is False
    monitor.start()
    monitor.start()  # idempotent
    assert monitor.running is True
    await asyncio.sleep(0.05)
    assert monitor.reset() >= 0.0
    assert monitor.max_lag_seconds == 0.0
    await monitor.stop()
    await monitor.stop()  # safe when already stopped
    assert monitor.running is False


@pytest.mark.asyncio
async def test_lag_gauge_reports_window_max_then_decays() -> None:
    """The gauge holds a spike for one window only; the all-time max does not pin it."""
    import time

    from app.core.metrics import registry

    # Wide margins: the spike stays in its 1 s window long enough to be read under load,
    # and the decay check allows up to 250 ms of unrelated scheduling noise.
    monitor = LoopLagMonitor(interval_ms=5, gauge_window_seconds=1.0)
    monitor.start()
    try:
        await asyncio.sleep(0.02)
        time.sleep(0.5)  # deliberate block on the loop
        await asyncio.sleep(0.02)
        spike = registry.get_sample_value("rudix_event_loop_lag_seconds")
        assert spike is not None and spike >= 0.4
        assert monitor.window_max_lag_seconds >= 0.4

        await asyncio.sleep(2.2)  # at least one full window without the block
        decayed = registry.get_sample_value("rudix_event_loop_lag_seconds")
        assert decayed is not None and decayed < 0.25
        assert monitor.max_lag_seconds >= 0.4  # the probe value is kept until reset()
    finally:
        await monitor.stop()


@pytest.mark.asyncio
async def test_start_and_stop_helpers_respect_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "loop_lag_monitor_enabled", False)
    assert loop_lag.start_loop_lag_monitor() is None

    monkeypatch.setattr(settings, "loop_lag_monitor_enabled", True)
    monkeypatch.setattr(settings, "loop_lag_monitor_interval_ms", 5)
    started = loop_lag.start_loop_lag_monitor()
    assert started is not None and started.running
    assert loop_lag.start_loop_lag_monitor() is started
    await loop_lag.stop_loop_lag_monitor()
    assert started.running is False
    await loop_lag.stop_loop_lag_monitor()  # no-op when nothing is running


@pytest.mark.asyncio
async def test_lifespan_starts_and_stops_monitor(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import lifespan as lifespan_module

    events: list[str] = []

    async def _noop(*args: Any, **kwargs: Any) -> None:
        return None

    for name in (
        "init_sentry",
        "init_langfuse",
        "init_minio",
        "init_clamav",
        "close_rabbitmq",
        "close_qdrant",
        "close_minio",
        "close_clamav",
        "shutdown_langfuse",
    ):
        monkeypatch.setattr(lifespan_module, name, lambda *a, **k: None)
    for name in (
        "_init_optional_dependency",
        "init_neo4j",
        "run_graph_migrations",
        "probe_local_providers",
        "close_redis",
        "close_neo4j",
    ):
        monkeypatch.setattr(lifespan_module, name, _noop)
    monkeypatch.setattr(lifespan_module, "start_loop_lag_monitor", lambda: events.append("start"))

    async def _stop() -> None:
        events.append("stop")

    monkeypatch.setattr(lifespan_module, "stop_loop_lag_monitor", _stop)

    async with lifespan_module.lifespan(None):  # type: ignore[arg-type]
        assert events == ["start"]
    assert events == ["start", "stop"]


@pytest.mark.asyncio
async def test_avatar_upload_presign_replace_and_remove(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    client = RecordingClient()
    monkeypatch.setattr(minio_module, "minio_client", client)
    monkeypatch.setattr(profile_api, "get_minio_client", lambda **_: client)
    configure_app_auth(monkeypatch)
    tenant = await seed_tenant(db_session, role=OrganizationRole.member)
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 16

    async with api_client(monkeypatch, db_session) as http:
        first = await http.post(
            "/api/v1/me/avatar",
            headers=tenant.headers,
            files={"file": ("a.png", png, "image/png")},
        )
        assert first.status_code == 200, first.text
        assert first.json()["avatar_url"] == "https://signed.example/avatar"
        second = await http.post(
            "/api/v1/me/avatar",
            headers=tenant.headers,
            files={"file": ("a.png", png, "image/png")},
        )
        assert second.status_code == 200, second.text
        removed = await http.delete("/api/v1/me/avatar", headers=tenant.headers)
        assert removed.status_code == 204

    kinds = [name for name, _ in client.calls]
    # put, (presign), delete old + put, (presign), delete on removal
    assert kinds.count("put") == 2
    assert kinds.count("delete") == 2
    assert kinds.count("presign") >= 2
    assert all(
        kwargs.get("Bucket") == settings.minio_bucket
        for name, kwargs in client.calls
        if name in {"put", "delete"}
    )


@pytest.mark.asyncio
async def test_avatar_presign_failure_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    class Failing(RecordingClient):
        def generate_presigned_url(self, *args: Any, **kwargs: Any) -> str:
            raise RuntimeError("signing down")

    monkeypatch.setattr(profile_api, "get_minio_client", lambda **_: Failing())
    assert await profile_api._avatar_presigned_url("avatars/u/x.png") is None

    monkeypatch.setattr(profile_api, "get_minio_client", lambda **_: None)
    assert await profile_api._avatar_presigned_url("avatars/u/x.png") is None


class _ExplodingBody(RecordingBody):
    def read(self, amt: int | None = None) -> bytes:
        raise OSError("connection reset")


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["get_object", "first_read"])
async def test_download_storage_failures_map_to_503(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession, failure: str
) -> None:
    class Client(RecordingClient):
        def get_object(self, **kwargs: Any) -> dict[str, Any]:
            if failure == "get_object":
                raise RuntimeError("storage down")
            return {"Body": _ExplodingBody(b"")}

    monkeypatch.setattr(minio_module, "minio_client", Client())
    configure_app_auth(monkeypatch)
    tenant = await seed_tenant(db_session)
    document, _ = await seed_document(db_session, tenant, chunks=0)
    await db_session.commit()

    async with api_client(monkeypatch, db_session) as http:
        response = await http.get(
            f"/api/v1/documents/{document.id}/download", headers=tenant.headers
        )

    assert response.status_code == 503
    assert response.json()["detail"] == "Document file is unavailable"
    assert "storage down" not in response.text
    assert "connection reset" not in response.text


@pytest.mark.asyncio
async def test_download_empty_object_returns_empty_body(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    client = RecordingClient()
    client.body = RecordingBody(b"")
    monkeypatch.setattr(minio_module, "minio_client", client)
    configure_app_auth(monkeypatch)
    tenant = await seed_tenant(db_session)
    document, _ = await seed_document(db_session, tenant, chunks=0)
    await db_session.commit()

    async with api_client(monkeypatch, db_session) as http:
        response = await http.get(
            f"/api/v1/documents/{document.id}/download", headers=tenant.headers
        )

    assert response.status_code == 200
    assert response.content == b""
    assert client.body.closed is True


@pytest.mark.asyncio
async def test_download_streams_with_content_length_from_storage(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    client = RecordingClient()
    monkeypatch.setattr(minio_module, "minio_client", client)
    configure_app_auth(monkeypatch)
    tenant = await seed_tenant(db_session)
    document, _ = await seed_document(db_session, tenant, chunks=0)
    await db_session.commit()

    async with api_client(monkeypatch, db_session) as http:
        identity = await http.get(
            f"/api/v1/documents/{document.id}/download",
            headers={**tenant.headers, "Accept-Encoding": "identity"},
        )
        client.body = RecordingBody(b"abcdefgh")
        compressed = await http.get(
            f"/api/v1/documents/{document.id}/download",
            headers={**tenant.headers, "Accept-Encoding": "gzip"},
        )

    assert identity.status_code == 200
    assert identity.content == b"abcdefgh"
    assert identity.headers["content-length"] == "8"
    assert identity.headers["content-disposition"].startswith("attachment;")
    # GZip replaces the storage length with chunked transfer; httpx decodes the body.
    assert compressed.status_code == 200
    assert compressed.headers.get("content-encoding") == "gzip"
    assert "content-length" not in compressed.headers
    assert compressed.content == b"abcdefgh"


@pytest.mark.asyncio
async def test_account_deletion_removes_avatar_object_via_async_wrapper(
    monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession
) -> None:
    client = RecordingClient()
    monkeypatch.setattr(profile_api, "get_minio_client", lambda **_: client)
    configure_app_auth(monkeypatch)
    tenant = await seed_tenant(db_session, role=OrganizationRole.member)
    avatar_key = f"avatars/{tenant.user.id}/old.png"
    tenant.user.avatar_url = avatar_key
    await db_session.commit()

    async with api_client(monkeypatch, db_session) as http:
        response = await http.delete("/api/v1/me", headers=tenant.headers)

    assert response.status_code == 204, response.text
    assert client.calls == [("delete", {"Bucket": settings.minio_bucket, "Key": avatar_key})]
