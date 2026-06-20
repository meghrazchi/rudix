"""AgentTraceService — build sanitized trace timelines, share tokens, and retention policy."""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import AgentTraceRetentionPolicy, AgentTraceShareToken

_REDACTED = "[redacted]"
_SENSITIVE_KEYS = frozenset(
    {"secret", "token", "password", "api_key", "key", "access_token", "refresh_token"}
)
_DEFAULT_SHARE_TTL_HOURS = 48


# ── Redaction helpers ─────────────────────────────────────────────────────────


def _scrub_sensitive_keys(obj: Any, depth: int = 0) -> Any:
    """Recursively replace values whose key name is in _SENSITIVE_KEYS."""
    if depth > 6 or not isinstance(obj, dict):
        return obj
    result: dict[str, Any] = {}
    for k, v in obj.items():
        if k.lower() in _SENSITIVE_KEYS:
            result[k] = _REDACTED
        elif isinstance(v, dict):
            result[k] = _scrub_sensitive_keys(v, depth + 1)
        elif isinstance(v, list):
            result[k] = [
                _scrub_sensitive_keys(item, depth + 1) if isinstance(item, dict) else item
                for item in v
            ]
        else:
            result[k] = v
    return result


def _redact_step_inputs(inputs: dict[str, Any], policy: RetentionPolicySnapshot) -> dict[str, Any]:
    result = _scrub_sensitive_keys(inputs)
    if policy.redact_prompts:
        for prompt_key in ("prompt", "query", "question", "system_prompt", "user_prompt"):
            if prompt_key in result:
                result[prompt_key] = _REDACTED
    return result


def _redact_step_outputs(
    outputs: dict[str, Any], policy: RetentionPolicySnapshot
) -> dict[str, Any]:
    result = _scrub_sensitive_keys(outputs)
    if policy.redact_prompts:
        for key in ("llm_response", "raw_llm_output", "completion"):
            if key in result:
                result[key] = _REDACTED
    if policy.redact_raw_content:
        for key in ("raw_content", "document_text", "page_text", "chunk_text"):
            if key in result:
                result[key] = _REDACTED
    return result


def _redact_tool_call(
    arguments: dict[str, Any],
    output: dict[str, Any],
    policy: RetentionPolicySnapshot,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if policy.redact_tool_arguments:
        arguments = {"redacted": True}
    else:
        arguments = _scrub_sensitive_keys(arguments)
    output = _scrub_sensitive_keys(output)
    if policy.redact_raw_content:
        for key in ("content", "text", "raw_text", "document_content"):
            if key in output:
                output[key] = _REDACTED
    return arguments, output


# ── Data classes ──────────────────────────────────────────────────────────────


class RetentionPolicySnapshot:
    def __init__(
        self,
        retain_days: int = 90,
        redact_prompts: bool = False,
        redact_raw_content: bool = False,
        redact_tool_arguments: bool = False,
        full_redact: bool = False,
    ) -> None:
        self.retain_days = retain_days
        if full_redact:
            self.redact_prompts = True
            self.redact_raw_content = True
            self.redact_tool_arguments = True
        else:
            self.redact_prompts = redact_prompts
            self.redact_raw_content = redact_raw_content
            self.redact_tool_arguments = redact_tool_arguments

    @classmethod
    def from_model(cls, model: AgentTraceRetentionPolicy) -> RetentionPolicySnapshot:
        return cls(
            retain_days=model.retain_days,
            redact_prompts=model.redact_prompts,
            redact_raw_content=model.redact_raw_content,
            redact_tool_arguments=model.redact_tool_arguments,
        )

    @classmethod
    def default(cls) -> RetentionPolicySnapshot:
        return cls()

    @classmethod
    def full_redact_policy(cls) -> RetentionPolicySnapshot:
        return cls(full_redact=True)

    def is_any_redaction_active(self) -> bool:
        return self.redact_prompts or self.redact_raw_content or self.redact_tool_arguments


# ── Timeline event builders ───────────────────────────────────────────────────


def _ts(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def build_trace_timeline(run: Any, policy: RetentionPolicySnapshot) -> list[dict[str, Any]]:
    """Build a flat sorted timeline from an AgentRun with its steps/tool_calls/approvals."""
    events: list[tuple[datetime, dict[str, Any]]] = []

    run_start = run.started_at or run.created_at
    events.append(
        (
            run_start,
            {
                "event_type": "run_started",
                "run_id": str(run.id),
                "timestamp": _ts(run_start),
                "data": {
                    "objective": run.objective,
                    "surface": run.surface,
                    "status": run.status,
                    "budget": run.budget_json or {},
                },
            },
        )
    )

    steps_by_id: dict[str, Any] = {}
    for step in sorted(run.steps or [], key=lambda s: s.sequence):
        steps_by_id[str(step.id)] = step

        if step.started_at:
            events.append(
                (
                    step.started_at,
                    {
                        "event_type": "step_started",
                        "run_id": str(run.id),
                        "step_id": str(step.id),
                        "timestamp": _ts(step.started_at),
                        "data": {
                            "sequence": step.sequence,
                            "step_name": step.step_name,
                            "inputs": _redact_step_inputs(step.inputs_json or {}, policy),
                        },
                    },
                )
            )

        end_ts = step.completed_at or step.started_at or run_start
        event_type = (
            "step_completed"
            if step.status == "completed"
            else "step_skipped"
            if step.status == "skipped"
            else "step_failed"
            if step.status == "failed"
            else "step_ended"
        )
        if step.completed_at or step.status in ("completed", "failed", "skipped"):
            events.append(
                (
                    end_ts,
                    {
                        "event_type": event_type,
                        "run_id": str(run.id),
                        "step_id": str(step.id),
                        "timestamp": _ts(step.completed_at or end_ts),
                        "data": {
                            "sequence": step.sequence,
                            "step_name": step.step_name,
                            "status": step.status,
                            "duration_ms": step.duration_ms,
                            "outputs": _redact_step_outputs(step.outputs_json or {}, policy),
                            "metrics": step.metrics_json or {},
                            "observation": step.observation_json or {},
                            "error_message": step.error_message,
                            "error_details": _scrub_sensitive_keys(step.error_details_json or {}),
                        },
                    },
                )
            )

    for tc in run.tool_calls or []:
        tc_start = tc.started_at or run_start
        redacted_args, redacted_output = _redact_tool_call(
            tc.arguments_json or {}, tc.output_json or {}, policy
        )
        if tc.started_at:
            events.append(
                (
                    tc_start,
                    {
                        "event_type": "tool_called",
                        "run_id": str(run.id),
                        "step_id": str(tc.agent_step_id) if tc.agent_step_id else None,
                        "tool_call_id": str(tc.id),
                        "timestamp": _ts(tc.started_at),
                        "data": {
                            "call_id": tc.call_id,
                            "tool_name": tc.tool_name,
                            "surface": tc.surface,
                            "effect_policy": tc.effect_policy,
                            "attempt_number": tc.attempt_number,
                            "arguments": redacted_args,
                            "input_size_bytes": tc.input_size_bytes,
                        },
                    },
                )
            )

        if tc.completed_at:
            events.append(
                (
                    tc.completed_at,
                    {
                        "event_type": "tool_result",
                        "run_id": str(run.id),
                        "step_id": str(tc.agent_step_id) if tc.agent_step_id else None,
                        "tool_call_id": str(tc.id),
                        "timestamp": _ts(tc.completed_at),
                        "data": {
                            "call_id": tc.call_id,
                            "tool_name": tc.tool_name,
                            "status": tc.status,
                            "output": redacted_output,
                            "error": _scrub_sensitive_keys(tc.error_json or {}),
                            "output_size_bytes": tc.output_size_bytes,
                            "latency_ms": tc.latency_ms,
                        },
                    },
                )
            )

    for approval in run.approvals or []:
        events.append(
            (
                approval.created_at,
                {
                    "event_type": "approval_requested",
                    "run_id": str(run.id),
                    "step_id": str(approval.agent_step_id) if approval.agent_step_id else None,
                    "tool_call_id": str(approval.tool_call_id) if approval.tool_call_id else None,
                    "approval_id": str(approval.id),
                    "timestamp": _ts(approval.created_at),
                    "data": {
                        "status": approval.status,
                        "request_summary": approval.request_summary,
                        "expires_at": _ts(approval.expires_at),
                    },
                },
            )
        )
        if approval.decided_at:
            events.append(
                (
                    approval.decided_at,
                    {
                        "event_type": "approval_decided",
                        "run_id": str(run.id),
                        "approval_id": str(approval.id),
                        "timestamp": _ts(approval.decided_at),
                        "data": {
                            "status": approval.status,
                            "decision_reason": approval.decision_reason,
                        },
                    },
                )
            )

    terminal_ts = run.completed_at or run.cancelled_at
    if terminal_ts or run.status in ("completed", "failed", "cancelled"):
        terminal_ts = terminal_ts or run_start
        terminal_type = (
            "run_completed"
            if run.status == "completed"
            else "run_cancelled"
            if run.status == "cancelled"
            else "run_failed"
        )
        events.append(
            (
                terminal_ts,
                {
                    "event_type": terminal_type,
                    "run_id": str(run.id),
                    "timestamp": _ts(terminal_ts),
                    "data": {
                        "status": run.status,
                        "total_cost_usd": str(run.total_cost_usd)
                        if run.total_cost_usd is not None
                        else None,
                        "outcome": run.outcome_json or {},
                        "error_message": run.error_message,
                        "error_details": _scrub_sensitive_keys(run.error_details_json or {}),
                        "observations": run.observations_json or {},
                    },
                },
            )
        )

    events.sort(key=lambda e: e[0])
    return [ev for _, ev in events]


# ── Service ───────────────────────────────────────────────────────────────────


class AgentTraceService:
    async def get_retention_policy(
        self, db: AsyncSession, organization_id: UUID
    ) -> RetentionPolicySnapshot:
        row = await db.scalar(
            select(AgentTraceRetentionPolicy).where(
                AgentTraceRetentionPolicy.organization_id == organization_id
            )
        )
        if row is None:
            return RetentionPolicySnapshot.default()
        return RetentionPolicySnapshot.from_model(row)

    async def upsert_retention_policy(
        self,
        db: AsyncSession,
        organization_id: UUID,
        updated_by_user_id: UUID,
        retain_days: int,
        redact_prompts: bool,
        redact_raw_content: bool,
        redact_tool_arguments: bool,
    ) -> AgentTraceRetentionPolicy:
        row = await db.scalar(
            select(AgentTraceRetentionPolicy).where(
                AgentTraceRetentionPolicy.organization_id == organization_id
            )
        )
        if row is None:
            row = AgentTraceRetentionPolicy(
                organization_id=organization_id,
                updated_by_user_id=updated_by_user_id,
                retain_days=retain_days,
                redact_prompts=redact_prompts,
                redact_raw_content=redact_raw_content,
                redact_tool_arguments=redact_tool_arguments,
            )
            db.add(row)
        else:
            row.updated_by_user_id = updated_by_user_id
            row.retain_days = retain_days
            row.redact_prompts = redact_prompts
            row.redact_raw_content = redact_raw_content
            row.redact_tool_arguments = redact_tool_arguments
            row.updated_at = datetime.now(UTC)
        await db.flush()
        return row

    def build_trace(self, run: Any, policy: RetentionPolicySnapshot) -> dict[str, Any]:
        timeline = build_trace_timeline(run, policy)
        return {
            "run_id": str(run.id),
            "organization_id": str(run.organization_id),
            "status": run.status,
            "objective": run.objective,
            "surface": run.surface,
            "started_at": _ts(run.started_at),
            "completed_at": _ts(run.completed_at),
            "cancelled_at": _ts(run.cancelled_at),
            "created_at": _ts(run.created_at),
            "total_cost_usd": str(run.total_cost_usd) if run.total_cost_usd is not None else None,
            "error_message": run.error_message,
            "trace_request_id": run.trace_request_id,
            "redacted": policy.is_any_redaction_active(),
            "timeline": timeline,
            "total_events": len(timeline),
            "step_count": len(run.steps or []),
            "tool_call_count": len(run.tool_calls or []),
            "approval_count": len(run.approvals or []),
            "policy_snapshot": run.policy_snapshot_json,
        }

    def build_export(self, run: Any) -> dict[str, Any]:
        """Safe metadata export — no raw content, no tool arguments, no prompts."""
        RetentionPolicySnapshot.full_redact_policy()
        steps_summary = [
            {
                "sequence": s.sequence,
                "step_name": s.step_name,
                "status": s.status,
                "duration_ms": s.duration_ms,
                "error_message": s.error_message,
                "started_at": _ts(s.started_at),
                "completed_at": _ts(s.completed_at),
            }
            for s in sorted(run.steps or [], key=lambda s: s.sequence)
        ]
        tool_summary = [
            {
                "tool_name": tc.tool_name,
                "surface": tc.surface,
                "effect_policy": tc.effect_policy,
                "status": tc.status,
                "attempt_number": tc.attempt_number,
                "input_size_bytes": tc.input_size_bytes,
                "output_size_bytes": tc.output_size_bytes,
                "latency_ms": tc.latency_ms,
                "started_at": _ts(tc.started_at),
                "completed_at": _ts(tc.completed_at),
            }
            for tc in run.tool_calls or []
        ]
        approval_summary = [
            {
                "status": a.status,
                "request_summary": a.request_summary,
                "decision_reason": a.decision_reason,
                "expires_at": _ts(a.expires_at),
                "decided_at": _ts(a.decided_at),
            }
            for a in run.approvals or []
        ]
        return {
            "run_id": str(run.id),
            "organization_id": str(run.organization_id),
            "status": run.status,
            "objective": run.objective,
            "surface": run.surface,
            "started_at": _ts(run.started_at),
            "completed_at": _ts(run.completed_at),
            "cancelled_at": _ts(run.cancelled_at),
            "created_at": _ts(run.created_at),
            "total_cost_usd": str(run.total_cost_usd) if run.total_cost_usd is not None else None,
            "error_message": run.error_message,
            "trace_request_id": run.trace_request_id,
            "steps": steps_summary,
            "tool_calls": tool_summary,
            "approvals": approval_summary,
            "export_safe": True,
            "exported_at": datetime.now(UTC).isoformat(),
        }

    async def create_share_token(
        self,
        db: AsyncSession,
        organization_id: UUID,
        run_id: UUID,
        created_by_user_id: UUID,
        label: str | None = None,
        expires_in_hours: int = _DEFAULT_SHARE_TTL_HOURS,
    ) -> tuple[AgentTraceShareToken, str]:
        raw_token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        expires_at = datetime.now(UTC) + timedelta(hours=expires_in_hours)
        share_token = AgentTraceShareToken(
            organization_id=organization_id,
            agent_run_id=run_id,
            created_by_user_id=created_by_user_id,
            token_hash=token_hash,
            label=label,
            expires_at=expires_at,
        )
        db.add(share_token)
        await db.flush()
        return share_token, raw_token

    async def resolve_share_token(
        self, db: AsyncSession, raw_token: str
    ) -> AgentTraceShareToken | None:
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        row = await db.scalar(
            select(AgentTraceShareToken).where(
                AgentTraceShareToken.token_hash == token_hash,
                AgentTraceShareToken.revoked_at.is_(None),
            )
        )
        if row is None:
            return None
        if row.expires_at and row.expires_at < datetime.now(UTC):
            return None
        return row

    async def revoke_share_token(
        self, db: AsyncSession, token_id: UUID, organization_id: UUID
    ) -> bool:
        row = await db.scalar(
            select(AgentTraceShareToken).where(
                AgentTraceShareToken.id == token_id,
                AgentTraceShareToken.organization_id == organization_id,
                AgentTraceShareToken.revoked_at.is_(None),
            )
        )
        if row is None:
            return False
        row.revoked_at = datetime.now(UTC)
        row.updated_at = datetime.now(UTC)
        await db.flush()
        return True
