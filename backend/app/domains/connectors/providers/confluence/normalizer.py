"""Confluence API response → NormalizedExternalItem conversion helpers."""
from __future__ import annotations

from datetime import UTC, datetime
from html.parser import HTMLParser
from typing import Any
from uuid import UUID

from app.domains.connectors.schemas.connectors import NormalizedExternalItem
from app.domains.connectors.sdk.content_hash import hash_dict
from app.domains.connectors.sdk.metadata import build_metadata
from app.models.enums import ExternalItemType, ExternalItemVisibility

_PROVIDER_KEY = "confluence"


def _parse_datetime(value: str | None) -> datetime:
    if not value:
        return datetime.now(UTC)
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt
    except ValueError:
        return datetime.now(UTC)


class _HTMLTextExtractor(HTMLParser):
    """Strips HTML tags and collects text nodes."""

    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        stripped = data.strip()
        if stripped:
            self._parts.append(stripped)

    def get_text(self) -> str:
        return " ".join(self._parts)


def _storage_html_to_text(html: str | None) -> str:
    """Convert Confluence storage-format HTML to plain text."""
    if not html:
        return ""
    extractor = _HTMLTextExtractor()
    try:
        extractor.feed(html)
    except Exception:
        return html
    return extractor.get_text()


def _page_url(site_url: str, page: dict[str, Any]) -> str:
    links = page.get("_links") or {}
    webui = links.get("webui", "")
    if webui:
        return f"{site_url.rstrip('/')}/wiki{webui}"
    space_key = (page.get("space") or {}).get("key", "")
    page_id = page.get("id", "")
    return f"{site_url.rstrip('/')}/wiki/spaces/{space_key}/pages/{page_id}"


def _breadcrumb(page: dict[str, Any]) -> list[str]:
    ancestors = page.get("ancestors") or []
    return [a.get("title", "") for a in ancestors if a.get("title")]


def _page_content_hash(page: dict[str, Any]) -> str:
    body_html = (page.get("body") or {}).get("storage", {}).get("value", "")
    body_text = _storage_html_to_text(body_html)
    version = page.get("version") or {}
    payload = {
        "id": page.get("id", ""),
        "title": page.get("title", ""),
        "body": body_text[:2000],
        "version_number": version.get("number", 0),
        "last_modified": version.get("when", ""),
    }
    return hash_dict(payload)


def _comment_content_hash(comment: dict[str, Any]) -> str:
    body_html = (comment.get("body") or {}).get("storage", {}).get("value", "")
    body_text = _storage_html_to_text(body_html)
    version = comment.get("version") or {}
    payload = {
        "id": comment.get("id", ""),
        "body": body_text[:2000],
        "last_modified": version.get("when", ""),
    }
    return hash_dict(payload)


def _attachment_content_hash(attachment: dict[str, Any]) -> str:
    extensions = attachment.get("extensions") or {}
    version = attachment.get("version") or {}
    payload = {
        "id": attachment.get("id", ""),
        "title": attachment.get("title", ""),
        "file_size": extensions.get("fileSize", 0),
        "created": version.get("when", ""),
    }
    return hash_dict(payload)


def normalize_page(
    page: dict[str, Any],
    *,
    organization_id: UUID,
    connection_id: UUID,
    external_source_id: UUID | None,
    site_url: str,
    sync_version: int,
) -> NormalizedExternalItem:
    """Convert a raw Confluence page dict into a NormalizedExternalItem."""
    page_id = page["id"]
    title = page.get("title") or page_id
    space = page.get("space") or {}
    version = page.get("version") or {}
    history = page.get("history") or {}

    editor = version.get("by") or {}
    creator = history.get("createdBy") or {}
    labels_data = (page.get("metadata") or {}).get("labels") or {}
    labels = [r.get("name", "") for r in (labels_data.get("results") or []) if r.get("name")]

    ancestors = page.get("ancestors") or []
    parent_page_id = ancestors[-1]["id"] if ancestors else None
    breadcrumb = _breadcrumb(page)

    metadata = build_metadata(
        page_id=page_id,
        space_key=space.get("key"),
        space_name=space.get("name"),
        version_number=version.get("number"),
        last_editor_display_name=editor.get("displayName"),
        last_editor_account_id=editor.get("accountId"),
        creator_display_name=creator.get("displayName"),
        creator_account_id=creator.get("accountId"),
        created=history.get("createdDate"),
        updated=version.get("when"),
        status=page.get("status"),
        labels=labels if labels else None,
        breadcrumb=breadcrumb if breadcrumb else None,
        parent_page_id=parent_page_id,
    )

    return NormalizedExternalItem(
        organization_id=organization_id,
        provider_key=_PROVIDER_KEY,
        provider_item_id=page_id,
        item_type=ExternalItemType.wiki_page,
        title=title,
        source_url=_page_url(site_url, page),
        content_hash=_page_content_hash(page),
        updated_at=_parse_datetime(version.get("when") or history.get("createdDate")),
        sync_version=sync_version,
        connection_id=connection_id,
        external_source_id=external_source_id,
        provider_parent_id=parent_page_id,
        root_provider_item_id=ancestors[0]["id"] if ancestors else None,
        visibility=ExternalItemVisibility.org_wide,
        metadata=metadata,
    )


def normalize_comment(
    comment: dict[str, Any],
    *,
    page_id: str,
    page_url: str,
    organization_id: UUID,
    connection_id: UUID,
    external_source_id: UUID | None,
    sync_version: int,
) -> NormalizedExternalItem:
    """Convert a raw Confluence comment dict into a NormalizedExternalItem."""
    comment_id = comment["id"]
    version = comment.get("version") or {}
    author = version.get("by") or {}
    body_html = (comment.get("body") or {}).get("storage", {}).get("value", "")
    body_text = _storage_html_to_text(body_html)

    author_name = author.get("displayName") or "Unknown"
    title = f"Comment by {author_name} on page {page_id}"
    if body_text:
        snippet = body_text[:77].rstrip() + "…" if len(body_text) > 80 else body_text
        title = f"{title}: {snippet}"

    metadata = build_metadata(
        comment_id=comment_id,
        page_id=page_id,
        author_account_id=author.get("accountId"),
        author_display_name=author.get("displayName"),
        created=version.get("when"),
        updated=version.get("when"),
    )

    return NormalizedExternalItem(
        organization_id=organization_id,
        provider_key=_PROVIDER_KEY,
        provider_item_id=f"comment-{comment_id}",
        item_type=ExternalItemType.comment,
        title=title[:512],
        source_url=f"{page_url}?focusedCommentId={comment_id}",
        content_hash=_comment_content_hash(comment),
        updated_at=_parse_datetime(version.get("when")),
        sync_version=sync_version,
        connection_id=connection_id,
        external_source_id=external_source_id,
        provider_parent_id=page_id,
        root_provider_item_id=page_id,
        visibility=ExternalItemVisibility.org_wide,
        metadata=metadata,
    )


def normalize_attachment(
    attachment: dict[str, Any],
    *,
    page_id: str,
    organization_id: UUID,
    connection_id: UUID,
    external_source_id: UUID | None,
    site_url: str,
    sync_version: int,
) -> NormalizedExternalItem:
    """Convert a raw Confluence attachment dict into a NormalizedExternalItem."""
    attachment_id = attachment["id"]
    title = attachment.get("title") or f"attachment-{attachment_id}"
    extensions = attachment.get("extensions") or {}
    mime_type = extensions.get("mediaType")
    file_size = extensions.get("fileSize")
    version = attachment.get("version") or {}
    author = version.get("by") or {}

    links = attachment.get("_links") or {}
    download_path = links.get("download", "")
    download_url = (
        f"{site_url.rstrip('/')}{download_path}"
        if download_path
        else f"{site_url.rstrip('/')}/wiki/spaces/pages/{page_id}"
    )

    metadata = build_metadata(
        attachment_id=attachment_id,
        page_id=page_id,
        filename=title,
        size_bytes=file_size,
        mime_type=mime_type,
        author_display_name=author.get("displayName"),
        created=version.get("when"),
    )

    return NormalizedExternalItem(
        organization_id=organization_id,
        provider_key=_PROVIDER_KEY,
        provider_item_id=f"attachment-{attachment_id}",
        item_type=ExternalItemType.attachment,
        title=title,
        source_url=download_url,
        content_hash=_attachment_content_hash(attachment),
        updated_at=_parse_datetime(version.get("when")),
        sync_version=sync_version,
        connection_id=connection_id,
        external_source_id=external_source_id,
        provider_parent_id=page_id,
        root_provider_item_id=page_id,
        mime_type=mime_type,
        visibility=ExternalItemVisibility.org_wide,
        metadata=metadata,
    )
