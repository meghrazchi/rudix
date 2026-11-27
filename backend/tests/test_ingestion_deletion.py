"""Document deletion removes its ingestion stage rows and artifacts (F143, R06-01)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from ingestion_golden_support import (
    IngestionEnv,
    Seeded,
    ingestion_env,  # noqa: F401  (fixture)
    ingestion_env_pg,  # noqa: F401  (fixture)
)
from sqlalchemy import func, select

from app.clients import minio_client as minio_module
from app.models.document_processing import DocumentProcessingStage, DocumentStageArtifact
from app.workers import document_tasks
from app.workers.ingestion.store import DbStageStore


class _MinioDeleter:
    def __init__(self) -> None:
        self.deleted: list[str] = []

    def list_objects_v2(self, **kwargs: Any) -> dict[str, Any]:
        return {"IsTruncated": False, "Contents": [{"Key": f"{kwargs['Prefix']}.txt"}]}

    def delete_object(self, **kwargs: Any) -> None:
        self.deleted.append(kwargs["Key"])


async def _leave_stage_state(env: IngestionEnv, seeded: Seeded, run_id: str) -> None:
    store = DbStageStore(
        env.factory,
        organization_id=seeded.organization_id,
        document_id=seeded.document_id,
        run_id=run_id,
    )
    await store.lease("extract", owner=run_id)
    await store.write_artifacts(
        "extract", {0: {"page_number": 1, "text": "private text"}}, replace_stage=True
    )


async def _counts(env: IngestionEnv, document_id: UUID) -> tuple[int, int]:
    async with env.factory() as session:
        stages = await session.execute(
            select(func.count()).where(DocumentProcessingStage.document_id == document_id)
        )
        artifacts = await session.execute(
            select(func.count()).where(DocumentStageArtifact.document_id == document_id)
        )
        return int(stages.scalar_one()), int(artifacts.scalar_one())


def _scenario(env: IngestionEnv) -> None:
    env.set_content(b"Deletion removes every copy of the document text.")
    target = env.seed()
    other = env.seed()
    for seeded in (target, other):
        env.run_task(document_tasks.process_document, seeded.document_id, task_id=f"t-{seeded}")
        # A killed earlier run left a stage row and an artifact with document text behind.
        env.run_async(_leave_stage_state(env, seeded, "killed-run"))
    assert env.run_async(_counts(env, target.document_id))[1] == 1

    deleter = _MinioDeleter()
    env.monkeypatch.setattr(minio_module, "minio_client", deleter)
    result = env.run_task(
        document_tasks.delete_document,
        target.document_id,
        task_id="delete-1",
        organization_id=str(target.organization_id),
    )

    assert result["status"] == "deleted"
    assert deleter.deleted
    assert env.run_async(_counts(env, target.document_id)) == (0, 0)
    # The other organisation's document keeps its stage rows and artifacts.
    stages, artifacts = env.run_async(_counts(env, other.document_id))
    assert stages == 9 and artifacts == 1


def test_delete_removes_stage_rows_and_artifacts(
    ingestion_env: IngestionEnv,  # noqa: F811
) -> None:
    _scenario(ingestion_env)


@pytest.mark.requires_postgres
def test_delete_removes_stage_rows_and_artifacts_on_postgres(
    ingestion_env_pg: IngestionEnv,  # noqa: F811
) -> None:
    _scenario(ingestion_env_pg)
