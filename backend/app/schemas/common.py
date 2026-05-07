from datetime import datetime
from typing import TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")
HealthMetadataValue = str | int | float | bool | None


class HealthDependency(BaseModel):
    ok: bool
    detail: str | None = None
    metadata: dict[str, HealthMetadataValue] = Field(default_factory=dict)


class HealthResponse(BaseModel):
    status: str
    timestamp: datetime
    dependencies: dict[str, HealthDependency] = Field(default_factory=dict)
    failed_dependencies: list[str] = Field(default_factory=list)


class ErrorResponse(BaseModel):
    code: str
    message: str


class PaginatedResponse[T](BaseModel):
    items: list[T]
    total: int
    limit: int
    offset: int
