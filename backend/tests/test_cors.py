from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app


def test_documents_preflight_allows_frontend_origin() -> None:
    client = TestClient(app)
    origin = str(settings.frontend_base_url).rstrip("/")

    response = client.options(
        "/api/v1/documents",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization,x-organization-id,x-request-id",
        },
    )

    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == origin
