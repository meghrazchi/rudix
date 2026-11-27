"""Distributed ingestion chain: one task per stage, resume, duplicates, supersession (R06-01).

Celery runs eagerly (``ingestion_chain_support``), so ``documents.process`` and every
``documents.ingest.<stage>`` task execute through their real ``apply_async`` hand-off.
``WorkerKilled`` is a ``BaseException`` like a dying worker process: the stage row stays
``running`` and the message is redelivered with the same task id and kwargs.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from ingestion_chain_support import (
    ALL_STAGES,
    ChainHarness,
    WorkerKilled,
    chain,  # noqa: F401  (fixture)
    state,
)
from ingestion_golden_support import (
    FailingEntityExtraction,
    ingestion_env,  # noqa: F401  (fixture)
)
from sqlalchemy import update

from app.core.config import settings
from app.models.document import Document
from app.models.enums import DocumentStatus
from app.workers import document_reaper_tasks, document_tasks
from app.workers.celery_app import BEAT_SCHEDULE, TASK_ROUTES
from app.workers.ingestion import chain as chain_module
from app.workers.ingestion.chain import CHAIN_ORDER
from app.workers.ingestion.stages import (
    chunk,
    clean_detect,
    dlp,
    extract,
    finalize,
    index,
)
from app.workers.ingestion.stages.base import StageName

STAGE_MODULES = {
    "extract": extract,
    "clean_detect": clean_detect,
    "dlp": dlp,
    "chunk": chunk,
    "index": index,
}


def _arm(chain: ChainHarness, point: str, armed: dict[str, bool]) -> None:  # noqa: F811
    env = chain.env
    if point in STAGE_MODULES:
        module = STAGE_MODULES[point]
        real = module.run

        async def _run(ctx: Any) -> Any:
            outcome = await real(ctx)
            if armed["on"]:
                armed["on"] = False
                raise WorkerKilled(point)
            return outcome

        env.monkeypatch.setattr(module, "run", _run)
    elif point == "embed":

        def _before(call_index: int) -> None:
            if armed["on"] and call_index == 1:
                armed["on"] = False
                raise WorkerKilled("embed")

        env.fakes.embeddings.before_call = _before
    elif point == "finalize_before_commit":
        real_usage = finalize._record_usage

        async def _usage(*args: Any, **kwargs: Any) -> None:
            await real_usage(*args, **kwargs)
            if armed["on"]:
                armed["on"] = False
                raise WorkerKilled("finalize before commit")

        env.monkeypatch.setattr(finalize, "_record_usage", _usage)
    elif point == "finalize_after_commit":
        real_after = finalize.after_commit

        async def _after(ctx: Any) -> None:
            if armed["on"]:
                armed["on"] = False
                raise WorkerKilled("finalize after commit")
            await real_after(ctx)

        env.monkeypatch.setattr(finalize, "after_commit", _after)
    else:  # pragma: no cover - guards the parametrisation
        raise AssertionError(point)


KILL_POINTS = [
    ("extract", StageName.extract),
    ("clean_detect", StageName.clean_detect),
    ("dlp", StageName.dlp),
    ("chunk", StageName.chunk),
    ("embed", StageName.embed),
    ("index", StageName.index),
    ("finalize_before_commit", StageName.finalize),
    ("finalize_after_commit", StageName.finalize),
]


def test_chain_runs_each_stage_as_its_own_task(chain: ChainHarness) -> None:  # noqa: F811
    seeded = chain.env.seed()
    result = chain.process(seeded, chunking_profile_config=PROFILE_CONFIG).get()
    assert result["status"] == DocumentStatus.processing.value
    assert result["stage"] == "extract"
    assert chain.stages() == [str(stage) for stage in CHAIN_ORDER]
    final = chain.env.run_async(state(chain.env, seeded))
    assert final["status"] == DocumentStatus.indexed.value
    assert final["claim"] is None
    assert final["chunk_count"] == 6
    assert final["usage"] == 1 and final["audits"] == 1
    assert final["artifacts"] == 0
    assert final["completed"] == ALL_STAGES
    assert final["runs"] == [result["run_id"]]
    # One pipeline-explorer run spans every stage task.
    assert final["pipeline_runs"] == 1
    assert final["pipeline_events"] > 8
    assert chain.env.fakes.minio.reads == 1
    assert len(chain.env.fakes.embeddings.batches) == 3
    # Every message carried the run identity and the tenant.
    for message in chain.messages:
        assert message.kwargs["run_id"] == result["run_id"]
        assert message.kwargs["claim_token"] == "process-1"
        assert message.kwargs["organization_id"] == str(seeded.organization_id)


def test_stage_routes_use_the_processing_embedding_and_graph_queues() -> None:
    for stage in ("extract", "clean_detect", "dlp", "chunk"):
        route = TASK_ROUTES[f"documents.ingest.{stage}"]
        assert route["queue"] == settings.celery_queue_documents_processing
    for stage in ("embed", "index", "finalize"):
        route = TASK_ROUTES[f"documents.ingest.{stage}"]
        assert route["queue"] == settings.celery_queue_documents_embedding
    assert TASK_ROUTES["documents.graph_extract"]["queue"] == settings.celery_queue_documents_graph


PROFILE_CONFIG = {"strategy": "token_recursive", "chunk_size_tokens": 25, "chunk_overlap_tokens": 5}


@pytest.mark.parametrize(("point", "stage"), KILL_POINTS)
def test_killed_stage_resumes_on_redelivery_without_duplicates(
    chain: ChainHarness,  # noqa: F811
    point: str,
    stage: StageName,
) -> None:
    seeded = chain.env.seed()
    armed = {"on": True}
    _arm(chain, point, armed)
    with pytest.raises(WorkerKilled):
        chain.process(seeded, chunking_profile_config=PROFILE_CONFIG)
    assert armed["on"] is False
    killed = chain.last(stage)
    killed_state = chain.env.run_async(state(chain.env, seeded))
    committed = point == "finalize_after_commit"
    assert (killed_state["status"] == DocumentStatus.indexed.value) is committed
    batches_before = len(chain.env.fakes.embeddings.batches)

    chain.redeliver(killed)
    final = chain.env.run_async(state(chain.env, seeded))
    assert final["status"] == DocumentStatus.indexed.value
    assert final["claim"] is None
    assert final["chunk_count"] == 6
    assert final["usage"] == 1
    assert final["audits"] == 1
    assert final["artifacts"] == 0
    assert final["completed"] == ALL_STAGES
    assert len(final["runs"]) == 1
    # The redelivered stage resumed: OCR/extraction ran again only when extract was killed.
    assert chain.env.fakes.minio.reads == (2 if point == "extract" else 1)
    embedded = [cid for batch in chain.env.fakes.embeddings.batches for cid in batch]
    assert len(embedded) == len(set(embedded)) == 6
    if point == "embed":
        # Killed while embedding batch 2 of 3: batch 1 is not embedded again.
        assert batches_before == 1
    if point in ("index", "finalize_before_commit", "finalize_after_commit"):
        assert len(chain.env.fakes.embeddings.batches) == batches_before
    assert chain.env.fakes.qdrant.points == final["point_ids"]
    assert final["pipeline_runs"] == 1


def test_every_stage_message_delivered_twice_is_a_no_op(chain: ChainHarness) -> None:  # noqa: F811
    seeded = chain.env.seed()
    chain.process(seeded, chunking_profile_config=PROFILE_CONFIG)
    first = chain.env.run_async(state(chain.env, seeded))
    reads = chain.env.fakes.minio.reads
    batches = len(chain.env.fakes.embeddings.batches)
    upserts = len(chain.env.fakes.qdrant.upserts)
    originals = list(chain.messages)
    for number, message in enumerate(originals):
        # A second copy of the message (another delivery id) after the run finished.
        chain.redeliver(message, task_id=f"duplicate-{number}")
    again = chain.env.run_async(state(chain.env, seeded))
    for key in ("status", "chunk_count", "point_ids", "usage", "audits", "completed", "runs"):
        assert again[key] == first[key], key
    assert chain.env.fakes.minio.reads == reads
    assert len(chain.env.fakes.embeddings.batches) == batches
    assert len(chain.env.fakes.qdrant.upserts) == upserts


def test_duplicate_message_while_the_stage_runs_returns_lease_held(
    chain: ChainHarness,  # noqa: F811
) -> None:
    seeded = chain.env.seed()
    armed = {"on": True}
    _arm(chain, "embed", armed)
    with pytest.raises(WorkerKilled):
        chain.process(seeded, chunking_profile_config=PROFILE_CONFIG)
    killed = chain.last(StageName.embed)
    # Another copy (other delivery id) while the killed one's lease is still fresh.
    duplicate = chain.redeliver(killed, task_id="other-delivery").get()
    assert duplicate["status"] == "lease_held"
    assert chain.env.run_async(state(chain.env, seeded))["status"] == "processing"
    chain.redeliver(killed)
    assert chain.env.run_async(state(chain.env, seeded))["status"] == DocumentStatus.indexed.value


def test_superseded_claim_token_stops_the_old_chain(chain: ChainHarness) -> None:  # noqa: F811
    seeded = chain.env.seed()
    armed = {"on": True}
    _arm(chain, "chunk", armed)
    with pytest.raises(WorkerKilled):
        chain.process(seeded, chunking_profile_config=PROFILE_CONFIG)

    async def _take_over() -> None:
        async with chain.env.factory() as session, session.begin():
            await session.execute(
                update(Document)
                .where(Document.id == seeded.document_id)
                .values(processing_task_id="newer-claim")
            )

    chain.env.run_async(_take_over())
    result = chain.redeliver(chain.last(StageName.chunk)).get()
    assert result["status"] == "superseded"
    final = chain.env.run_async(state(chain.env, seeded))
    assert final["status"] == DocumentStatus.processing.value
    assert final["claim"] == "newer-claim"
    assert final["usage"] == 0
    assert StageName.embed not in chain.stages()


def test_graph_failure_leaves_the_document_indexed(chain: ChainHarness) -> None:  # noqa: F811
    env = chain.env
    env.monkeypatch.setattr(settings, "enterprise_graph_enabled", True)
    env.monkeypatch.setattr(settings, "feature_enable_entity_extraction", True)
    env.monkeypatch.setattr(settings, "entity_extraction_strict_mode", True)
    env.monkeypatch.setattr(document_tasks, "_entity_extraction_service", FailingEntityExtraction())
    seeded = env.seed()
    chain.process(seeded, chunking_profile_config=PROFILE_CONFIG)
    final = env.run_async(state(env, seeded))
    assert final["status"] == DocumentStatus.indexed.value
    assert final["completed"] == ALL_STAGES
    graph = final["stage_metrics"][StageName.graph_extract]
    assert graph["graph_status"] == "failed"
    assert graph["error_code"] == "ENTITY_EXTRACTION_FAILED"
    assert final["failed_jobs"] == []
    assert chain.stages()[-1] == "graph_extract"


def test_failed_stage_records_a_resumable_failed_job(chain: ChainHarness) -> None:  # noqa: F811
    env = chain.env
    seeded = env.seed()

    def _fail(call_index: int) -> None:
        if call_index == 1:
            from app.domains.documents.services.embedding_service import (
                PermanentEmbeddingError,
            )

            raise PermanentEmbeddingError("provider rejected the input")

    env.fakes.embeddings.before_call = _fail
    chain.process(seeded, chunking_profile_config=PROFILE_CONFIG)
    failed = env.run_async(state(env, seeded))
    assert failed["status"] == DocumentStatus.failed.value
    assert len(failed["failed_jobs"]) == 1
    task_name, metadata, job_id = failed["failed_jobs"][0]
    assert task_name == "documents.process"
    assert metadata == {"stage": "embed", "run_id": failed["runs"][0]}

    # Dashboard retry (F156 _dispatch_retry): documents.process with job_id resumes the run.
    env.fakes.embeddings.before_call = None
    reads = env.fakes.minio.reads
    result = chain.process(
        seeded,
        task_id="dashboard-retry",
        job_id=str(job_id),
        chunking_profile_config=PROFILE_CONFIG,
    ).get()
    assert result["run_id"] == failed["runs"][0]
    assert result["stage"] == "embed"
    final = env.run_async(state(env, seeded))
    assert final["status"] == DocumentStatus.indexed.value
    assert env.fakes.minio.reads == reads
    assert final["usage"] == 1


def test_reaper_resume_reuses_the_run(chain: ChainHarness) -> None:  # noqa: F811
    env = chain.env
    seeded = env.seed()
    armed = {"on": True}
    _arm(chain, "embed", armed)
    with pytest.raises(WorkerKilled):
        chain.process(seeded, chunking_profile_config=PROFILE_CONFIG)
    run_id = chain.last(StageName.embed).kwargs["run_id"]
    # The stale lease of the dead worker expires before the reaper re-queues.
    env.monkeypatch.setattr(settings, "ingest_stage_lease_seconds", 10)

    async def _age_lease() -> None:
        from datetime import UTC, datetime, timedelta

        from app.models.document_processing import DocumentProcessingStage

        async with env.factory() as session, session.begin():
            await session.execute(
                update(DocumentProcessingStage)
                .where(DocumentProcessingStage.document_id == seeded.document_id)
                .values(heartbeat_at=datetime.now(UTC) - timedelta(hours=1))
            )
            # The reaper releases the claim before re-queueing.
            await session.execute(
                update(Document)
                .where(Document.id == seeded.document_id)
                .values(processing_task_id=None, status="uploaded")
            )

    env.run_async(_age_lease())
    result = chain.process(
        seeded,
        task_id="reaped-requeue",
        resume_run_id=run_id,
        chunking_profile_config=PROFILE_CONFIG,
    ).get()
    assert result["run_id"] == run_id
    assert result["stage"] == "embed"
    final = env.run_async(state(env, seeded))
    assert final["status"] == DocumentStatus.indexed.value
    assert final["runs"] == [run_id]
    # Extraction (and OCR) ran once for the whole document.
    assert env.fakes.minio.reads == 1
    assert final["usage"] == 1


def test_redelivered_process_message_reaches_the_same_run(chain: ChainHarness) -> None:  # noqa: F811
    seeded = chain.env.seed()
    first = chain.process(seeded, chunking_profile_config=PROFILE_CONFIG).get()
    assert first["run_id"] == chain_module.fresh_run_id(str(seeded.document_id), "process-1")
    again = chain.process(seeded, chunking_profile_config=PROFILE_CONFIG).get()
    assert again["status"] == "skipped"
    assert chain.env.run_async(state(chain.env, seeded))["usage"] == 1


def test_resume_of_a_finished_run_starts_a_new_run(chain: ChainHarness) -> None:  # noqa: F811
    seeded = chain.env.seed()
    first = chain.process(seeded, chunking_profile_config=PROFILE_CONFIG).get()
    result = document_tasks.reindex_document.apply(
        args=[str(seeded.document_id)],
        kwargs={
            "organization_id": str(seeded.organization_id),
            "resume_run_id": first["run_id"],
            "chunking_profile_config": PROFILE_CONFIG,
        },
        task_id="reindex-1",
    ).get()
    assert result["run_id"] != first["run_id"]
    assert result["status"] == DocumentStatus.processing.value
    final = chain.env.run_async(state(chain.env, seeded))
    assert final["status"] == DocumentStatus.indexed.value
    assert final["runs"] == [result["run_id"]]


# ── reaper resume, artifact purge, inline mode ────────────────────────────────────────


def _maintenance(env: Any) -> Any:
    @asynccontextmanager
    async def _session() -> AsyncIterator[Any]:
        async with env.factory() as session:
            yield session

    return _session


def test_reaper_requeues_with_the_latest_unfinished_run(chain: ChainHarness) -> None:  # noqa: F811
    env = chain.env
    seeded = env.seed()
    armed = {"on": True}
    _arm(chain, "embed", armed)
    with pytest.raises(WorkerKilled):
        chain.process(seeded, chunking_profile_config=PROFILE_CONFIG)
    run_id = chain.last(StageName.embed).kwargs["run_id"]
    env.monkeypatch.setattr(document_reaper_tasks, "maintenance_session", _maintenance(env))
    sent: list[dict[str, Any]] = []
    env.monkeypatch.setattr(
        document_reaper_tasks.celery_app, "send_task", lambda name, **kw: sent.append(kw)
    )

    async def _stale() -> None:
        async with env.factory() as session, session.begin():
            await session.execute(
                update(Document)
                .where(Document.id == seeded.document_id)
                .values(processing_started_at=datetime.now(UTC) - timedelta(days=1))
            )

    env.run_async(_stale())
    counts = env.run_async(document_reaper_tasks._reap_stale_documents_async())
    assert counts["requeued"] == 1
    assert sent[0]["kwargs"]["resume_run_id"] == run_id
    assert sent[0]["kwargs"]["organization_id"] == str(seeded.organization_id)


def test_stage_artifact_purge_keeps_processing_documents(chain: ChainHarness) -> None:  # noqa: F811
    env = chain.env
    stuck = env.seed()
    abandoned = env.seed()
    for seeded in (stuck, abandoned):
        armed = {"on": True}
        _arm(chain, "dlp", armed)
        with pytest.raises(WorkerKilled):
            chain.process(
                seeded, task_id=f"p-{seeded.document_id}", chunking_profile_config=PROFILE_CONFIG
            )

    async def _abandon() -> None:
        async with env.factory() as session, session.begin():
            await session.execute(
                update(Document)
                .where(Document.id == abandoned.document_id)
                .values(status=DocumentStatus.failed.value, processing_task_id=None)
            )

    env.run_async(_abandon())
    env.monkeypatch.setattr(document_reaper_tasks, "maintenance_session", _maintenance(env))
    later = datetime.now(UTC) + timedelta(hours=settings.ingest_stage_artifact_ttl_hours + 1)
    result = env.run_async(document_reaper_tasks._purge_stage_artifacts_async(later))
    assert result["deleted"] > 0
    assert env.run_async(state(env, abandoned))["artifacts"] == 0
    assert env.run_async(state(env, stuck))["artifacts"] > 0
    # Nothing is older than the TTL now.
    assert env.run_async(document_reaper_tasks._purge_stage_artifacts_async())["deleted"] == 0


def test_purge_task_is_scheduled_daily_and_runs_its_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry = BEAT_SCHEDULE["documents-stage-artifacts-purge"]
    assert entry["task"] == "documents.stage_artifacts.purge"
    route = TASK_ROUTES["documents.stage_artifacts.purge"]
    assert route["queue"] == settings.celery_task_default_queue

    async def _purge() -> dict[str, int]:
        return {"deleted": 0}

    monkeypatch.setattr(document_reaper_tasks, "_purge_stage_artifacts_async", _purge)
    assert document_reaper_tasks.purge_stage_artifacts.run() == {"deleted": 0}


TEXT_FOR_INLINE = "Policy text. " * 40


def test_inline_mode_resumes_a_given_run(ingestion_env: Any) -> None:  # noqa: F811
    env = ingestion_env
    env.set_content(TEXT_FOR_INLINE.encode())
    seeded = env.seed()
    armed = {"on": True}
    real = chunk.run

    async def _run(ctx: Any) -> Any:
        outcome = await real(ctx)
        if armed["on"]:
            armed["on"] = False
            raise WorkerKilled("chunk")
        return outcome

    env.monkeypatch.setattr(chunk, "run", _run)
    ids = {"organization_id": str(seeded.organization_id), "user_id": str(seeded.user_id)}
    with pytest.raises(WorkerKilled):
        env.run_task(document_tasks.process_document, seeded.document_id, task_id="first", **ids)

    async def _release() -> None:
        from app.models.document_processing import DocumentProcessingStage

        async with env.factory() as session, session.begin():
            # Reaped: the dead worker's stage heartbeat is as old as the document's.
            await session.execute(
                update(DocumentProcessingStage)
                .where(DocumentProcessingStage.document_id == seeded.document_id)
                .values(heartbeat_at=datetime.now(UTC) - timedelta(hours=2))
            )
            await session.execute(
                update(Document)
                .where(Document.id == seeded.document_id)
                .values(processing_task_id=None, status="uploaded")
            )

    env.run_async(_release())
    result = env.run_task(
        document_tasks.process_document,
        seeded.document_id,
        task_id="second",
        resume_run_id="first",
        **ids,
    )
    assert result["status"] == DocumentStatus.indexed.value
    assert env.fakes.minio.reads == 1
    assert env.run_async(state(env, seeded))["runs"] == ["first"]


def test_duplicate_outbox_publication_is_harmless(ingestion_env: Any) -> None:  # noqa: F811
    env = ingestion_env
    env.set_content(TEXT_FOR_INLINE.encode())
    seeded = env.seed()
    ids = {"organization_id": str(seeded.organization_id), "user_id": str(seeded.user_id)}
    first = env.run_task(document_tasks.process_document, seeded.document_id, task_id="a", **ids)
    # The relay published the same row again (the mark was lost): the claim is held.
    again = env.run_task(document_tasks.process_document, seeded.document_id, task_id="b", **ids)
    assert first["status"] == DocumentStatus.indexed.value
    assert again["status"] == "skipped"
    final = env.run_async(state(env, seeded))
    assert final["usage"] == 1 and final["audits"] == 1


def test_dispatch_publishes_with_apply_async_and_wraps_publish_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.workers.base_task import TransientTaskError
    from app.workers.ingestion import dispatch

    calls: list[dict[str, Any]] = []

    class _Task:
        name = "documents.ingest.embed"
        fail = False

        def apply_async(self, *, kwargs: dict[str, Any]) -> str:
            if self.fail:
                raise ConnectionError("broker down")
            calls.append(kwargs)
            return "sent"

    fake = _Task()
    monkeypatch.setattr(dispatch, "stage_task", lambda stage: fake)
    assert dispatch.celery_app_eager() is False
    message = {"document_id": "d", "organization_id": "o", "run_id": "r"}
    assert dispatch.dispatch_stage(StageName.embed, message) == "sent"
    assert calls == [message]
    fake.fail = True
    with pytest.raises(TransientTaskError):
        dispatch.dispatch_stage(StageName.embed, message)
    # The real lookup returns the registered stage task.
    monkeypatch.undo()
    assert dispatch.stage_task(StageName.embed).name == "documents.ingest.embed"


def test_failed_job_run_lookup_ignores_bad_ids_and_other_organizations(
    ingestion_env: Any,  # noqa: F811
) -> None:
    from uuid import uuid4

    from app.models.failed_job import FailedJob

    env = ingestion_env
    seeded = env.seed()
    job_id = uuid4()

    async def _seed_job() -> None:
        async with env.factory() as session, session.begin():
            session.add(
                FailedJob(
                    id=job_id,
                    organization_id=seeded.organization_id,
                    task_id="t",
                    task_name="documents.process",
                    job_type="extraction",
                    status="failed",
                    error_code="X",
                    error_message="x",
                    attempt_count=1,
                    is_retryable=True,
                    metadata_json={"stage": "embed", "run_id": "run-9"},
                )
            )

    env.run_async(_seed_job())
    lookup = chain_module.run_id_from_failed_job
    assert env.run_async(lookup(str(job_id), str(seeded.organization_id))) == "run-9"
    assert env.run_async(lookup(str(job_id), str(uuid4()))) is None
    assert env.run_async(lookup("not-a-uuid", None)) is None
    assert env.run_async(lookup(str(uuid4()), None)) is None
    # A finished or unknown run is not resumed; inline mode then uses the claim's id.
    run_id, resumed = env.run_async(
        chain_module.resolve_run_id(
            str(seeded.document_id),
            claim_token="claim",
            resume_run_id=None,
            job_id=str(job_id),
            organization_id=str(seeded.organization_id),
            chain=False,
        )
    )
    assert (run_id, resumed) == ("claim", False)
    assert chain_module.first_incomplete({str(s) for s in CHAIN_ORDER}) is None
