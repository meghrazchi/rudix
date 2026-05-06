from fastapi import APIRouter

from app.api import chat, documents, evaluations, health, pipeline

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(documents.router)
api_router.include_router(chat.router)
api_router.include_router(evaluations.router)
api_router.include_router(pipeline.router)
