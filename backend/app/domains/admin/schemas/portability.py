from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

WorkspaceExportSection = Literal[
    "collections",
    "document_metadata",
    "chat_transcripts",
    "evaluation_datasets",
    "evaluation_results",
    "audit_logs",
    "settings",
    "api_metadata",
    "webhook_metadata",
]

WorkspaceImportSection = Literal[
    "collections",
    "document_metadata",
    "evaluation_datasets",
]

WorkspacePortabilityJobType = Literal["export", "import"]
WorkspacePortabilityJobStatus = Literal[
    "queued",
    "running",
    "validated",
    "completed",
    "failed",
    "validation_failed",
    "expired",
]

DEFAULT_WORKSPACE_EXPORT_SECTIONS: tuple[WorkspaceExportSection, ...] = (
    "collections",
    "document_metadata",
    "chat_transcripts",
    "evaluation_datasets",
    "evaluation_results",
    "audit_logs",
    "settings",
    "api_metadata",
    "webhook_metadata",
)


class WorkspaceExportRequest(BaseModel):
    sections: list[WorkspaceExportSection] = Field(
        default_factory=lambda: list(DEFAULT_WORKSPACE_EXPORT_SECTIONS),
        min_length=1,
        max_length=len(DEFAULT_WORKSPACE_EXPORT_SECTIONS),
    )
    from_date: date | None = Field(default=None, alias="from")
    to_date: date | None = Field(default=None, alias="to")
    max_rows_per_section: int = Field(default=5000, ge=1, le=10000)

    @field_validator("sections")
    @classmethod
    def dedupe_sections(
        cls,
        value: list[WorkspaceExportSection],
    ) -> list[WorkspaceExportSection]:
        deduped: list[WorkspaceExportSection] = []
        for section in value:
            if section not in deduped:
                deduped.append(section)
        return deduped

    @model_validator(mode="after")
    def validate_date_range(self) -> WorkspaceExportRequest:
        if (
            self.from_date is not None
            and self.to_date is not None
            and self.from_date > self.to_date
        ):
            raise ValueError("from must be less than or equal to to")
        return self


class WorkspaceImportRequest(BaseModel):
    artifact: dict[str, Any] = Field(default_factory=dict)
    apply: bool = False

    @field_validator("artifact")
    @classmethod
    def validate_artifact_not_empty(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not value:
            raise ValueError("artifact must not be empty")
        return value


class PortabilityValidationIssue(BaseModel):
    section: str
    path: str
    code: str
    message: str


class PortabilityWarning(BaseModel):
    section: str
    code: str
    message: str


class WorkspacePortabilityJobResponse(BaseModel):
    job_id: str
    organization_id: str
    created_by_user_id: str | None = None
    job_type: WorkspacePortabilityJobType
    status: WorkspacePortabilityJobStatus
    requested_sections: list[str]
    parameters: dict[str, Any]
    artifact_filename: str | None = None
    artifact_mime_type: str | None = None
    artifact_size_bytes: int | None = None
    validation_errors: list[PortabilityValidationIssue] = Field(default_factory=list)
    warnings: list[PortabilityWarning] = Field(default_factory=list)
    error_message: str | None = None
    records_processed: int
    records_failed: int
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    expires_at: datetime | None = None
    download_available: bool


class WorkspacePortabilityJobListResponse(BaseModel):
    items: list[WorkspacePortabilityJobResponse]
    total: int
    limit: int
    offset: int
