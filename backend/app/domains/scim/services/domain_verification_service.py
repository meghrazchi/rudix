from __future__ import annotations

import secrets
import socket
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.org_domain_verification import OrgDomainVerification

_TOKEN_PREFIX = "rudix-domain-verify="
_TOKEN_BYTES = 24  # 48 hex chars


def _generate_verification_token() -> str:
    return secrets.token_hex(_TOKEN_BYTES)


def _check_dns_txt(domain: str, token: str) -> tuple[bool, str]:
    """
    Look up TXT records for _rudix-challenge.<domain> and check for the token.
    Returns (verified, message).
    """
    challenge_host = f"_rudix-challenge.{domain}"
    expected = f"{_TOKEN_PREFIX}{token}"
    try:
        # getaddrinfo won't resolve TXT; use a simple approach via socket DNS lookup
        # For a real implementation, use dnspython or a subprocess dig call.
        # Here we use a best-effort approach: try to resolve and compare.
        # In production this should use an async DNS library.
        answers = _resolve_txt(challenge_host)
    except Exception as exc:
        return False, f"DNS lookup failed: {exc}"

    for record in answers:
        if record.strip() == expected:
            return True, "DNS TXT record found and verified."

    if answers:
        return (
            False,
            f"TXT record found at {challenge_host} but value did not match. Found: {answers[:3]}",
        )
    return False, f"No TXT records found at {challenge_host}."


def _resolve_txt(hostname: str) -> list[str]:
    """Resolve DNS TXT records. Falls back to dnspython if available, else raises."""
    try:
        import dns.resolver  # type: ignore[import-untyped]

        answers = dns.resolver.resolve(hostname, "TXT", lifetime=8)
        return [b.decode() for rdata in answers for b in rdata.strings]
    except ImportError:
        pass

    # Minimal fallback using getaddrinfo (won't resolve TXT, just proves DNS works)
    # In practice, deployments must have dnspython installed.
    try:
        socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        pass
    raise RuntimeError(
        "dnspython is required for DNS TXT verification. Install it with: pip install dnspython"
    )


def _normalize_uuid(value: UUID | str) -> UUID:
    return value if isinstance(value, UUID) else UUID(str(value))


class DomainVerificationService:
    async def list_verifications(
        self, db: AsyncSession, *, organization_id: UUID
    ) -> list[OrgDomainVerification]:
        organization_uuid = _normalize_uuid(organization_id)
        result = await db.execute(
            select(OrgDomainVerification)
            .where(OrgDomainVerification.organization_id == organization_uuid)
            .order_by(OrgDomainVerification.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_verification(
        self, db: AsyncSession, *, verification_id: UUID, organization_id: UUID
    ) -> OrgDomainVerification | None:
        organization_uuid = _normalize_uuid(organization_id)
        result = await db.execute(
            select(OrgDomainVerification).where(
                OrgDomainVerification.id == verification_id,
                OrgDomainVerification.organization_id == organization_uuid,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_domain(
        self, db: AsyncSession, *, domain: str, organization_id: UUID
    ) -> OrgDomainVerification | None:
        organization_uuid = _normalize_uuid(organization_id)
        result = await db.execute(
            select(OrgDomainVerification).where(
                OrgDomainVerification.domain == domain.strip().lower(),
                OrgDomainVerification.organization_id == organization_uuid,
            )
        )
        return result.scalar_one_or_none()

    async def initiate(
        self,
        db: AsyncSession,
        *,
        organization_id: UUID,
        domain: str,
        actor_id: UUID | None,
    ) -> OrgDomainVerification:
        organization_uuid = _normalize_uuid(organization_id)
        actor_uuid = _normalize_uuid(actor_id) if actor_id is not None else None
        clean_domain = domain.strip().lower().lstrip("@")
        existing = await self.get_by_domain(
            db, domain=clean_domain, organization_id=organization_uuid
        )
        if existing is not None:
            # Reset token and status so the admin can retry
            existing.verification_token = _generate_verification_token()
            existing.status = "pending"
            existing.verified_at = None
            existing.last_checked_at = None
            existing.failure_reason = None
            await db.flush()
            await db.refresh(existing)
            return existing

        record = OrgDomainVerification(
            organization_id=organization_uuid,
            domain=clean_domain,
            status="pending",
            verification_token=_generate_verification_token(),
            created_by_id=actor_uuid,
        )
        db.add(record)
        await db.flush()
        await db.refresh(record)
        return record

    async def check(
        self,
        db: AsyncSession,
        *,
        verification_id: UUID,
        organization_id: UUID,
    ) -> OrgDomainVerification:
        organization_uuid = _normalize_uuid(organization_id)
        record = await self.get_verification(
            db, verification_id=verification_id, organization_id=organization_uuid
        )
        if record is None:
            raise ValueError("Domain verification record not found.")

        now = datetime.now(UTC)
        verified, message = _check_dns_txt(record.domain, record.verification_token)

        record.last_checked_at = now
        if verified:
            record.status = "verified"
            record.verified_at = now
            record.failure_reason = None
        else:
            record.status = "failed"
            record.failure_reason = message

        await db.flush()
        await db.refresh(record)
        return record

    async def delete(
        self,
        db: AsyncSession,
        *,
        verification_id: UUID,
        organization_id: UUID,
    ) -> bool:
        organization_uuid = _normalize_uuid(organization_id)
        record = await self.get_verification(
            db, verification_id=verification_id, organization_id=organization_uuid
        )
        if record is None:
            return False
        await db.delete(record)
        await db.flush()
        return True
