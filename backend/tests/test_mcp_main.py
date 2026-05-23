import os

# Ensure strict settings can be loaded when app imports in tests.
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
os.environ.setdefault("RABBITMQ_URL", "amqp://guest:guest@localhost:5672//")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("OPENAI_API_KEY", "sk-test")
os.environ.setdefault("AUTH_PROVIDER", "app")
os.environ.setdefault("APP_AUTH_SECRET", "test-secret")

from app.core.config import Environment, MCPTransport, settings
from app.mcp.main import main


def test_mcp_main_returns_nonzero_when_feature_flag_is_disabled(
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "feature_enable_mcp", False)

    exit_code = main([])

    assert exit_code == 2


def test_mcp_main_runs_streamable_http_transport(
    monkeypatch,
) -> None:
    called = {"streamable": False}
    monkeypatch.setattr(settings, "feature_enable_mcp", True)
    monkeypatch.setattr(settings, "mcp_transport", MCPTransport.streamable_http)
    monkeypatch.setattr(
        "app.mcp.main.run_streamable_http_server", lambda: called.__setitem__("streamable", True)
    )

    exit_code = main([])

    assert exit_code == 0
    assert called["streamable"] is True


def test_mcp_main_rejects_stdio_transport_in_production(
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "feature_enable_mcp", True)
    monkeypatch.setattr(settings, "environment", Environment.production)
    monkeypatch.setattr(settings, "mcp_transport", MCPTransport.streamable_http)

    exit_code = main(["--transport", "stdio"])

    assert exit_code == 2
