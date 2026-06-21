from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_principal
from app.auth.models import AuthenticatedPrincipal
from app.db.session import get_db_session
from app.models.organization import Organization

router = APIRouter(prefix="/organization", tags=["organization"])


# ── Response schema ───────────────────────────────────────────────────────────


class OrganizationProfile(BaseModel):
    id: str
    name: str
    slug: str
    primary_domain: str | None
    domain_allowlist: list[str]
    support_email: str | None
    description: str | None
    created_at: str | None
    plan: str | None


# ── GET /organization ─────────────────────────────────────────────────────────


@router.get("", response_model=OrganizationProfile)
async def get_organization(
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> OrganizationProfile:
    if not principal.organization_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No organization context for this principal.",
        )

    org_uuid = UUID(principal.organization_id)
    row = await db.execute(select(Organization).where(Organization.id == org_uuid))
    org = row.scalar_one_or_none()
    if org is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found.")

    return OrganizationProfile(
        id=str(org.id),
        name=org.name,
        slug=org.slug,
        primary_domain=None,
        domain_allowlist=[],
        support_email=None,
        description=None,
        created_at=org.created_at.isoformat() if org.created_at else None,
        plan=None,
    )


# ── PATCH /organization ───────────────────────────────────────────────────────


class OrganizationPatch(BaseModel):
    name: str | None = None
    slug: str | None = None


@router.patch("", response_model=OrganizationProfile)
async def update_organization(
    body: OrganizationPatch,
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> OrganizationProfile:
    if not principal.organization_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No organization context."
        )

    org_uuid = UUID(principal.organization_id)
    row = await db.execute(select(Organization).where(Organization.id == org_uuid))
    org = row.scalar_one_or_none()
    if org is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found.")

    if body.name is not None:
        org.name = body.name
    if body.slug is not None:
        org.slug = body.slug

    await db.commit()
    await db.refresh(org)

    return OrganizationProfile(
        id=str(org.id),
        name=org.name,
        slug=org.slug,
        primary_domain=None,
        domain_allowlist=[],
        support_email=None,
        description=None,
        created_at=org.created_at.isoformat() if org.created_at else None,
        plan=None,
    )


# ── GET /organization/settings ────────────────────────────────────────────────


class OrgSettings(BaseModel):
    default_member_role: str
    invite_only: bool
    allowed_email_domains: list[str]
    default_document_visibility: str
    default_collection: str | None
    retention_days: int | None
    source_download: str
    evaluation_access: bool
    agentic_access: bool
    mcp_access: bool
    analytics_enabled: bool


class OrgSettingsPatch(BaseModel):
    analytics_enabled: bool | None = None


async def _load_org(
    db: AsyncSession,
    principal: AuthenticatedPrincipal,
) -> Organization:
    if not principal.organization_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No organization context for this principal.",
        )

    org_uuid = UUID(principal.organization_id)
    row = await db.execute(select(Organization).where(Organization.id == org_uuid))
    org = row.scalar_one_or_none()
    if org is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found.")
    return org


@router.get("/settings", response_model=OrgSettings)
async def get_organization_settings(
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> OrgSettings:
    org = await _load_org(db, principal)
    return OrgSettings(
        default_member_role="member",
        invite_only=False,
        allowed_email_domains=[],
        default_document_visibility="private",
        default_collection=None,
        retention_days=None,
        source_download="admins",
        evaluation_access=True,
        agentic_access=False,
        mcp_access=False,
        analytics_enabled=org.analytics_enabled,
    )


# ── PATCH /organization/settings ──────────────────────────────────────────────


@router.patch("/settings", response_model=OrgSettings)
async def update_organization_settings(
    body: OrgSettingsPatch,
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> OrgSettings:
    org = await _load_org(db, principal)
    if body.analytics_enabled is not None:
        org.analytics_enabled = body.analytics_enabled
    await db.commit()
    await db.refresh(org)
    return OrgSettings(
        default_member_role="member",
        invite_only=False,
        allowed_email_domains=[],
        default_document_visibility="private",
        default_collection=None,
        retention_days=None,
        source_download="admins",
        evaluation_access=True,
        agentic_access=False,
        mcp_access=False,
        analytics_enabled=org.analytics_enabled,
    )


# ── GET /organization/ingestion ───────────────────────────────────────────────


class IngestionDefaults(BaseModel):
    allowed_file_types: list[str]
    max_upload_size_mb: int | None
    max_page_count: int | None
    duplicate_handling: str
    auto_index: bool
    reindex_policy: str
    retry_policy: str
    default_metadata_tags: list[str]


@router.get("/ingestion", response_model=IngestionDefaults)
async def get_ingestion_defaults(
    _principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
) -> IngestionDefaults:
    return IngestionDefaults(
        allowed_file_types=["pdf", "docx", "txt", "md", "csv", "xlsx"],
        max_upload_size_mb=100,
        max_page_count=None,
        duplicate_handling="skip",
        auto_index=True,
        reindex_policy="on_update",
        retry_policy="three_times",
        default_metadata_tags=[],
    )


# ── PATCH /organization/ingestion ─────────────────────────────────────────────


@router.patch("/ingestion", response_model=IngestionDefaults)
async def update_ingestion_defaults(
    _principal: Annotated[AuthenticatedPrincipal, Depends(get_current_principal)],
) -> IngestionDefaults:
    return IngestionDefaults(
        allowed_file_types=["pdf", "docx", "txt", "md", "csv", "xlsx"],
        max_upload_size_mb=100,
        max_page_count=None,
        duplicate_handling="skip",
        auto_index=True,
        reindex_policy="on_update",
        retry_policy="three_times",
        default_metadata_tags=[],
    )
