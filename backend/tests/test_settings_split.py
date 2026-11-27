from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from app.core.config import Settings
from app.core.settings.snapshot import sanitized_snapshot

BACKEND_DIR = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"
ENV_EXAMPLE = BACKEND_DIR.parent / ".env.example"
MAX_LINES = 500

# Keys in .env.example that belong to Docker Compose services or the frontend, not Settings.
ENV_EXAMPLE_NON_SETTINGS_PREFIXES = (
    "NEXT_PUBLIC_",
    "GRAFANA_",
    "PROMETHEUS_",
    "LITELLM_",
    "MATOMO_",
    "OLLAMA_",
    "VLLM_",
    "POSTGRES_",
)
ENV_EXAMPLE_NON_SETTINGS_KEYS = {
    "CLAMAV_IMAGE",
    "MINIO_IMAGE",
    "MINIO_ROOT_PASSWORD",
    "MINIO_ROOT_USER",
    "NEO4J_HEAP_INITIAL",
    "NEO4J_HEAP_MAX",
    "NEO4J_IMAGE",
    "NEO4J_MEMORY_LIMIT",
    "NEO4J_PAGECACHE",
    "QDRANT_IMAGE",
    "RABBITMQ_DEFAULT_PASS",
    "RABBITMQ_DEFAULT_USER",
    "RABBITMQ_IMAGE",
    "REDIS_IMAGE",
    "REDIS_PASSWORD",
}

SNAPSHOT_ENV = {
    "ENVIRONMENT": "development",
    "API_BASE_URL": "http://localhost:8000",
    "FRONTEND_BASE_URL": "http://localhost:3000",
    "APP_AUTH_SECRET": "snapshot-secret-value",
    "OPENAI_API_KEY": "sk-snapshot-key",
    "ENTERPRISE_GRAPH_ENABLED": "true",
    "NEO4J_URI": "bolt://neo4j-user:neo4j-pass@localhost:7687",
    "NEO4J_USERNAME": "neo4j",
    "NEO4J_PASSWORD": "neo4j-secret",
    "SENTRY_DSN": "https://key@example.ingest.sentry.io/1",
    "REDIS_URL": "redis://:redis-pass@localhost:6379/0",
    "RABBITMQ_URL": "amqp://guest:guest@localhost:5672//",
    "QDRANT_URL": "http://localhost:6333",
    "QDRANT_COLLECTION": "snapshot_chunks",
    "MINIO_ENDPOINT": "http://localhost:9000",
    "MINIO_ACCESS_KEY": "minio-access",
    "MINIO_SECRET_KEY": "minio-secret-key",
    "MINIO_BUCKET": "snapshot-bucket",
    "DATABASE_URL": "postgresql+asyncpg://user:dbpass@localhost:5432/rudix",
    "FEATURE_ENABLE_MCP": "true",
    "MCP_TRANSPORT": "streamable_http",
    "MCP_REQUIRE_BEARER_AUTH": "false",
    "MCP_DEV_PRINCIPAL_USER_ID": "11111111-1111-1111-1111-111111111111",
    "MCP_DEV_PRINCIPAL_ORGANIZATION_ID": "22222222-2222-2222-2222-222222222222",
    "MCP_DEV_PRINCIPAL_ROLES": "admin,member",
}


def _env_name(name: str) -> str:
    info = Settings.model_fields[name]
    alias = info.validation_alias or info.alias
    return alias if isinstance(alias, str) else name.upper()


def _clear_settings_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in Settings.model_fields:
        monkeypatch.delenv(_env_name(name), raising=False)
        monkeypatch.delenv(name, raising=False)


def _env_example_entries() -> dict[str, str]:
    entries: dict[str, str] = {}
    for raw in ENV_EXAMPLE.read_text().splitlines():
        match = re.match(r"^([A-Z][A-Z0-9_]*)=(.*)$", raw)
        if match:
            entries[match.group(1)] = match.group(2).strip().strip("'\"")
    return entries


def test_config_and_settings_modules_stay_under_line_limit() -> None:
    paths = [
        BACKEND_DIR / "app/core/config.py",
        *sorted((BACKEND_DIR / "app/core/settings").glob("*.py")),
    ]
    assert len(paths) > 10
    too_long = {p.name: n for p in paths if (n := len(p.read_text().splitlines())) > MAX_LINES}
    assert too_long == {}


def test_live_fields_are_superset_of_recorded_fields_with_same_env_names() -> None:
    recorded = dict(
        line.split("|", 1)
        for line in (FIXTURES / "settings_fields.txt").read_text().splitlines()
        if line.strip()
    )
    assert len(recorded) > 300
    live = {name: _env_name(name) for name in Settings.model_fields}
    missing = sorted(set(recorded) - set(live))
    assert missing == []
    changed = {n: (recorded[n], live[n]) for n in recorded if recorded[n] != live[n]}
    assert changed == {}


def test_every_env_example_key_maps_to_a_field_or_is_allowlisted() -> None:
    env_names = {_env_name(name) for name in Settings.model_fields}
    unknown = sorted(
        key
        for key in _env_example_entries()
        if key not in env_names
        and key not in ENV_EXAMPLE_NON_SETTINGS_KEYS
        and not key.startswith(ENV_EXAMPLE_NON_SETTINGS_PREFIXES)
    )
    assert unknown == []


def test_settings_load_with_env_example_values(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_settings_env(monkeypatch)
    for key, value in _env_example_entries().items():
        monkeypatch.setenv(key, value)
    loaded = Settings(_env_file=None)  # type: ignore[call-arg]
    assert loaded.api_prefix
    assert loaded.graph_migrations_on_startup is None


def test_sanitized_snapshot_matches_pre_split_output(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_settings_env(monkeypatch)
    for key, value in SNAPSHOT_ENV.items():
        monkeypatch.setenv(key, value)
    loaded = Settings(_env_file=None)  # type: ignore[call-arg]
    expected = json.loads((FIXTURES / "settings_snapshot.json").read_text())
    actual = json.loads(json.dumps(loaded.sanitized_snapshot(), sort_keys=True, default=str))
    assert actual == expected
    assert sanitized_snapshot(loaded) == loaded.sanitized_snapshot()
    dumped = json.dumps(actual)
    for secret in ("sk-snapshot-key", "neo4j-secret", "dbpass", "redis-pass", "minio-secret-key"):
        assert secret not in dumped


def test_consistency_validation_still_runs_in_original_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_settings_env(monkeypatch)
    for key, value in SNAPSHOT_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("RETRIEVAL_FINAL_TOP_K", "50")
    monkeypatch.setenv("RETRIEVAL_INITIAL_TOP_K", "10")
    with pytest.raises(ValueError, match="retrieval_final_top_k must be less than or equal"):
        Settings(_env_file=None)  # type: ignore[call-arg]

    monkeypatch.delenv("RETRIEVAL_FINAL_TOP_K")
    monkeypatch.delenv("RETRIEVAL_INITIAL_TOP_K")
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("API_BASE_URL", "http://localhost:8000")
    with pytest.raises(ValueError, match="api_base_url must use https"):
        Settings(_env_file=None)  # type: ignore[call-arg]
