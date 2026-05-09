from fastapi import APIRouter, Depends

from app.api import chat, documents, evaluation_sets, evaluations, health, pipeline
from app.auth.dependencies import get_current_principal

api_router = APIRouter()
api_router.include_router(health.router)

protected_router = APIRouter(dependencies=[Depends(get_current_principal)])
protected_router.include_router(documents.router)
protected_router.include_router(chat.router)
protected_router.include_router(evaluation_sets.router)
protected_router.include_router(evaluations.router)
protected_router.include_router(pipeline.router)

api_router.include_router(protected_router)
