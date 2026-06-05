"""Jira API response → NormalizedExternalItem conversion helpers."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from app.domains.connectors.schemas.connectors import NormalizedExternalItem
from app.domains.connectors.sdk.content_hash import hash_dict, hash_text
from app.domains.connectors.sdk.metadata import build_metadata
from app.models.enums import ExternalItemType, ExternalItemVisibility

_PROVIDER_KEY = "jira"


def _parse_datetime(value: str | None) -> datetime:
    """Parse an ISO 8601 datetime string from Jira into an aware UTC datetime."""
    if not value:
        return datetime.now(UTC)
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt
    except ValueError:
        return datetime.now(UTC)


def _adf_to_text(adf: Any) -> str:
    """Extract plain text from an Atlassian Document Format (ADF) node or string."""
    if adf is None:
        return ""
    if isinstance(adf, str):
        return adf
    if not isinstance(adf, dict):
        return str(adf)

    text_parts: list[str] = []

    node_type = adf.get("type", "")
    if node_type == "text":
        return adf.get("text", "")

    for child in adf.get("content", []):
        text_parts.append(_adf_to_text(child))

    return " ".join(part for part in text_parts if part)


def _issue_content_hash(issue: dict[str, Any]) -> str:
    fields = issue.get("fields", {})
    description = _adf_to_text(fields.get("description"))
    comment_total = (fields.get("comment") or {}).get("total", 0)
    payload = {
        "key": issue.get("key", ""),
        "summary": fields.get("summary", ""),
        "description": description[:2000],
        "status": (fields.get("status") or {}).get("name", ""),
        "priority": (fields.get("priority") or {}).get("name", ""),
        "updated": fields.get("updated", ""),
        "comment_total": comment_total,
    }
    return hash_dict(payload)


def _comment_content_hash(comment: dict[str, Any]) -> str:
    body = _adf_to_text(comment.get("body"))
    payload = {
        "id": comment.get("id", ""),
        "body": body[:2000],
        "updated": comment.get("updated", ""),
    }
    return hash_dict(payload)


def _attachment_content_hash(attachment: dict[str, Any]) -> str:
    payload = {
        "id": attachment.get("id", ""),
        "filename": attachment.get("filename", ""),
        "size": attachment.get("size", 0),
        "created": attachment.get("created", ""),
    }
    return hash_dict(payload)


def normalize_issue(
    issue: dict[str, Any],
    *,
    organization_id: UUID,
    connection_id: UUID,
    external_source_id: UUID | None,
    site_url: str,
    sync_version: int,
) -> NormalizedExternalItem:
    """Convert a raw Jira issue dict into a NormalizedExternalItem."""
    fields = issue.get("fields", {})
    issue_key = issue["key"]
    issue_url = f"{site_url.rstrip('/')}/browse/{issue_key}"

    assignee = fields.get("assignee") or {}
    reporter = fields.get("reporter") or {}
    status = fields.get("status") or {}
    priority = fields.get("priority") or {}
    issue_type = fields.get("issuetype") or {}
    project = fields.get("project") or {}

    labels = fields.get("labels") or []
    components = [c.get("name", "") for c in (fields.get("components") or [])]

    metadata = build_metadata(
        issue_key=issue_key,
        issue_id=issue.get("id"),
        status=status.get("name"),
        priority=priority.get("name"),
        issue_type=issue_type.get("name"),
        project_key=project.get("key"),
        project_name=project.get("name"),
        assignee_account_id=assignee.get("accountId"),
        assignee_display_name=assignee.get("displayName"),
        reporter_account_id=reporter.get("accountId"),
        reporter_display_name=reporter.get("displayName"),
        labels=labels if labels else None,
        components=components if components else None,
        created=fields.get("created"),
        updated=fields.get("updated"),
        attachment_count=len(fields.get("attachment") or []),
        comment_count=(fields.get("comment") or {}).get("total", 0),
    )

    return NormalizedExternalItem(
        organization_id=organization_id,
        provider_key=_PROVIDER_KEY,
        provider_item_id=issue_key,
        item_type=ExternalItemType.issue,
        title=fields.get("summary") or issue_key,
        source_url=issue_url,
        content_hash=_issue_content_hash(issue),
        updated_at=_parse_datetime(fields.get("updated")),
        sync_version=sync_version,
        connection_id=connection_id,
        external_source_id=external_source_id,
        visibility=ExternalItemVisibility.org_wide,
        metadata=metadata,
    )


def normalize_comment(
    comment: dict[str, Any],
    *,
    issue_key: str,
    organization_id: UUID,
    connection_id: UUID,
    external_source_id: UUID | None,
    site_url: str,
    sync_version: int,
) -> NormalizedExternalItem:
    """Convert a raw Jira comment dict into a NormalizedExternalItem."""
    comment_id = comment["id"]
    author = comment.get("author") or {}
    body_text = _adf_to_text(comment.get("body"))

    title_author = author.get("displayName") or "Unknown"
    title = f"Comment by {title_author} on {issue_key}"
    if len(body_text) > 80:
        snippet = body_text[:77].rstrip() + "…"
    else:
        snippet = body_text
    if snippet:
        title = f"{title}: {snippet}"

    issue_url = f"{site_url.rstrip('/')}/browse/{issue_key}"

    metadata = build_metadata(
        comment_id=comment_id,
        issue_key=issue_key,
        author_account_id=author.get("accountId"),
        author_display_name=author.get("displayName"),
        created=comment.get("created"),
        updated=comment.get("updated"),
    )

    return NormalizedExternalItem(
        organization_id=organization_id,
        provider_key=_PROVIDER_KEY,
        provider_item_id=f"comment-{comment_id}",
        item_type=ExternalItemType.comment,
        title=title[:512],
        source_url=f"{issue_url}?focusedCommentId={comment_id}",
        content_hash=_comment_content_hash(comment),
        updated_at=_parse_datetime(comment.get("updated") or comment.get("created")),
        sync_version=sync_version,
        connection_id=connection_id,
        external_source_id=external_source_id,
        provider_parent_id=issue_key,
        root_provider_item_id=issue_key,
        visibility=ExternalItemVisibility.org_wide,
        metadata=metadata,
    )


def normalize_attachment(
    attachment: dict[str, Any],
    *,
    issue_key: str,
    organization_id: UUID,
    connection_id: UUID,
    external_source_id: UUID | None,
    site_url: str,
    sync_version: int,
) -> NormalizedExternalItem:
    """Convert a raw Jira attachment dict into a NormalizedExternalItem."""
    attachment_id = attachment["id"]
    filename = attachment.get("filename") or f"attachment-{attachment_id}"
    mime_type = attachment.get("mimeType")
    author = attachment.get("author") or {}
    content_url = attachment.get("content") or f"{site_url.rstrip('/')}/browse/{issue_key}"

    metadata = build_metadata(
        attachment_id=attachment_id,
        issue_key=issue_key,
        filename=filename,
        size_bytes=attachment.get("size"),
        mime_type=mime_type,
        author_display_name=author.get("displayName"),
        created=attachment.get("created"),
    )

    return NormalizedExternalItem(
        organization_id=organization_id,
        provider_key=_PROVIDER_KEY,
        provider_item_id=f"attachment-{attachment_id}",
        item_type=ExternalItemType.attachment,
        title=filename,
        source_url=content_url,
        content_hash=_attachment_content_hash(attachment),
        updated_at=_parse_datetime(attachment.get("created")),
        sync_version=sync_version,
        connection_id=connection_id,
        external_source_id=external_source_id,
        provider_parent_id=issue_key,
        root_provider_item_id=issue_key,
        mime_type=mime_type,
        visibility=ExternalItemVisibility.org_wide,
        metadata=metadata,
    )
