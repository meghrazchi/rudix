from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import String, and_, cast, false, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from app.models.usage import AuditLog, UsageEvent


class UsageRepository:
    _SUCCESS_RESULTS = ("ok", "success", "succeeded", "completed")
    _FAILURE_RESULTS = ("failed", "failure", "error", "denied", "rejected")

    @staticmethod
    def _metadata_text(key: str):
        return AuditLog.metadata_json[key].as_string()

    def _with_audit_filters(
        self,
        statement: Select,
        *,
        organization_id: UUID,
        from_created_at: datetime | None = None,
        to_created_at: datetime | None = None,
        user_id: UUID | None = None,
        system_actor_only: bool = False,
        actor_email: str | None = None,
        action: str | None = None,
        resource_type: str | None = None,
        resource_id: UUID | None = None,
        request_id: str | None = None,
        session_id: str | None = None,
        ip_address: str | None = None,
        document_id: UUID | None = None,
        collection_id: UUID | None = None,
        result: str | None = None,
        severity: str | None = None,
        search: str | None = None,
    ) -> Select:
        statement = statement.where(AuditLog.organization_id == organization_id)
        if from_created_at is not None:
            statement = statement.where(AuditLog.created_at >= from_created_at)
        if to_created_at is not None:
            statement = statement.where(AuditLog.created_at <= to_created_at)
        if user_id is not None:
            statement = statement.where(AuditLog.user_id == user_id)
        if system_actor_only:
            statement = statement.where(AuditLog.user_id.is_(None))
        if actor_email is not None:
            statement = statement.where(
                func.lower(self._metadata_text("actor_email")).like(f"%{actor_email.lower()}%")
            )
        if action is not None:
            statement = statement.where(AuditLog.action == action)
        if resource_type is not None:
            statement = statement.where(AuditLog.resource_type == resource_type)
        if resource_id is not None:
            statement = statement.where(AuditLog.resource_id == resource_id)
        if request_id is not None:
            statement = statement.where(
                func.lower(self._metadata_text("request_id")) == request_id.lower()
            )

        if session_id is not None:
            session_term = f"%{session_id.lower()}%"
            statement = statement.where(
                or_(
                    func.lower(self._metadata_text("session_id")).like(session_term),
                    func.lower(self._metadata_text("auth_session_id")).like(session_term),
                    func.lower(self._metadata_text("chat_session_id")).like(session_term),
                )
            )

        if ip_address is not None:
            ip_term = f"%{ip_address.lower()}%"
            statement = statement.where(
                or_(
                    func.lower(self._metadata_text("ip_address")).like(ip_term),
                    func.lower(self._metadata_text("ip")).like(ip_term),
                )
            )

        if document_id is not None:
            document_id_text = str(document_id)
            statement = statement.where(
                or_(
                    and_(
                        AuditLog.resource_type == "document",
                        cast(AuditLog.resource_id, String) == document_id_text,
                    ),
                    self._metadata_text("document_id") == document_id_text,
                )
            )

        if collection_id is not None:
            collection_id_text = str(collection_id)
            statement = statement.where(
                or_(
                    and_(
                        AuditLog.resource_type == "collection",
                        cast(AuditLog.resource_id, String) == collection_id_text,
                    ),
                    self._metadata_text("collection_id") == collection_id_text,
                )
            )

        if severity is not None:
            statement = statement.where(
                func.lower(self._metadata_text("severity")) == severity.lower()
            )

        status_code = self._metadata_text("status_code")
        http_status = self._metadata_text("http_status")
        result_text = func.lower(self._metadata_text("result"))
        outcome_text = func.lower(self._metadata_text("outcome"))
        success_status = or_(
            status_code.like("2%"),
            status_code.like("3%"),
            http_status.like("2%"),
            http_status.like("3%"),
        )
        failure_status = or_(
            status_code.like("4%"),
            status_code.like("5%"),
            http_status.like("4%"),
            http_status.like("5%"),
        )
        success_text = or_(
            result_text.in_(self._SUCCESS_RESULTS),
            outcome_text.in_(self._SUCCESS_RESULTS),
        )
        failure_text = or_(
            result_text.in_(self._FAILURE_RESULTS),
            outcome_text.in_(self._FAILURE_RESULTS),
        )
        success_expr = or_(success_status, success_text)
        failure_expr = or_(failure_status, failure_text)

        if result == "success":
            statement = statement.where(success_expr)
        elif result == "failure":
            statement = statement.where(failure_expr)
        elif result == "unknown":
            statement = statement.where(
                func.coalesce(success_expr, false()) == false(),
                func.coalesce(failure_expr, false()) == false(),
            )

        if search is not None:
            normalized = f"%{search.lower()}%"
            statement = statement.where(
                or_(
                    func.lower(AuditLog.action).like(normalized),
                    func.lower(AuditLog.resource_type).like(normalized),
                    func.lower(cast(AuditLog.resource_id, String)).like(normalized),
                    func.lower(cast(AuditLog.user_id, String)).like(normalized),
                    func.lower(self._metadata_text("request_id")).like(normalized),
                    func.lower(self._metadata_text("session_id")).like(normalized),
                    func.lower(self._metadata_text("ip_address")).like(normalized),
                    func.lower(self._metadata_text("document_id")).like(normalized),
                    func.lower(self._metadata_text("collection_id")).like(normalized),
                )
            )

        return statement

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
        provider_key: str | None = None,
        profile_name: str | None = None,
        task_type: str | None = None,
        retry_count: int | None = None,
        timed_out: bool = False,
        fallback_used: bool = False,
        error_code: str | None = None,
        request_id: str | None = None,
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
            provider_key=provider_key,
            profile_name=profile_name,
            task_type=task_type,
            retry_count=retry_count,
            timed_out=timed_out,
            fallback_used=fallback_used,
            error_code=error_code,
            request_id=request_id,
        )
        session.add(usage_event)
        await session.flush()
        await session.refresh(usage_event)
        return usage_event

    async def create_audit_log(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        user_id: UUID | None,
        action: str,
        resource_type: str,
        resource_id: UUID | None = None,
        metadata: dict | None = None,
    ) -> AuditLog:
        audit_log = AuditLog(
            organization_id=organization_id,
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            metadata_json=metadata or {},
        )
        session.add(audit_log)
        await session.flush()
        await session.refresh(audit_log)
        return audit_log

    async def list_usage_events(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        from_created_at: datetime | None = None,
        to_created_at: datetime | None = None,
        user_id: UUID | None = None,
    ) -> list[UsageEvent]:
        statement = select(UsageEvent).where(UsageEvent.organization_id == organization_id)
        if from_created_at is not None:
            statement = statement.where(UsageEvent.created_at >= from_created_at)
        if to_created_at is not None:
            statement = statement.where(UsageEvent.created_at <= to_created_at)
        if user_id is not None:
            statement = statement.where(UsageEvent.user_id == user_id)

        result = await session.execute(
            statement.order_by(UsageEvent.created_at.asc(), UsageEvent.id.asc())
        )
        return list(result.scalars().all())

    async def list_audit_logs(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        limit: int = 50,
        offset: int = 0,
        from_created_at: datetime | None = None,
        to_created_at: datetime | None = None,
        user_id: UUID | None = None,
        system_actor_only: bool = False,
        actor_email: str | None = None,
        action: str | None = None,
        resource_type: str | None = None,
        resource_id: UUID | None = None,
        request_id: str | None = None,
        session_id: str | None = None,
        ip_address: str | None = None,
        document_id: UUID | None = None,
        collection_id: UUID | None = None,
        result: str | None = None,
        severity: str | None = None,
        search: str | None = None,
    ) -> list[AuditLog]:
        statement = self._with_audit_filters(
            select(AuditLog),
            organization_id=organization_id,
            from_created_at=from_created_at,
            to_created_at=to_created_at,
            user_id=user_id,
            system_actor_only=system_actor_only,
            actor_email=actor_email,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            request_id=request_id,
            session_id=session_id,
            ip_address=ip_address,
            document_id=document_id,
            collection_id=collection_id,
            result=result,
            severity=severity,
            search=search,
        )

        statement = (
            statement.order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await session.execute(statement)
        return list(result.scalars().all())

    async def count_audit_logs(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        from_created_at: datetime | None = None,
        to_created_at: datetime | None = None,
        user_id: UUID | None = None,
        system_actor_only: bool = False,
        actor_email: str | None = None,
        action: str | None = None,
        resource_type: str | None = None,
        resource_id: UUID | None = None,
        request_id: str | None = None,
        session_id: str | None = None,
        ip_address: str | None = None,
        document_id: UUID | None = None,
        collection_id: UUID | None = None,
        result: str | None = None,
        severity: str | None = None,
        search: str | None = None,
    ) -> int:
        statement = self._with_audit_filters(
            select(func.count(AuditLog.id)),
            organization_id=organization_id,
            from_created_at=from_created_at,
            to_created_at=to_created_at,
            user_id=user_id,
            system_actor_only=system_actor_only,
            actor_email=actor_email,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            request_id=request_id,
            session_id=session_id,
            ip_address=ip_address,
            document_id=document_id,
            collection_id=collection_id,
            result=result,
            severity=severity,
            search=search,
        )

        result = await session.execute(statement)
        return int(result.scalar_one())

    async def count_audit_logs_grouped_by_action(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        from_created_at: datetime | None = None,
        to_created_at: datetime | None = None,
        action_prefix: str | None = None,
    ) -> dict[str, int]:
        statement = (
            select(AuditLog.action, func.count(AuditLog.id))
            .where(AuditLog.organization_id == organization_id)
            .group_by(AuditLog.action)
        )
        if from_created_at is not None:
            statement = statement.where(AuditLog.created_at >= from_created_at)
        if to_created_at is not None:
            statement = statement.where(AuditLog.created_at <= to_created_at)
        if action_prefix:
            statement = statement.where(AuditLog.action.like(f"{action_prefix}%"))

        rows = (await session.execute(statement)).all()
        return {str(action): int(count) for action, count in rows}

    async def list_usage_events_filtered(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        from_created_at: datetime | None = None,
        to_created_at: datetime | None = None,
        user_id: UUID | None = None,
        model_name: str | None = None,
        event_type_prefix: str | None = None,
    ) -> list[UsageEvent]:
        statement = select(UsageEvent).where(UsageEvent.organization_id == organization_id)
        if from_created_at is not None:
            statement = statement.where(UsageEvent.created_at >= from_created_at)
        if to_created_at is not None:
            statement = statement.where(UsageEvent.created_at <= to_created_at)
        if user_id is not None:
            statement = statement.where(UsageEvent.user_id == user_id)
        if model_name is not None:
            statement = statement.where(UsageEvent.model_name == model_name)
        if event_type_prefix is not None:
            statement = statement.where(UsageEvent.event_type.like(f"{event_type_prefix}%"))
        result = await session.execute(
            statement.order_by(UsageEvent.created_at.asc(), UsageEvent.id.asc())
        )
        return list(result.scalars().all())

    async def count_active_users(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        from_created_at: datetime | None = None,
        to_created_at: datetime | None = None,
    ) -> int:
        statement = (
            select(func.count(func.distinct(UsageEvent.user_id)))
            .where(UsageEvent.organization_id == organization_id)
            .where(UsageEvent.user_id.is_not(None))
        )
        if from_created_at is not None:
            statement = statement.where(UsageEvent.created_at >= from_created_at)
        if to_created_at is not None:
            statement = statement.where(UsageEvent.created_at <= to_created_at)
        result = await session.execute(statement)
        return int(result.scalar_one() or 0)

    @dataclass
    class _UserAggRow:
        user_id: str
        event_count: int
        input_tokens: int
        output_tokens: int
        cost_usd: Decimal

    async def aggregate_by_user(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        from_created_at: datetime | None = None,
        to_created_at: datetime | None = None,
        limit: int = 10,
    ) -> list["UsageRepository._UserAggRow"]:
        statement = (
            select(
                cast(UsageEvent.user_id, String).label("user_id"),
                func.count(UsageEvent.id).label("event_count"),
                func.coalesce(func.sum(UsageEvent.input_tokens), 0).label("input_tokens"),
                func.coalesce(func.sum(UsageEvent.output_tokens), 0).label("output_tokens"),
                func.coalesce(func.sum(UsageEvent.cost_usd), Decimal("0")).label("cost_usd"),
            )
            .where(UsageEvent.organization_id == organization_id)
            .where(UsageEvent.user_id.is_not(None))
            .group_by(UsageEvent.user_id)
            .order_by(func.coalesce(func.sum(UsageEvent.cost_usd), Decimal("0")).desc())
            .limit(limit)
        )
        if from_created_at is not None:
            statement = statement.where(UsageEvent.created_at >= from_created_at)
        if to_created_at is not None:
            statement = statement.where(UsageEvent.created_at <= to_created_at)
        rows = (await session.execute(statement)).all()
        return [
            UsageRepository._UserAggRow(
                user_id=str(row.user_id),
                event_count=int(row.event_count),
                input_tokens=int(row.input_tokens or 0),
                output_tokens=int(row.output_tokens or 0),
                cost_usd=Decimal(str(row.cost_usd or "0")),
            )
            for row in rows
        ]

    @dataclass
    class _ModelAggRow:
        model_name: str
        event_count: int
        input_tokens: int
        output_tokens: int
        cost_usd: Decimal

    async def aggregate_by_model(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        from_created_at: datetime | None = None,
        to_created_at: datetime | None = None,
        limit: int = 10,
    ) -> list["UsageRepository._ModelAggRow"]:
        statement = (
            select(
                UsageEvent.model_name,
                func.count(UsageEvent.id).label("event_count"),
                func.coalesce(func.sum(UsageEvent.input_tokens), 0).label("input_tokens"),
                func.coalesce(func.sum(UsageEvent.output_tokens), 0).label("output_tokens"),
                func.coalesce(func.sum(UsageEvent.cost_usd), Decimal("0")).label("cost_usd"),
            )
            .where(UsageEvent.organization_id == organization_id)
            .where(UsageEvent.model_name.is_not(None))
            .group_by(UsageEvent.model_name)
            .order_by(func.coalesce(func.sum(UsageEvent.cost_usd), Decimal("0")).desc())
            .limit(limit)
        )
        if from_created_at is not None:
            statement = statement.where(UsageEvent.created_at >= from_created_at)
        if to_created_at is not None:
            statement = statement.where(UsageEvent.created_at <= to_created_at)
        rows = (await session.execute(statement)).all()
        return [
            UsageRepository._ModelAggRow(
                model_name=str(row.model_name),
                event_count=int(row.event_count),
                input_tokens=int(row.input_tokens or 0),
                output_tokens=int(row.output_tokens or 0),
                cost_usd=Decimal(str(row.cost_usd or "0")),
            )
            for row in rows
        ]

    async def count_events_by_feature_area(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        from_created_at: datetime | None = None,
        to_created_at: datetime | None = None,
    ) -> dict[str, int]:
        statement = (
            select(UsageEvent.event_type, func.count(UsageEvent.id))
            .where(UsageEvent.organization_id == organization_id)
            .group_by(UsageEvent.event_type)
        )
        if from_created_at is not None:
            statement = statement.where(UsageEvent.created_at >= from_created_at)
        if to_created_at is not None:
            statement = statement.where(UsageEvent.created_at <= to_created_at)
        rows = (await session.execute(statement)).all()
        area_counts: dict[str, int] = {}
        for event_type, count in rows:
            if event_type:
                prefix = event_type.split(".")[0]
            else:
                prefix = "unknown"
            area_counts[prefix] = area_counts.get(prefix, 0) + int(count)
        return area_counts

    @dataclass
    class _ProviderAggRow:
        provider_key: str
        total_events: int
        failed_events: int
        timed_out_events: int
        fallback_events: int
        retry_events: int
        total_retry_count: int
        latency_values: list[float]

    async def aggregate_by_provider(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        from_created_at: datetime | None = None,
        to_created_at: datetime | None = None,
    ) -> list["UsageRepository._ProviderAggRow"]:
        """Aggregate usage events by provider_key for health monitoring.

        Only returns rows where provider_key is set (F228 events).
        """
        statement = select(UsageEvent).where(
            UsageEvent.organization_id == organization_id,
            UsageEvent.provider_key.is_not(None),
        )
        if from_created_at is not None:
            statement = statement.where(UsageEvent.created_at >= from_created_at)
        if to_created_at is not None:
            statement = statement.where(UsageEvent.created_at <= to_created_at)
        rows = list((await session.execute(statement)).scalars().all())

        buckets: dict[str, UsageRepository._ProviderAggRow] = {}
        for row in rows:
            key = row.provider_key or "unknown"
            if key not in buckets:
                buckets[key] = UsageRepository._ProviderAggRow(
                    provider_key=key,
                    total_events=0,
                    failed_events=0,
                    timed_out_events=0,
                    fallback_events=0,
                    retry_events=0,
                    total_retry_count=0,
                    latency_values=[],
                )
            b = buckets[key]
            b.total_events += 1
            if row.error_code is not None:
                b.failed_events += 1
            if row.timed_out:
                b.timed_out_events += 1
            if row.fallback_used:
                b.fallback_events += 1
            if row.retry_count is not None and row.retry_count > 0:
                b.retry_events += 1
                b.total_retry_count += row.retry_count
            metadata = row.metadata_json if isinstance(row.metadata_json, dict) else {}
            for lat_key in ("latency_ms", "answer_latency_ms", "duration_ms"):
                lat = metadata.get(lat_key)
                if isinstance(lat, (int, float)) and lat >= 0:
                    b.latency_values.append(float(lat))
                    break

        return list(buckets.values())
