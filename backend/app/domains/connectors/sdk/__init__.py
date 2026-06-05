"""Connector provider SDK — shared utilities for building adapter implementations."""
from app.domains.connectors.sdk.content_hash import hash_acl, hash_dict, hash_text
from app.domains.connectors.sdk.metadata import build_metadata, normalize_metadata
from app.domains.connectors.sdk.models import ExternalACL, ExternalSource, SyncCursor
from app.domains.connectors.sdk.pagination import CursorPage, paginate_list
from app.domains.connectors.sdk.rate_limits import parse_retry_after, raise_for_rate_limit
from app.domains.connectors.sdk.url_builder import build_url, normalize_url

__all__ = [
    "ExternalACL",
    "ExternalSource",
    "SyncCursor",
    "CursorPage",
    "paginate_list",
    "hash_text",
    "hash_dict",
    "hash_acl",
    "build_metadata",
    "normalize_metadata",
    "parse_retry_after",
    "raise_for_rate_limit",
    "build_url",
    "normalize_url",
]
