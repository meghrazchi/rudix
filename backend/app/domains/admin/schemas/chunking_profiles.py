from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


def _slugify(name: str) -> str:
    slug = name.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-{2,}", "-", slug)
    slug = slug.strip("-")
    return slug[:64]


class ChunkingProfileConfigInput(BaseModel):
    strategy: str = Field(default="token_recursive", min_length=1, max_length=64)
    chunk_size_tokens: int = Field(default=700, ge=100, le=4000)
    chunk_overlap_tokens: int = Field(default=120, ge=0, le=2000)
    language: str | None = Field(default=None, min_length=2, max_length=32)
    min_tokens: int | None = Field(default=None, ge=1, le=500)
    strategy_options: dict[str, Any] = Field(default_factory=dict)

    @field_validator("strategy")
    @classmethod
    def _validate_strategy(cls, value: str) -> str:
        from app.domains.documents.chunking.registry import get_registry

        known = get_registry().known_strategies()
        if value not in known:
            raise ValueError(
                f"Unknown chunking strategy {value!r}. Known: {', '.join(sorted(known))}"
            )
        return value

    @model_validator(mode="after")
    def _overlap_smaller_than_size(self) -> ChunkingProfileConfigInput:
        if self.chunk_overlap_tokens >= self.chunk_size_tokens:
            raise ValueError("chunk_overlap_tokens must be smaller than chunk_size_tokens")
        return self


class ChunkingProfileCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    slug: str | None = Field(
        default=None,
        min_length=2,
        max_length=64,
        pattern=r"^[a-z0-9][a-z0-9-]*[a-z0-9]$",
    )
    config: ChunkingProfileConfigInput
    set_as_default: bool = False

    @model_validator(mode="after")
    def _derive_slug(self) -> ChunkingProfileCreateRequest:
        if self.slug is None:
            derived = _slugify(self.name)
            if len(derived) < 2:
                derived = f"profile-{derived}" if derived else "profile"
            self.slug = derived
        return self


class ChunkingProfileUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    config: ChunkingProfileConfigInput | None = None
    set_as_default: bool | None = None


class ChunkingProfileResponse(BaseModel):
    profile_id: str
    organization_id: str
    name: str
    slug: str
    config: ChunkingProfileConfigInput
    is_default: bool
    is_system: bool
    created_at: datetime
    updated_at: datetime
    created_by_user_id: str | None
    updated_by_user_id: str | None


class ChunkingProfileListResponse(BaseModel):
    profiles: list[ChunkingProfileResponse]
    total: int
    has_org_default: bool


class StrategyInfo(BaseModel):
    name: str
    display_name: str
    description: str
    suitable_for: list[str]
    requires_page_structure: bool
    supports_hierarchical: bool


class StrategyCatalogResponse(BaseModel):
    strategies: list[StrategyInfo]
    default_config: ChunkingProfileConfigInput
    feature_chunking_profiles_enabled: bool


class ChunkingProfilePreviewRequest(BaseModel):
    config: ChunkingProfileConfigInput
    sample_text: str = Field(min_length=1, max_length=20_000)
    file_type: str = Field(default="txt", pattern=r"^(txt|md|pdf|docx)$")


class ChunkingPreviewChunkMeta(BaseModel):
    chunk_index: int
    token_count: int
    section_path: str | None
    chunk_level: int
    is_parent: bool


class ChunkingProfilePreviewResponse(BaseModel):
    strategy_used: str
    chunk_count: int
    min_tokens: int
    max_tokens: int
    avg_tokens: float
    total_tokens: int
    reason_codes: list[str] = Field(default_factory=list)
    sample_chunks: list[ChunkingPreviewChunkMeta]
    warnings: list[str]


class ReindexWithProfileRequest(BaseModel):
    chunking_profile_id: str | None = None
    chunking_profile_config: ChunkingProfileConfigInput | None = None
    ocr_languages: list[str] | None = None

    @model_validator(mode="after")
    def _validate(self) -> ReindexWithProfileRequest:
        if self.chunking_profile_id is not None and self.chunking_profile_config is not None:
            raise ValueError(
                "Provide either chunking_profile_id or chunking_profile_config, not both"
            )
        if self.ocr_languages is not None:
            from app.domains.documents.services.ocr_language_config import (
                UnsupportedOcrLanguageError,
                validate_iso_languages,
            )

            try:
                self.ocr_languages = validate_iso_languages(self.ocr_languages)
            except UnsupportedOcrLanguageError as exc:
                raise ValueError(str(exc)) from exc
        return self
