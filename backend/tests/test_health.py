from app.main import app
from fastapi.testclient import TestClient


def test_healthz_returns_ok() -> None:
    client = TestClient(app)

    response = client.get("/api/v1/healthz")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
