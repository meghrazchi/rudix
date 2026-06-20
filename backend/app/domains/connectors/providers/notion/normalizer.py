"""Notion API response → NormalizedExternalItem conversion helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from app.domains.connectors.schemas.connectors import NormalizedExternalItem
from app.domains.connectors.sdk.content_hash import hash_dict
from app.domains.connectors.sdk.metadata import build_metadata
from app.models.enums import ExternalItemType, ExternalItemVisibility

_PROVIDER_KEY = "notion"

# Block types whose rich_text content renders to plain text
_TEXT_BLOCK_TYPES = frozenset(
    {
        "paragraph",
        "heading_1",
        "heading_2",
        "heading_3",
        "bulleted_list_item",
        "numbered_list_item",
        "toggle",
        "quote",
        "callout",
        "code",
    }
)

# Block types that represent downloadable files / media attachments
NOTION_FILE_BLOCK_TYPES = frozenset({"image", "file", "pdf", "video", "audio"})


def _parse_datetime(value: str | None) -> datetime:
    if not value:
        return datetime.now(UTC)
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    except ValueError:
        return datetime.now(UTC)


def _rich_text_to_plain(rich_text: list[dict[str, Any]] | None) -> str:
    return "".join(rt.get("plain_text", "") for rt in (rich_text or []))


def extract_page_title(page: dict[str, Any]) -> str:
    """Return the plain-text title of a Notion page."""
    for prop in (page.get("properties") or {}).values():
        if prop.get("type") == "title":
            text = _rich_text_to_plain(prop.get("title"))
            if text.strip():
                return text.strip()
    return str(page.get("id", "Untitled"))


def extract_database_title(database: dict[str, Any]) -> str:
    """Return the plain-text title of a Notion database."""
    return _rich_text_to_plain(database.get("title")) or str(database.get("id", "Untitled"))


def extract_parent_id(parent: dict[str, Any] | None) -> str | None:
    """Return the parent page_id or database_id, or None for workspace root."""
    if not parent:
        return None
    parent_type = parent.get("type")
    if parent_type == "page_id":
        return parent.get("page_id")
    if parent_type == "database_id":
        return parent.get("database_id")
    return None


def _page_content_hash(page: dict[str, Any]) -> str:
    return hash_dict(
        {
            "id": page.get("id", ""),
            "last_edited_time": page.get("last_edited_time", ""),
            "archived": page.get("archived", False),
            "title": extract_page_title(page)[:500],
        }
    )


def _database_content_hash(database: dict[str, Any]) -> str:
    return hash_dict(
        {
            "id": database.get("id", ""),
            "last_edited_time": database.get("last_edited_time", ""),
            "archived": database.get("archived", False),
            "title": extract_database_title(database)[:500],
        }
    )


def _comment_content_hash(comment: dict[str, Any]) -> str:
    return hash_dict(
        {
            "id": comment.get("id", ""),
            "last_edited_time": comment.get("last_edited_time", ""),
            "body": _rich_text_to_plain(comment.get("rich_text"))[:1000],
        }
    )


def _file_block_content_hash(block: dict[str, Any]) -> str:
    block_type = block.get("type", "file")
    file_obj = block.get(block_type) or {}
    # Notion hosted URLs expire; use only the stable path prefix
    hosted_url = (file_obj.get("file") or {}).get("url", "")
    external_url = (file_obj.get("external") or {}).get("url", "")
    url_prefix = (hosted_url or external_url)[:200]
    return hash_dict(
        {
            "id": block.get("id", ""),
            "last_edited_time": block.get("last_edited_time", ""),
            "url_prefix": url_prefix,
        }
    )


def normalize_page(
    page: dict[str, Any],
    *,
    organization_id: UUID,
    connection_id: UUID,
    external_source_id: UUID | None,
    workspace_id: str | None,
    sync_version: int,
) -> NormalizedExternalItem:
    """Convert a raw Notion page dict into a NormalizedExternalItem.

    Pages (including database items) are returned as cloud_file/text/plain so
    the sync engine downloads their rendered block content through the document
    ingestion pipeline.
    """
    page_id = page["id"]
    title = extract_page_title(page)
    url = str(page.get("url") or "").strip()
    if not url.startswith("http"):
        url = f"https://www.notion.so/{page_id.replace('-', '')}"

    parent = page.get("parent") or {}
    parent_id = extract_parent_id(parent)
    in_database = parent.get("type") == "database_id"
    created_time = page.get("created_time")
    last_edited_time = page.get("last_edited_time")
    created_by_id = (page.get("created_by") or {}).get("id")
    last_edited_by_id = (page.get("last_edited_by") or {}).get("id")

    metadata = build_metadata(
        page_id=page_id,
        workspace_id=workspace_id,
        parent_type=parent.get("type"),
        parent_id=parent_id,
        in_database=in_database or None,
        database_id=parent.get("database_id") if in_database else None,
        created_time=created_time,
        last_edited_time=last_edited_time,
        created_by_id=created_by_id,
        last_edited_by_id=last_edited_by_id,
        archived=page.get("archived") or None,
        url=url,
    )

    return NormalizedExternalItem(
        organization_id=organization_id,
        provider_key=_PROVIDER_KEY,
        provider_item_id=page_id,
        item_type=ExternalItemType.cloud_file,
        mime_type="text/plain",
        title=title,
        source_url=url,
        content_hash=_page_content_hash(page),
        updated_at=_parse_datetime(last_edited_time or created_time),
        sync_version=sync_version,
        connection_id=connection_id,
        external_source_id=external_source_id,
        provider_parent_id=parent_id,
        root_provider_item_id=workspace_id,
        visibility=ExternalItemVisibility.org_wide,
        metadata=metadata,
    )


def normalize_database(
    database: dict[str, Any],
    *,
    organization_id: UUID,
    connection_id: UUID,
    external_source_id: UUID | None,
    workspace_id: str | None,
    sync_version: int,
) -> NormalizedExternalItem:
    """Convert a raw Notion database dict into a NormalizedExternalItem (folder/container)."""
    db_id = database["id"]
    title = extract_database_title(database)
    url = str(database.get("url") or "").strip()
    if not url.startswith("http"):
        url = f"https://www.notion.so/{db_id.replace('-', '')}"

    parent = database.get("parent") or {}
    parent_id = extract_parent_id(parent)
    created_time = database.get("created_time")
    last_edited_time = database.get("last_edited_time")

    metadata = build_metadata(
        database_id=db_id,
        workspace_id=workspace_id,
        parent_type=parent.get("type"),
        parent_id=parent_id,
        created_time=created_time,
        last_edited_time=last_edited_time,
        archived=database.get("archived") or None,
        url=url,
    )

    return NormalizedExternalItem(
        organization_id=organization_id,
        provider_key=_PROVIDER_KEY,
        provider_item_id=db_id,
        item_type=ExternalItemType.folder,
        title=title,
        source_url=url,
        content_hash=_database_content_hash(database),
        updated_at=_parse_datetime(last_edited_time or created_time),
        sync_version=sync_version,
        connection_id=connection_id,
        external_source_id=external_source_id,
        provider_parent_id=parent_id,
        root_provider_item_id=workspace_id,
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
    """Convert a raw Notion comment dict into a NormalizedExternalItem."""
    comment_id = comment["id"]
    body = _rich_text_to_plain(comment.get("rich_text"))
    author_id = (comment.get("created_by") or {}).get("id", "unknown")

    snippet = body[:77].rstrip() + "…" if len(body) > 80 else body
    title = f"Comment: {snippet}" if snippet else f"Comment {comment_id}"

    metadata = build_metadata(
        comment_id=comment_id,
        page_id=page_id,
        author_id=author_id,
        created_time=comment.get("created_time"),
        last_edited_time=comment.get("last_edited_time"),
    )

    return NormalizedExternalItem(
        organization_id=organization_id,
        provider_key=_PROVIDER_KEY,
        provider_item_id=f"comment:{comment_id}",
        item_type=ExternalItemType.comment,
        title=title[:512],
        source_url=page_url,
        content_hash=_comment_content_hash(comment),
        updated_at=_parse_datetime(comment.get("last_edited_time") or comment.get("created_time")),
        sync_version=sync_version,
        connection_id=connection_id,
        external_source_id=external_source_id,
        provider_parent_id=page_id,
        root_provider_item_id=page_id,
        visibility=ExternalItemVisibility.org_wide,
        metadata=metadata,
    )


def normalize_file_block(
    block: dict[str, Any],
    *,
    page_id: str,
    page_url: str,
    organization_id: UUID,
    connection_id: UUID,
    external_source_id: UUID | None,
    sync_version: int,
) -> NormalizedExternalItem:
    """Convert a Notion file/image/pdf block into an attachment NormalizedExternalItem."""
    block_id = block["id"]
    block_type = block.get("type", "file")
    file_obj = block.get(block_type) or {}

    caption = _rich_text_to_plain(file_obj.get("caption"))
    file_name = file_obj.get("name") or caption or block_type

    external_url = (file_obj.get("external") or {}).get("url", "")
    hosted_url = (file_obj.get("file") or {}).get("url", "")
    file_url = external_url or hosted_url or page_url
    if not file_url.startswith("http"):
        file_url = page_url

    mime_type: str | None = None
    if block_type == "pdf":
        mime_type = "application/pdf"

    metadata = build_metadata(
        block_id=block_id,
        block_type=block_type,
        page_id=page_id,
        file_name=file_name or None,
        caption=caption or None,
    )

    display_title = file_name[:512] if file_name else f"{block_type.capitalize()} from {page_id}"

    return NormalizedExternalItem(
        organization_id=organization_id,
        provider_key=_PROVIDER_KEY,
        provider_item_id=f"block:{block_id}",
        item_type=ExternalItemType.attachment,
        title=display_title,
        source_url=file_url,
        content_hash=_file_block_content_hash(block),
        updated_at=_parse_datetime(block.get("last_edited_time")),
        sync_version=sync_version,
        connection_id=connection_id,
        external_source_id=external_source_id,
        provider_parent_id=page_id,
        root_provider_item_id=page_id,
        mime_type=mime_type,
        visibility=ExternalItemVisibility.org_wide,
        metadata=metadata,
    )


def render_blocks_to_text(blocks: list[dict[str, Any]], *, depth: int = 0) -> str:
    """Render a list of Notion block dicts to plain text for RAG ingestion."""
    lines: list[str] = []
    indent = "  " * depth

    for block in blocks:
        block_type = block.get("type", "")
        content = block.get(block_type) or {}

        if block_type in ("heading_1", "heading_2", "heading_3"):
            text = _rich_text_to_plain(content.get("rich_text"))
            if text:
                prefix = "#" * int(block_type[-1])
                lines.append(f"{indent}{prefix} {text}")
        elif block_type == "paragraph":
            text = _rich_text_to_plain(content.get("rich_text"))
            if text:
                lines.append(f"{indent}{text}")
        elif block_type in ("bulleted_list_item", "numbered_list_item"):
            text = _rich_text_to_plain(content.get("rich_text"))
            if text:
                marker = "-" if "bulleted" in block_type else "1."
                lines.append(f"{indent}{marker} {text}")
        elif block_type == "toggle":
            text = _rich_text_to_plain(content.get("rich_text"))
            if text:
                lines.append(f"{indent}> {text}")
        elif block_type == "quote":
            text = _rich_text_to_plain(content.get("rich_text"))
            if text:
                lines.append(f"{indent}| {text}")
        elif block_type == "callout":
            text = _rich_text_to_plain(content.get("rich_text"))
            if text:
                emoji = (content.get("icon") or {}).get("emoji", "")
                lines.append(f"{indent}{emoji} {text}".strip())
        elif block_type == "code":
            text = _rich_text_to_plain(content.get("rich_text"))
            lang = content.get("language", "")
            if text:
                lines.append(f"{indent}```{lang}")
                lines.append(f"{indent}{text}")
                lines.append(f"{indent}```")
        elif block_type == "table_row":
            cells = [_rich_text_to_plain(cell) for cell in (content.get("cells") or [])]
            if cells:
                lines.append(f"{indent}| " + " | ".join(cells) + " |")
        elif block_type == "divider":
            lines.append(f"{indent}---")
        elif block_type == "child_page":
            child_title = content.get("title", "")
            if child_title:
                lines.append(f"{indent}[Page: {child_title}]")
        elif block_type == "child_database":
            child_title = content.get("title", "")
            if child_title:
                lines.append(f"{indent}[Database: {child_title}]")

        children: list[dict[str, Any]] = block.get("_children") or []
        if children and depth < 5:
            child_text = render_blocks_to_text(children, depth=depth + 1)
            if child_text:
                lines.append(child_text)

    return "\n".join(line for line in lines if line)
