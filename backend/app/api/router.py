from fastapi import APIRouter, Depends

from app.auth.dependencies import get_current_principal
from app.interfaces.http import (
    admin,
    auth,
    chat,
    documents,
    evaluation_sets,
    evaluations,
    pipeline,
    team,
)

from . import health

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)

protected_router = APIRouter(dependencies=[Depends(get_current_principal)])
protected_router.include_router(documents.router)
protected_router.include_router(chat.router)
protected_router.include_router(evaluation_sets.router)
protected_router.include_router(evaluations.router)
protected_router.include_router(pipeline.router)
protected_router.include_router(admin.router)
protected_router.include_router(team.router)

api_router.include_router(protected_router)
