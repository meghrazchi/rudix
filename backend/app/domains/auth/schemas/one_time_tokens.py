"""Purposes of single-use account tokens (0.9.0 contract 5.2.2)."""

from __future__ import annotations

from enum import StrEnum


class OneTimeTokenPurpose(StrEnum):
    # Same values, same order, as ``ONE_TIME_TOKEN_PURPOSES`` (the CHECK constraint).
    email_verification = "email_verification"
    password_reset = "password_reset"
    mfa_challenge = "mfa_challenge"
    mfa_enrolment = "mfa_enrolment"
    step_up = "step_up"
    saml_request = "saml_request"
    saml_assertion = "saml_assertion"
