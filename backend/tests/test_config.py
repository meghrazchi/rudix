import json

import pytest
from pydantic import ValidationError

from app.core.config import AuthProvider, Environment, MCPTransport, Settings

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
    "EVALUATION_PREVENT_DUPLICATE_ACTIVE_RUNS",
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
    "APP_AUTH_REFRESH_TOKEN_TTL_SECONDS",
    "APP_AUTH_ISSUER",
    "APP_AUTH_AUDIENCE",
    "APP_AUTH_LOGIN_PASSWORD",
    "APP_AUTH_AUTO_PROVISION_USERS",
    "AUTH_JWKS_CACHE_TTL_SECONDS",
    "CLERK_JWKS_URL",
    "CLERK_JWT_ISSUER",
    "CLERK_JWT_AUDIENCE",
    "SUPABASE_JWKS_URL",
    "SUPABASE_JWT_ISSUER",
    "SUPABASE_JWT_AUDIENCE",
    "SENTRY_RELEASE",
    "SENTRY_ERROR_SAMPLE_RATE",
    "SENTRY_TRACES_SAMPLE_RATE",
    "SENTRY_PROFILES_SAMPLE_RATE",
    "SENTRY_TEST_EVENT_ENABLED",
    "MALWARE_SCAN_ENABLED",
    "MALWARE_SCAN_REQUIRED",
    "MALWARE_SCAN_BYPASS_ON_UNAVAILABLE",
    "MALWARE_SCAN_CLAMAV_HOST",
    "MALWARE_SCAN_CLAMAV_PORT",
    "MALWARE_SCAN_TIMEOUT_SECONDS",
    "MALWARE_SCAN_MAX_BYTES",
    "MALWARE_SCAN_STREAM_CHUNK_SIZE_BYTES",
    "FEATURE_ENABLE_MCP",
    "MCP_SERVER_NAME",
    "MCP_TRANSPORT",
    "MCP_HTTP_HOST",
    "MCP_HTTP_PORT",
    "MCP_HTTP_PATH",
    "MCP_REQUIRE_BEARER_AUTH",
    "MCP_DEV_PRINCIPAL_USER_ID",
    "MCP_DEV_PRINCIPAL_ORGANIZATION_ID",
    "MCP_DEV_PRINCIPAL_ROLES",
    "MCP_CAPABILITIES_OWNER",
    "MCP_CAPABILITIES_ADMIN",
    "MCP_CAPABILITIES_MEMBER",
    "MCP_CAPABILITIES_VIEWER",
    "MCP_RATE_LIMIT_ENABLED",
    "MCP_RATE_LIMIT_WINDOW_SECONDS",
    "MCP_RATE_LIMIT_REQUESTS",
    "FEATURE_ENABLE_EXTERNAL_MCP_CONNECTORS",
    "MCP_EXTERNAL_SERVERS",
    "CONNECTOR_CREDENTIAL_ENCRYPTION_KEY",
    "CONNECTOR_CREDENTIAL_ENCRYPTION_KEY_ID",
    "CONNECTOR_OAUTH_STATE_TTL_SECONDS",
    "CONNECTOR_OAUTH_CLIENTS",
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


def test_invalid_malware_scan_size_limit_fails_fast() -> None:
    payload = valid_settings_kwargs()
    payload["max_upload_size_mb"] = 1
    payload["malware_scan_max_bytes"] = 2 * 1024 * 1024

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


def test_production_rejects_sentry_test_endpoint_flag() -> None:
    payload = valid_settings_kwargs()
    payload["environment"] = Environment.production
    payload["sentry_dsn"] = "https://public@example.com/1"
    payload["sentry_test_event_enabled"] = True

    with pytest.raises(ValidationError):
        Settings(_env_file=None, **payload)


def test_production_rejects_malware_scan_bypass_when_required() -> None:
    payload = valid_settings_kwargs()
    payload["environment"] = Environment.production
    payload["sentry_dsn"] = "https://public@example.com/1"
    payload["malware_scan_required"] = True
    payload["malware_scan_bypass_on_unavailable"] = True

    with pytest.raises(ValidationError):
        Settings(_env_file=None, **payload)


def test_malware_scan_required_requires_enabled_flag() -> None:
    payload = valid_settings_kwargs()
    payload["malware_scan_enabled"] = False
    payload["malware_scan_required"] = True

    with pytest.raises(ValidationError):
        Settings(_env_file=None, **payload)


def test_sentry_test_event_enabled_defaults_to_true_in_test() -> None:
    payload = valid_settings_kwargs()
    payload["environment"] = Environment.test

    settings = Settings(_env_file=None, **payload)

    assert settings.is_sentry_test_event_enabled is True


def test_clerk_provider_requires_jwks() -> None:
    payload = valid_settings_kwargs()
    payload["auth_provider"] = AuthProvider.clerk
    payload.pop("clerk_jwks_url", None)

    with pytest.raises(ValidationError):
        Settings(_env_file=None, **payload)


def test_clerk_provider_requires_issuer_and_audience() -> None:
    payload = valid_settings_kwargs()
    payload["auth_provider"] = AuthProvider.clerk
    payload["clerk_jwks_url"] = "https://example.com/.well-known/jwks.json"
    payload.pop("clerk_jwt_issuer", None)

    with pytest.raises(ValidationError):
        Settings(_env_file=None, **payload)

    payload = valid_settings_kwargs()
    payload["auth_provider"] = AuthProvider.clerk
    payload["clerk_jwks_url"] = "https://example.com/.well-known/jwks.json"
    payload["clerk_jwt_issuer"] = "https://clerk.example.com"
    payload.pop("clerk_jwt_audience", None)

    with pytest.raises(ValidationError):
        Settings(_env_file=None, **payload)


def test_snapshot_redacts_secrets_and_credentials() -> None:
    payload = valid_settings_kwargs()
    payload["database_url"] = "postgresql+asyncpg://user:secret@db.internal:5432/rag_app"
    payload["rabbitmq_url"] = "amqp://guest:secret@mq.internal:5672//"
    payload["feature_enable_mcp"] = True
    payload["mcp_dev_principal_user_id"] = "user-dev-001"
    payload["mcp_dev_principal_organization_id"] = "org-dev-001"
    payload["mcp_dev_principal_roles"] = "owner"

    settings = Settings(_env_file=None, **payload)
    snapshot = settings.sanitized_snapshot()

    assert snapshot["openai_api_key_set"] is True
    assert snapshot["minio_secret_key_set"] is True
    assert "secret" not in snapshot["database_url"]
    assert "secret" not in snapshot["rabbitmq_url"]
    assert snapshot["features"]["mcp"] is True
    assert snapshot["mcp"]["dev_principal_user_id_set"] is True


def test_connector_oauth_client_snapshot_redacts_client_secret() -> None:
    payload = valid_settings_kwargs()
    payload["connector_credential_encryption_key"] = "connector-encryption-secret"
    payload["connector_oauth_clients"] = [
        {
            "provider_key": "jira",
            "client_id": "jira-client-id",
            "client_secret": "jira-client-secret",
            "redirect_uri": "https://app.example.com/api/v1/connectors/oauth/callback",
        }
    ]

    settings = Settings(_env_file=None, **payload)
    snapshot = settings.sanitized_snapshot()

    assert snapshot["connector_credentials"]["encryption_key_set"] is True
    assert snapshot["connector_credentials"]["oauth_clients"][0]["provider_key"] == "jira"
    assert snapshot["connector_credentials"]["oauth_clients"][0]["client_secret_set"] is True
    assert "jira-client-secret" not in str(snapshot)


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


def test_mcp_stdio_requires_dev_principal_configuration() -> None:
    payload = valid_settings_kwargs()
    payload["feature_enable_mcp"] = True
    payload["mcp_transport"] = MCPTransport.stdio

    with pytest.raises(ValidationError):
        Settings(_env_file=None, **payload)


def test_mcp_stdio_is_rejected_in_production() -> None:
    payload = valid_settings_kwargs()
    payload["environment"] = Environment.production
    payload["sentry_dsn"] = "https://public@example.com/1"
    payload["feature_enable_mcp"] = True
    payload["mcp_transport"] = MCPTransport.stdio
    payload["mcp_dev_principal_user_id"] = "user-dev-001"
    payload["mcp_dev_principal_organization_id"] = "org-dev-001"
    payload["mcp_dev_principal_roles"] = "owner"

    with pytest.raises(ValidationError):
        Settings(_env_file=None, **payload)


def test_mcp_stdio_accepts_valid_dev_principal_configuration() -> None:
    payload = valid_settings_kwargs()
    payload["feature_enable_mcp"] = True
    payload["mcp_transport"] = MCPTransport.stdio
    payload["mcp_dev_principal_user_id"] = "user-dev-001"
    payload["mcp_dev_principal_organization_id"] = "org-dev-001"
    payload["mcp_dev_principal_roles"] = "owner,viewer"

    parsed = Settings(_env_file=None, **payload)

    assert parsed.feature_enable_mcp is True
    assert parsed.mcp_transport == MCPTransport.stdio
    assert parsed.mcp_dev_principal_roles == ["owner", "viewer"]


def test_streamable_mcp_optional_auth_requires_dev_principal() -> None:
    payload = valid_settings_kwargs()
    payload["feature_enable_mcp"] = True
    payload["mcp_transport"] = MCPTransport.streamable_http
    payload["mcp_require_bearer_auth"] = False

    with pytest.raises(ValidationError):
        Settings(_env_file=None, **payload)


def test_streamable_mcp_optional_auth_is_rejected_in_production() -> None:
    payload = valid_settings_kwargs()
    payload["environment"] = Environment.production
    payload["sentry_dsn"] = "https://public@example.com/1"
    payload["feature_enable_mcp"] = True
    payload["mcp_transport"] = MCPTransport.streamable_http
    payload["mcp_require_bearer_auth"] = False
    payload["mcp_dev_principal_user_id"] = "user-dev-001"
    payload["mcp_dev_principal_organization_id"] = "org-dev-001"
    payload["mcp_dev_principal_roles"] = "viewer"

    with pytest.raises(ValidationError):
        Settings(_env_file=None, **payload)


def test_mcp_capabilities_parse_and_normalize() -> None:
    payload = valid_settings_kwargs()
    payload["feature_enable_mcp"] = True
    payload["mcp_capabilities_viewer"] = "documents.read,pipeline.read,documents.read"

    parsed = Settings(_env_file=None, **payload)

    assert parsed.mcp_capabilities_viewer == ["documents.read", "pipeline.read"]


def test_external_mcp_servers_parse_from_json() -> None:
    payload = valid_settings_kwargs()
    payload["feature_enable_external_mcp_connectors"] = True
    payload["mcp_external_servers"] = json.dumps(
        [
            {
                "server_id": "acme_tools",
                "enabled": True,
                "transport": "streamable_http",
                "base_url": "https://mcp.example.com/mcp",
                "auth_type": "bearer",
                "auth_token": "external-token",
                "allow_tools": ["lookup_customer", "lookup_invoice"],
                "read_only_tools": ["lookup_customer"],
                "required_roles": ["owner", "admin"],
            }
        ]
    )

    parsed = Settings(_env_file=None, **payload)

    assert parsed.feature_enable_external_mcp_connectors is True
    assert len(parsed.mcp_external_servers) == 1
    server = parsed.mcp_external_servers[0]
    assert server.server_id == "acme_tools"
    assert server.allow_tools == ["lookup_customer", "lookup_invoice"]
    assert server.read_only_tools == ["lookup_customer"]
    assert server.required_roles == ["owner", "admin"]


def test_external_mcp_requires_auth_in_production() -> None:
    payload = valid_settings_kwargs()
    payload["environment"] = Environment.production
    payload["sentry_dsn"] = "https://public@example.com/1"
    payload["feature_enable_external_mcp_connectors"] = True
    payload["mcp_external_servers"] = [
        {
            "server_id": "acme_tools",
            "enabled": True,
            "transport": "streamable_http",
            "base_url": "https://mcp.example.com/mcp",
            "auth_type": "none",
            "allow_tools": ["lookup_customer"],
            "required_roles": ["owner"],
        }
    ]

    with pytest.raises(ValidationError):
        Settings(_env_file=None, **payload)
