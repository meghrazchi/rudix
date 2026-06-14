"""Backend tests for F279: Neo4j Enterprise Graph infrastructure.

Covers:
  A. Config: enterprise_graph_enabled=false — default, no validation errors
  B. Config: enterprise_graph_enabled=true, missing neo4j_uri — ValidationError
  C. Config: enterprise_graph_enabled=true, missing neo4j_username — ValidationError
  D. Config: enterprise_graph_enabled=true, missing neo4j_password — ValidationError
  E. Config: enterprise_graph_enabled=true, all required fields — no error
  F. Config: neo4j_uri invalid scheme — ValidationError
  G. Config: neo4j_uri valid bolt+s:// scheme — accepted
  H. Config: sanitized_snapshot includes enterprise_graph block, no credentials
  I. init_neo4j disabled — no-op, driver stays None
  J. init_neo4j enabled, verify_connectivity fails — driver stays None, no raise
  K. init_neo4j enabled, success — driver is set
  L. close_neo4j — closes driver, resets to None
  M. check_neo4j_health disabled — returns True (not applicable)
  N. check_neo4j_health driver None — returns False
  O. check_neo4j_health session query fails — returns False
  P. check_neo4j_health session query succeeds — returns True
  Q. GET /admin/graph/health — disabled → {enabled:false, status:disabled}
  R. GET /admin/graph/health — enabled, driver None → status=unavailable
  S. GET /admin/graph/health — enabled, driver active, healthy → status=connected
  T. GET /admin/graph/health — enabled, driver active, query fails → status=unavailable
  U. GET /admin/graph/health — member role → 403
  V. /ready includes neo4j dependency when enabled
  W. /ready excludes neo4j dependency when disabled

Run:
    pytest tests/test_graph_health_f279.py -v
"""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

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

from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app

import app.clients.neo4j_client as neo4j_module

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _reset_driver() -> None:
    neo4j_module._neo4j_driver = None


def _make_admin_token() -> str:
    from app.auth.token_codec import create_app_access_token

    return create_app_access_token(
        user_id="user-admin",
        organization_id="org-1",
        roles=["owner"],
        settings=settings,
    )


def _make_member_token() -> str:
    from app.auth.token_codec import create_app_access_token

    return create_app_access_token(
        user_id="user-member",
        organization_id="org-1",
        roles=["member"],
        settings=settings,
    )


# ---------------------------------------------------------------------------
# A-H. Config validation tests
# ---------------------------------------------------------------------------


def test_a_enterprise_graph_disabled_by_default() -> None:
    assert settings.enterprise_graph_enabled is False


def test_b_enabled_without_uri_raises() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="neo4j_uri is required"):
        settings.model_validate(
            {
                **settings.model_dump(),
                "enterprise_graph_enabled": True,
                "neo4j_uri": None,
                "neo4j_username": "neo4j",
                "neo4j_password": "secret",
            }
        )


def test_c_enabled_without_username_raises() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="neo4j_username is required"):
        settings.model_validate(
            {
                **settings.model_dump(),
                "enterprise_graph_enabled": True,
                "neo4j_uri": "bolt://localhost:7687",
                "neo4j_username": None,
                "neo4j_password": "secret",
            }
        )


def test_d_enabled_without_password_raises() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="neo4j_password is required"):
        settings.model_validate(
            {
                **settings.model_dump(),
                "enterprise_graph_enabled": True,
                "neo4j_uri": "bolt://localhost:7687",
                "neo4j_username": "neo4j",
                "neo4j_password": None,
            }
        )


def test_e_enabled_with_all_fields_passes() -> None:
    from pydantic import SecretStr

    validated = settings.model_validate(
        {
            **settings.model_dump(),
            "enterprise_graph_enabled": True,
            "neo4j_uri": "bolt://localhost:7687",
            "neo4j_username": "neo4j",
            "neo4j_password": SecretStr("pass"),
        }
    )
    assert validated.enterprise_graph_enabled is True
    assert validated.neo4j_database == "neo4j"


def test_f_invalid_uri_scheme_raises() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="neo4j_uri must start with"):
        settings.model_validate(
            {
                **settings.model_dump(),
                "neo4j_uri": "http://localhost:7687",
            }
        )


def test_g_bolt_plus_s_scheme_accepted() -> None:
    validated = settings.model_validate(
        {
            **settings.model_dump(),
            "neo4j_uri": "bolt+s://localhost:7687",
        }
    )
    assert validated.neo4j_uri == "bolt+s://localhost:7687"


def test_h_sanitized_snapshot_enterprise_graph_block_no_credentials() -> None:
    snapshot = settings.sanitized_snapshot()
    graph = snapshot["enterprise_graph"]
    assert "enabled" in graph
    assert "uri_set" in graph
    assert "database" in graph
    # Credentials must never appear
    assert "password" not in str(graph).lower()
    assert "neo4j_password" not in str(graph)
    assert "secret" not in str(graph).lower()


# ---------------------------------------------------------------------------
# I-L. neo4j_client init / close
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_i_init_neo4j_disabled_is_noop() -> None:
    _reset_driver()
    with patch.object(settings, "enterprise_graph_enabled", False):
        await neo4j_module.init_neo4j()
    assert neo4j_module._neo4j_driver is None


@pytest.mark.asyncio
async def test_j_init_neo4j_connectivity_fails_does_not_raise() -> None:
    _reset_driver()
    mock_driver = AsyncMock()
    mock_driver.verify_connectivity = AsyncMock(side_effect=ConnectionRefusedError("refused"))
    mock_driver.close = AsyncMock()

    with (
        patch.object(settings, "enterprise_graph_enabled", True),
        patch.object(settings, "neo4j_uri", "bolt://localhost:7687"),
        patch.object(settings, "neo4j_username", "neo4j"),
        patch.object(settings, "neo4j_password", MagicMock(get_secret_value=lambda: "pass")),
        patch("app.clients.neo4j_client._NEO4J_PACKAGE_AVAILABLE", True),
        patch(
            "app.clients.neo4j_client.AsyncGraphDatabase",
            MagicMock(driver=MagicMock(return_value=mock_driver)),
        ),
    ):
        await neo4j_module.init_neo4j()

    assert neo4j_module._neo4j_driver is None


@pytest.mark.asyncio
async def test_k_init_neo4j_success_sets_driver() -> None:
    _reset_driver()
    mock_driver = AsyncMock()
    mock_driver.verify_connectivity = AsyncMock(return_value=None)

    with (
        patch.object(settings, "enterprise_graph_enabled", True),
        patch.object(settings, "neo4j_uri", "bolt://localhost:7687"),
        patch.object(settings, "neo4j_username", "neo4j"),
        patch.object(settings, "neo4j_password", MagicMock(get_secret_value=lambda: "pass")),
        patch("app.clients.neo4j_client._NEO4J_PACKAGE_AVAILABLE", True),
        patch(
            "app.clients.neo4j_client.AsyncGraphDatabase",
            MagicMock(driver=MagicMock(return_value=mock_driver)),
        ),
    ):
        await neo4j_module.init_neo4j()

    assert neo4j_module._neo4j_driver is mock_driver
    _reset_driver()


@pytest.mark.asyncio
async def test_l_close_neo4j_calls_close_and_resets() -> None:
    mock_driver = AsyncMock()
    mock_driver.close = AsyncMock()
    neo4j_module._neo4j_driver = mock_driver  # type: ignore[assignment]

    await neo4j_module.close_neo4j()

    mock_driver.close.assert_awaited_once()
    assert neo4j_module._neo4j_driver is None


# ---------------------------------------------------------------------------
# M-P. check_neo4j_health
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_m_health_check_disabled_returns_true() -> None:
    _reset_driver()
    with patch.object(settings, "enterprise_graph_enabled", False):
        result = await neo4j_module.check_neo4j_health()
    assert result is True


@pytest.mark.asyncio
async def test_n_health_check_driver_none_returns_false() -> None:
    _reset_driver()
    with patch.object(settings, "enterprise_graph_enabled", True):
        result = await neo4j_module.check_neo4j_health()
    assert result is False


@pytest.mark.asyncio
async def test_o_health_check_session_query_fails_returns_false() -> None:
    _reset_driver()
    mock_result = AsyncMock()
    mock_result.consume = AsyncMock(side_effect=RuntimeError("query error"))
    mock_session = AsyncMock()
    mock_session.run = AsyncMock(return_value=mock_result)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)
    mock_driver = MagicMock()
    mock_driver.session = MagicMock(return_value=mock_session)
    neo4j_module._neo4j_driver = mock_driver  # type: ignore[assignment]

    with patch.object(settings, "enterprise_graph_enabled", True):
        result = await neo4j_module.check_neo4j_health()

    assert result is False
    _reset_driver()


@pytest.mark.asyncio
async def test_p_health_check_session_query_succeeds_returns_true() -> None:
    _reset_driver()
    mock_result = AsyncMock()
    mock_result.consume = AsyncMock(return_value=None)
    mock_session = AsyncMock()
    mock_session.run = AsyncMock(return_value=mock_result)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)
    mock_driver = MagicMock()
    mock_driver.session = MagicMock(return_value=mock_session)
    neo4j_module._neo4j_driver = mock_driver  # type: ignore[assignment]

    with patch.object(settings, "enterprise_graph_enabled", True):
        result = await neo4j_module.check_neo4j_health()

    assert result is True
    _reset_driver()


# ---------------------------------------------------------------------------
# Q-U. GET /admin/graph/health endpoint
# ---------------------------------------------------------------------------


def _patch_all_ready_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _ok() -> bool:
        return True

    monkeypatch.setattr("app.api.health.check_database_health", _ok)
    monkeypatch.setattr("app.api.health.check_redis_health", _ok)
    monkeypatch.setattr("app.api.health.check_rabbitmq_health", _ok)
    monkeypatch.setattr("app.api.health.check_qdrant_health", lambda: True)
    monkeypatch.setattr("app.api.health.check_minio_health", lambda: True)


def test_q_graph_health_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "enterprise_graph_enabled", False)
    token = _make_admin_token()
    client = TestClient(app)

    response = client.get(
        "/api/v1/admin/graph/health",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is False
    assert body["status"] == "disabled"


def test_r_graph_health_enabled_driver_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "enterprise_graph_enabled", True)
    monkeypatch.setattr(settings, "neo4j_uri", "bolt://localhost:7687")
    monkeypatch.setattr(settings, "neo4j_database", "neo4j")
    neo4j_module._neo4j_driver = None
    token = _make_admin_token()
    client = TestClient(app)

    response = client.get(
        "/api/v1/admin/graph/health",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is True
    assert body["status"] == "unavailable"
    assert body["detail"] == "neo4j_driver_not_initialized"


def test_s_graph_health_enabled_connected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "enterprise_graph_enabled", True)
    monkeypatch.setattr(settings, "neo4j_uri", "bolt://localhost:7687")
    monkeypatch.setattr(settings, "neo4j_database", "neo4j")
    neo4j_module._neo4j_driver = MagicMock()  # type: ignore[assignment]
    monkeypatch.setattr(neo4j_module, "check_neo4j_health", AsyncMock(return_value=True))
    token = _make_admin_token()
    client = TestClient(app)

    response = client.get(
        "/api/v1/admin/graph/health",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is True
    assert body["status"] == "connected"
    assert body["detail"] is None
    _reset_driver()


def test_t_graph_health_enabled_query_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "enterprise_graph_enabled", True)
    monkeypatch.setattr(settings, "neo4j_uri", "bolt://localhost:7687")
    monkeypatch.setattr(settings, "neo4j_database", "neo4j")
    neo4j_module._neo4j_driver = MagicMock()  # type: ignore[assignment]
    monkeypatch.setattr(neo4j_module, "check_neo4j_health", AsyncMock(return_value=False))
    token = _make_admin_token()
    client = TestClient(app)

    response = client.get(
        "/api/v1/admin/graph/health",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is True
    assert body["status"] == "unavailable"
    assert body["detail"] == "neo4j_query_failed"
    _reset_driver()


def test_u_graph_health_member_gets_403(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "enterprise_graph_enabled", False)
    token = _make_member_token()
    client = TestClient(app)

    response = client.get(
        "/api/v1/admin/graph/health",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403


# ---------------------------------------------------------------------------
# V-W. /ready includes/excludes neo4j based on feature flag
# ---------------------------------------------------------------------------


def test_v_ready_includes_neo4j_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_all_ready_ok(monkeypatch)
    monkeypatch.setattr(settings, "enterprise_graph_enabled", True)
    monkeypatch.setattr("app.api.health.check_neo4j_health", AsyncMock(return_value=True))
    client = TestClient(app)

    response = client.get("/api/v1/ready")

    assert response.status_code == 200
    body = response.json()
    assert "neo4j" in body["dependencies"]


def test_w_ready_excludes_neo4j_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_all_ready_ok(monkeypatch)
    monkeypatch.setattr(settings, "enterprise_graph_enabled", False)
    client = TestClient(app)

    response = client.get("/api/v1/ready")

    assert response.status_code == 200
    body = response.json()
    assert "neo4j" not in body["dependencies"]
