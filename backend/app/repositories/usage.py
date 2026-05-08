from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.usage import UsageEvent


class UsageRepository:
    async def create_usage_event(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        user_id: UUID | None,
        event_type: str,
        model_name: str | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        cost_usd: Decimal | None = None,
        metadata: dict | None = None,
    ) -> UsageEvent:
        usage_event = UsageEvent(
            organization_id=organization_id,
            user_id=user_id,
            event_type=event_type,
            model_name=model_name,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
            metadata_json=metadata or {},
        )
        session.add(usage_event)
        await session.flush()
        await session.refresh(usage_event)
        return usage_event
