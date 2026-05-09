import pytest
from pydantic import ValidationError

from app.core.config import AuthProvider, Environment, Settings

ENV_KEYS = [
    "ENVIRONMENT",
    "API_BASE_URL",
    "FRONTEND_BASE_URL",
    "DATABASE_URL",
    "QDRANT_URL",
    "QDRANT_COLLECTION",
    "MINIO_ENDPOINT",
    "MINIO_ACCESS_KEY",
    "MINIO_SECRET_KEY",
    "MINIO_BUCKET",
    "RABBITMQ_URL",
    "REDIS_URL",
    "RATE_LIMIT_ENABLED",
    "RATE_LIMIT_DISABLE_IN_DEVELOPMENT",
    "RATE_LIMIT_DISABLE_IN_TEST",
    "RATE_LIMIT_REDIS_FAILURE_MODE",
    "RATE_LIMIT_WINDOW_SECONDS",
    "RATE_LIMIT_UPLOAD_REQUESTS",
    "RATE_LIMIT_CHAT_REQUESTS",
    "RATE_LIMIT_EVALUATION_REQUESTS",
    "RATE_LIMIT_DELETE_REQUESTS",
    "RATE_LIMIT_ADMIN_REQUESTS",
    "RERANK_MMR_LAMBDA",
    "RERANK_MMR_CANDIDATE_COUNT",
    "RERANK_MMR_DUPLICATE_SIMILARITY_THRESHOLD",
    "CONFIDENCE_WEIGHT_TOP_SIMILARITY",
    "CONFIDENCE_WEIGHT_AVERAGE_SIMILARITY",
    "CONFIDENCE_WEIGHT_RERANK_SCORE",
    "CONFIDENCE_WEIGHT_CITATION_SUPPORT",
    "CONFIDENCE_WEIGHT_AGREEMENT",
    "CONFIDENCE_MEDIUM_THRESHOLD",
    "CONFIDENCE_HIGH_THRESHOLD",
    "CONFIDENCE_NOT_FOUND_THRESHOLD",
    "CONFIDENCE_NOT_FOUND_PENALTY_MULTIPLIER",
    "CONFIDENCE_CITATION_COVERAGE_TARGET",
    "DOCUMENT_INDEX_VERSION",
    "EMBEDDING_BATCH_MAX_ITEMS",
    "EMBEDDING_BATCH_MAX_TOKENS",
    "EMBEDDING_RETRY_MAX_ATTEMPTS",
    "EMBEDDING_RETRY_BASE_SECONDS",
    "EMBEDDING_RETRY_MAX_SECONDS",
    "OPENAI_EMBEDDING_COST_PER_MILLION_TOKENS_USD",
    "LLM_RETRY_MAX_ATTEMPTS",
    "LLM_RETRY_BASE_SECONDS",
    "LLM_RETRY_MAX_SECONDS",
    "OPENAI_LLM_INPUT_COST_PER_MILLION_TOKENS_USD",
    "OPENAI_LLM_OUTPUT_COST_PER_MILLION_TOKENS_USD",
    "OPENAI_API_KEY",
    "AUTH_PROVIDER",
    "APP_AUTH_SECRET",
    "APP_AUTH_ACCESS_TOKEN_TTL_SECONDS",
    "APP_AUTH_ISSUER",
    "APP_AUTH_AUDIENCE",
    "CLERK_JWKS_URL",
    "SUPABASE_JWKS_URL",
]


@pytest.fixture(autouse=True)
def clear_config_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def valid_settings_kwargs() -> dict:
    return {
        "environment": Environment.development,
        "api_base_url": "http://localhost:8000",
        "frontend_base_url": "http://localhost:3000",
        "database_url": "postgresql+asyncpg://postgres:postgres@localhost:5432/rag_app",
        "qdrant_url": "http://localhost:6333",
        "qdrant_collection": "documents",
        "minio_endpoint": "http://localhost:9000",
        "minio_access_key": "minioadmin",
        "minio_secret_key": "minioadmin",
        "minio_bucket": "documents",
        "rabbitmq_url": "amqp://guest:guest@localhost:5672//",
        "redis_url": "redis://localhost:6379/0",
        "openai_api_key": "sk-test",
        "auth_provider": AuthProvider.app,
        "app_auth_secret": "test-secret",
        "app_auth_issuer": "rudix-test",
        "app_auth_audience": "rudix-test-audience",
        "cors_origins": "http://localhost:3000,http://127.0.0.1:3000",
    }


def test_valid_config_parsing() -> None:
    settings = Settings(_env_file=None, **valid_settings_kwargs())

    assert settings.environment == Environment.development
    assert str(settings.api_base_url) == "http://localhost:8000/"
    assert str(settings.frontend_base_url) == "http://localhost:3000/"
    assert settings.max_upload_size_mb == 25
    assert [str(origin) for origin in settings.cors_origins] == [
        "http://localhost:3000/",
        "http://127.0.0.1:3000/",
    ]


def test_missing_required_value_fails_fast() -> None:
    payload = valid_settings_kwargs()
    payload.pop("database_url")

    with pytest.raises(ValidationError):
        Settings(_env_file=None, **payload)


def test_malformed_url_fails_fast() -> None:
    payload = valid_settings_kwargs()
    payload["qdrant_url"] = "not-a-url"

    with pytest.raises(ValidationError):
        Settings(_env_file=None, **payload)


def test_invalid_numeric_limit_fails_fast() -> None:
    payload = valid_settings_kwargs()
    payload["max_upload_size_mb"] = 0

    with pytest.raises(ValidationError):
        Settings(_env_file=None, **payload)


def test_invalid_redis_timeout_relationship_fails_fast() -> None:
    payload = valid_settings_kwargs()
    payload["redis_socket_connect_timeout_seconds"] = 5
    payload["redis_socket_timeout_seconds"] = 1

    with pytest.raises(ValidationError):
        Settings(_env_file=None, **payload)


def test_invalid_dependency_timeout_relationship_fails_fast() -> None:
    payload = valid_settings_kwargs()
    payload["dependency_connect_timeout_seconds"] = 3
    payload["dependency_read_timeout_seconds"] = 1

    with pytest.raises(ValidationError):
        Settings(_env_file=None, **payload)


def test_invalid_celery_queue_name_fails_fast() -> None:
    payload = valid_settings_kwargs()
    payload["celery_queue_documents_processing"] = "documents processing"

    with pytest.raises(ValidationError):
        Settings(_env_file=None, **payload)


def test_invalid_document_index_version_fails_fast() -> None:
    payload = valid_settings_kwargs()
    payload["document_index_version"] = "v1 release"

    with pytest.raises(ValidationError):
        Settings(_env_file=None, **payload)


def test_invalid_embedding_retry_window_fails_fast() -> None:
    payload = valid_settings_kwargs()
    payload["embedding_retry_base_seconds"] = 2.0
    payload["embedding_retry_max_seconds"] = 1.0

    with pytest.raises(ValidationError):
        Settings(_env_file=None, **payload)


def test_invalid_llm_retry_window_fails_fast() -> None:
    payload = valid_settings_kwargs()
    payload["llm_retry_base_seconds"] = 2.0
    payload["llm_retry_max_seconds"] = 1.0

    with pytest.raises(ValidationError):
        Settings(_env_file=None, **payload)


def test_invalid_rerank_candidate_count_relationship_fails_fast() -> None:
    payload = valid_settings_kwargs()
    payload["retrieval_final_top_k"] = 10
    payload["rerank_mmr_candidate_count"] = 5

    with pytest.raises(ValidationError):
        Settings(_env_file=None, **payload)


def test_invalid_confidence_threshold_relationship_fails_fast() -> None:
    payload = valid_settings_kwargs()
    payload["confidence_medium_threshold"] = 0.7
    payload["confidence_high_threshold"] = 0.6

    with pytest.raises(ValidationError):
        Settings(_env_file=None, **payload)


def test_invalid_confidence_not_found_threshold_relationship_fails_fast() -> None:
    payload = valid_settings_kwargs()
    payload["confidence_medium_threshold"] = 0.5
    payload["confidence_not_found_threshold"] = 0.6

    with pytest.raises(ValidationError):
        Settings(_env_file=None, **payload)


def test_invalid_confidence_weight_sum_fails_fast() -> None:
    payload = valid_settings_kwargs()
    payload["confidence_weight_top_similarity"] = 0.0
    payload["confidence_weight_average_similarity"] = 0.0
    payload["confidence_weight_rerank_score"] = 0.0
    payload["confidence_weight_citation_support"] = 0.0
    payload["confidence_weight_agreement"] = 0.0

    with pytest.raises(ValidationError):
        Settings(_env_file=None, **payload)


def test_production_requires_sentry_dsn() -> None:
    payload = valid_settings_kwargs()
    payload["environment"] = Environment.production

    with pytest.raises(ValidationError):
        Settings(_env_file=None, **payload)


def test_production_rejects_default_app_auth_secret() -> None:
    payload = valid_settings_kwargs()
    payload["environment"] = Environment.production
    payload["sentry_dsn"] = "https://public@example.com/1"
    payload["app_auth_secret"] = "dev-insecure-change-me"

    with pytest.raises(ValidationError):
        Settings(_env_file=None, **payload)


def test_clerk_provider_requires_jwks() -> None:
    payload = valid_settings_kwargs()
    payload["auth_provider"] = AuthProvider.clerk
    payload.pop("clerk_jwks_url", None)

    with pytest.raises(ValidationError):
        Settings(_env_file=None, **payload)


def test_snapshot_redacts_secrets_and_credentials() -> None:
    payload = valid_settings_kwargs()
    payload["database_url"] = "postgresql+asyncpg://user:secret@db.internal:5432/rag_app"
    payload["rabbitmq_url"] = "amqp://guest:secret@mq.internal:5672//"

    settings = Settings(_env_file=None, **payload)
    snapshot = settings.sanitized_snapshot()

    assert snapshot["openai_api_key_set"] is True
    assert snapshot["minio_secret_key_set"] is True
    assert "secret" not in snapshot["database_url"]
    assert "secret" not in snapshot["rabbitmq_url"]


def test_rate_limit_disabled_by_default_in_development() -> None:
    settings = Settings(_env_file=None, **valid_settings_kwargs())

    assert settings.environment == Environment.development
    assert settings.is_rate_limit_active is False


def test_rate_limit_disabled_by_default_in_test_environment() -> None:
    payload = valid_settings_kwargs()
    payload["environment"] = Environment.test

    settings = Settings(_env_file=None, **payload)

    assert settings.is_rate_limit_active is False


def test_rate_limit_can_be_enabled_in_test_environment() -> None:
    payload = valid_settings_kwargs()
    payload["environment"] = Environment.test
    payload["rate_limit_disable_in_test"] = False

    settings = Settings(_env_file=None, **payload)

    assert settings.is_rate_limit_active is True
