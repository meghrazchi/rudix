"""Admin read API contracts for vector index generations (R06-08).

The response never carries collection names, point counts, or other organisations'
numbers: only the active and building generation's model, and the caller's
organisation's document progress.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class VectorIndexActiveGeneration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    generation: int | None = Field(description="Generation number; null in legacy mode.")
    embedding_model: str
    vector_size: int
    activated_at: datetime | None = None


class VectorIndexBuildingGeneration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    generation: int
    embedding_model: str
    state: Literal["building", "verifying"]
    started_at: datetime


class VectorIndexOrganizationProgress(BaseModel):
    model_config = ConfigDict(extra="forbid")

    documents_total: int = Field(ge=0, description="Indexed documents of your organisation.")
    documents_done: int = Field(
        ge=0, description="Of those, documents the building generation already holds."
    )


class VectorIndexStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    alias: str | None
    legacy_mode: bool
    active: VectorIndexActiveGeneration | None
    building: VectorIndexBuildingGeneration | None = None
    progress: VectorIndexOrganizationProgress | None = Field(
        default=None, description="Present while a generation is building or verifying."
    )
