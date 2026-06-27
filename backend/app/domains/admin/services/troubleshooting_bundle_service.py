"""F329: TroubleshootingBundleService — builds safe, redacted diagnostic bundles."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.logging import get_logger
from app.domains.admin.schemas.troubleshooting_bundle import (
    BundleCitation,
    BundleConfigFingerprint,
    BundleIdentifiers,
    BundleLifecycleStage,
    BundleLogEntry,
    BundleModelMetadata,
    BundleRedactionConfig,
    BundleRetrievalDiagnostics,
    BundleSourceType,
    BundleWarning,
    ChatMessageBundleDetail,
    ConnectorSyncBundleDetail,
    DocumentBundleDetail,
    EvaluationRunBundleDetail,
    FailedJobBundleDetail,
    TroubleshootingBundleResponse,
)
from app.domains.admin.services.audit_service import sanitize_metadata
from app.models.chat import ChatMessage, ChatSession
from app.models.connector_sync import ConnectorSyncRun
from app.models.document import Document
from app.models.evaluation import EvaluationRun
from app.models.failed_job import FailedJob
from app.models.pipeline import PipelineEvent, PipelineRun

_logger = get_logger("services.troubleshooting_bundle")

_REDACTED_PLACEHOLDER = "<redacted>"
_REDACTED_PII_PLACEHOLDER = "<redacted:pii>"


class NotFoundError(Exception):
    pass


class AccessDeniedError(Exception):
    pass


def _redact_str(value: str | None, *, placeholder: str = _REDACTED_PLACEHOLDER) -> str | None:
    if value is None:
        return None
    return placeholder if value.strip() else value


def _safe_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _build_lifecycle_from_events(events: list[PipelineEvent]) -> list[BundleLifecycleStage]:
    stages = []
    for ev in sorted(events, key=lambda e: e.sequence):
        latency = None
        if ev.started_at and ev.completed_at:
            latency = int((ev.completed_at - ev.started_at).total_seconds() * 1000)
        elif ev.duration_ms is not None:
            latency = ev.duration_ms
        stages.append(
            BundleLifecycleStage(
                stage=ev.node_name,
                status=ev.status,
                started_at=ev.started_at,
                completed_at=ev.completed_at,
                latency_ms=latency,
                error_message=_redact_str(ev.error_message) if ev.error_message else None,
            )
        )
    return stages


def _build_log_entries(
    logs_raw: list[Any],
    config: BundleRedactionConfig,
) -> list[BundleLogEntry]:
    """Convert raw pipeline log dicts to safe BundleLogEntry records."""
    if not config.include_redacted_logs:
        return []
    entries: list[BundleLogEntry] = []
    for item in logs_raw:
        if not isinstance(item, dict):
            continue
        event = str(item.get("event", ""))
        level = str(item.get("level", "info"))
        ts_raw = item.get("timestamp")
        ts: datetime | None = None
        if isinstance(ts_raw, str):
            try:
                ts = datetime.fromisoformat(ts_raw)
            except ValueError:
                pass
        safe_fields = sanitize_metadata(
            {k: v for k, v in item.items() if k not in {"event", "level", "timestamp"}}
        )
        if config.redact_snippets:
            safe_fields.pop("snippet", None)
            safe_fields.pop("chunk_text", None)
        if config.redact_prompts:
            safe_fields.pop("prompt", None)
            safe_fields.pop("system_prompt", None)
        entries.append(
            BundleLogEntry(
                timestamp=ts,
                level=level,
                event=event,
                redacted=True,
                fields=safe_fields,
            )
        )
    return entries


def _extract_retrieval_from_trust_metadata(
    trust_meta: dict[str, Any] | None,
) -> BundleRetrievalDiagnostics | None:
    if not trust_meta:
        return None
    rd = trust_meta.get("retrieval_diagnostics") or {}
    if not rd:
        return None
    return BundleRetrievalDiagnostics(
        profile_key=rd.get("rag_profile_key"),
        strategy=rd.get("retrieval_strategy"),
        top_k=rd.get("top_k"),
        reranker_enabled=rd.get("reranker_enabled"),
        reranker_model=rd.get("reranker_model"),
        hybrid_enabled=rd.get("hybrid_enabled"),
        query_rewriting_enabled=rd.get("query_rewriting_enabled"),
        result_count=rd.get("result_count"),
        scores=rd.get("scores") or [],
        warnings=rd.get("warnings") or [],
    )


def _extract_citations_from_trust_metadata(
    trust_meta: dict[str, Any] | None,
    config: BundleRedactionConfig,
) -> list[BundleCitation]:
    if not trust_meta:
        return []
    citations_raw = trust_meta.get("citations") or []
    results: list[BundleCitation] = []
    for i, c in enumerate(citations_raw):
        if not isinstance(c, dict):
            continue
        results.append(
            BundleCitation(
                citation_index=i,
                document_id=str(c.get("document_id", "")),
                document_filename=c.get("document_filename") if not config.redact_source_content else None,
                page_number=c.get("page_number"),
                trust_status=c.get("trust_status"),
                freshness_status=c.get("freshness_status"),
                ocr_quality_status=c.get("ocr_quality_status"),
                retrieval_score=_safe_float(c.get("retrieval_score")),
                rerank_score=_safe_float(c.get("rerank_score")),
            )
        )
    return results


def _extract_config_fingerprint_from_trust_metadata(
    trust_meta: dict[str, Any] | None,
) -> BundleConfigFingerprint | None:
    if not trust_meta:
        return None
    return BundleConfigFingerprint(
        rag_profile_key=trust_meta.get("rag_profile_key"),
        answer_language_mode=trust_meta.get("answer_language_mode"),
        collection_ids=[str(c) for c in (trust_meta.get("collection_ids") or [])],
        feature_flags=trust_meta.get("active_feature_flags") or [],
    )


class TroubleshootingBundleService:
    async def build(
        self,
        session: AsyncSession,
        *,
        source_type: BundleSourceType,
        source_id: UUID,
        organization_id: UUID,
        actor_user_id: UUID,
        config: BundleRedactionConfig,
        include_markdown: bool,
    ) -> TroubleshootingBundleResponse:
        bundle_id = str(uuid.uuid4())
        generated_at = datetime.now(tz=UTC)

        if source_type == BundleSourceType.chat_message:
            detail, lifecycle, cfg_fp, logs, warnings, identifiers = await self._build_chat(
                session, source_id=source_id, org_id=organization_id, config=config
            )
        elif source_type == BundleSourceType.document:
            detail, lifecycle, cfg_fp, logs, warnings, identifiers = await self._build_document(
                session, source_id=source_id, org_id=organization_id, config=config
            )
        elif source_type == BundleSourceType.connector_sync:
            detail, lifecycle, cfg_fp, logs, warnings, identifiers = await self._build_connector_sync(
                session, source_id=source_id, org_id=organization_id, config=config
            )
        elif source_type == BundleSourceType.evaluation_run:
            detail, lifecycle, cfg_fp, logs, warnings, identifiers = await self._build_evaluation_run(
                session, source_id=source_id, org_id=organization_id, config=config
            )
        elif source_type == BundleSourceType.failed_job:
            detail, lifecycle, cfg_fp, logs, warnings, identifiers = await self._build_failed_job(
                session, source_id=source_id, org_id=organization_id, config=config
            )
        else:
            raise ValueError(f"Unknown source_type: {source_type}")

        base_identifiers = BundleIdentifiers(
            bundle_id=bundle_id,
            source_type=source_type.value,
            source_id=str(source_id),
            organization_id=str(organization_id),
            trace_id=identifiers.get("trace_id"),
            request_id=identifiers.get("request_id"),
            celery_task_id=identifiers.get("celery_task_id"),
        )

        bundle = TroubleshootingBundleResponse(
            bundle_id=bundle_id,
            generated_at=generated_at,
            exported_by_user_id=str(actor_user_id),
            organization_id=str(organization_id),
            source_type=source_type.value,
            source_id=str(source_id),
            redaction_config=config,
            identifiers=base_identifiers,
            lifecycle_stages=lifecycle,
            config_fingerprint=cfg_fp,
            warnings=warnings,
            detail=detail,
            logs=logs,
        )

        if include_markdown:
            bundle.markdown_summary = self._build_markdown(bundle)

        return bundle

    # ── Per-source builders ─────────────────────────────────────────────────────

    async def _build_chat(
        self,
        session: AsyncSession,
        *,
        source_id: UUID,
        org_id: UUID,
        config: BundleRedactionConfig,
    ) -> tuple:
        stmt = (
            select(ChatMessage)
            .where(ChatMessage.id == source_id)
            .options(
                selectinload(ChatMessage.session),
                selectinload(ChatMessage.pipeline_runs).selectinload(PipelineRun.events),
            )
        )
        row = (await session.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise NotFoundError(f"ChatMessage {source_id} not found")

        session_row: ChatSession | None = row.session
        if session_row is not None and session_row.organization_id != org_id:
            raise AccessDeniedError("Resource belongs to a different organization")

        trust_meta: dict[str, Any] = row.trust_metadata_json or {}
        retrieval = _extract_retrieval_from_trust_metadata(trust_meta)
        citations = _extract_citations_from_trust_metadata(trust_meta, config)
        cfg_fp = _extract_config_fingerprint_from_trust_metadata(trust_meta)
        policy = trust_meta.get("policy_enforcement") or {}

        model_meta = BundleModelMetadata(
            model_name=row.model_name,
            token_input_count=row.token_input_count,
            token_output_count=row.token_output_count,
            latency_ms=row.latency_ms,
            cost_usd=float(row.cost_usd) if row.cost_usd is not None else None,
            provider_type=trust_meta.get("provider_type"),
            provider_profile=trust_meta.get("provider_profile"),
            model_profile_key=trust_meta.get("model_profile_key"),
        )

        detail = ChatMessageBundleDetail(
            session_id=str(session_row.id) if session_row is not None else None,
            role=row.role,
            confidence_score=row.confidence_score,
            scope_mode=trust_meta.get("scope_mode"),
            grounded_verification_passed=trust_meta.get("grounded_verification_passed"),
            policy_enforced=bool(policy),
            policy_action=policy.get("action"),
            retrieval=retrieval,
            citations=citations,
            model=model_meta,
        )

        lifecycle: list[BundleLifecycleStage] = []
        all_logs: list[Any] = []
        for run in row.pipeline_runs or []:
            lifecycle.extend(_build_lifecycle_from_events(run.events or []))
            all_logs.extend(run.logs_json or [])

        logs = _build_log_entries(all_logs, config)
        warnings: list[BundleWarning] = []
        if row.confidence_score is not None and row.confidence_score < 0.5:
            warnings.append(
                BundleWarning(
                    code="LOW_CONFIDENCE",
                    message=f"Confidence score is {row.confidence_score:.2f} (below 0.5)",
                    severity="warning",
                )
            )

        identifiers: dict[str, str | None] = {
            "trace_id": trust_meta.get("trace_id"),
            "request_id": trust_meta.get("request_id"),
        }
        return detail, lifecycle, cfg_fp, logs, warnings, identifiers

    async def _build_document(
        self,
        session: AsyncSession,
        *,
        source_id: UUID,
        org_id: UUID,
        config: BundleRedactionConfig,
    ) -> tuple:
        stmt = (
            select(Document)
            .where(Document.id == source_id, Document.organization_id == org_id)
            .options(selectinload(Document.pipeline_runs).selectinload(PipelineRun.events))
        )
        row = (await session.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise NotFoundError(f"Document {source_id} not found")

        all_logs: list[Any] = []
        lifecycle: list[BundleLifecycleStage] = []
        for run in row.pipeline_runs or []:
            lifecycle.extend(_build_lifecycle_from_events(run.events or []))
            all_logs.extend(run.logs_json or [])

        extraction_snapshot = row.extraction_snapshot or {}
        detail = DocumentBundleDetail(
            filename=row.filename if not config.redact_source_content else None,
            file_type=row.file_type,
            status=row.status,
            trust_status=row.trust_status,
            quality_state=row.quality_state,
            language=row.language,
            language_confidence=row.language_confidence,
            ocr_quality_status=row.ocr_quality_status,
            page_count=row.page_count,
            chunk_count=row.chunk_count,
            word_count=extraction_snapshot.get("word_count"),
            extraction_strategy=extraction_snapshot.get("strategy"),
            pipeline_stages=lifecycle,
        )

        logs = _build_log_entries(all_logs, config)
        warnings: list[BundleWarning] = []
        if row.ocr_quality_status in ("low", "failed"):
            warnings.append(
                BundleWarning(
                    code="LOW_OCR_QUALITY",
                    message=f"OCR quality is '{row.ocr_quality_status}'",
                    severity="warning",
                )
            )
        if row.status == "failed":
            warnings.append(
                BundleWarning(code="DOCUMENT_FAILED", message="Document is in 'failed' status", severity="error")
            )

        identifiers: dict[str, str | None] = {}
        return detail, lifecycle, None, logs, warnings, identifiers

    async def _build_connector_sync(
        self,
        session: AsyncSession,
        *,
        source_id: UUID,
        org_id: UUID,
        config: BundleRedactionConfig,
    ) -> tuple:
        stmt = select(ConnectorSyncRun).where(
            ConnectorSyncRun.id == source_id,
            ConnectorSyncRun.organization_id == org_id,
        )
        row = (await session.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise NotFoundError(f"ConnectorSyncRun {source_id} not found")

        detail = ConnectorSyncBundleDetail(
            sync_job_id=str(row.sync_job_id),
            connection_id=str(row.connection_id),
            trigger_type=row.trigger_type,
            status=row.status,
            sync_version=row.sync_version,
            items_seen=row.items_seen,
            items_upserted=row.items_upserted,
            items_deleted=row.items_deleted,
            started_at=row.started_at,
            completed_at=row.completed_at,
            error_message_redacted=bool(row.error_message),
            error_code=row.error_details_json.get("code") if row.error_details_json else None,
            conflict_count=len(row.conflicts) if hasattr(row, "conflicts") else None,
        )

        lifecycle: list[BundleLifecycleStage] = []
        if row.status == "failed" and row.error_message:
            lifecycle.append(
                BundleLifecycleStage(
                    stage="sync",
                    status="failed",
                    started_at=row.started_at,
                    completed_at=row.completed_at,
                    error_message=_redact_str(row.error_message),
                )
            )

        warnings: list[BundleWarning] = []
        if row.status == "failed":
            warnings.append(
                BundleWarning(code="SYNC_FAILED", message="Connector sync run failed", severity="error")
            )

        identifiers: dict[str, str | None] = {
            "celery_task_id": row.celery_task_id,
        }
        return detail, lifecycle, None, [], warnings, identifiers

    async def _build_evaluation_run(
        self,
        session: AsyncSession,
        *,
        source_id: UUID,
        org_id: UUID,
        config: BundleRedactionConfig,
    ) -> tuple:
        stmt = (
            select(EvaluationRun)
            .where(EvaluationRun.id == source_id)
            .options(selectinload(EvaluationRun.results))
        )
        row = (await session.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise NotFoundError(f"EvaluationRun {source_id} not found")

        results = row.results or []
        avg_retrieval = None
        avg_faith = None
        avg_latency = None
        failed_count = 0
        if results:
            r_scores = [r.retrieval_score for r in results if r.retrieval_score is not None]
            f_scores = [r.faithfulness_score for r in results if r.faithfulness_score is not None]
            l_vals = [r.latency_ms for r in results if r.latency_ms is not None]
            avg_retrieval = sum(r_scores) / len(r_scores) if r_scores else None
            avg_faith = sum(f_scores) / len(f_scores) if f_scores else None
            avg_latency = sum(l_vals) / len(l_vals) if l_vals else None
            failed_count = sum(1 for r in results if not r.details.get("passed", True))

        detail = EvaluationRunBundleDetail(
            evaluation_set_id=str(row.evaluation_set_id),
            status=row.status,
            model_profile_key=row.model_profile_key,
            provider_type=row.provider_type,
            provider_profile=row.provider_profile,
            started_at=row.started_at,
            completed_at=row.completed_at,
            total_questions=len(results),
            avg_retrieval_score=avg_retrieval,
            avg_faithfulness_score=avg_faith,
            avg_latency_ms=avg_latency,
            failed_count=failed_count,
        )

        warnings: list[BundleWarning] = []
        if row.status == "failed":
            warnings.append(
                BundleWarning(code="EVAL_RUN_FAILED", message="Evaluation run failed", severity="error")
            )
        if failed_count and len(results) > 0 and (failed_count / len(results)) > 0.2:
            warnings.append(
                BundleWarning(
                    code="HIGH_FAILURE_RATE",
                    message=f"{failed_count}/{len(results)} evaluation cases did not pass",
                    severity="warning",
                )
            )

        identifiers: dict[str, str | None] = {}
        return detail, [], None, [], warnings, identifiers

    async def _build_failed_job(
        self,
        session: AsyncSession,
        *,
        source_id: UUID,
        org_id: UUID,
        config: BundleRedactionConfig,
    ) -> tuple:
        stmt = select(FailedJob).where(
            FailedJob.id == source_id, FailedJob.organization_id == org_id
        )
        row = (await session.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise NotFoundError(f"FailedJob {source_id} not found")

        detail = FailedJobBundleDetail(
            task_name=row.task_name,
            job_type=row.job_type,
            queue_name=row.queue_name,
            status=row.status,
            error_code=row.error_code,
            attempt_count=row.attempt_count,
            is_retryable=row.is_retryable,
            entity_type=row.entity_type,
            entity_id=str(row.entity_id) if row.entity_id else None,
            last_attempted_at=row.last_attempted_at,
        )

        lifecycle = [
            BundleLifecycleStage(
                stage=row.task_name,
                status=row.status,
                error_code=row.error_code,
            )
        ]

        warnings: list[BundleWarning] = []
        if not row.is_retryable:
            warnings.append(
                BundleWarning(
                    code="NOT_RETRYABLE",
                    message="This job is marked as not retryable",
                    severity="warning",
                )
            )
        if row.attempt_count and row.attempt_count > 3:
            warnings.append(
                BundleWarning(
                    code="HIGH_ATTEMPT_COUNT",
                    message=f"Job has been attempted {row.attempt_count} times",
                    severity="warning",
                )
            )

        identifiers: dict[str, str | None] = {}
        return detail, lifecycle, None, [], warnings, identifiers

    # ── Markdown summary ────────────────────────────────────────────────────────

    def _build_markdown(self, bundle: TroubleshootingBundleResponse) -> str:
        lines = [
            "# Troubleshooting Bundle",
            "",
            f"**Bundle ID:** `{bundle.bundle_id}`  ",
            f"**Generated:** {bundle.generated_at.isoformat()}  ",
            f"**Source:** `{bundle.source_type}` / `{bundle.source_id}`  ",
            f"**Organization:** `{bundle.organization_id}`",
            "",
        ]

        if bundle.identifiers.trace_id:
            lines += [f"**Trace ID:** `{bundle.identifiers.trace_id}`  "]
        if bundle.identifiers.request_id:
            lines += [f"**Request ID:** `{bundle.identifiers.request_id}`  "]
        if bundle.identifiers.celery_task_id:
            lines += [f"**Celery Task:** `{bundle.identifiers.celery_task_id}`  "]
        lines.append("")

        if bundle.warnings:
            lines += ["## Warnings", ""]
            for w in bundle.warnings:
                lines.append(f"- **[{w.severity.upper()}]** `{w.code}` — {w.message}")
            lines.append("")

        if bundle.lifecycle_stages:
            lines += ["## Pipeline Stages", ""]
            lines += ["| Stage | Status | Latency | Error |", "|-------|--------|---------|-------|"]
            for s in bundle.lifecycle_stages:
                lat = f"{s.latency_ms}ms" if s.latency_ms is not None else "—"
                err = s.error_message or "—"
                lines.append(f"| {s.stage} | {s.status} | {lat} | {err} |")
            lines.append("")

        if bundle.config_fingerprint:
            fp = bundle.config_fingerprint
            lines += ["## Configuration Fingerprint", ""]
            if fp.rag_profile_key:
                lines.append(f"- **RAG Profile:** `{fp.rag_profile_key}`")
            if fp.answer_language_mode:
                lines.append(f"- **Answer Language Mode:** `{fp.answer_language_mode}`")
            if fp.collection_ids:
                lines.append(f"- **Collections:** {', '.join(fp.collection_ids)}")
            if fp.feature_flags:
                lines.append(f"- **Active Flags:** {', '.join(fp.feature_flags)}")
            lines.append("")

        lines += [
            "---",
            "*This bundle was generated by Rudix and contains redacted diagnostic information.*",
            f"*Redaction config: prompts={bundle.redaction_config.redact_prompts}, "
            f"snippets={bundle.redaction_config.redact_snippets}, "
            f"pii={bundle.redaction_config.redact_pii}*",
        ]

        return "\n".join(lines)
