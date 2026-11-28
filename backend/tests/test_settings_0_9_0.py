"""0.9.0 settings modules, snapshot section, and shared anchors (S1)."""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest
from pydantic import BaseModel, ValidationError

from app.core import config as config_module
from app.core.config import Settings
from app.core.settings import account_security, billing
from app.core.settings.account_security import AccountSecuritySettings
from app.core.settings.billing import BillingSettings
from tests.test_settings_split import SNAPSHOT_ENV

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = BACKEND_DIR.parent
TASKS = ("A1", "A2", "A3", "B1", "B2", "C1", "C2", "D1")


def _fresh(monkeypatch: pytest.MonkeyPatch, **env: str) -> Settings:
    for name in ("BILLING_PROVIDER", "AUTH_ONE_TIME_TOKEN_RETENTION_HOURS"):
        monkeypatch.delenv(name, raising=False)
    for key, value in {**SNAPSHOT_ENV, **env}.items():
        monkeypatch.setenv(key, value)
    return Settings(_env_file=None)  # type: ignore[call-arg]


def test_defaults_keep_todays_behaviour(monkeypatch: pytest.MonkeyPatch) -> None:
    loaded = _fresh(monkeypatch)
    assert loaded.billing_provider == "none"
    assert loaded.auth_one_time_token_retention_hours == 24
    assert issubclass(Settings, AccountSecuritySettings)
    assert issubclass(Settings, BillingSettings)


def test_values_are_validated(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _fresh(monkeypatch, BILLING_PROVIDER="stripe").billing_provider == "stripe"
    with pytest.raises(ValidationError):
        _fresh(monkeypatch, BILLING_PROVIDER="paypal")
    with pytest.raises(ValidationError):
        _fresh(monkeypatch, AUTH_ONE_TIME_TOKEN_RETENTION_HOURS="0")


def test_snapshot_has_the_product_completeness_section(monkeypatch: pytest.MonkeyPatch) -> None:
    section = _fresh(monkeypatch).sanitized_snapshot()["product_completeness"]
    assert section == {"billing_provider": "none", "auth_one_time_token_retention_hours": 24}
    source = (BACKEND_DIR / "app/core/settings/snapshot.py").read_text()
    for task in TASKS:
        assert f"# anchor: v090-{task}" in source


def test_validators_run_from_the_settings_model_validator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        config_module, "validate_account_security", lambda s: calls.append("account")
    )
    monkeypatch.setattr(config_module, "validate_billing", lambda s: calls.append("billing"))
    _fresh(monkeypatch)
    assert calls == ["account", "billing"]
    # The stubs accept a settings object and change nothing.
    loaded = _fresh(monkeypatch)
    account_security.validate_account_security(loaded)
    billing.validate_billing(loaded)
    assert loaded.billing_provider == "none"


def test_no_setting_is_defined_by_two_bases() -> None:
    owners: dict[str, str] = {}
    duplicates: list[str] = []
    for base in Settings.__mro__:
        if not (isinstance(base, type) and issubclass(base, BaseModel)) or base is Settings:
            continue
        for name in inspect.get_annotations(base):
            if name.startswith("_") or name == "model_config":
                continue
            if name in owners and owners[name] != base.__name__:
                duplicates.append(f"{name}: {owners[name]} and {base.__name__}")
            owners.setdefault(name, base.__name__)
    assert duplicates == []


def test_module_anchors_exist() -> None:
    account = inspect.getsource(account_security)
    for task in ("A1", "A2", "A3"):
        assert account.count(f"# v090-{task}") == 2
    billing_source = inspect.getsource(billing)
    for task in ("B1", "B2"):
        assert billing_source.count(f"# v090-{task}") == 2
    router = (BACKEND_DIR / "app/api/router.py").read_text()
    celery = (BACKEND_DIR / "app/workers/celery_app.py").read_text()
    env_example = (REPO_DIR / ".env.example").read_text()
    assert "# --- Product completeness (0.9.0) ---" in env_example
    assert "\nBILLING_PROVIDER=none\n" in env_example
    for task in TASKS:
        assert router.count(f"# anchor: v090-{task}\n") == 2
        assert env_example.count(f"# anchor: v090-{task}\n") == 1
    for task in ("S1", "A1", "B1", "D1"):
        assert celery.count(f"# anchor: v090-{task}\n") == 3
    assert "# v090-A1" in (BACKEND_DIR / "app/workers/account_tasks.py").read_text()
