import os
from typing import Any

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

from app.auth.errors import AuthenticationError, AuthorizationError
from app.auth.models import AuthenticatedPrincipal
from app.core.config import settings
from app.domains.agents.schemas import ToolCall
from app.mcp.resources import MCPResourceRuntime, register_mcp_resources


def _principal(*, role: str = "viewer") -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        user_id="user-123",
        organization_id="org-123",
        email="viewer@example.com",
        roles=[role],
        auth_provider="app",
    )


class _StubDocumentService:
    async def search_documents(
        self,
        call: ToolCall,
        principal: AuthenticatedPrincipal,
    ) -> dict[str, Any]:
        _ = principal
        return {
            "query": call.arguments.get("query"),
            "status": call.arguments.get("status"),
            "sort_by": call.arguments.get("sort_by"),
            "sort_order": call.arguments.get("sort_order"),
            "limit": call.arguments.get("limit"),
            "offset": call.arguments.get("offset"),
            "total": 1,
            "items": [
                {
                    "document_id": "c0000000-0000-4000-8000-000000000001",
                    "filename": "Policy Handbook.pdf",
                    "status": "indexed",
                }
            ],
        }

    async def get_document_detail(
        self,
        call: ToolCall,
        principal: AuthenticatedPrincipal,
    ) -> dict[str, Any]:
        _ = principal
        document_id = str(call.arguments.get("document_id"))
        if document_id == "invalid-id":
            raise ValueError("invalid document id")
        if document_id == "c0000000-0000-4000-8000-000000000099":
            raise AuthorizationError("not allowed")
        return {
            "document": {
                "document_id": document_id,
                "filename": "Policy Handbook.pdf",
                "status": "indexed",
                "error_message": None,
                "error_details": None,
                "created_at": "2026-05-23T00:00:00Z",
                "updated_at": "2026-05-23T00:01:00Z",
            }
        }

    async def list_document_chunks(
        self,
        call: ToolCall,
        principal: AuthenticatedPrincipal,
    ) -> dict[str, Any]:
        _ = principal
        limit = int(call.arguments.get("limit", 0))
        if limit > 200:
            raise ValueError("limit must be <= 200")
        return {
            "document_id": str(call.arguments.get("document_id")),
            "status": "indexed",
            "limit": limit,
            "offset": int(call.arguments.get("offset", 0)),
            "total": 1,
            "items": [
                {
                    "chunk_id": "d0000000-0000-4000-8000-000000000001",
                    "chunk_index": 0,
                    "page_number": 2,
                    "token_count": 88,
                    "preview": "Policy snippet.",
                    "embedding_model": "text-embedding-3-small",
                    "index_version": "v1",
                    "created_at": "2026-05-23T00:02:00Z",
                }
            ],
        }

    async def answer_from_context(
        self,
        call: ToolCall,
        principal: AuthenticatedPrincipal,
    ) -> dict[str, Any]:
        _ = principal
        long_snippet = "Policy snippet " * 30
        return {
            "response": "Grounded answer",
            "not_found": False,
            "confidence": {"score": 0.81, "category": "high"},
            "citations": [
                {
                    "document_id": "c0000000-0000-4000-8000-000000000001",
                    "chunk_id": "d0000000-0000-4000-8000-000000000001",
                    "filename": "Policy Handbook.pdf",
                    "page_number": 2,
                    "snippet": long_snippet,
                    "similarity_score": 0.91,
                }
            ],
            "debug": {
                "retrieval_count": 4,
                "selected_count": 2,
                "rerank_applied": True,
            },
            "request_question": call.arguments.get("question"),
        }


async def _noop_rate_limit(*, principal: AuthenticatedPrincipal, tool_name: str) -> None:
    _ = (principal, tool_name)


async def _resolve_viewer_principal(_: dict[str, str]) -> AuthenticatedPrincipal:
    return _principal()


async def _resolve_admin_principal(_: dict[str, str]) -> AuthenticatedPrincipal:
    return _principal(role="admin")


async def test_mcp_resource_runtime_documents_success(monkeypatch) -> None:
    runtime = MCPResourceRuntime(service=_StubDocumentService())  # type: ignore[arg-type]
    monkeypatch.setattr(settings, "feature_enable_mcp", True)
    monkeypatch.setattr("app.mcp.resource_runtime.get_http_headers_from_context", lambda: {})
    monkeypatch.setattr(
        "app.mcp.resource_runtime.resolve_mcp_principal",
        _resolve_viewer_principal,
    )
    monkeypatch.setattr("app.mcp.resource_runtime.enforce_mcp_rate_limit", _noop_rate_limit)

    payload = await runtime.read_documents(query="policy", limit=500, offset=0)

    assert payload["ok"] is True
    assert payload["resource"] == "documents.list"
    assert payload["data"]["total"] == 1
    assert payload["data"]["limit"] == 50
    assert payload["data"]["items"][0]["filename"] == "Policy Handbook.pdf"
    assert "error_details" not in payload["data"]["items"][0]


async def test_mcp_resource_runtime_returns_safe_auth_error(monkeypatch) -> None:
    runtime = MCPResourceRuntime(service=_StubDocumentService())  # type: ignore[arg-type]
    monkeypatch.setattr(settings, "feature_enable_mcp", True)
    monkeypatch.setattr("app.mcp.resource_runtime.get_http_headers_from_context", lambda: {})

    async def _auth_failure(_: dict[str, str]) -> AuthenticatedPrincipal:
        raise AuthenticationError("token=super-secret")

    monkeypatch.setattr("app.mcp.resource_runtime.resolve_mcp_principal", _auth_failure)
    monkeypatch.setattr("app.mcp.resource_runtime.enforce_mcp_rate_limit", _noop_rate_limit)

    payload = await runtime.read_documents(query="policy")

    assert payload["ok"] is False
    assert payload["error"]["code"] == "authorization_failed"
    assert "super-secret" not in str(payload)


async def test_mcp_resource_runtime_org_isolation(monkeypatch) -> None:
    runtime = MCPResourceRuntime(service=_StubDocumentService())  # type: ignore[arg-type]
    monkeypatch.setattr(settings, "feature_enable_mcp", True)
    monkeypatch.setattr("app.mcp.resource_runtime.get_http_headers_from_context", lambda: {})
    monkeypatch.setattr(
        "app.mcp.resource_runtime.resolve_mcp_principal",
        _resolve_viewer_principal,
    )
    monkeypatch.setattr("app.mcp.resource_runtime.enforce_mcp_rate_limit", _noop_rate_limit)

    payload = await runtime.read_document_detail(document_id="c0000000-0000-4000-8000-000000000099")

    assert payload["ok"] is False
    assert payload["error"]["code"] == "authorization_failed"


async def test_mcp_resource_runtime_validation_failure(monkeypatch) -> None:
    runtime = MCPResourceRuntime(service=_StubDocumentService())  # type: ignore[arg-type]
    monkeypatch.setattr(settings, "feature_enable_mcp", True)
    monkeypatch.setattr("app.mcp.resource_runtime.get_http_headers_from_context", lambda: {})
    monkeypatch.setattr(
        "app.mcp.resource_runtime.resolve_mcp_principal",
        _resolve_viewer_principal,
    )
    monkeypatch.setattr("app.mcp.resource_runtime.enforce_mcp_rate_limit", _noop_rate_limit)

    payload = await runtime.read_document_detail(document_id="invalid-id")

    assert payload["ok"] is False
    assert payload["error"]["code"] == "validation_failed"


async def test_mcp_resource_runtime_citations_payload(monkeypatch) -> None:
    runtime = MCPResourceRuntime(service=_StubDocumentService())  # type: ignore[arg-type]
    monkeypatch.setattr(settings, "feature_enable_mcp", True)
    monkeypatch.setattr("app.mcp.resource_runtime.get_http_headers_from_context", lambda: {})
    monkeypatch.setattr(
        "app.mcp.resource_runtime.resolve_mcp_principal",
        _resolve_admin_principal,
    )
    monkeypatch.setattr("app.mcp.resource_runtime.enforce_mcp_rate_limit", _noop_rate_limit)

    payload = await runtime.read_citations(
        query="policy+controls",
        document_id="c0000000-0000-4000-8000-000000000001",
        top_k=4,
        rerank=True,
    )

    assert payload["ok"] is True
    assert payload["resource"] == "documents.citations"
    assert payload["data"]["query"] == "policy controls"
    assert payload["data"]["citations"][0]["filename"] == "Policy Handbook.pdf"
    assert len(payload["data"]["citations"][0]["snippet"]) <= 180
    assert payload["data"]["retrieval"]["selected_count"] == 2


def test_register_mcp_resources_templates() -> None:
    registered_uris: list[str] = []

    class _StubServer:
        def resource(self, *args: Any, **kwargs: Any):  # type: ignore[no-untyped-def]
            if "uri" in kwargs:
                registered_uris.append(str(kwargs["uri"]))
            elif args:
                registered_uris.append(str(args[0]))
            else:
                raise AssertionError("resource registration missing uri")

            def _decorator(handler: Any) -> Any:
                return handler

            return _decorator

    register_mcp_resources(
        _StubServer(), runtime=MCPResourceRuntime(service=_StubDocumentService())
    )  # type: ignore[arg-type]

    assert "rudix://documents{?status,sort_by,sort_order,limit,offset,query}" in registered_uris
    assert "rudix://documents/{document_id}" in registered_uris
    assert "rudix://documents/{document_id}/status" in registered_uris
    assert "rudix://documents/{document_id}/chunks{?limit,offset}" in registered_uris
    assert "rudix://search/{query}{?status,sort_by,sort_order,limit,offset}" in registered_uris
    assert "rudix://citations/{query}{?document_id,top_k,rerank}" in registered_uris
