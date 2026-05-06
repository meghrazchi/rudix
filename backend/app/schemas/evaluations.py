from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class TriggerEvaluationRequest(BaseModel):
    document_id: str = Field(min_length=3)
    dataset_name: str = Field(min_length=2, max_length=255)


class TriggerEvaluationResponse(BaseModel):
    evaluation_run_id: str
    status: Literal["queued"] = "queued"


class EvaluationStatusResponse(BaseModel):
    evaluation_run_id: str
    status: Literal["queued", "running", "completed", "failed"]
    score: float | None = None
    updated_at: datetime | None = None
