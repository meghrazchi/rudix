"""Response schemas for the agent run trace endpoints (R07-05).

The trace body is assembled by ``AgentTraceService.build_trace``; these models describe
the same keys so the OpenAPI document (and the generated frontend types) are accurate.
Routes use ``response_model_exclude_unset`` so optional event keys that the service does
not emit stay absent from the JSON, exactly as before.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class AgentTraceEventResponse(BaseModel):
    event_type: str
    run_id: str
    step_id: str | None = None
    tool_call_id: str | None = None
    approval_id: str | None = None
    timestamp: str
    data: dict[str, Any]


class AgentTraceResponse(BaseModel):
    run_id: str
    organization_id: str
    status: str
    objective: str | None
    surface: str
    started_at: str | None
    completed_at: str | None
    cancelled_at: str | None
    created_at: str
    total_cost_usd: str | None
    error_message: str | None
    trace_request_id: str | None
    redacted: bool
    timeline: list[AgentTraceEventResponse]
    total_events: int
    step_count: int
    tool_call_count: int
    approval_count: int
    policy_snapshot: dict[str, Any] | None
    shared_via_token: bool | None = None
