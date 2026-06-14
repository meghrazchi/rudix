from __future__ import annotations

import hashlib
import hmac
import json
import re
from dataclasses import dataclass
from time import time
from typing import Any, Protocol
from urllib.parse import parse_qs

from fastapi import HTTPException, Request, status

from app.core.config import settings
from app.domains.chat.schemas.chat import SourceScopeRequest


@dataclass(frozen=True)
class BotAskEvent:
    provider: str
    external_workspace_id: str
    external_user_id: str
    question: str
    external_tenant_id: str = ""
    external_team_id: str = ""
    channel_id: str | None = None
    thread_id: str | None = None
    response_url: str | None = None
    service_url: str | None = None
    conversation_id: str | None = None
    activity_id: str | None = None
    event_id: str | None = None
    source_scope: SourceScopeRequest | None = None
    document_ids: tuple[str, ...] = ()
    raw_event_type: str | None = None


class BotTransportAdapter(Protocol):
    provider: str

    def verify_request(self, request: Request, raw_body: bytes) -> None: ...

    async def parse_event(
        self, request: Request, raw_body: bytes
    ) -> BotAskEvent | dict[str, str]: ...


def _safe_parse_json(raw_body: bytes) -> dict[str, Any]:
    try:
        parsed = json.loads(raw_body.decode("utf-8") or "{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "invalid_payload", "message": "Invalid JSON payload"},
        ) from exc
    if not isinstance(parsed, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "invalid_payload", "message": "Payload must be an object"},
        )
    return parsed


def _source_scope_from_payload(payload: dict[str, Any]) -> SourceScopeRequest | None:
    raw_scope = payload.get("source_scope")
    if raw_scope is None and isinstance(payload.get("metadata"), dict):
        raw_scope = payload["metadata"].get("source_scope")
    if raw_scope is None:
        return None
    if not isinstance(raw_scope, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "invalid_source_scope", "message": "source_scope must be an object"},
        )
    return SourceScopeRequest.model_validate(raw_scope)


def _clean_text(value: object) -> str:
    return str(value or "").strip()


def _clean_question(value: object) -> str:
    text = _clean_text(value)
    return re.sub(r"^\s*<@[A-Z0-9]+>\s*", "", text).strip()


def _as_payload_dict(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}


def _question_scope_from_text(
    value: object,
) -> tuple[str, SourceScopeRequest | None, tuple[str, ...]]:
    text = _clean_question(value)
    matches = list(re.finditer(r"(?:^|\s)--(collection|document)\s+([^\s]+)", text))
    if not matches:
        return text, None, ()

    collections: list[str] = []
    documents: list[str] = []
    for match in matches:
        target = match.group(1)
        identifier = match.group(2).strip()
        if target == "collection" and identifier not in collections:
            collections.append(identifier)
        if target == "document" and identifier not in documents:
            documents.append(identifier)

    cleaned_parts: list[str] = []
    cursor = 0
    for match in matches:
        cleaned_parts.append(text[cursor : match.start()])
        cursor = match.end()
    cleaned_parts.append(text[cursor:])
    question = re.sub(r"\s+", " ", "".join(cleaned_parts)).strip()

    scope = None
    if collections:
        scope = SourceScopeRequest(mode="collections", collection_ids=collections)
    return question, scope, tuple(documents)


class SlackBotAdapter:
    provider = "slack"

    def verify_request(self, request: Request, raw_body: bytes) -> None:
        secret = settings.bot_slack_signing_secret
        if secret is None:
            return

        timestamp = request.headers.get("x-slack-request-timestamp", "")
        signature = request.headers.get("x-slack-signature", "")
        if not timestamp.isdigit() or not signature:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"code": "invalid_signature", "message": "Invalid Slack signature"},
            )
        if abs(time() - int(timestamp)) > 300:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"code": "stale_signature", "message": "Stale Slack request"},
            )

        base = b"v0:" + timestamp.encode("utf-8") + b":" + raw_body
        expected = (
            "v0="
            + hmac.new(
                secret.get_secret_value().encode("utf-8"),
                base,
                hashlib.sha256,
            ).hexdigest()
        )
        if not hmac.compare_digest(expected, signature):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"code": "invalid_signature", "message": "Invalid Slack signature"},
            )

    async def parse_event(self, request: Request, raw_body: bytes) -> BotAskEvent | dict[str, str]:
        content_type = request.headers.get("content-type", "")
        if "application/x-www-form-urlencoded" in content_type:
            form = {key: values[-1] for key, values in parse_qs(raw_body.decode()).items()}
            question, inline_scope, document_ids = _question_scope_from_text(form.get("text"))
            return BotAskEvent(
                provider=self.provider,
                external_workspace_id=_clean_text(form.get("team_id")),
                external_user_id=_clean_text(form.get("user_id")),
                question=question,
                external_tenant_id=_clean_text(form.get("enterprise_id")),
                channel_id=_clean_text(form.get("channel_id")) or None,
                thread_id=_clean_text(form.get("thread_ts")) or None,
                response_url=_clean_text(form.get("response_url")) or None,
                event_id=_clean_text(form.get("trigger_id")) or None,
                source_scope=inline_scope,
                document_ids=document_ids,
                raw_event_type=_clean_text(form.get("command")) or "slash_command",
            )

        payload = _safe_parse_json(raw_body)
        if payload.get("type") == "url_verification":
            challenge = _clean_text(payload.get("challenge"))
            return {"challenge": challenge}

        event = payload.get("event") if isinstance(payload.get("event"), dict) else payload
        if not isinstance(event, dict):
            event = payload

        question, inline_scope, document_ids = _question_scope_from_text(
            event.get("text") or payload.get("text")
        )
        return BotAskEvent(
            provider=self.provider,
            external_workspace_id=_clean_text(payload.get("team_id") or event.get("team")),
            external_user_id=_clean_text(event.get("user") or payload.get("user_id")),
            question=question,
            external_tenant_id=_clean_text(payload.get("enterprise_id")),
            channel_id=_clean_text(event.get("channel") or payload.get("channel_id")) or None,
            thread_id=_clean_text(event.get("thread_ts") or event.get("ts")) or None,
            response_url=_clean_text(payload.get("response_url")) or None,
            event_id=_clean_text(payload.get("event_id") or event.get("client_msg_id")) or None,
            source_scope=_source_scope_from_payload(payload) or inline_scope,
            document_ids=document_ids,
            raw_event_type=_clean_text(payload.get("type")) or "event_callback",
        )


class TeamsBotAdapter:
    provider = "teams"

    def verify_request(self, request: Request, raw_body: bytes) -> None:
        del raw_body
        secret = settings.bot_teams_shared_secret
        if secret is None:
            return

        authorization = request.headers.get("authorization", "")
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not hmac.compare_digest(
            token,
            secret.get_secret_value(),
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"code": "invalid_signature", "message": "Invalid Teams request"},
            )

    async def parse_event(self, request: Request, raw_body: bytes) -> BotAskEvent | dict[str, str]:
        del request
        payload = _safe_parse_json(raw_body)
        conversation = _as_payload_dict(payload.get("conversation"))
        from_user = _as_payload_dict(payload.get("from"))
        channel_data = _as_payload_dict(payload.get("channelData"))
        tenant = _as_payload_dict(channel_data.get("tenant"))
        team = _as_payload_dict(channel_data.get("team"))

        tenant_id = _clean_text(
            payload.get("tenant_id")
            or tenant.get("id")
            or channel_data.get("tenantId")
            or payload.get("external_tenant_id")
        )
        team_id = _clean_text(
            payload.get("team_id")
            or team.get("id")
            or conversation.get("id")
            or payload.get("external_team_id")
        )
        workspace_id = _clean_text(payload.get("workspace_id") or tenant_id or team_id)
        external_user_id = _clean_text(
            payload.get("user_id")
            or from_user.get("aadObjectId")
            or from_user.get("id")
            or payload.get("external_user_id")
        )

        question, inline_scope, document_ids = _question_scope_from_text(payload.get("text"))
        return BotAskEvent(
            provider=self.provider,
            external_workspace_id=workspace_id,
            external_tenant_id=tenant_id,
            external_team_id=team_id,
            external_user_id=external_user_id,
            question=question,
            channel_id=_clean_text(payload.get("channelId")) or None,
            thread_id=_clean_text(conversation.get("id") or payload.get("replyToId")) or None,
            service_url=_clean_text(payload.get("serviceUrl")) or None,
            conversation_id=_clean_text(conversation.get("id")) or None,
            activity_id=_clean_text(payload.get("replyToId") or payload.get("id")) or None,
            event_id=_clean_text(payload.get("id")) or None,
            source_scope=_source_scope_from_payload(payload) or inline_scope,
            document_ids=document_ids,
            raw_event_type=_clean_text(payload.get("type")) or "message",
        )
