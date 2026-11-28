"""APP_AUTH_SECRET rotation with a verify-only previous secret (R08-11)."""

from __future__ import annotations

import base64
import json
import logging
import os
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import SecretStr

os.environ.setdefault("ENVIRONMENT", "test")


from app.auth import token_codec
from app.auth.errors import AuthenticationError
from app.core.config import Settings, settings
from app.core.metrics import registry
from app.domains.bots.services import oauth
from tests.test_settings_split import SNAPSHOT_ENV, _clear_settings_env

OLD_SECRET = "rotation-old-secret-value-0001"
NEW_SECRET = "rotation-new-secret-value-0002"
VERIFIED_BY_PREVIOUS = "rudix_auth_token_verified_by_previous_key_total"


def _previous_key_count(kind: str) -> float:
    value = registry.get_sample_value(VERIFIED_BY_PREVIOUS, {"kind": kind})
    return value or 0.0


@pytest.fixture
def metrics_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "metrics_enabled", True)


def _rotate(monkeypatch: pytest.MonkeyPatch, *, previous: str | None) -> None:
    monkeypatch.setattr(settings, "app_auth_secret", SecretStr(NEW_SECRET))
    monkeypatch.setattr(
        settings,
        "app_auth_secret_previous",
        SecretStr(previous) if previous is not None else None,
    )


def _old_tokens(monkeypatch: pytest.MonkeyPatch) -> tuple[str, str]:
    monkeypatch.setattr(settings, "app_auth_secret", SecretStr(OLD_SECRET))
    monkeypatch.setattr(settings, "app_auth_secret_previous", None)
    access = token_codec.create_app_access_token(subject="user-1", organization_id="org-1")
    refresh = token_codec.create_app_refresh_token(subject="user-1", session_id="s-1")
    return access, refresh


@pytest.mark.usefixtures("metrics_on")
def test_old_secret_tokens_valid_while_previous_is_set(monkeypatch: pytest.MonkeyPatch) -> None:
    access, refresh = _old_tokens(monkeypatch)
    _rotate(monkeypatch, previous=OLD_SECRET)
    access_before = _previous_key_count("access")
    refresh_before = _previous_key_count("refresh")

    assert token_codec.decode_app_access_token(access)["sub"] == "user-1"
    assert token_codec.decode_app_refresh_token(refresh)["session_id"] == "s-1"

    assert _previous_key_count("access") == access_before + 1
    assert _previous_key_count("refresh") == refresh_before + 1


def test_old_secret_tokens_rejected_after_previous_removed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    access, refresh = _old_tokens(monkeypatch)
    _rotate(monkeypatch, previous=None)
    with pytest.raises(AuthenticationError, match="Invalid token signature"):
        token_codec.decode_app_access_token(access)
    with pytest.raises(AuthenticationError, match="Invalid token signature"):
        token_codec.decode_app_refresh_token(refresh)


@pytest.mark.usefixtures("metrics_on")
def test_new_tokens_are_signed_with_current_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    _rotate(monkeypatch, previous=OLD_SECRET)
    access = token_codec.create_app_access_token(subject="user-2")
    before = _previous_key_count("access")
    assert token_codec.decode_app_access_token(access)["sub"] == "user-2"
    assert _previous_key_count("access") == before

    # Without the previous secret the new token still verifies: it never used it.
    monkeypatch.setattr(settings, "app_auth_secret_previous", None)
    assert token_codec.decode_app_access_token(access)["sub"] == "user-2"
    # And the old secret alone does not verify it.
    monkeypatch.setattr(settings, "app_auth_secret", SecretStr(OLD_SECRET))
    with pytest.raises(AuthenticationError, match="Invalid token signature"):
        token_codec.decode_app_access_token(access)


def _tamper(token: str, **claims: object) -> str:
    header, payload, signature = token.split(".")
    decoded = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    decoded.update(claims)
    raw = json.dumps(decoded, separators=(",", ":"), sort_keys=True).encode()
    forged = base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
    return f"{header}.{forged}.{signature}"


def test_tampered_tokens_rejected_with_either_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    old_access, _ = _old_tokens(monkeypatch)
    _rotate(monkeypatch, previous=OLD_SECRET)
    new_access = token_codec.create_app_access_token(subject="user-3")
    for token in (old_access, new_access):
        with pytest.raises(AuthenticationError, match="Invalid token signature"):
            token_codec.decode_app_access_token(_tamper(token, role="owner"))
    with pytest.raises(AuthenticationError, match="Invalid token format"):
        token_codec.decode_app_access_token("not-a-token")


def test_previous_key_still_runs_claim_checks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "app_auth_secret", SecretStr(OLD_SECRET))
    monkeypatch.setattr(settings, "app_auth_secret_previous", None)
    expired = token_codec.create_app_access_token(subject="user-4", ttl_seconds=60)
    wrong_audience = token_codec.create_app_access_token(subject="user-4", audience="other")
    refresh = token_codec.create_app_refresh_token(subject="user-4")
    _rotate(monkeypatch, previous=OLD_SECRET)

    later = datetime.now(UTC) + timedelta(hours=2)

    class _FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz: object = None) -> datetime:  # type: ignore[override]
            return later

    with pytest.raises(AuthenticationError, match="Invalid token audience"):
        token_codec.decode_app_access_token(wrong_audience)
    with pytest.raises(AuthenticationError, match="Invalid token type"):
        token_codec.decode_app_access_token(refresh)
    monkeypatch.setattr(token_codec, "datetime", _FrozenDatetime)
    with pytest.raises(AuthenticationError, match="Token has expired"):
        token_codec.decode_app_access_token(expired)


def test_legacy_access_token_without_token_use_counts_previous_key(
    monkeypatch: pytest.MonkeyPatch, metrics_on: None
) -> None:
    monkeypatch.setattr(settings, "app_auth_secret", SecretStr(OLD_SECRET))
    monkeypatch.setattr(settings, "app_auth_secret_previous", None)
    token = token_codec.create_app_access_token(subject="user-5")
    header, payload, _ = token.split(".")
    decoded = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    decoded.pop("token_use")
    raw = json.dumps(decoded, separators=(",", ":"), sort_keys=True).encode()
    legacy_payload = base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
    signing_input = f"{header}.{legacy_payload}"
    legacy = f"{signing_input}.{token_codec._sign(signing_input, OLD_SECRET)}"
    _rotate(monkeypatch, previous=OLD_SECRET)
    before = _previous_key_count("access")
    assert token_codec.decode_app_access_token(legacy)["sub"] == "user-5"
    assert _previous_key_count("access") == before + 1


def test_metric_not_recorded_when_metrics_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    access, _ = _old_tokens(monkeypatch)
    _rotate(monkeypatch, previous=OLD_SECRET)
    monkeypatch.setattr(settings, "metrics_enabled", False)
    before = _previous_key_count("access")
    token_codec.decode_app_access_token(access)
    assert _previous_key_count("access") == before


def test_blank_previous_secret_is_ignored_at_verification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    access, _ = _old_tokens(monkeypatch)
    _rotate(monkeypatch, previous="   ")
    with pytest.raises(AuthenticationError, match="Invalid token signature"):
        token_codec.decode_app_access_token(access)


@pytest.mark.usefixtures("metrics_on")
def test_bot_oauth_state_verifies_with_previous_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "app_auth_secret", SecretStr(OLD_SECRET))
    monkeypatch.setattr(settings, "app_auth_secret_previous", None)
    exp = int((datetime.now(UTC) + timedelta(minutes=5)).timestamp())
    state = oauth._encode_state({"v": 1, "exp": exp})

    _rotate(monkeypatch, previous=OLD_SECRET)
    before = _previous_key_count("bot_oauth_state")
    assert oauth._decode_state(state)["exp"] == exp
    assert _previous_key_count("bot_oauth_state") == before + 1

    fresh = oauth._encode_state({"v": 1, "exp": exp})
    assert oauth._decode_state(fresh)["exp"] == exp
    assert _previous_key_count("bot_oauth_state") == before + 1

    payload, signature = state.split(".", 1)
    with pytest.raises(oauth.BotOAuthError, match="Invalid Slack OAuth state"):
        oauth._decode_state(f"{payload}x.{signature}")

    monkeypatch.setattr(settings, "app_auth_secret_previous", None)
    with pytest.raises(oauth.BotOAuthError, match="Invalid Slack OAuth state"):
        oauth._decode_state(state)
    assert oauth._decode_state(fresh)["exp"] == exp


def _clear_auth_env(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_settings_env(monkeypatch)
    for key, value in SNAPSHOT_ENV.items():
        monkeypatch.setenv(key, value)


def test_previous_equal_to_current_rejected_at_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_auth_env(monkeypatch)
    monkeypatch.setenv("APP_AUTH_SECRET", NEW_SECRET)
    monkeypatch.setenv("APP_AUTH_SECRET_PREVIOUS", NEW_SECRET)
    with pytest.raises(ValueError, match="must differ from app_auth_secret") as excinfo:
        Settings(_env_file=None)  # type: ignore[call-arg]
    assert NEW_SECRET not in str(excinfo.value)


def test_blank_previous_rejected_at_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_auth_env(monkeypatch)
    monkeypatch.setenv("APP_AUTH_SECRET", NEW_SECRET)
    monkeypatch.setenv("APP_AUTH_SECRET_PREVIOUS", "  ")
    with pytest.raises(ValueError, match="must not be empty"):
        Settings(_env_file=None)  # type: ignore[call-arg]


def test_snapshot_and_logs_hold_no_secret_value(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _clear_auth_env(monkeypatch)
    monkeypatch.setenv("APP_AUTH_SECRET", NEW_SECRET)
    monkeypatch.setenv("APP_AUTH_SECRET_PREVIOUS", OLD_SECRET)
    caplog.set_level(logging.DEBUG)
    loaded = Settings(_env_file=None)  # type: ignore[call-arg]
    snapshot = loaded.sanitized_snapshot()
    assert snapshot["infrastructure"]["app_auth_secret_previous_set"] is True
    dumped = json.dumps(snapshot, default=str) + repr(loaded) + caplog.text
    assert OLD_SECRET not in dumped
    assert NEW_SECRET not in dumped

    monkeypatch.delenv("APP_AUTH_SECRET_PREVIOUS")
    unset = Settings(_env_file=None)  # type: ignore[call-arg]
    assert unset.sanitized_snapshot()["infrastructure"]["app_auth_secret_previous_set"] is False
