from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.domains.admin.repositories.chunking_profiles import ChunkingProfileRepository
from app.domains.admin.schemas.chunking_profiles import (
    ChunkingPreviewChunkMeta,
    ChunkingProfileConfigInput,
    ChunkingProfileCreateRequest,
    ChunkingProfileListResponse,
    ChunkingProfilePreviewRequest,
    ChunkingProfilePreviewResponse,
    ChunkingProfileResponse,
    ChunkingProfileUpdateRequest,
    StrategyCatalogResponse,
    StrategyInfo,
)
from app.models.chunking_profile import OrganizationChunkingProfile

_STRATEGY_CATALOG: dict[str, StrategyInfo] = {
    "token_recursive": StrategyInfo(
        name="token_recursive",
        display_name="Token Recursive",
        description=(
            "Default recursive text splitting by token count. Preserves sentence and "
            "paragraph boundaries where possible. Best general-purpose choice."
        ),
        suitable_for=["general text", "articles", "documentation", "reports"],
        requires_page_structure=False,
        supports_hierarchical=False,
    ),
    "token_fixed": StrategyInfo(
        name="token_fixed",
        display_name="Token Fixed",
        description=(
            "Fixed-size token windows with optional overlap. Produces uniform chunks "
            "ideal for dense retrieval benchmarks."
        ),
        suitable_for=["uniform embedding density", "benchmarking"],
        requires_page_structure=False,
        supports_hierarchical=False,
    ),
    "paragraph_recursive": StrategyInfo(
        name="paragraph_recursive",
        display_name="Paragraph Recursive",
        description=(
            "Splits at natural paragraph boundaries first, then recurses within large "
            "paragraphs. Preserves topical coherence."
        ),
        suitable_for=["prose", "blog posts", "narrative text"],
        requires_page_structure=False,
        supports_hierarchical=False,
    ),
    "sentence_window": StrategyInfo(
        name="sentence_window",
        display_name="Sentence Window",
        description=(
            "Sentences are embedded individually but retrieved with surrounding context "
            "sentences. Trades storage for finer-grained precision."
        ),
        suitable_for=["QA datasets", "customer support", "fact-dense text"],
        requires_page_structure=False,
        supports_hierarchical=False,
    ),
    "page_aware": StrategyInfo(
        name="page_aware",
        display_name="Page Aware",
        description=(
            "Respects page boundaries so citations can reference exact source pages. "
            "Required when page-accurate citation provenance matters."
        ),
        suitable_for=["PDFs", "scanned documents", "legal contracts"],
        requires_page_structure=True,
        supports_hierarchical=False,
    ),
    "heading_aware": StrategyInfo(
        name="heading_aware",
        display_name="Heading Aware",
        description=(
            "Groups content under its nearest heading, keeping sections semantically "
            "cohesive. Works best with well-structured Markdown or DOCX files."
        ),
        suitable_for=["Markdown", "DOCX", "technical manuals", "wiki pages"],
        requires_page_structure=False,
        supports_hierarchical=False,
    ),
    "adaptive_hybrid": StrategyInfo(
        name="adaptive_hybrid",
        display_name="Adaptive Hybrid",
        description=(
            "Automatically selects the best strategy per document based on file type, "
            "page count, heading density, and OCR status."
        ),
        suitable_for=["mixed document libraries", "automated pipelines"],
        requires_page_structure=False,
        supports_hierarchical=False,
    ),
    "hierarchical": StrategyInfo(
        name="hierarchical",
        display_name="Hierarchical",
        description=(
            "Produces parent chunks (larger context) and child chunks (fine-grained "
            "retrieval). Enables parent-document retrieval patterns."
        ),
        suitable_for=["long documents", "multi-section reports", "parent-document retrieval"],
        requires_page_structure=False,
        supports_hierarchical=True,
    ),
}


@dataclass
class _SimplePage:
    page_number: int
    text: str


def _build_profile_response(profile: OrganizationChunkingProfile) -> ChunkingProfileResponse:
    config = ChunkingProfileConfigInput.model_validate(profile.config_json)
    return ChunkingProfileResponse(
        profile_id=str(profile.id),
        organization_id=str(profile.organization_id),
        name=profile.name,
        slug=profile.slug,
        config=config,
        is_default=profile.is_default,
        is_system=profile.is_system,
        created_at=profile.created_at,
        updated_at=profile.updated_at,
        created_by_user_id=str(profile.created_by_user_id)
        if profile.created_by_user_id is not None
        else None,
        updated_by_user_id=str(profile.updated_by_user_id)
        if profile.updated_by_user_id is not None
        else None,
    )


class ChunkingProfileService:
    def __init__(
        self,
        *,
        repository: ChunkingProfileRepository | None = None,
    ) -> None:
        self._repository = repository or ChunkingProfileRepository()

    def get_strategy_catalog(self) -> StrategyCatalogResponse:
        from app.domains.documents.chunking.registry import get_registry

        known = set(get_registry().known_strategies())
        strategies = [info for name, info in sorted(_STRATEGY_CATALOG.items()) if name in known]
        return StrategyCatalogResponse(
            strategies=strategies,
            default_config=ChunkingProfileConfigInput(),
            feature_chunking_profiles_enabled=settings.feature_enable_chunking_profiles,
        )

    async def list_profiles(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
    ) -> ChunkingProfileListResponse:
        profiles = await self._repository.list_by_organization(
            session, organization_id=organization_id
        )
        responses = [_build_profile_response(p) for p in profiles]
        return ChunkingProfileListResponse(
            profiles=responses,
            total=len(responses),
            has_org_default=any(p.is_default for p in profiles),
        )

    async def get_profile(
        self,
        session: AsyncSession,
        *,
        profile_id: UUID,
        organization_id: UUID,
    ) -> ChunkingProfileResponse:
        profile = await self._repository.get_by_id(
            session, profile_id=profile_id, organization_id=organization_id
        )
        if profile is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Chunking profile not found",
            )
        return _build_profile_response(profile)

    async def create_profile(
        self,
        session: AsyncSession,
        *,
        organization_id: UUID,
        created_by_user_id: UUID,
        payload: ChunkingProfileCreateRequest,
    ) -> ChunkingProfileResponse:
        # slug is always set by ChunkingProfileCreateRequest's model_validator
        slug = payload.slug or ""
        existing = await self._repository.get_by_slug(
            session, slug=slug, organization_id=organization_id
        )
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"A chunking profile with slug {slug!r} already exists in this organization",
            )

        if payload.set_as_default:
            await self._repository.clear_org_default(session, organization_id=organization_id)

        profile = await self._repository.create(
            session,
            organization_id=organization_id,
            created_by_user_id=created_by_user_id,
            name=payload.name,
            slug=slug,
            config_json=payload.config.model_dump(mode="json"),
            is_default=payload.set_as_default,
        )
        return _build_profile_response(profile)

    async def update_profile(
        self,
        session: AsyncSession,
        *,
        profile_id: UUID,
        organization_id: UUID,
        updated_by_user_id: UUID,
        payload: ChunkingProfileUpdateRequest,
    ) -> ChunkingProfileResponse:
        profile = await self._repository.get_by_id(
            session, profile_id=profile_id, organization_id=organization_id
        )
        if profile is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Chunking profile not found",
            )
        if profile.is_system:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="System profiles cannot be modified",
            )

        new_is_default: bool | None = None
        if payload.set_as_default is True and not profile.is_default:
            await self._repository.clear_org_default(
                session,
                organization_id=organization_id,
                exclude_profile_id=profile_id,
            )
            new_is_default = True
        elif payload.set_as_default is False and profile.is_default:
            new_is_default = False

        updated = await self._repository.update(
            session,
            profile=profile,
            updated_by_user_id=updated_by_user_id,
            name=payload.name,
            config_json=payload.config.model_dump(mode="json") if payload.config else None,
            is_default=new_is_default,
        )
        return _build_profile_response(updated)

    async def delete_profile(
        self,
        session: AsyncSession,
        *,
        profile_id: UUID,
        organization_id: UUID,
    ) -> None:
        profile = await self._repository.get_by_id(
            session, profile_id=profile_id, organization_id=organization_id
        )
        if profile is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Chunking profile not found",
            )
        if profile.is_system:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="System profiles cannot be deleted",
            )
        await self._repository.delete(session, profile=profile)

    async def set_default(
        self,
        session: AsyncSession,
        *,
        profile_id: UUID,
        organization_id: UUID,
        updated_by_user_id: UUID,
    ) -> ChunkingProfileResponse:
        profile = await self._repository.get_by_id(
            session, profile_id=profile_id, organization_id=organization_id
        )
        if profile is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Chunking profile not found",
            )
        if not profile.is_default:
            await self._repository.clear_org_default(
                session,
                organization_id=organization_id,
                exclude_profile_id=profile_id,
            )
            updated = await self._repository.update(
                session,
                profile=profile,
                updated_by_user_id=updated_by_user_id,
                is_default=True,
            )
            return _build_profile_response(updated)
        return _build_profile_response(profile)

    async def preview(
        self,
        payload: ChunkingProfilePreviewRequest,
    ) -> ChunkingProfilePreviewResponse:
        from app.domains.documents.chunking.config import ChunkingProfileConfig
        from app.domains.documents.chunking.registry import get_registry
        from app.domains.documents.chunking.selector import SelectionResult

        profile_cfg = ChunkingProfileConfig.model_construct(
            strategy=payload.config.strategy,
            chunk_size_tokens=payload.config.chunk_size_tokens,
            chunk_overlap_tokens=payload.config.chunk_overlap_tokens,
            language=payload.config.language,
            min_tokens=payload.config.min_tokens
            or max(1, min(32, payload.config.chunk_size_tokens // 8)),
            strategy_options=dict(payload.config.strategy_options),
        )

        strategy = get_registry().resolve(
            profile_cfg,
            embedding_model=settings.openai_embedding_model,
            index_version=settings.document_index_version,
        )

        pages = [_SimplePage(page_number=1, text=payload.sample_text)]
        document_id = uuid4()
        chunks = await strategy.chunk(document_id=document_id, pages=pages)

        raw_selection = getattr(strategy, "last_selection", None)
        reason_codes = (
            list(raw_selection.reason_codes) if isinstance(raw_selection, SelectionResult) else []
        )

        if not chunks:
            return ChunkingProfilePreviewResponse(
                strategy_used=payload.config.strategy,
                chunk_count=0,
                min_tokens=0,
                max_tokens=0,
                avg_tokens=0.0,
                total_tokens=0,
                reason_codes=reason_codes,
                sample_chunks=[],
                warnings=["No chunks produced — sample text may be too short."],
            )

        token_counts = [c.token_count for c in chunks]
        total_tokens = sum(token_counts)
        warnings: list[str] = []
        if any(c.token_count < 20 for c in chunks):
            warnings.append(
                "Some chunks have fewer than 20 tokens. Consider increasing chunk_size_tokens "
                "or reducing chunk_overlap_tokens."
            )

        sample_chunks = [
            ChunkingPreviewChunkMeta(
                chunk_index=c.chunk_index,
                token_count=c.token_count,
                section_path=c.section_path,
                chunk_level=c.chunk_level,
                is_parent=c.child_count is not None and c.child_count > 0,
            )
            for c in chunks[:10]
        ]

        return ChunkingProfilePreviewResponse(
            strategy_used=chunks[0].strategy_name,
            chunk_count=len(chunks),
            min_tokens=min(token_counts),
            max_tokens=max(token_counts),
            avg_tokens=round(total_tokens / len(chunks), 1),
            total_tokens=total_tokens,
            reason_codes=reason_codes,
            sample_chunks=sample_chunks,
            warnings=warnings,
        )

    async def resolve_profile_config_for_reindex(
        self,
        session: AsyncSession,
        *,
        profile_id: str | None,
        inline_config: ChunkingProfileConfigInput | None,
        organization_id: UUID,
    ) -> dict[str, Any] | None:
        """Resolve a chunking profile config dict for the reindex task, or return None for system default."""
        if profile_id is None and inline_config is None:
            return None
        if inline_config is not None:
            return inline_config.model_dump(mode="json")
        try:
            pid = UUID(profile_id)  # type: ignore[arg-type]
        except (ValueError, AttributeError) as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="chunking_profile_id must be a valid UUID",
            ) from exc
        profile = await self._repository.get_by_id(
            session, profile_id=pid, organization_id=organization_id
        )
        if profile is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Chunking profile {profile_id!r} not found",
            )
        return dict(profile.config_json)
