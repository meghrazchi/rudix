"""Environment-driven configuration for the load harness.

Every value comes from the environment so no host, account, or organization is hard-coded:

* ``RUDIX_LOAD_BASE_URL``: API origin, for example ``http://localhost:8000``.
* ``RUDIX_LOAD_EMAIL`` / ``RUDIX_LOAD_PASSWORD``: the seeded load-test account.
* ``RUDIX_LOAD_ORG_ID``: optional ``X-Organization-ID`` header value.
* ``RUDIX_LOAD_SCENARIO_WEIGHTS``: ``name=weight`` pairs, comma separated.
* ``RUDIX_LOAD_QUESTIONS_FILE``: optional file with one question per line.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

API_PREFIX = "/api/v1"

SCENARIO_NAMES: tuple[str, ...] = (
    "chat_ws",
    "chat_http",
    "documents_list",
    "upload_ingest",
    "admin_dashboard",
)

DEFAULT_WEIGHTS: dict[str, int] = {
    "chat_ws": 3,
    "chat_http": 1,
    "documents_list": 4,
    "upload_ingest": 1,
    "admin_dashboard": 1,
}

DEFAULT_QUESTIONS: tuple[str, ...] = (
    "What is the refund policy?",
    "Summarize the onboarding checklist.",
    "Which teams own the incident response process?",
    "What are the data retention rules?",
    "How do I request access to a document collection?",
)


def parse_weights(raw: str | None) -> dict[str, int]:
    """Parse ``chat_ws=3,documents_list=1``; unknown names and bad values raise."""
    weights = dict(DEFAULT_WEIGHTS)
    if not raw or not raw.strip():
        return weights
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        name, sep, value = part.partition("=")
        name = name.strip()
        if not sep or name not in SCENARIO_NAMES:
            raise ValueError(f"invalid scenario weight entry: {part!r}")
        weight = int(value.strip())
        if weight < 0:
            raise ValueError(f"scenario weight must be >= 0: {part!r}")
        weights[name] = weight
    return weights


def load_questions(path: str | None) -> tuple[str, ...]:
    if not path:
        return DEFAULT_QUESTIONS
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    questions = tuple(line.strip() for line in lines if line.strip() and not line.startswith("#"))
    return questions or DEFAULT_QUESTIONS


@dataclass(frozen=True)
class LoadConfig:
    base_url: str
    email: str
    password: str
    org_id: str | None
    weights: dict[str, int] = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))
    questions: tuple[str, ...] = DEFAULT_QUESTIONS
    ingest_timeout_seconds: float = 300.0
    ws_answer_timeout_seconds: float = 120.0

    @property
    def ws_base_url(self) -> str:
        if self.base_url.startswith("https://"):
            return "wss://" + self.base_url[len("https://") :]
        if self.base_url.startswith("http://"):
            return "ws://" + self.base_url[len("http://") :]
        return self.base_url


def load_config(env: Mapping[str, str] | None = None) -> LoadConfig:
    source = os.environ if env is None else env
    return LoadConfig(
        base_url=source.get("RUDIX_LOAD_BASE_URL", "http://localhost:8000").rstrip("/"),
        email=source.get("RUDIX_LOAD_EMAIL", ""),
        password=source.get("RUDIX_LOAD_PASSWORD", ""),
        org_id=source.get("RUDIX_LOAD_ORG_ID") or None,
        weights=parse_weights(source.get("RUDIX_LOAD_SCENARIO_WEIGHTS")),
        questions=load_questions(source.get("RUDIX_LOAD_QUESTIONS_FILE")),
        ingest_timeout_seconds=float(source.get("RUDIX_LOAD_INGEST_TIMEOUT_SECONDS", "300")),
        ws_answer_timeout_seconds=float(source.get("RUDIX_LOAD_WS_TIMEOUT_SECONDS", "120")),
    )
