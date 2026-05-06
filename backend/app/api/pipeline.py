from fastapi import APIRouter

router = APIRouter(prefix="/pipeline", tags=["pipeline"])


@router.get("/steps")
async def list_pipeline_steps() -> dict[str, list[str]]:
    return {
        "steps": [
            "extract",
            "chunk",
            "embed",
            "index",
            "retrieve",
            "generate",
            "evaluate",
        ]
    }
