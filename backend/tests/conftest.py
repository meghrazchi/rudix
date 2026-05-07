from fastapi.testclient import TestClient


def get_test_client() -> TestClient:
    from app.main import app

    return TestClient(app)
