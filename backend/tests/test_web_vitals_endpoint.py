import os
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("API_BASE_URL", "http://localhost:8000")
os.environ.setdefault("FRONTEND_BASE_URL", "http://localhost:3000")
os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/rag_app"
)
os.environ.setdefault("QDRANT_URL", "http://localhost:6333")
os.environ.setdefault("QDRANT_COLLECTION", "documents")
os.environ.setdefault("MINIO_ENDPOINT", "http://localhost:9000")
os.environ.setdefault("MINIO_ACCESS_KEY", "minioadmin")
os.environ.setdefault("MINIO_SECRET_KEY", "minioadmin")
os.environ.setdefault("MINIO_BUCKET", "documents")
os.environ.setdefault("RABBITMQ_URL", "amqp://admin:admin123@localhost:5672//")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("OPENAI_API_KEY", "sk-test")
os.environ.setdefault("AUTH_PROVIDER", "app")
os.environ.setdefault("APP_AUTH_SECRET", "test-secret")

from app.clients import redis_client as redis_module
from app.core import metrics_frontend
from app.core.config import RateLimitRedisFailureMode, settings
from app.core.metrics import registry
from app.main import app
from tests.redis_fakes import BrokenRedis, FakeRedis

URL = "/api/v1/telemetry/web-vitals"


def _sample(**overrides: Any) -> dict[str, Any]:
    sample: dict[str, Any] = {
        "name": "LCP",
        "value": 1800.5,
        "route": "/[locale]/pricing",
        "rating": "good",
        "navigation_type": "navigate",
    }
    sample.update(overrides)
    return sample


def _body(*samples: dict[str, Any]) -> dict[str, Any]:
    return {"samples": list(samples) or [_sample()]}


def _count(name: str, **labels: str) -> float:
    return registry.get_sample_value(name, labels) or 0.0


@pytest_asyncio.fixture
async def client(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AsyncClient]:
    monkeypatch.setattr(settings, "web_vitals_ingest_enabled", True)
    monkeypatch.setattr(settings, "web_vitals_max_routes", 200)
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    metrics_frontend.reset_known_routes_for_testing()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as http:
        yield http
    metrics_frontend.reset_known_routes_for_testing()


@pytest.mark.asyncio
async def test_disabled_returns_404_even_for_invalid_bodies(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "web_vitals_ingest_enabled", False)

    rejected_before = _count("rudix_web_vitals_samples_total", metric="all", outcome="rejected")

    assert (await client.post(URL, json=_body())).status_code == 404
    assert (await client.post(URL, json={"nope": 1})).status_code == 404
    malformed = await client.post(
        URL, content=b"{not json", headers={"content-type": "application/json"}
    )
    assert malformed.status_code == 404
    assert (
        _count("rudix_web_vitals_samples_total", metric="all", outcome="rejected")
        == rejected_before
    )


@pytest.mark.asyncio
async def test_enabled_accepts_and_observes_histograms(client: AsyncClient) -> None:
    labels = {"metric": "LCP", "route": "/[locale]/pricing"}
    before = _count("rudix_web_vitals_value_ms_count", **labels)
    accepted_before = _count("rudix_web_vitals_samples_total", metric="LCP", outcome="accepted")

    response = await client.post(URL, json=_body())

    assert response.status_code == 204
    assert response.content == b""
    assert _count("rudix_web_vitals_value_ms_count", **labels) == before + 1
    assert _count("rudix_web_vitals_value_ms_sum", **labels) >= 1800.5
    assert (
        _count("rudix_web_vitals_samples_total", metric="LCP", outcome="accepted")
        == accepted_before + 1
    )


@pytest.mark.asyncio
async def test_cls_goes_to_its_own_histogram(client: AsyncClient) -> None:
    before = _count("rudix_web_vitals_cls_count", route="/[locale]")

    response = await client.post(
        URL, json=_body(_sample(name="CLS", value=0.07, route="/[locale]", rating="good"))
    )

    assert response.status_code == 204
    assert _count("rudix_web_vitals_cls_count", route="/[locale]") == before + 1


@pytest.mark.asyncio
async def test_no_authentication_is_required(client: AsyncClient) -> None:
    response = await client.post(
        URL, json=_body(_sample(navigation_type=None, rating="poor")), headers={}
    )

    assert response.status_code == 204


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad_sample",
    [
        {"name": "FID"},
        {"route": "/pricing?x=1"},
        {"route": "pricing"},
        {"route": "/" + "a" * 130},
        {"value": -1},
        {"value": 60001},
        {"name": "CLS", "value": 10.5},
        {"rating": "great"},
        {"navigation_type": "teleport"},
        {"extra_field": "x"},
    ],
)
async def test_invalid_samples_are_rejected_and_counted(
    client: AsyncClient, bad_sample: dict[str, Any]
) -> None:
    before = _count("rudix_web_vitals_samples_total", metric="all", outcome="rejected")

    response = await client.post(URL, json=_body(_sample(**bad_sample)))

    assert response.status_code == 422
    assert _count("rudix_web_vitals_samples_total", metric="all", outcome="rejected") == before + 1


@pytest.mark.asyncio
async def test_batch_size_is_bounded(client: AsyncClient) -> None:
    assert (await client.post(URL, json={"samples": []})).status_code == 422
    too_many = {"samples": [_sample() for _ in range(11)]}
    assert (await client.post(URL, json=too_many)).status_code == 422
    ten = {"samples": [_sample() for _ in range(10)]}
    assert (await client.post(URL, json=ten)).status_code == 204
    assert (await client.post(URL, json={"samples": [_sample()], "x": 1})).status_code == 422


@pytest.mark.asyncio
async def test_route_labels_are_bounded(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "web_vitals_max_routes", 2)
    other_before = _count("rudix_web_vitals_value_ms_count", metric="TTFB", route="other")

    for route in ("/a", "/b", "/c", "/d", "/a"):
        response = await client.post(URL, json=_body(_sample(name="TTFB", value=120, route=route)))
        assert response.status_code == 204

    assert _count("rudix_web_vitals_value_ms_count", metric="TTFB", route="/a") >= 2
    assert _count("rudix_web_vitals_value_ms_count", metric="TTFB", route="/b") >= 1
    assert _count("rudix_web_vitals_value_ms_count", metric="TTFB", route="/c") == 0
    assert _count("rudix_web_vitals_value_ms_count", metric="TTFB", route="other") == (
        other_before + 2
    )


@pytest.mark.asyncio
async def test_rate_limit_returns_429_and_counts(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_disable_in_test", False)
    monkeypatch.setattr(settings, "web_vitals_rate_limit_per_minute", 2)
    monkeypatch.setattr(settings, "rate_limit_redis_failure_mode", RateLimitRedisFailureMode.open)
    monkeypatch.setattr(redis_module, "redis_client", FakeRedis())
    before = _count("rudix_web_vitals_samples_total", metric="all", outcome="rate_limited")

    statuses = [(await client.post(URL, json=_body())).status_code for _ in range(3)]
    other_ip = await client.post(URL, json=_body(), headers={"x-forwarded-for": "203.0.113.9"})

    assert statuses == [204, 204, 429]
    assert other_ip.status_code == 204
    assert (
        _count("rudix_web_vitals_samples_total", metric="all", outcome="rate_limited") == before + 1
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("redis_client", "mode", "expected"),
    [
        (None, RateLimitRedisFailureMode.open, 204),
        (None, RateLimitRedisFailureMode.closed, 503),
        (BrokenRedis(), RateLimitRedisFailureMode.open, 204),
        (BrokenRedis(), RateLimitRedisFailureMode.closed, 503),
    ],
)
async def test_redis_unavailable_follows_failure_mode(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    redis_client: Any,
    mode: RateLimitRedisFailureMode,
    expected: int,
) -> None:
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_disable_in_test", False)
    monkeypatch.setattr(settings, "rate_limit_redis_failure_mode", mode)
    monkeypatch.setattr(redis_module, "redis_client", redis_client)

    assert (await client.post(URL, json=_body())).status_code == expected


@pytest.mark.asyncio
async def test_cors_preflight_from_allowed_origin_passes(client: AsyncClient) -> None:
    origin = str(settings.frontend_base_url).rstrip("/")

    response = await client.options(
        URL,
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin
    assert "POST" in response.headers["access-control-allow-methods"]


@pytest.mark.asyncio
async def test_no_values_or_ips_are_logged(
    client: AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level("DEBUG"):
        await client.post(
            URL,
            json=_body(_sample(value=4242.4242)),
            headers={"x-forwarded-for": "198.51.100.77"},
        )

    assert "4242.4242" not in caplog.text
    assert "198.51.100.77" not in caplog.text
