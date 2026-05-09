from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import ensure_document_ids_access, require_roles
from app.auth.models import AuthenticatedPrincipal
from app.core.logging import log_evaluation_event
from app.db.session import get_db_session
from app.models.enums import OrganizationRole
from app.models.evaluation import EvaluationQuestion, EvaluationSet
from app.repositories.evaluations import EvaluationRepository
from app.schemas.evaluations import (
    CreateEvaluationQuestionRequest,
    CreateEvaluationSetRequest,
    EvaluationQuestionListResponse,
    EvaluationQuestionResponse,
    EvaluationSetListResponse,
    EvaluationSetResponse,
)

router = APIRouter(prefix="/evaluation-sets", tags=["evaluation-sets"])
evaluation_repository = EvaluationRepository()


def _organization_id_from_principal(principal: AuthenticatedPrincipal) -> UUID:
    if principal.organization_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No active organization context for principal",
        )
    try:
        return UUID(principal.organization_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Principal organization context is invalid",
        ) from exc


def _parse_evaluation_set_id(evaluation_set_id: str) -> UUID:
    try:
        return UUID(evaluation_set_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Evaluation set not found") from exc


def _normalize_question_payload(question: EvaluationQuestion) -> tuple[list[str], dict[str, object]]:
    raw_metadata = dict(question.metadata_json or {})
    raw_tags = raw_metadata.pop("tags", [])
    if not isinstance(raw_tags, list):
        raw_tags = []

    tags: list[str] = []
    for tag in raw_tags:
        if not isinstance(tag, str):
            continue
        normalized = tag.strip()
        if normalized:
            tags.append(normalized)

    return tags, raw_metadata


def _to_evaluation_set_response(
    evaluation_set: EvaluationSet,
    *,
    question_count: int,
) -> EvaluationSetResponse:
    return EvaluationSetResponse(
        evaluation_set_id=str(evaluation_set.id),
        name=evaluation_set.name,
        description=evaluation_set.description,
        question_count=question_count,
        created_at=evaluation_set.created_at,
        updated_at=evaluation_set.updated_at,
    )


def _to_question_response(question: EvaluationQuestion) -> EvaluationQuestionResponse:
    tags, metadata = _normalize_question_payload(question)
    return EvaluationQuestionResponse(
        evaluation_question_id=str(question.id),
        evaluation_set_id=str(question.evaluation_set_id),
        question=question.question,
        expected_answer=question.expected_answer,
        expected_document_id=str(question.expected_document_id) if question.expected_document_id is not None else None,
        expected_page_number=question.expected_page_number,
        tags=tags,
        metadata=metadata,
        created_at=question.created_at,
        updated_at=question.updated_at,
    )


async def _get_evaluation_set_or_404(
    *,
    evaluation_set_id: str,
    organization_id: UUID,
    db_session: AsyncSession,
) -> EvaluationSet:
    parsed_id = _parse_evaluation_set_id(evaluation_set_id)
    evaluation_set = await evaluation_repository.get_evaluation_set(
        db_session,
        evaluation_set_id=parsed_id,
        organization_id=organization_id,
    )
    if evaluation_set is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Evaluation set not found")
    return evaluation_set


@router.post("", response_model=EvaluationSetResponse, status_code=status.HTTP_201_CREATED)
async def create_evaluation_set(
    payload: CreateEvaluationSetRequest,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(
            require_roles(
                OrganizationRole.owner.value,
                OrganizationRole.admin.value,
                OrganizationRole.member.value,
            )
        ),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> EvaluationSetResponse:
    organization_id = _organization_id_from_principal(principal)
    evaluation_set = await evaluation_repository.create_evaluation_set(
        db_session,
        organization_id=organization_id,
        name=payload.name,
        description=payload.description,
    )
    await db_session.commit()
    await db_session.refresh(evaluation_set)

    log_evaluation_event(
        event="evaluation_set.created",
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        job_id=str(evaluation_set.id),
        status_code=status.HTTP_201_CREATED,
    )
    return _to_evaluation_set_response(evaluation_set, question_count=0)


@router.get("", response_model=EvaluationSetListResponse)
async def list_evaluation_sets(
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(
            require_roles(
                OrganizationRole.owner.value,
                OrganizationRole.admin.value,
                OrganizationRole.member.value,
                OrganizationRole.viewer.value,
            )
        ),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
    limit: Annotated[int, Query(ge=1, le=200)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> EvaluationSetListResponse:
    organization_id = _organization_id_from_principal(principal)
    evaluation_sets = await evaluation_repository.list_evaluation_sets(
        db_session,
        organization_id=organization_id,
        limit=limit,
        offset=offset,
    )
    total = await evaluation_repository.count_evaluation_sets(
        db_session,
        organization_id=organization_id,
    )

    items: list[EvaluationSetResponse] = []
    for evaluation_set in evaluation_sets:
        question_count = await evaluation_repository.count_evaluation_questions(
            db_session,
            evaluation_set_id=evaluation_set.id,
        )
        items.append(_to_evaluation_set_response(evaluation_set, question_count=question_count))

    log_evaluation_event(
        event="evaluation_set.listed",
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        status_code=status.HTTP_200_OK,
        total=total,
        returned=len(items),
        limit=limit,
        offset=offset,
    )
    return EvaluationSetListResponse(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("/{evaluation_set_id}/questions", response_model=EvaluationQuestionResponse, status_code=status.HTTP_201_CREATED)
async def create_evaluation_question(
    evaluation_set_id: str,
    payload: CreateEvaluationQuestionRequest,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(
            require_roles(
                OrganizationRole.owner.value,
                OrganizationRole.admin.value,
                OrganizationRole.member.value,
            )
        ),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> EvaluationQuestionResponse:
    organization_id = _organization_id_from_principal(principal)
    evaluation_set = await _get_evaluation_set_or_404(
        evaluation_set_id=evaluation_set_id,
        organization_id=organization_id,
        db_session=db_session,
    )

    expected_document_id: UUID | None = None
    if payload.expected_document_id is not None:
        parsed_ids = await ensure_document_ids_access(
            document_ids=[payload.expected_document_id],
            principal=principal,
            db_session=db_session,
        )
        if parsed_ids:
            expected_document_id = parsed_ids[0]

    metadata_payload = dict(payload.metadata)
    metadata_payload["tags"] = payload.tags

    question = await evaluation_repository.create_evaluation_question(
        db_session,
        evaluation_set_id=evaluation_set.id,
        question=payload.question,
        expected_answer=payload.expected_answer,
        expected_document_id=expected_document_id,
        expected_page_number=payload.expected_page_number,
        metadata=metadata_payload,
    )
    await db_session.commit()
    await db_session.refresh(question)

    log_evaluation_event(
        event="evaluation_set.question.created",
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        job_id=str(question.id),
        status_code=status.HTTP_201_CREATED,
        evaluation_set_id=str(evaluation_set.id),
    )
    return _to_question_response(question)


@router.get("/{evaluation_set_id}/questions", response_model=EvaluationQuestionListResponse)
async def list_evaluation_questions(
    evaluation_set_id: str,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(
            require_roles(
                OrganizationRole.owner.value,
                OrganizationRole.admin.value,
                OrganizationRole.member.value,
                OrganizationRole.viewer.value,
            )
        ),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
    limit: Annotated[int, Query(ge=1, le=200)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> EvaluationQuestionListResponse:
    organization_id = _organization_id_from_principal(principal)
    evaluation_set = await _get_evaluation_set_or_404(
        evaluation_set_id=evaluation_set_id,
        organization_id=organization_id,
        db_session=db_session,
    )

    questions = await evaluation_repository.list_evaluation_questions(
        db_session,
        evaluation_set_id=evaluation_set.id,
        limit=limit,
        offset=offset,
    )
    total = await evaluation_repository.count_evaluation_questions(
        db_session,
        evaluation_set_id=evaluation_set.id,
    )

    items = [_to_question_response(question) for question in questions]
    log_evaluation_event(
        event="evaluation_set.question.listed",
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        job_id=str(evaluation_set.id),
        status_code=status.HTTP_200_OK,
        total=total,
        returned=len(items),
        limit=limit,
        offset=offset,
    )
    return EvaluationQuestionListResponse(
        evaluation_set_id=str(evaluation_set.id),
        items=items,
        total=total,
        limit=limit,
        offset=offset,
    )
