"""Tests for F222: Docker Compose local model profiles and startup probe.

CI does NOT download model weights; all tests use mocks or static config parsing.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

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

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = REPO_ROOT / "docker-compose.yml"
LITELLM_CONFIG = REPO_ROOT / "infra" / "litellm" / "config.yaml"


# ── Compose file YAML syntax ──────────────────────────────────────────────────


def _load_compose() -> dict:
    with COMPOSE_FILE.open() as fh:
        return yaml.safe_load(fh)


def test_compose_file_is_valid_yaml() -> None:
    compose = _load_compose()
    assert isinstance(compose, dict)
    assert "services" in compose


def test_compose_services_key_is_dict() -> None:
    compose = _load_compose()
    assert isinstance(compose["services"], dict)


# ── Profile membership ────────────────────────────────────────────────────────


def test_ollama_service_has_ollama_profile() -> None:
    services = _load_compose()["services"]
    assert "ollama" in services
    assert "ollama" in services["ollama"]["profiles"]


def test_vllm_service_has_vllm_profile() -> None:
    services = _load_compose()["services"]
    assert "vllm" in services
    assert "vllm" in services["vllm"]["profiles"]


def test_litellm_service_has_litellm_profile() -> None:
    services = _load_compose()["services"]
    assert "litellm" in services
    assert "litellm" in services["litellm"]["profiles"]


def test_core_services_have_no_profiles() -> None:
    """api, worker, postgres etc. must not be gated behind a profile."""
    services = _load_compose()["services"]
    always_on = {"api", "worker", "postgres", "qdrant", "minio", "rabbitmq", "redis"}
    for name in always_on:
        assert name in services
        assert "profiles" not in services[name], (
            f"Service '{name}' should not be profile-gated"
        )


# ── No host-port exposure for model services ─────────────────────────────────


def test_ollama_has_no_host_port_binding() -> None:
    services = _load_compose()["services"]
    assert "ports" not in services["ollama"], (
        "ollama must not bind host ports by default — internal network only"
    )


def test_vllm_has_no_host_port_binding() -> None:
    services = _load_compose()["services"]
    assert "ports" not in services["vllm"], (
        "vllm must not bind host ports by default — internal network only"
    )


def test_litellm_has_no_host_port_binding() -> None:
    services = _load_compose()["services"]
    assert "ports" not in services["litellm"], (
        "litellm must not bind host ports by default — internal network only"
    )


# ── Environment variable substitution present ────────────────────────────────


def test_ollama_image_uses_env_substitution() -> None:
    services = _load_compose()["services"]
    assert "${OLLAMA_IMAGE" in services["ollama"]["image"]


def test_vllm_image_uses_env_substitution() -> None:
    services = _load_compose()["services"]
    assert "${VLLM_IMAGE" in services["vllm"]["image"]


def test_litellm_image_uses_env_substitution() -> None:
    services = _load_compose()["services"]
    assert "${LITELLM_IMAGE" in services["litellm"]["image"]


# ── Health checks present ─────────────────────────────────────────────────────


def test_ollama_has_healthcheck() -> None:
    services = _load_compose()["services"]
    assert "healthcheck" in services["ollama"]


def test_vllm_has_healthcheck() -> None:
    services = _load_compose()["services"]
    assert "healthcheck" in services["vllm"]


def test_litellm_has_healthcheck() -> None:
    services = _load_compose()["services"]
    assert "healthcheck" in services["litellm"]


# ── Named volumes declared ────────────────────────────────────────────────────


def test_ollama_data_volume_declared() -> None:
    compose = _load_compose()
    assert "ollama_data" in compose.get("volumes", {})


def test_vllm_cache_volume_declared() -> None:
    compose = _load_compose()
    assert "vllm_cache" in compose.get("volumes", {})


# ── LiteLLM config file syntax ───────────────────────────────────────────────


def test_litellm_config_is_valid_yaml() -> None:
    with LITELLM_CONFIG.open() as fh:
        cfg = yaml.safe_load(fh)
    assert isinstance(cfg, dict)


def test_litellm_config_has_model_list() -> None:
    with LITELLM_CONFIG.open() as fh:
        cfg = yaml.safe_load(fh)
    assert "model_list" in cfg
    assert isinstance(cfg["model_list"], list)
    assert len(cfg["model_list"]) >= 1


def test_litellm_config_no_hardcoded_api_keys() -> None:
    """Real API keys must not be baked into the config template."""
    raw = LITELLM_CONFIG.read_text()
    for bad in ("sk-proj-", "sk-ant-", "Bearer ", "hf_"):
        assert bad not in raw, f"Potential hardcoded key pattern '{bad}' found in litellm config"


def test_litellm_config_uses_env_var_for_master_key() -> None:
    with LITELLM_CONFIG.open() as fh:
        cfg = yaml.safe_load(fh)
    master_key = cfg.get("general_settings", {}).get("master_key", "")
    assert "os.environ" in master_key, (
        "master_key must be injected via os.environ/VAR, not hardcoded"
    )


# ── Startup probe: _tcp_reachable ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_tcp_reachable_returns_true_on_success() -> None:
    from app.core.lifespan import _tcp_reachable

    mock_writer = MagicMock()
    mock_writer.close = MagicMock()
    mock_writer.wait_closed = AsyncMock()

    with patch(
        "asyncio.open_connection",
        new_callable=AsyncMock,
        return_value=(MagicMock(), mock_writer),
    ):
        result = await _tcp_reachable("localhost", 11434)

    assert result is True


@pytest.mark.asyncio
async def test_tcp_reachable_returns_false_on_connection_refused() -> None:
    from app.core.lifespan import _tcp_reachable

    with patch(
        "asyncio.open_connection",
        side_effect=OSError("Connection refused"),
    ):
        result = await _tcp_reachable("localhost", 11434)

    assert result is False


@pytest.mark.asyncio
async def test_tcp_reachable_returns_false_on_timeout() -> None:
    from app.core.lifespan import _tcp_reachable

    async def _slow(*_a: object, **_kw: object) -> None:
        await asyncio.sleep(60)

    with patch("asyncio.open_connection", side_effect=_slow):
        result = await _tcp_reachable("localhost", 11434, timeout=0.01)

    assert result is False


# ── Startup probe: probe_local_providers ─────────────────────────────────────


@pytest.mark.asyncio
async def test_probe_skips_when_provider_not_local(caplog: pytest.LogCaptureFixture) -> None:
    from app.core.lifespan import probe_local_providers

    mock_settings = MagicMock()
    mock_settings.llm_default_provider = "openai"
    mock_settings.embedding_default_provider = "openai"

    with patch("app.core.lifespan.probe_local_providers.__module__"), \
         patch("app.core.config.settings", mock_settings), \
         caplog.at_level("WARNING"):
        await probe_local_providers()

    assert "[local-llm]" not in caplog.text


@pytest.mark.asyncio
async def test_probe_warns_when_local_llm_url_not_set(caplog: pytest.LogCaptureFixture) -> None:
    from app.core.lifespan import probe_local_providers

    mock_settings = MagicMock()
    mock_settings.llm_default_provider = "local"
    mock_settings.local_llm_base_url = None
    mock_settings.embedding_default_provider = "openai"

    with patch("app.core.config.settings", mock_settings), \
         caplog.at_level("WARNING", logger="app.core.lifespan"):
        await probe_local_providers()

    assert "base URL is not configured" in caplog.text


@pytest.mark.asyncio
async def test_probe_warns_when_local_llm_unreachable(caplog: pytest.LogCaptureFixture) -> None:
    from app.core.lifespan import probe_local_providers

    mock_settings = MagicMock()
    mock_settings.llm_default_provider = "local"
    mock_settings.local_llm_base_url = MagicMock()
    mock_settings.local_llm_base_url.__str__ = lambda _: "http://ollama:11434/v1"
    mock_settings.embedding_default_provider = "openai"

    with patch("app.core.config.settings", mock_settings), \
         patch("app.core.lifespan._tcp_reachable", new_callable=AsyncMock, return_value=False), \
         caplog.at_level("WARNING", logger="app.core.lifespan"):
        await probe_local_providers()

    assert "not reachable" in caplog.text
    assert "make up-ollama" in caplog.text


@pytest.mark.asyncio
async def test_probe_logs_info_when_local_llm_reachable(caplog: pytest.LogCaptureFixture) -> None:
    from app.core.lifespan import probe_local_providers

    mock_settings = MagicMock()
    mock_settings.llm_default_provider = "local"
    mock_settings.local_llm_base_url = MagicMock()
    mock_settings.local_llm_base_url.__str__ = lambda _: "http://ollama:11434/v1"
    mock_settings.embedding_default_provider = "openai"

    with patch("app.core.config.settings", mock_settings), \
         patch("app.core.lifespan._tcp_reachable", new_callable=AsyncMock, return_value=True), \
         caplog.at_level("INFO", logger="app.core.lifespan"):
        await probe_local_providers()

    assert "is reachable" in caplog.text


@pytest.mark.asyncio
async def test_probe_checks_both_llm_and_embedding(caplog: pytest.LogCaptureFixture) -> None:
    from app.core.lifespan import probe_local_providers

    mock_settings = MagicMock()
    mock_settings.llm_default_provider = "local"
    mock_settings.local_llm_base_url = MagicMock()
    mock_settings.local_llm_base_url.__str__ = lambda _: "http://ollama:11434/v1"
    mock_settings.embedding_default_provider = "local"
    mock_settings.local_embedding_base_url = MagicMock()
    mock_settings.local_embedding_base_url.__str__ = lambda _: "http://ollama:11434/v1"

    calls: list[tuple[str, int]] = []

    async def _fake_probe(host: str, port: int, **_kw: object) -> bool:
        calls.append((host, port))
        return True

    with patch("app.core.config.settings", mock_settings), \
         patch("app.core.lifespan._tcp_reachable", side_effect=_fake_probe), \
         caplog.at_level("INFO", logger="app.core.lifespan"):
        await probe_local_providers()

    assert len(calls) == 2


@pytest.mark.asyncio
async def test_probe_warns_when_embedding_url_not_set(caplog: pytest.LogCaptureFixture) -> None:
    from app.core.lifespan import probe_local_providers

    mock_settings = MagicMock()
    mock_settings.llm_default_provider = "openai"
    mock_settings.embedding_default_provider = "local"
    mock_settings.local_embedding_base_url = None

    with patch("app.core.config.settings", mock_settings), \
         caplog.at_level("WARNING", logger="app.core.lifespan"):
        await probe_local_providers()

    assert "base URL is not configured" in caplog.text


# ── Default compose stack starts without local model containers ───────────────


def test_default_services_exclude_local_model_containers() -> None:
    """Services without a profiles key start by default; model containers must be opt-in."""
    compose = _load_compose()
    default_services = [
        name
        for name, svc in compose["services"].items()
        if "profiles" not in svc
    ]
    for local_svc in ("ollama", "vllm", "litellm"):
        assert local_svc not in default_services, (
            f"'{local_svc}' must require an explicit profile to start"
        )
