"""Request-level helpers shared by the chat transports and the pipeline (R05-01)."""

from typing import Any
from uuid import UUID

from fastapi import HTTPException, Request, status

from app.auth.models import AuthenticatedPrincipal
from app.clients import qdrant_client as qdrant_module


def _principal_user_and_org(principal: AuthenticatedPrincipal) -> tuple[UUID, UUID]:
    if principal.organization_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No active organization context for principal",
        )
    try:
        return UUID(principal.user_id), UUID(principal.organization_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Principal identity context is invalid",
        ) from exc


def _get_qdrant_client() -> Any:
    """Search client of the chat request path (R06-07).

    ``AsyncQdrantClient`` with ``QDRANT_SEARCH_TIMEOUT_SECONDS`` for the running loop; a
    client injected into ``qdrant_client.qdrant_client`` (tests, tools) is used instead.
    """
    injected = qdrant_module.injected_sync_client()
    if injected is not None:
        return injected
    return qdrant_module.get_async_search_client()


def _request_id_from_request(request: Request) -> str | None:
    request_id = getattr(request.state, "request_id", None)
    if isinstance(request_id, str) and request_id.strip():
        return request_id
    return request.headers.get("x-request-id")
