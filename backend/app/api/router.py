from fastapi import APIRouter, Depends

from app.auth.dependencies import get_current_principal
from app.interfaces.http import (
    admin,
    admin_chunking_profiles,
    admin_documents,
    admin_governance,
    agent_runs,
    auth,
    billing,
    chat,
    collections,
    documents,
    evaluation_sets,
    evaluations,
    feedback_review,
    model_provider_settings,
    notifications,
    observability,
    org_settings,
    pipeline,
    profile,
    prompt_templates,
    quality_gates,
    quotas,
    rag_profiles,
    safety_evals,
    security_settings,
    team,
)

from . import health

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)

protected_router = APIRouter(dependencies=[Depends(get_current_principal)])
protected_router.include_router(documents.router)
protected_router.include_router(collections.router)
protected_router.include_router(collections.documents_router)
protected_router.include_router(chat.router)
protected_router.include_router(agent_runs.router)
protected_router.include_router(evaluation_sets.router)
protected_router.include_router(evaluations.router)
protected_router.include_router(pipeline.router)
protected_router.include_router(prompt_templates.router)
protected_router.include_router(notifications.router)
protected_router.include_router(feedback_review.router)
protected_router.include_router(quality_gates.router)
protected_router.include_router(model_provider_settings.router)
protected_router.include_router(quotas.admin_router)
protected_router.include_router(quotas.user_router)
protected_router.include_router(rag_profiles.router)
protected_router.include_router(safety_evals.router)
protected_router.include_router(admin.router)
protected_router.include_router(observability.router)
protected_router.include_router(admin_documents.router)
protected_router.include_router(admin_governance.router)
protected_router.include_router(admin_chunking_profiles.router)
protected_router.include_router(team.router)
protected_router.include_router(profile.router)
protected_router.include_router(security_settings.router)
protected_router.include_router(org_settings.router)
protected_router.include_router(billing.router)

api_router.include_router(protected_router)
