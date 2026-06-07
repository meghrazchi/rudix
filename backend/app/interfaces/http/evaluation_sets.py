from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import ensure_document_ids_access, require_roles
from app.auth.models import AuthenticatedPrincipal
from app.core.logging import log_evaluation_event
from app.db.session import get_db_session
from app.domains.admin.services.audit_service import AuditLogService
from app.domains.evaluations.repositories.evaluations import EvaluationRepository
from app.domains.evaluations.schemas.evaluations import (
    ConvertFeedbackToCasesRequest,
    ConvertFeedbackToCasesResponse,
    CreateEvaluationQuestionRequest,
    CreateEvaluationSetRequest,
    DatasetValidationIssue,
    DuplicateDatasetResponse,
    EvaluationDatasetVersionListResponse,
    EvaluationDatasetVersionResponse,
    EvaluationQuestionListResponse,
    EvaluationQuestionResponse,
    EvaluationSetListResponse,
    EvaluationSetResponse,
    ImportCasesRequest,
    ImportCasesResponse,
    PublishDatasetResponse,
    UpdateEvaluationQuestionRequest,
    UpdateEvaluationSetRequest,
    ValidateDatasetResponse,
)
from app.models.enums import OrganizationRole
from app.models.evaluation import EvaluationDatasetVersion, EvaluationQuestion, EvaluationSet

router = APIRouter(prefix="/evaluation-sets", tags=["evaluation-sets"])
evaluation_repository = EvaluationRepository()
audit_log_service = AuditLogService()


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


def _user_id_from_principal(principal: AuthenticatedPrincipal) -> UUID:
    try:
        return UUID(principal.user_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Principal user context is invalid",
        ) from exc


def _parse_evaluation_set_id(evaluation_set_id: str) -> UUID:
    try:
        return UUID(evaluation_set_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Evaluation set not found"
        ) from exc


def _parse_evaluation_question_id(evaluation_question_id: str) -> UUID:
    try:
        return UUID(evaluation_question_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Evaluation question not found"
        ) from exc


def _normalize_question_payload(
    question: EvaluationQuestion,
) -> tuple[list[str], dict[str, object]]:
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
        status=evaluation_set.status,
        version=evaluation_set.version,
        owner_id=str(evaluation_set.owner_id) if evaluation_set.owner_id else None,
        scope=evaluation_set.scope_json or {},
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
        expected_document_id=str(question.expected_document_id)
        if question.expected_document_id is not None
        else None,
        expected_page_number=question.expected_page_number,
        difficulty=question.difficulty,
        owner_id=str(question.owner_id) if question.owner_id else None,
        tags=tags,
        metadata=metadata,
        created_at=question.created_at,
        updated_at=question.updated_at,
    )


def _to_version_response(
    version: EvaluationDatasetVersion,
) -> EvaluationDatasetVersionResponse:
    return EvaluationDatasetVersionResponse(
        version_id=str(version.id),
        evaluation_set_id=str(version.evaluation_set_id),
        version_number=version.version_number,
        question_count=version.question_count,
        published_by_id=str(version.published_by_id) if version.published_by_id else None,
        published_at=version.published_at,
        created_at=version.created_at,
    )


def _request_id_from_request(request: Request) -> str | None:
    request_id = getattr(request.state, "request_id", None)
    if isinstance(request_id, str) and request_id.strip():
        return request_id
    return request.headers.get("x-request-id")


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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Evaluation set not found"
        )
    return evaluation_set


@router.post("", response_model=EvaluationSetResponse, status_code=status.HTTP_201_CREATED)
async def create_evaluation_set(
    request: Request,
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
    user_id = _user_id_from_principal(principal)
    request_id = _request_id_from_request(request)
    evaluation_set = await evaluation_repository.create_evaluation_set(
        db_session,
        organization_id=organization_id,
        name=payload.name,
        description=payload.description,
        owner_id=user_id,
    )
    await audit_log_service.record(
        db_session,
        organization_id=organization_id,
        user_id=user_id,
        action="evaluation.set.created",
        resource_type="evaluation_set",
        resource_id=evaluation_set.id,
        request_id=request_id,
        metadata={
            "name": payload.name,
            "status_code": status.HTTP_201_CREATED,
        },
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


@router.patch("/{evaluation_set_id}", response_model=EvaluationSetResponse)
async def update_evaluation_set(
    request: Request,
    evaluation_set_id: str,
    payload: UpdateEvaluationSetRequest,
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
    user_id = _user_id_from_principal(principal)
    request_id = _request_id_from_request(request)
    parsed_id = _parse_evaluation_set_id(evaluation_set_id)

    evaluation_set = await evaluation_repository.update_evaluation_set(
        db_session,
        evaluation_set_id=parsed_id,
        organization_id=organization_id,
        name=payload.name,
        description=payload.description,
        scope=payload.scope,
    )
    if evaluation_set is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Evaluation set not found"
        )

    await audit_log_service.record(
        db_session,
        organization_id=organization_id,
        user_id=user_id,
        action="evaluation.set.updated",
        resource_type="evaluation_set",
        resource_id=evaluation_set.id,
        request_id=request_id,
        metadata={"status_code": status.HTTP_200_OK},
    )
    await db_session.commit()
    await db_session.refresh(evaluation_set)

    question_count = await evaluation_repository.count_evaluation_questions(
        db_session, evaluation_set_id=evaluation_set.id
    )
    return _to_evaluation_set_response(evaluation_set, question_count=question_count)


@router.delete("/{evaluation_set_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_evaluation_set(
    request: Request,
    evaluation_set_id: str,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(
            require_roles(
                OrganizationRole.owner.value,
                OrganizationRole.admin.value,
            )
        ),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> None:
    organization_id = _organization_id_from_principal(principal)
    user_id = _user_id_from_principal(principal)
    request_id = _request_id_from_request(request)
    parsed_id = _parse_evaluation_set_id(evaluation_set_id)

    deleted = await evaluation_repository.delete_evaluation_set(
        db_session,
        evaluation_set_id=parsed_id,
        organization_id=organization_id,
    )
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Evaluation set not found"
        )

    await audit_log_service.record(
        db_session,
        organization_id=organization_id,
        user_id=user_id,
        action="evaluation.set.deleted",
        resource_type="evaluation_set",
        resource_id=parsed_id,
        request_id=request_id,
        metadata={"status_code": status.HTTP_204_NO_CONTENT},
    )
    await db_session.commit()

    log_evaluation_event(
        event="evaluation_set.deleted",
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        job_id=evaluation_set_id,
        status_code=status.HTTP_204_NO_CONTENT,
    )


@router.post("/{evaluation_set_id}/publish", response_model=PublishDatasetResponse)
async def publish_evaluation_set(
    request: Request,
    evaluation_set_id: str,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(
            require_roles(
                OrganizationRole.owner.value,
                OrganizationRole.admin.value,
            )
        ),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> PublishDatasetResponse:
    organization_id = _organization_id_from_principal(principal)
    user_id = _user_id_from_principal(principal)
    request_id = _request_id_from_request(request)
    parsed_id = _parse_evaluation_set_id(evaluation_set_id)

    question_count = await evaluation_repository.count_evaluation_questions(
        db_session, evaluation_set_id=parsed_id
    )
    if question_count == 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot publish an evaluation set with no questions",
        )

    evaluation_set = await evaluation_repository.publish_evaluation_set(
        db_session,
        evaluation_set_id=parsed_id,
        organization_id=organization_id,
        published_by_id=user_id,
    )
    if evaluation_set is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Evaluation set not found"
        )

    await audit_log_service.record(
        db_session,
        organization_id=organization_id,
        user_id=user_id,
        action="evaluation.set.published",
        resource_type="evaluation_set",
        resource_id=evaluation_set.id,
        request_id=request_id,
        metadata={
            "version": evaluation_set.version,
            "question_count": question_count,
            "status_code": status.HTTP_200_OK,
        },
    )
    await db_session.commit()

    log_evaluation_event(
        event="evaluation_set.published",
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        job_id=str(evaluation_set.id),
        status_code=status.HTTP_200_OK,
    )
    return PublishDatasetResponse(
        evaluation_set_id=str(evaluation_set.id),
        version_number=evaluation_set.version,
        question_count=question_count,
    )


@router.post(
    "/{evaluation_set_id}/duplicate",
    response_model=DuplicateDatasetResponse,
    status_code=status.HTTP_201_CREATED,
)
async def duplicate_evaluation_set(
    request: Request,
    evaluation_set_id: str,
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
) -> DuplicateDatasetResponse:
    organization_id = _organization_id_from_principal(principal)
    user_id = _user_id_from_principal(principal)
    request_id = _request_id_from_request(request)
    parsed_id = _parse_evaluation_set_id(evaluation_set_id)

    source = await evaluation_repository.get_evaluation_set(
        db_session, evaluation_set_id=parsed_id, organization_id=organization_id
    )
    if source is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Evaluation set not found"
        )

    new_name = f"{source.name} (copy)"
    new_set = await evaluation_repository.duplicate_evaluation_set(
        db_session,
        evaluation_set_id=parsed_id,
        organization_id=organization_id,
        new_name=new_name,
        owner_id=user_id,
    )
    if new_set is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Evaluation set not found"
        )

    question_count = await evaluation_repository.count_evaluation_questions(
        db_session, evaluation_set_id=new_set.id
    )
    await audit_log_service.record(
        db_session,
        organization_id=organization_id,
        user_id=user_id,
        action="evaluation.set.duplicated",
        resource_type="evaluation_set",
        resource_id=new_set.id,
        request_id=request_id,
        metadata={
            "source_set_id": str(parsed_id),
            "question_count": question_count,
            "status_code": status.HTTP_201_CREATED,
        },
    )
    await db_session.commit()
    await db_session.refresh(new_set)

    log_evaluation_event(
        event="evaluation_set.duplicated",
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        job_id=str(new_set.id),
        status_code=status.HTTP_201_CREATED,
    )
    return DuplicateDatasetResponse(
        evaluation_set_id=str(new_set.id),
        name=new_set.name,
        question_count=question_count,
        created_at=new_set.created_at,
    )


@router.post(
    "/{evaluation_set_id}/import",
    response_model=ImportCasesResponse,
)
async def import_evaluation_cases(
    request: Request,
    evaluation_set_id: str,
    payload: ImportCasesRequest,
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
) -> ImportCasesResponse:
    organization_id = _organization_id_from_principal(principal)
    user_id = _user_id_from_principal(principal)
    request_id = _request_id_from_request(request)
    evaluation_set = await _get_evaluation_set_or_404(
        evaluation_set_id=evaluation_set_id,
        organization_id=organization_id,
        db_session=db_session,
    )

    imported, skipped, errors = await evaluation_repository.bulk_import_questions(
        db_session,
        evaluation_set_id=evaluation_set.id,
        raw_data=payload.data,
        fmt=payload.format,
        skip_duplicates=payload.skip_duplicates,
    )

    if imported > 0:
        await audit_log_service.record(
            db_session,
            organization_id=organization_id,
            user_id=user_id,
            action="evaluation.set.cases.imported",
            resource_type="evaluation_set",
            resource_id=evaluation_set.id,
            request_id=request_id,
            metadata={
                "imported": imported,
                "skipped": skipped,
                "format": payload.format,
                "status_code": status.HTTP_200_OK,
            },
        )
    await db_session.commit()

    log_evaluation_event(
        event="evaluation_set.cases.imported",
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        job_id=str(evaluation_set.id),
        status_code=status.HTTP_200_OK,
        imported=imported,
        skipped=skipped,
    )
    return ImportCasesResponse(
        imported=imported,
        skipped_duplicates=skipped,
        validation_errors=errors,
    )


@router.get("/{evaluation_set_id}/validate", response_model=ValidateDatasetResponse)
async def validate_evaluation_dataset(
    evaluation_set_id: str,
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
) -> ValidateDatasetResponse:
    organization_id = _organization_id_from_principal(principal)
    evaluation_set = await _get_evaluation_set_or_404(
        evaluation_set_id=evaluation_set_id,
        organization_id=organization_id,
        db_session=db_session,
    )

    raw_issues = await evaluation_repository.validate_dataset(
        db_session,
        evaluation_set_id=evaluation_set.id,
        organization_id=organization_id,
    )
    issues = [DatasetValidationIssue(**issue) for issue in raw_issues]

    return ValidateDatasetResponse(
        evaluation_set_id=str(evaluation_set.id),
        is_valid=len(issues) == 0,
        issue_count=len(issues),
        issues=issues,
    )


@router.get("/{evaluation_set_id}/versions", response_model=EvaluationDatasetVersionListResponse)
async def list_dataset_versions(
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
) -> EvaluationDatasetVersionListResponse:
    organization_id = _organization_id_from_principal(principal)
    evaluation_set = await _get_evaluation_set_or_404(
        evaluation_set_id=evaluation_set_id,
        organization_id=organization_id,
        db_session=db_session,
    )

    versions = await evaluation_repository.list_dataset_versions(
        db_session, evaluation_set_id=evaluation_set.id
    )
    items = [_to_version_response(v) for v in versions]
    return EvaluationDatasetVersionListResponse(
        evaluation_set_id=str(evaluation_set.id),
        items=items,
        total=len(items),
    )


@router.post(
    "/from-feedback",
    response_model=ConvertFeedbackToCasesResponse,
    status_code=status.HTTP_201_CREATED,
)
async def convert_feedback_to_cases(
    request: Request,
    payload: ConvertFeedbackToCasesRequest,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(
            require_roles(
                OrganizationRole.owner.value,
                OrganizationRole.admin.value,
            )
        ),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ConvertFeedbackToCasesResponse:
    from uuid import UUID as _UUID

    from app.models.chat import MessageFeedback

    organization_id = _organization_id_from_principal(principal)
    user_id = _user_id_from_principal(principal)
    request_id = _request_id_from_request(request)

    parsed_set_id = _parse_evaluation_set_id(payload.evaluation_set_id)
    evaluation_set = await evaluation_repository.get_evaluation_set(
        db_session, evaluation_set_id=parsed_set_id, organization_id=organization_id
    )
    if evaluation_set is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Evaluation set not found"
        )

    existing_texts = await evaluation_repository.get_existing_question_texts(
        db_session, evaluation_set_id=evaluation_set.id
    )

    from sqlalchemy import select as _select

    created = 0
    skipped = 0
    for fid_str in payload.feedback_ids:
        try:
            fid = _UUID(fid_str)
        except ValueError:
            skipped += 1
            continue

        result = await db_session.execute(_select(MessageFeedback).where(MessageFeedback.id == fid))
        feedback = result.scalar_one_or_none()
        if feedback is None:
            skipped += 1
            continue

        message_text = ""
        if hasattr(feedback, "message") and feedback.message is not None:
            msg = feedback.message
            if hasattr(msg, "content") and msg.content:
                message_text = str(msg.content).strip()

        if not message_text or message_text.lower() in existing_texts:
            skipped += 1
            continue

        await evaluation_repository.create_evaluation_question(
            db_session,
            evaluation_set_id=evaluation_set.id,
            question=message_text,
            difficulty=payload.default_difficulty,
            metadata={"source": "feedback", "feedback_id": fid_str},
        )
        existing_texts.add(message_text.lower())
        created += 1

    if created > 0:
        await audit_log_service.record(
            db_session,
            organization_id=organization_id,
            user_id=user_id,
            action="evaluation.set.cases.from_feedback",
            resource_type="evaluation_set",
            resource_id=evaluation_set.id,
            request_id=request_id,
            metadata={
                "created": created,
                "skipped": skipped,
                "status_code": status.HTTP_201_CREATED,
            },
        )
    await db_session.commit()

    return ConvertFeedbackToCasesResponse(
        created=created,
        skipped=skipped,
        evaluation_set_id=str(evaluation_set.id),
    )


@router.post(
    "/{evaluation_set_id}/questions",
    response_model=EvaluationQuestionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_evaluation_question(
    request: Request,
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
    user_id = _user_id_from_principal(principal)
    request_id = _request_id_from_request(request)
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
        difficulty=payload.difficulty,
        owner_id=user_id,
        metadata=metadata_payload,
    )
    await audit_log_service.record(
        db_session,
        organization_id=organization_id,
        user_id=user_id,
        action="evaluation.question.created",
        resource_type="evaluation_question",
        resource_id=question.id,
        request_id=request_id,
        metadata={
            "evaluation_set_id": str(evaluation_set.id),
            "expected_document_id": str(expected_document_id)
            if expected_document_id is not None
            else None,
            "expected_page_number": payload.expected_page_number,
            "difficulty": payload.difficulty,
            "tag_count": len(payload.tags),
            "has_expected_answer": bool(payload.expected_answer),
            "status_code": status.HTTP_201_CREATED,
        },
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


@router.patch(
    "/{evaluation_set_id}/questions/{evaluation_question_id}",
    response_model=EvaluationQuestionResponse,
)
async def update_evaluation_question(
    request: Request,
    evaluation_set_id: str,
    evaluation_question_id: str,
    payload: UpdateEvaluationQuestionRequest,
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
    user_id = _user_id_from_principal(principal)
    request_id = _request_id_from_request(request)
    evaluation_set = await _get_evaluation_set_or_404(
        evaluation_set_id=evaluation_set_id,
        organization_id=organization_id,
        db_session=db_session,
    )
    parsed_question_id = _parse_evaluation_question_id(evaluation_question_id)

    expected_document_id: UUID | None = None
    clear_expected_document = False
    if payload.expected_document_id is not None:
        if payload.expected_document_id == "":
            clear_expected_document = True
        else:
            parsed_ids = await ensure_document_ids_access(
                document_ids=[payload.expected_document_id],
                principal=principal,
                db_session=db_session,
            )
            if parsed_ids:
                expected_document_id = parsed_ids[0]

    metadata: dict | None = None
    if payload.metadata is not None or payload.tags is not None:
        existing = await evaluation_repository.get_evaluation_question(
            db_session,
            evaluation_question_id=parsed_question_id,
            evaluation_set_id=evaluation_set.id,
        )
        if existing is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Evaluation question not found"
            )
        raw_metadata = dict(existing.metadata_json or {})
        if payload.tags is not None:
            raw_metadata["tags"] = payload.tags
        if payload.metadata is not None:
            raw_metadata.update(payload.metadata)
        metadata = raw_metadata

    question = await evaluation_repository.update_evaluation_question(
        db_session,
        evaluation_question_id=parsed_question_id,
        evaluation_set_id=evaluation_set.id,
        question=payload.question,
        expected_answer=payload.expected_answer,
        clear_expected_answer=False,
        expected_document_id=expected_document_id,
        clear_expected_document=clear_expected_document,
        expected_page_number=payload.expected_page_number,
        clear_expected_page=False,
        difficulty=payload.difficulty,
        clear_difficulty=False,
        metadata=metadata,
    )
    if question is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Evaluation question not found"
        )

    await audit_log_service.record(
        db_session,
        organization_id=organization_id,
        user_id=user_id,
        action="evaluation.question.updated",
        resource_type="evaluation_question",
        resource_id=question.id,
        request_id=request_id,
        metadata={"evaluation_set_id": str(evaluation_set.id), "status_code": status.HTTP_200_OK},
    )
    await db_session.commit()
    await db_session.refresh(question)
    return _to_question_response(question)


@router.delete(
    "/{evaluation_set_id}/questions/{evaluation_question_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_evaluation_question(
    request: Request,
    evaluation_set_id: str,
    evaluation_question_id: str,
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
) -> None:
    organization_id = _organization_id_from_principal(principal)
    user_id = _user_id_from_principal(principal)
    request_id = _request_id_from_request(request)
    evaluation_set = await _get_evaluation_set_or_404(
        evaluation_set_id=evaluation_set_id,
        organization_id=organization_id,
        db_session=db_session,
    )
    parsed_question_id = _parse_evaluation_question_id(evaluation_question_id)

    deleted = await evaluation_repository.delete_evaluation_question(
        db_session,
        evaluation_question_id=parsed_question_id,
        evaluation_set_id=evaluation_set.id,
    )
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Evaluation question not found"
        )

    await audit_log_service.record(
        db_session,
        organization_id=organization_id,
        user_id=user_id,
        action="evaluation.question.deleted",
        resource_type="evaluation_question",
        resource_id=parsed_question_id,
        request_id=request_id,
        metadata={
            "evaluation_set_id": str(evaluation_set.id),
            "status_code": status.HTTP_204_NO_CONTENT,
        },
    )
    await db_session.commit()

    log_evaluation_event(
        event="evaluation_set.question.deleted",
        organization_id=principal.organization_id,
        user_id=principal.user_id,
        job_id=evaluation_question_id,
        status_code=status.HTTP_204_NO_CONTENT,
        evaluation_set_id=evaluation_set_id,
    )
