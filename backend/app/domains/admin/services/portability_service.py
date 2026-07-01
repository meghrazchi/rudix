from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domains.admin.schemas.portability import (
    PortabilityValidationIssue,
    PortabilityWarning,
    WorkspaceExportRequest,
    WorkspaceImportRequest,
    WorkspacePortabilityJobResponse,
)
from app.domains.admin.services.audit_service import sanitize_metadata
from app.models.api_key import ApiKey
from app.models.chat import ChatSession
from app.models.collection import Collection, CollectionAccessGrant
from app.models.document import Document
from app.models.enums import EvaluationDatasetStatus
from app.models.evaluation import EvaluationQuestion, EvaluationRun, EvaluationSet
from app.models.governance import OrganizationGovernancePolicy
from app.models.metadata import DocumentMetadata, MetadataField
from app.models.organization import Organization
from app.models.portability import WorkspacePortabilityJob
from app.models.usage import AuditLog
from app.models.webhook import Webhook

EXPORT_SCHEMA_VERSION = "rudix.workspace_export.v1"
IMPORT_REPORT_SCHEMA_VERSION = "rudix.workspace_import_report.v1"
ARTIFACT_TTL_DAYS = 7
IMPORTABLE_SECTIONS = {"collections", "document_metadata", "evaluation_datasets"}
EXPORTABLE_SECTIONS = {
    "collections",
    "document_metadata",
    "chat_transcripts",
    "evaluation_datasets",
    "evaluation_results",
    "audit_logs",
    "settings",
    "api_metadata",
    "webhook_metadata",
}
COLLECTION_POLICIES = {"org_wide", "admin_only", "selected_roles", "selected_members"}
METADATA_FIELD_TYPES = {"text", "select", "multi_select", "date", "boolean", "number"}
FILE_TYPES = {"pdf", "txt", "docx"}
RETENTION_CLASSES = {"standard", "legal_hold", "confidential", "archive", "gdpr_restricted"}

_INLINE_SECRET_PATTERN = re.compile(
    r"(?i)\b(api[_-]?key|access[_-]?token|refresh[_-]?token|client[_-]?secret|"
    r"private[_-]?key|secret|token|password)\b\s*[:=]\s*([^\s,;]+)"
)
_BEARER_PATTERN = re.compile(r"(?i)\bbearer\s+[a-z0-9._~+/=-]+")


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    return value


def _redact_inline_secrets(value: str) -> str:
    redacted = _INLINE_SECRET_PATTERN.sub(r"\1=***", value)
    return _BEARER_PATTERN.sub("Bearer ***", redacted)


def _clean_string(value: Any, max_length: int) -> str | None:
    if not isinstance(value, str):
        return None
    trimmed = value.strip()
    if not trimmed:
        return None
    return trimmed[:max_length]


def _parse_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _utc_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _safe_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _section_payload(artifact: dict[str, Any], section: str) -> dict[str, Any]:
    sections = artifact.get("sections")
    if not isinstance(sections, dict):
        return {}
    payload = sections.get(section)
    return payload if isinstance(payload, dict) else {}


class WorkspacePortabilityService:
    async def create_export_job(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        actor_user_id: UUID,
        request: WorkspaceExportRequest,
    ) -> WorkspacePortabilityJob:
        job = WorkspacePortabilityJob(
            organization_id=organization_id,
            created_by_user_id=actor_user_id,
            job_type="export",
            status="queued",
            requested_sections_json=list(request.sections),
            parameters_json={
                "from": request.from_date.isoformat() if request.from_date else None,
                "to": request.to_date.isoformat() if request.to_date else None,
                "max_rows_per_section": request.max_rows_per_section,
            },
        )
        session.add(job)
        await session.flush()
        await self._run_export(session, job=job, request=request)
        await session.flush()
        await session.refresh(job)
        return job

    async def create_import_job(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        actor_user_id: UUID,
        request: WorkspaceImportRequest,
    ) -> WorkspacePortabilityJob:
        requested_sections = self._import_sections(request.artifact)
        job = WorkspacePortabilityJob(
            organization_id=organization_id,
            created_by_user_id=actor_user_id,
            job_type="import",
            status="queued",
            requested_sections_json=requested_sections,
            parameters_json={"apply": request.apply},
        )
        session.add(job)
        await session.flush()
        await self._run_import(
            session,
            job=job,
            artifact=request.artifact,
            apply_changes=request.apply,
            actor_user_id=actor_user_id,
        )
        await session.flush()
        await session.refresh(job)
        return job

    async def list_jobs(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        limit: int,
        offset: int,
    ) -> tuple[list[WorkspacePortabilityJob], int]:
        base = select(WorkspacePortabilityJob).where(
            WorkspacePortabilityJob.organization_id == organization_id
        )
        total = int(
            (await session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
        )
        result = await session.execute(
            base.order_by(
                WorkspacePortabilityJob.created_at.desc(),
                WorkspacePortabilityJob.id.desc(),
            )
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all()), total

    async def get_job(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        job_id: UUID,
    ) -> WorkspacePortabilityJob | None:
        result = await session.execute(
            select(WorkspacePortabilityJob).where(
                WorkspacePortabilityJob.id == job_id,
                WorkspacePortabilityJob.organization_id == organization_id,
            )
        )
        return result.scalar_one_or_none()

    def to_response(self, job: WorkspacePortabilityJob) -> WorkspacePortabilityJobResponse:
        now = datetime.now(UTC)
        download_available = (
            job.artifact_json is not None
            and job.status in {"completed", "validated"}
            and (job.expires_at is None or _utc_datetime(job.expires_at) > now)
        )
        return WorkspacePortabilityJobResponse(
            job_id=str(job.id),
            organization_id=str(job.organization_id),
            created_by_user_id=str(job.created_by_user_id) if job.created_by_user_id else None,
            job_type=job.job_type,  # type: ignore[arg-type]
            status=job.status,  # type: ignore[arg-type]
            requested_sections=list(job.requested_sections_json or []),
            parameters=dict(job.parameters_json or {}),
            artifact_filename=job.artifact_filename,
            artifact_mime_type=job.artifact_mime_type,
            artifact_size_bytes=job.artifact_size_bytes,
            validation_errors=[
                PortabilityValidationIssue.model_validate(item)
                for item in list(job.validation_errors_json or [])
            ],
            warnings=[
                PortabilityWarning.model_validate(item) for item in list(job.warnings_json or [])
            ],
            error_message=job.error_message,
            records_processed=job.records_processed,
            records_failed=job.records_failed,
            created_at=job.created_at,
            updated_at=job.updated_at,
            started_at=job.started_at,
            completed_at=job.completed_at,
            expires_at=job.expires_at,
            download_available=download_available,
        )

    async def _run_export(
        self,
        session: AsyncSession,
        *,
        job: WorkspacePortabilityJob,
        request: WorkspaceExportRequest,
    ) -> None:
        now = datetime.now(UTC)
        job.status = "running"
        job.started_at = now
        organization = await session.get(Organization, job.organization_id)
        sections: dict[str, Any] = {}
        total = 0
        bounds = self._datetime_bounds(request.from_date, request.to_date)

        for section in request.sections:
            payload, count = await self._export_section(
                session,
                section=section,
                organization_id=job.organization_id,
                max_rows=request.max_rows_per_section,
                bounds=bounds,
            )
            sections[section] = payload
            total += count

        artifact = {
            "schema_version": EXPORT_SCHEMA_VERSION,
            "generated_at": now.isoformat(),
            "organization": {
                "id": str(job.organization_id),
                "name": organization.name if organization else None,
                "slug": organization.slug if organization else None,
            },
            "requested_sections": list(request.sections),
            "limits": {
                "max_rows_per_section": request.max_rows_per_section,
                "from": request.from_date.isoformat() if request.from_date else None,
                "to": request.to_date.isoformat() if request.to_date else None,
                "artifact_expires_days": ARTIFACT_TTL_DAYS,
            },
            "sections": sections,
            "limitations": [
                "Original document files, extracted text, embeddings, and vector payloads are not included.",
                "API key hashes, webhook secret hashes, OAuth tokens, and connector credentials are never exported.",
                "Document manifests are safe metadata only and require separate file upload before re-indexing.",
            ],
        }
        filename = f"rudix-workspace-export-{str(job.id)[:8]}.json"
        self._store_artifact(job, artifact=artifact, filename=filename)
        job.status = "completed"
        job.records_processed = total
        job.completed_at = datetime.now(UTC)
        job.expires_at = job.completed_at + timedelta(days=ARTIFACT_TTL_DAYS)

    async def _export_section(
        self,
        session: AsyncSession,
        *,
        section: str,
        organization_id: UUID,
        max_rows: int,
        bounds: tuple[datetime | None, datetime | None],
    ) -> tuple[dict[str, Any], int]:
        if section == "collections":
            return await self._export_collections(session, organization_id, max_rows)
        if section == "document_metadata":
            return await self._export_document_metadata(session, organization_id, max_rows)
        if section == "chat_transcripts":
            return await self._export_chat(session, organization_id, max_rows, bounds)
        if section == "evaluation_datasets":
            return await self._export_evaluation_sets(session, organization_id, max_rows)
        if section == "evaluation_results":
            return await self._export_evaluation_results(session, organization_id, max_rows, bounds)
        if section == "audit_logs":
            return await self._export_audit_logs(session, organization_id, max_rows, bounds)
        if section == "settings":
            return await self._export_settings(session, organization_id)
        if section == "api_metadata":
            return await self._export_api_metadata(session, organization_id, max_rows)
        if section == "webhook_metadata":
            return await self._export_webhook_metadata(session, organization_id, max_rows)
        return {"items": []}, 0

    async def _export_collections(
        self,
        session: AsyncSession,
        organization_id: UUID,
        max_rows: int,
    ) -> tuple[dict[str, Any], int]:
        result = await session.execute(
            select(Collection)
            .options(
                selectinload(Collection.document_memberships),
                selectinload(Collection.access_grants),
            )
            .where(Collection.organization_id == organization_id, Collection.is_archived.is_(False))
            .order_by(Collection.created_at.asc(), Collection.id.asc())
            .limit(max_rows)
        )
        collections = list(result.scalars().all())
        items = [
            {
                "id": str(c.id),
                "name": c.name,
                "description": c.description,
                "access_policy": c.access_policy,
                "is_dynamic": c.is_dynamic,
                "rule_schema": _jsonable(c.rule_schema),
                "review_status": c.review_status,
                "review_due_date": _jsonable(c.review_due_date),
                "expiry_date": _jsonable(c.expiry_date),
                "trust_level": c.trust_level,
                "document_manifest_ids": [str(m.document_id) for m in c.document_memberships],
                "access_grants": [
                    {"grantee_type": g.grantee_type, "grantee_value": g.grantee_value}
                    for g in c.access_grants
                ],
                "created_at": c.created_at.isoformat(),
                "updated_at": c.updated_at.isoformat(),
            }
            for c in collections
        ]
        return {"items": items}, len(items)

    async def _export_document_metadata(
        self,
        session: AsyncSession,
        organization_id: UUID,
        max_rows: int,
    ) -> tuple[dict[str, Any], int]:
        field_result = await session.execute(
            select(MetadataField)
            .where(MetadataField.organization_id == organization_id)
            .order_by(MetadataField.sort_order.asc(), MetadataField.name.asc())
        )
        fields = list(field_result.scalars().all())
        doc_result = await session.execute(
            select(Document)
            .where(Document.organization_id == organization_id, Document.status != "deleted")
            .order_by(Document.created_at.asc(), Document.id.asc())
            .limit(max_rows)
        )
        documents = list(doc_result.scalars().all())
        value_result = await session.execute(
            select(DocumentMetadata, MetadataField)
            .join(MetadataField, MetadataField.id == DocumentMetadata.field_id)
            .join(Document, Document.id == DocumentMetadata.document_id)
            .where(
                DocumentMetadata.organization_id == organization_id, Document.status != "deleted"
            )
            .order_by(DocumentMetadata.created_at.asc())
            .limit(max_rows)
        )
        values = [
            {
                "document_id": str(value.document_id),
                "field_name": field.name,
                "value_text": value.value_text,
                "value_json": _jsonable(value.value_json),
            }
            for value, field in value_result.all()
        ]
        payload = {
            "fields": [
                {
                    "name": f.name,
                    "display_name": f.display_name,
                    "field_type": f.field_type,
                    "allowed_values": _jsonable(f.allowed_values),
                    "is_required": f.is_required,
                    "is_filterable": f.is_filterable,
                    "description": f.description,
                    "sort_order": f.sort_order,
                    "is_active": f.is_active,
                }
                for f in fields
            ],
            "documents": [self._document_manifest(d) for d in documents],
            "values": values,
        }
        return payload, len(fields) + len(documents) + len(values)

    async def _export_chat(
        self,
        session: AsyncSession,
        organization_id: UUID,
        max_rows: int,
        bounds: tuple[datetime | None, datetime | None],
    ) -> tuple[dict[str, Any], int]:
        stmt = (
            select(ChatSession)
            .options(selectinload(ChatSession.messages))
            .where(ChatSession.organization_id == organization_id)
            .order_by(ChatSession.created_at.asc(), ChatSession.id.asc())
            .limit(max_rows)
        )
        stmt = self._apply_bounds(stmt, ChatSession.created_at, bounds)
        sessions = list((await session.execute(stmt)).scalars().all())
        items = []
        count = 0
        for chat_session in sessions:
            messages = []
            for message in sorted(chat_session.messages, key=lambda item: item.created_at):
                count += 1
                messages.append(
                    {
                        "id": str(message.id),
                        "role": message.role,
                        "content": _redact_inline_secrets(message.content),
                        "confidence_score": message.confidence_score,
                        "latency_ms": message.latency_ms,
                        "model_name": message.model_name,
                        "created_at": message.created_at.isoformat(),
                    }
                )
            items.append(
                {
                    "id": str(chat_session.id),
                    "user_id": str(chat_session.user_id),
                    "title": chat_session.title,
                    "created_at": chat_session.created_at.isoformat(),
                    "updated_at": chat_session.updated_at.isoformat(),
                    "messages": messages,
                }
            )
        return {"items": items}, len(items) + count

    async def _export_evaluation_sets(
        self,
        session: AsyncSession,
        organization_id: UUID,
        max_rows: int,
    ) -> tuple[dict[str, Any], int]:
        result = await session.execute(
            select(EvaluationSet)
            .options(selectinload(EvaluationSet.questions))
            .where(EvaluationSet.organization_id == organization_id)
            .order_by(EvaluationSet.created_at.asc(), EvaluationSet.id.asc())
            .limit(max_rows)
        )
        sets = list(result.scalars().all())
        items = []
        count = 0
        for dataset in sets:
            questions = [
                {
                    "question": q.question,
                    "expected_answer": q.expected_answer,
                    "expected_page_number": q.expected_page_number,
                    "difficulty": q.difficulty,
                    "metadata": sanitize_metadata(q.metadata_json),
                    "question_language": q.question_language,
                    "expected_answer_language": q.expected_answer_language,
                    "source_language": q.source_language,
                    "translation_notes": q.translation_notes,
                }
                for q in sorted(dataset.questions, key=lambda item: item.created_at)
            ]
            count += len(questions)
            items.append(
                {
                    "id": str(dataset.id),
                    "name": dataset.name,
                    "description": dataset.description,
                    "status": dataset.status,
                    "version": dataset.version,
                    "scope": sanitize_metadata(dataset.scope_json),
                    "questions": questions,
                }
            )
        return {"items": items}, len(items) + count

    async def _export_evaluation_results(
        self,
        session: AsyncSession,
        organization_id: UUID,
        max_rows: int,
        bounds: tuple[datetime | None, datetime | None],
    ) -> tuple[dict[str, Any], int]:
        stmt = (
            select(EvaluationRun)
            .join(EvaluationSet, EvaluationSet.id == EvaluationRun.evaluation_set_id)
            .options(selectinload(EvaluationRun.results))
            .where(EvaluationSet.organization_id == organization_id)
            .order_by(EvaluationRun.created_at.asc(), EvaluationRun.id.asc())
            .limit(max_rows)
        )
        stmt = self._apply_bounds(stmt, EvaluationRun.created_at, bounds)
        runs = list((await session.execute(stmt)).scalars().all())
        items = []
        count = 0
        for run in runs:
            results = [
                {
                    "evaluation_question_id": str(r.evaluation_question_id),
                    "generated_answer": _redact_inline_secrets(r.generated_answer or ""),
                    "retrieval_score": r.retrieval_score,
                    "faithfulness_score": r.faithfulness_score,
                    "citation_accuracy_score": r.citation_accuracy_score,
                    "answer_relevance_score": r.answer_relevance_score,
                    "latency_ms": r.latency_ms,
                    "details": sanitize_metadata(r.details),
                }
                for r in sorted(run.results, key=lambda item: item.created_at)
            ]
            count += len(results)
            items.append(
                {
                    "id": str(run.id),
                    "evaluation_set_id": str(run.evaluation_set_id),
                    "status": run.status,
                    "config": sanitize_metadata(run.config),
                    "started_at": _jsonable(run.started_at),
                    "completed_at": _jsonable(run.completed_at),
                    "model_profile_key": run.model_profile_key,
                    "provider_type": run.provider_type,
                    "provider_profile": run.provider_profile,
                    "results": results,
                }
            )
        return {"items": items}, len(items) + count

    async def _export_audit_logs(
        self,
        session: AsyncSession,
        organization_id: UUID,
        max_rows: int,
        bounds: tuple[datetime | None, datetime | None],
    ) -> tuple[dict[str, Any], int]:
        stmt = (
            select(AuditLog)
            .where(AuditLog.organization_id == organization_id)
            .order_by(AuditLog.created_at.asc(), AuditLog.id.asc())
            .limit(max_rows)
        )
        stmt = self._apply_bounds(stmt, AuditLog.created_at, bounds)
        logs = list((await session.execute(stmt)).scalars().all())
        items = [
            {
                "id": str(log.id),
                "user_id": str(log.user_id) if log.user_id else None,
                "action": log.action,
                "resource_type": log.resource_type,
                "resource_id": str(log.resource_id) if log.resource_id else None,
                "metadata": sanitize_metadata(log.metadata_json),
                "created_at": log.created_at.isoformat(),
            }
            for log in logs
        ]
        return {"items": items}, len(items)

    async def _export_settings(
        self,
        session: AsyncSession,
        organization_id: UUID,
    ) -> tuple[dict[str, Any], int]:
        org = await session.get(Organization, organization_id)
        policy = (
            await session.execute(
                select(OrganizationGovernancePolicy).where(
                    OrganizationGovernancePolicy.organization_id == organization_id
                )
            )
        ).scalar_one_or_none()
        payload: dict[str, Any] = {
            "organization": {
                "name": org.name if org else None,
                "slug": org.slug if org else None,
                "analytics_enabled": org.analytics_enabled if org else None,
                "sample_docs_enabled": org.sample_docs_enabled if org else None,
            },
            "governance": None,
        }
        if policy is not None:
            payload["governance"] = {
                "agentic_mode_enabled": policy.agentic_mode_enabled,
                "mcp_exposure_enabled": policy.mcp_exposure_enabled,
                "allow_side_effect_tools": policy.allow_side_effect_tools,
                "allowed_tool_names": list(policy.allowed_tool_names_json or []),
                "max_steps": policy.max_steps,
                "max_tool_calls_per_run": policy.max_tool_calls_per_run,
                "max_tool_timeout_ms": policy.max_tool_timeout_ms,
                "max_total_tokens": policy.max_total_tokens,
                "max_total_cost_usd": _jsonable(policy.max_total_cost_usd),
                "local_only_mode": policy.local_only_mode,
                "cloud_fallback_allowed": policy.cloud_fallback_allowed,
                "admin_only_model_selection": policy.admin_only_model_selection,
                "retention_warning_acknowledged": policy.retention_warning_acknowledged,
            }
        return payload, 1

    async def _export_api_metadata(
        self,
        session: AsyncSession,
        organization_id: UUID,
        max_rows: int,
    ) -> tuple[dict[str, Any], int]:
        keys = list(
            (
                await session.execute(
                    select(ApiKey)
                    .where(ApiKey.organization_id == organization_id)
                    .order_by(ApiKey.created_at.asc(), ApiKey.id.asc())
                    .limit(max_rows)
                )
            )
            .scalars()
            .all()
        )
        items = [
            {
                "id": str(key.id),
                "name": key.name,
                "description": key.description,
                "key_prefix": key.key_prefix,
                "scopes": list(key.scopes or []),
                "status": key.status,
                "expires_at": _jsonable(key.expires_at),
                "last_used_at": _jsonable(key.last_used_at),
                "created_at": key.created_at.isoformat(),
            }
            for key in keys
        ]
        return {"items": items, "omitted_fields": ["key_hash", "raw_key"]}, len(items)

    async def _export_webhook_metadata(
        self,
        session: AsyncSession,
        organization_id: UUID,
        max_rows: int,
    ) -> tuple[dict[str, Any], int]:
        webhooks = list(
            (
                await session.execute(
                    select(Webhook)
                    .where(Webhook.organization_id == organization_id)
                    .order_by(Webhook.created_at.asc(), Webhook.id.asc())
                    .limit(max_rows)
                )
            )
            .scalars()
            .all()
        )
        items = [
            {
                "id": str(webhook.id),
                "name": webhook.name,
                "description": webhook.description,
                "url": webhook.url,
                "event_types": list(webhook.event_types or []),
                "status": webhook.status,
                "retry_policy": sanitize_metadata(webhook.retry_policy),
                "secret_configured": bool(webhook.secret_hash),
                "created_at": webhook.created_at.isoformat(),
            }
            for webhook in webhooks
        ]
        return {"items": items, "omitted_fields": ["secret_hash", "secret_prefix"]}, len(items)

    async def _run_import(
        self,
        session: AsyncSession,
        *,
        job: WorkspacePortabilityJob,
        artifact: dict[str, Any],
        apply_changes: bool,
        actor_user_id: UUID,
    ) -> None:
        now = datetime.now(UTC)
        job.started_at = now
        job.status = "running"
        errors, warnings, record_count = self._validate_import_artifact(artifact)
        job.validation_errors_json = errors
        job.warnings_json = warnings
        job.records_processed = record_count

        report = {
            "schema_version": IMPORT_REPORT_SCHEMA_VERSION,
            "validated_at": now.isoformat(),
            "applied": False,
            "validation_errors": errors,
            "warnings": warnings,
            "summary": {
                "validated_records": record_count,
                "created_records": 0,
                "skipped_records": 0,
            },
        }
        if errors:
            job.status = "validation_failed"
            job.records_failed = len(errors)
            job.error_message = "Import artifact failed validation"
            self._store_artifact(
                job, artifact=report, filename=f"rudix-import-report-{str(job.id)[:8]}.json"
            )
            job.completed_at = datetime.now(UTC)
            job.expires_at = job.completed_at + timedelta(days=ARTIFACT_TTL_DAYS)
            return

        if not apply_changes:
            job.status = "validated"
            self._store_artifact(
                job, artifact=report, filename=f"rudix-import-report-{str(job.id)[:8]}.json"
            )
            job.completed_at = datetime.now(UTC)
            job.expires_at = job.completed_at + timedelta(days=ARTIFACT_TTL_DAYS)
            return

        created, skipped = await self._apply_import(
            session,
            organization_id=job.organization_id,
            actor_user_id=actor_user_id,
            artifact=artifact,
        )
        report["applied"] = True
        report["summary"] = {
            "validated_records": record_count,
            "created_records": created,
            "skipped_records": skipped,
        }
        job.status = "completed"
        job.records_processed = created
        job.records_failed = 0
        self._store_artifact(
            job, artifact=report, filename=f"rudix-import-report-{str(job.id)[:8]}.json"
        )
        job.completed_at = datetime.now(UTC)
        job.expires_at = job.completed_at + timedelta(days=ARTIFACT_TTL_DAYS)

    async def _apply_import(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        actor_user_id: UUID,
        artifact: dict[str, Any],
    ) -> tuple[int, int]:
        created = 0
        skipped = 0
        collections = _safe_list(_section_payload(artifact, "collections").get("items"))
        for item in collections:
            item_dict = item if isinstance(item, dict) else {}
            name = _clean_string(item_dict.get("name"), 120)
            if name is None:
                continue
            existing = await self._collection_exists(session, organization_id, name)
            if existing:
                skipped += 1
                continue
            collection = Collection(
                organization_id=organization_id,
                owner_id=actor_user_id,
                name=name,
                description=_clean_string(item_dict.get("description"), 500),
                access_policy=item_dict.get("access_policy", "org_wide"),
                is_dynamic=bool(item_dict.get("is_dynamic", False)),
                rule_schema=item_dict.get("rule_schema")
                if isinstance(item_dict.get("rule_schema"), dict)
                else None,
            )
            session.add(collection)
            await session.flush()
            for grant in _safe_list(item_dict.get("access_grants")):
                grant_dict = grant if isinstance(grant, dict) else {}
                if grant_dict.get("grantee_type") in {"role", "member"} and isinstance(
                    grant_dict.get("grantee_value"), str
                ):
                    session.add(
                        CollectionAccessGrant(
                            collection_id=collection.id,
                            grantee_type=grant_dict["grantee_type"],
                            grantee_value=grant_dict["grantee_value"][:255],
                            granted_by_id=actor_user_id,
                        )
                    )
            created += 1

        created += await self._apply_metadata_fields(session, organization_id, artifact)
        dataset_created, dataset_skipped = await self._apply_evaluation_sets(
            session,
            organization_id,
            actor_user_id,
            artifact,
        )
        return created + dataset_created, skipped + dataset_skipped

    async def _apply_metadata_fields(
        self,
        session: AsyncSession,
        organization_id: UUID,
        artifact: dict[str, Any],
    ) -> int:
        created = 0
        fields = _safe_list(_section_payload(artifact, "document_metadata").get("fields"))
        for field in fields:
            field_dict = field if isinstance(field, dict) else {}
            name = _clean_string(field_dict.get("name"), 128)
            display_name = _clean_string(field_dict.get("display_name"), 256) or name
            field_type = field_dict.get("field_type")
            if name is None or field_type not in METADATA_FIELD_TYPES:
                continue
            existing = await self._metadata_field_exists(session, organization_id, name)
            if existing:
                continue
            sort_order = _parse_int(field_dict.get("sort_order"))
            session.add(
                MetadataField(
                    organization_id=organization_id,
                    name=name,
                    display_name=display_name or name,
                    field_type=field_type,
                    allowed_values=field_dict.get("allowed_values")
                    if isinstance(field_dict.get("allowed_values"), list)
                    else None,
                    is_required=bool(field_dict.get("is_required", False)),
                    is_filterable=bool(field_dict.get("is_filterable", True)),
                    description=_clean_string(field_dict.get("description"), 1024),
                    sort_order=sort_order if sort_order is not None and sort_order >= 0 else 0,
                    is_active=bool(field_dict.get("is_active", True)),
                )
            )
            created += 1
        return created

    async def _apply_evaluation_sets(
        self,
        session: AsyncSession,
        organization_id: UUID,
        actor_user_id: UUID,
        artifact: dict[str, Any],
    ) -> tuple[int, int]:
        created = 0
        skipped = 0
        datasets = _safe_list(_section_payload(artifact, "evaluation_datasets").get("items"))
        for item in datasets:
            item_dict = item if isinstance(item, dict) else {}
            name = _clean_string(item_dict.get("name"), 255)
            if name is None:
                continue
            existing = await self._evaluation_set_exists(session, organization_id, name)
            if existing:
                skipped += 1
                continue
            dataset = EvaluationSet(
                organization_id=organization_id,
                name=name,
                description=_clean_string(item_dict.get("description"), 8000),
                status=EvaluationDatasetStatus.draft.value,
                owner_id=actor_user_id,
                scope_json=item_dict.get("scope")
                if isinstance(item_dict.get("scope"), dict)
                else {},
            )
            session.add(dataset)
            await session.flush()
            for question in _safe_list(item_dict.get("questions")):
                question_dict = question if isinstance(question, dict) else {}
                question_text = _clean_string(question_dict.get("question"), 8000)
                if question_text is None:
                    continue
                expected_page_number = _parse_int(question_dict.get("expected_page_number"))
                session.add(
                    EvaluationQuestion(
                        evaluation_set_id=dataset.id,
                        question=question_text,
                        expected_answer=_clean_string(question_dict.get("expected_answer"), 8000),
                        expected_page_number=(
                            expected_page_number
                            if expected_page_number is not None and expected_page_number >= 1
                            else None
                        ),
                        difficulty=_clean_string(question_dict.get("difficulty"), 16),
                        owner_id=actor_user_id,
                        metadata_json=sanitize_metadata(
                            question_dict.get("metadata")
                            if isinstance(question_dict.get("metadata"), dict)
                            else {}
                        ),
                        question_language=_clean_string(question_dict.get("question_language"), 8),
                        expected_answer_language=_clean_string(
                            question_dict.get("expected_answer_language"), 8
                        ),
                        source_language=_clean_string(question_dict.get("source_language"), 8),
                        translation_notes=_clean_string(
                            question_dict.get("translation_notes"), 4000
                        ),
                    )
                )
            created += 1
        return created, skipped

    def _validate_import_artifact(
        self,
        artifact: dict[str, Any],
    ) -> tuple[list[dict[str, str]], list[dict[str, str]], int]:
        errors: list[dict[str, str]] = []
        warnings: list[dict[str, str]] = []
        sections = artifact.get("sections")
        if not isinstance(sections, dict):
            errors.append(
                self._issue(
                    "artifact",
                    "sections",
                    "missing_sections",
                    "artifact.sections must be an object",
                )
            )
            return errors, warnings, 0
        for section in sections:
            if section not in IMPORTABLE_SECTIONS and section in EXPORTABLE_SECTIONS:
                warnings.append(
                    self._warning(
                        section, "not_imported", f"{section} is export-only and will be ignored"
                    )
                )
            elif section not in EXPORTABLE_SECTIONS:
                warnings.append(
                    self._warning(section, "unknown_section", f"{section} is not recognized")
                )

        count = 0
        count += self._validate_collections(_section_payload(artifact, "collections"), errors)
        count += self._validate_metadata(
            _section_payload(artifact, "document_metadata"), errors, warnings
        )
        count += self._validate_evaluations(
            _section_payload(artifact, "evaluation_datasets"), errors
        )
        return errors, warnings, count

    def _validate_collections(self, payload: dict[str, Any], errors: list[dict[str, str]]) -> int:
        items = _safe_list(payload.get("items"))
        for index, item in enumerate(items):
            item_dict = item if isinstance(item, dict) else {}
            if _clean_string(item_dict.get("name"), 120) is None:
                errors.append(
                    self._issue(
                        "collections",
                        f"items[{index}].name",
                        "required",
                        "collection name is required",
                    )
                )
            if item_dict.get("access_policy", "org_wide") not in COLLECTION_POLICIES:
                errors.append(
                    self._issue(
                        "collections",
                        f"items[{index}].access_policy",
                        "invalid",
                        "unsupported access policy",
                    )
                )
        return len(items)

    def _validate_metadata(
        self,
        payload: dict[str, Any],
        errors: list[dict[str, str]],
        warnings: list[dict[str, str]],
    ) -> int:
        fields = _safe_list(payload.get("fields"))
        documents = _safe_list(payload.get("documents"))
        for index, field in enumerate(fields):
            field_dict = field if isinstance(field, dict) else {}
            if _clean_string(field_dict.get("name"), 128) is None:
                errors.append(
                    self._issue(
                        "document_metadata",
                        f"fields[{index}].name",
                        "required",
                        "metadata field name is required",
                    )
                )
            if field_dict.get("field_type") not in METADATA_FIELD_TYPES:
                errors.append(
                    self._issue(
                        "document_metadata",
                        f"fields[{index}].field_type",
                        "invalid",
                        "unsupported metadata field type",
                    )
                )
            sort_order = field_dict.get("sort_order")
            if sort_order is not None:
                parsed_sort_order = _parse_int(sort_order)
                if parsed_sort_order is None or parsed_sort_order < 0:
                    errors.append(
                        self._issue(
                            "document_metadata",
                            f"fields[{index}].sort_order",
                            "invalid",
                            "sort_order must be a non-negative integer",
                        )
                    )
            allowed_values = field_dict.get("allowed_values")
            if allowed_values is not None and not isinstance(allowed_values, list):
                errors.append(
                    self._issue(
                        "document_metadata",
                        f"fields[{index}].allowed_values",
                        "invalid",
                        "allowed_values must be an array when provided",
                    )
                )
        for index, document in enumerate(documents):
            doc = document if isinstance(document, dict) else {}
            if _clean_string(doc.get("filename"), 512) is None:
                errors.append(
                    self._issue(
                        "document_metadata",
                        f"documents[{index}].filename",
                        "required",
                        "document manifest filename is required",
                    )
                )
            if doc.get("file_type") not in FILE_TYPES:
                errors.append(
                    self._issue(
                        "document_metadata",
                        f"documents[{index}].file_type",
                        "invalid",
                        "unsupported document file type",
                    )
                )
            retention = doc.get("retention_class")
            if retention is not None and retention not in RETENTION_CLASSES:
                errors.append(
                    self._issue(
                        "document_metadata",
                        f"documents[{index}].retention_class",
                        "invalid",
                        "unsupported retention class",
                    )
                )
        if documents:
            warnings.append(
                self._warning(
                    "document_metadata",
                    "manifest_only",
                    "document manifests are validated but do not create documents or vectors",
                )
            )
        return len(fields) + len(documents)

    def _validate_evaluations(self, payload: dict[str, Any], errors: list[dict[str, str]]) -> int:
        items = _safe_list(payload.get("items"))
        count = 0
        for index, item in enumerate(items):
            item_dict = item if isinstance(item, dict) else {}
            if _clean_string(item_dict.get("name"), 255) is None:
                errors.append(
                    self._issue(
                        "evaluation_datasets",
                        f"items[{index}].name",
                        "required",
                        "dataset name is required",
                    )
                )
            questions = _safe_list(item_dict.get("questions"))
            count += len(questions)
            for question_index, question in enumerate(questions):
                q = question if isinstance(question, dict) else {}
                if _clean_string(q.get("question"), 8000) is None:
                    path = f"items[{index}].questions[{question_index}].question"
                    errors.append(
                        self._issue("evaluation_datasets", path, "required", "question is required")
                    )
                expected_page_number = q.get("expected_page_number")
                if expected_page_number is not None:
                    parsed_page = _parse_int(expected_page_number)
                    if parsed_page is None or parsed_page < 1:
                        path = f"items[{index}].questions[{question_index}].expected_page_number"
                        errors.append(
                            self._issue(
                                "evaluation_datasets",
                                path,
                                "invalid",
                                "expected_page_number must be a positive integer",
                            )
                        )
        return len(items) + count

    def _import_sections(self, artifact: dict[str, Any]) -> list[str]:
        sections = artifact.get("sections")
        if not isinstance(sections, dict):
            return []
        return [str(section) for section in sections if str(section) in IMPORTABLE_SECTIONS]

    def _document_manifest(self, document: Document) -> dict[str, Any]:
        return {
            "id": str(document.id),
            "filename": document.filename,
            "file_type": document.file_type,
            "status": document.status,
            "page_count": document.page_count,
            "chunk_count": document.chunk_count,
            "checksum": document.checksum,
            "source": document.source,
            "language": document.language,
            "retention_class": document.retention_class,
            "tags": document.tags,
            "review_status": document.review_status,
            "trust_status": document.trust_status,
            "quality_state": document.quality_state,
            "created_at": document.created_at.isoformat(),
            "updated_at": document.updated_at.isoformat(),
        }

    def _store_artifact(
        self,
        job: WorkspacePortabilityJob,
        *,
        artifact: dict[str, Any],
        filename: str,
    ) -> None:
        normalized = _jsonable(artifact)
        payload = json.dumps(normalized, sort_keys=True)
        job.artifact_json = normalized
        job.artifact_filename = filename
        job.artifact_mime_type = "application/json"
        job.artifact_size_bytes = len(payload.encode("utf-8"))

    def _issue(self, section: str, path: str, code: str, message: str) -> dict[str, str]:
        return {"section": section, "path": path, "code": code, "message": message}

    def _warning(self, section: str, code: str, message: str) -> dict[str, str]:
        return {"section": section, "code": code, "message": message}

    def _datetime_bounds(
        self,
        from_date: date | None,
        to_date: date | None,
    ) -> tuple[datetime | None, datetime | None]:
        start = datetime.combine(from_date, time.min, tzinfo=UTC) if from_date else None
        end = datetime.combine(to_date, time.max, tzinfo=UTC) if to_date else None
        return start, end

    def _apply_bounds(
        self, stmt: Any, column: Any, bounds: tuple[datetime | None, datetime | None]
    ) -> Any:
        start, end = bounds
        if start is not None:
            stmt = stmt.where(column >= start)
        if end is not None:
            stmt = stmt.where(column <= end)
        return stmt

    async def _collection_exists(
        self,
        session: AsyncSession,
        organization_id: UUID,
        name: str,
    ) -> bool:
        result = await session.execute(
            select(Collection.id).where(
                Collection.organization_id == organization_id,
                Collection.name == name,
                Collection.is_archived.is_(False),
            )
        )
        return result.scalar_one_or_none() is not None

    async def _metadata_field_exists(
        self,
        session: AsyncSession,
        organization_id: UUID,
        name: str,
    ) -> bool:
        result = await session.execute(
            select(MetadataField.id).where(
                MetadataField.organization_id == organization_id,
                MetadataField.name == name,
            )
        )
        return result.scalar_one_or_none() is not None

    async def _evaluation_set_exists(
        self,
        session: AsyncSession,
        organization_id: UUID,
        name: str,
    ) -> bool:
        result = await session.execute(
            select(EvaluationSet.id).where(
                EvaluationSet.organization_id == organization_id,
                EvaluationSet.name == name,
            )
        )
        return result.scalar_one_or_none() is not None
