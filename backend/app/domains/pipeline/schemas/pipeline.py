from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class PipelineStepListResponse(BaseModel):
    steps: list[str]


class PipelineNodeResponse(BaseModel):
    id: str
    label: str
    section: Literal["ingestion", "query", "evaluation"]
    description: str | None = None
    status: Literal["pending", "running", "completed", "failed", "skipped"]
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_ms: int | None = None
    metrics: dict[str, object] = Field(default_factory=dict)


class PipelineEdgeResponse(BaseModel):
    id: str
    source: str
    target: str


class PipelineRunGraphResponse(BaseModel):
    pipeline_run_id: str
    pipeline_type: str
    status: str
    nodes: list[PipelineNodeResponse]
    edges: list[PipelineEdgeResponse]


class PipelineRunResolveResponse(BaseModel):
    pipeline_run_id: str
    pipeline_type: str
    status: str


class PipelineNodeDetailResponse(BaseModel):
    node_id: str
    title: str
    description: str
    status: Literal["pending", "running", "completed", "failed", "skipped"]
    inputs: dict[str, object] = Field(default_factory=dict)
    outputs: dict[str, object] = Field(default_factory=dict)
    config: dict[str, object] = Field(default_factory=dict)
    logs: list[str] = Field(default_factory=list)
    error_message: str | None = None
    error_details: dict[str, object] = Field(default_factory=dict)
    metrics: dict[str, object] = Field(default_factory=dict)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_ms: int | None = None
