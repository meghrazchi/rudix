from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

# Canonical flag names. These map to settings.feature_enable_<name>.
FeatureFlagName = Literal[
    "agents",
    "mcp",
    "connectors",
    "evaluations",
    "chunking_profiles",
    "adaptive_chunking",
    "graph_rag",
    "graph_extraction",
    "graph_explorer",
    "advanced_pdf_extraction",
    "language_aware_rag",
    "pipeline_explorer",
    "local_llm_profiles",
    "experimental_profiles",
    "provider_fallback",
    "external_mcp_connectors",
    "query_rewriting",
]

ALL_FLAG_NAMES: tuple[FeatureFlagName, ...] = (
    "agents",
    "mcp",
    "connectors",
    "evaluations",
    "chunking_profiles",
    "adaptive_chunking",
    "graph_rag",
    "graph_extraction",
    "graph_explorer",
    "advanced_pdf_extraction",
    "language_aware_rag",
    "pipeline_explorer",
    "local_llm_profiles",
    "experimental_profiles",
    "provider_fallback",
    "external_mcp_connectors",
    "query_rewriting",
)


class FeatureFlagDetail(BaseModel):
    name: str
    enabled: bool
    env_default: bool
    has_org_override: bool
    override_enabled: bool | None = None
    override_reason: str | None = None
    overridden_by_user_id: str | None = None
    overridden_at: datetime | None = None


class FeatureFlagsResponse(BaseModel):
    organization_id: str
    flags: list[FeatureFlagDetail]


class FeatureFlagSetRequest(BaseModel):
    enabled: bool
    reason: str | None = Field(default=None, max_length=500)


class FeatureFlagSetResponse(BaseModel):
    organization_id: str
    flag: FeatureFlagDetail


class FeatureFlagDeleteResponse(BaseModel):
    organization_id: str
    flag_name: str
    reverted_to_env_default: bool
    env_default: bool


class PublicFeatureFlagsResponse(BaseModel):
    """Safe subset of flag states returned to authenticated non-admin users."""

    flags: dict[str, bool]
