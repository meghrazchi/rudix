"""Degraded boot recovery (R04-12): optional clients reconnect after a failed init."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.clients import qdrant_client as qdrant_module
from app.clients import redis_client as redis_module


def test_failed_qdrant_init_leaves_no_closed_client(monkeypatch: pytest.MonkeyPatch) -> None:
    broken = MagicMock()
    broken.get_collections.side_effect = ConnectionError("down")
    monkeypatch.setattr(qdrant_module, "qdrant_client", None)
    monkeypatch.setattr(qdrant_module, "create_qdrant_client", lambda _settings: broken)

    with pytest.raises(ConnectionError):
        qdrant_module.init_qdrant()

    broken.close.assert_called_once()
    assert qdrant_module.qdrant_client is None


def test_qdrant_health_reconnects_when_client_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    healthy = MagicMock()
    monkeypatch.setattr(qdrant_module, "qdrant_client", None)
    monkeypatch.setattr(qdrant_module.settings, "qdrant_bootstrap_collection", False)
    monkeypatch.setattr(qdrant_module, "create_qdrant_client", lambda _settings: healthy)

    assert qdrant_module.check_qdrant_health() is True
    assert qdrant_module.qdrant_client is healthy


def test_qdrant_health_false_while_still_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    broken = MagicMock()
    broken.get_collections.side_effect = ConnectionError("down")
    monkeypatch.setattr(qdrant_module, "qdrant_client", None)
    monkeypatch.setattr(qdrant_module, "create_qdrant_client", lambda _settings: broken)

    assert qdrant_module.check_qdrant_health() is False
    assert qdrant_module.qdrant_client is None


def test_qdrant_health_false_when_init_leaves_no_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(qdrant_module, "qdrant_client", None)
    monkeypatch.setattr(qdrant_module, "init_qdrant", lambda: None)

    assert qdrant_module.check_qdrant_health() is False


@pytest.mark.asyncio
async def test_redis_health_reconnects_when_client_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    healthy = MagicMock()
    healthy.ping = AsyncMock(return_value=True)
    monkeypatch.setattr(redis_module, "redis_client", None)
    monkeypatch.setattr(redis_module, "create_redis_client", lambda _settings: healthy)

    assert await redis_module.check_redis_health() is True
    assert redis_module.redis_client is healthy


@pytest.mark.asyncio
async def test_redis_health_false_while_still_unreachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    broken = MagicMock()
    broken.ping = AsyncMock(side_effect=ConnectionError("down"))
    broken.aclose = AsyncMock()
    monkeypatch.setattr(redis_module, "redis_client", None)
    monkeypatch.setattr(redis_module, "create_redis_client", lambda _settings: broken)

    assert await redis_module.check_redis_health() is False
    assert redis_module.redis_client is None
    broken.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_redis_health_false_when_init_leaves_no_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(redis_module, "redis_client", None)
    monkeypatch.setattr(redis_module, "init_redis", AsyncMock())

    assert await redis_module.check_redis_health() is False


def test_qdrant_health_false_when_existing_client_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    client = MagicMock()
    client.get_collections.side_effect = ConnectionError("down")
    monkeypatch.setattr(qdrant_module, "qdrant_client", client)

    assert qdrant_module.check_qdrant_health() is False
    assert qdrant_module.qdrant_client is client


@pytest.mark.asyncio
async def test_redis_health_false_when_existing_client_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = MagicMock()
    client.ping = AsyncMock(side_effect=ConnectionError("down"))
    monkeypatch.setattr(redis_module, "redis_client", client)

    assert await redis_module.check_redis_health() is False
    assert redis_module.redis_client is client
