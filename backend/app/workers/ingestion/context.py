"""State shared by the stages of one ingestion run (R06-01)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from uuid import UUID

from app.workers.ingestion.deps import IngestionDeps
from app.workers.ingestion.options import IngestionOptions

if TYPE_CHECKING:
    from app.workers.ingestion.recorder import PipelineRunRecorder
    from app.workers.ingestion.store import StageStore


@dataclass
class StageContext:
    document_id: UUID
    organization_id: str
    user_id: str
    request_id: str | None
    # Artifact namespace: the claim's task id, so a redelivery or retry resumes the run.
    run_id: str
    # documents.processing_task_id that must still hold the claim when finalize writes
    # ``indexed``; None (direct calls without a claim) writes unconditionally.
    claim_token: str | None
    options: IngestionOptions
    deps: IngestionDeps
    recorder: PipelineRunRecorder
    store: StageStore
    # Metrics of completed stages by stage name (loaded from stage rows on resume).
    metrics: dict[str, dict[str, Any]] = field(default_factory=dict)
    # Pipeline-explorer stage name used to attribute an unexpected failure.
    current_stage: str = "extract"
    # Chain mode (R06-01 part 2): the stage task's own message id leases the stage row, so a
    # redelivery of that message re-takes its lease and a duplicate message does not.
    lease_owner: str | None = None
    # Artifact parts or embed batches written since the last document heartbeat.
    parts_since_heartbeat: int = 0

    @property
    def document_id_str(self) -> str:
        return str(self.document_id)

    @property
    def owner(self) -> str:
        return self.lease_owner or self.claim_token or self.run_id

    def log_stage(self, stage: str, stage_status: str, **fields: Any) -> None:
        """Structured ``document.pipeline.stage`` log line (operational metadata only)."""
        self.deps.log_document_event(
            event="document.pipeline.stage",
            document_id=self.document_id_str,
            request_id=self.request_id,
            organization_id=self.organization_id,
            user_id=self.user_id,
            stage=stage,
            stage_status=stage_status,
            **fields,
        )
