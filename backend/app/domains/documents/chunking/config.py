from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, model_validator


class ChunkingProfileConfig(BaseModel):
    """Validated configuration for a single chunking pass."""

    strategy: str = Field(default="token_recursive", min_length=1, max_length=64)
    chunk_size_tokens: int = Field(default=700, ge=100, le=4000)
    chunk_overlap_tokens: int = Field(default=120, ge=0, le=2000)
    language: str | None = Field(default=None, min_length=2, max_length=32)
    min_tokens: int | None = Field(default=None, ge=1, le=500)
    strategy_options: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _overlap_smaller_than_size(self) -> ChunkingProfileConfig:
        if self.chunk_overlap_tokens >= self.chunk_size_tokens:
            raise ValueError(
                "chunk_overlap_tokens must be smaller than chunk_size_tokens"
            )
        return self
