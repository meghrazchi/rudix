from fastapi import APIRouter, Depends

from app.auth.dependencies import get_current_principal
from app.interfaces.http import (
    admin,
    admin_api_keys,
    admin_chunking_profiles,
    admin_documents,
    admin_email,
    admin_feature_flags,
    admin_governance,
    admin_roles,
    admin_scim,
    admin_sso,
    admin_status,
    admin_webhooks,
    agent_runs,
    auth,
    billing,
    bots,
    chat,
    collections,
    connector_discovery,
    connector_platform,
    connector_sync,
    connectors,
    documents,
    evaluation_sets,
    evaluations,
    failed_jobs,
    feature_flags,
    feedback_review,
    admin_graph_entities,
    admin_graph_observability,
    admin_graph_provenance,
    admin_graph_relations,
    admin_graph_schema,
    graph_health,
    graph_explorer,
    langfuse_diagnostics,
    model_profiles,
    model_provider_diagnostics,
    model_provider_settings,
    notifications,
    observability,
    org_settings,
    pipeline,
    profile,
    prompt_templates,
    provider_observability,
    quality_gates,
    quotas,
    rag_profiles,
    safety_evals,
    scim,
    security_settings,
    team,
    team_invitations,
)

from . import health

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(scim.router)
api_router.include_router(bots.public_router)
# WebSocket chat endpoint must be registered outside protected_router so that
# FastAPI does not try to inject get_current_principal as an HTTP dependency
# during the WebSocket upgrade (browsers cannot send Authorization headers).
api_router.include_router(chat.ws_router)

protected_router = APIRouter(dependencies=[Depends(get_current_principal)])
protected_router.include_router(documents.router)
protected_router.include_router(collections.router)
protected_router.include_router(collections.documents_router)
api_router.include_router(connectors.public_router)
api_router.include_router(team_invitations.public_router)
protected_router.include_router(connector_platform.router)
protected_router.include_router(connector_discovery.router)
protected_router.include_router(connectors.router)
protected_router.include_router(connector_sync.router)
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
protected_router.include_router(model_profiles.router)
protected_router.include_router(model_provider_diagnostics.router)
protected_router.include_router(quotas.admin_router)
protected_router.include_router(quotas.user_router)
protected_router.include_router(rag_profiles.router)
protected_router.include_router(safety_evals.router)
protected_router.include_router(admin.router)
protected_router.include_router(observability.router)
protected_router.include_router(provider_observability.router)
protected_router.include_router(langfuse_diagnostics.router)
protected_router.include_router(graph_health.router)
protected_router.include_router(graph_explorer.router)
protected_router.include_router(admin_graph_schema.router)
protected_router.include_router(admin_graph_observability.router)
protected_router.include_router(admin_graph_entities.router)
protected_router.include_router(admin_graph_provenance.router)
protected_router.include_router(admin_graph_relations.router)
protected_router.include_router(failed_jobs.router)
protected_router.include_router(admin_status.router)
protected_router.include_router(admin_sso.router)
protected_router.include_router(admin_scim.router)
protected_router.include_router(admin_documents.router)
protected_router.include_router(admin_governance.router)
protected_router.include_router(admin_feature_flags.router)
protected_router.include_router(admin_chunking_profiles.router)
protected_router.include_router(admin_roles.router)
protected_router.include_router(admin_api_keys.router)
protected_router.include_router(admin_webhooks.router)
protected_router.include_router(bots.admin_router)
protected_router.include_router(admin_email.router)
protected_router.include_router(team.router)
protected_router.include_router(team_invitations.router)
protected_router.include_router(profile.router)
protected_router.include_router(security_settings.router)
protected_router.include_router(org_settings.router)
protected_router.include_router(billing.router)
protected_router.include_router(feature_flags.router)

api_router.include_router(protected_router)
