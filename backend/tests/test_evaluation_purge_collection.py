"""The eval-version purge scans and purges QDRANT_EVALUATION_COLLECTION too (R06-12)."""

from __future__ import annotations

from typing import Any

import pytest
from qdrant_client.http.exceptions import UnexpectedResponse
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from test_purge_eval_index_versions import (
    FakeQdrantClient,
    _by_key,
    _load_script,
    _Point,
    _seed,
)

from app.core.config import settings
from app.domains.evaluations.services.eval_index_purge_service import EvalIndexPurgeService

EVAL = "rudix_eval_vectors"


class MultiCollectionClient:
    """One FakeQdrantClient per collection; a missing collection answers 404 (or ``status``)."""

    def __init__(self, collections: dict[str, FakeQdrantClient], *, status: int = 404) -> None:
        self.collections = collections
        self.status = status
        self.scrolled: list[str] = []
        self.deleted_from: list[str] = []

    def _get(self, name: str) -> FakeQdrantClient:
        if name not in self.collections:
            raise UnexpectedResponse(self.status, "Not Found", b"", None)  # type: ignore[arg-type]
        return self.collections[name]

    def scroll(self, **kwargs: Any) -> Any:
        self.scrolled.append(kwargs["collection_name"])
        return self._get(kwargs["collection_name"]).scroll(**kwargs)

    def delete(self, **kwargs: Any) -> None:
        self.deleted_from.append(kwargs["collection_name"])
        self._get(kwargs["collection_name"]).delete(**kwargs)


def _eval_points(seeded: dict[str, Any], version: str, count: int) -> list[_Point]:
    return [
        _Point(
            id=f"eval-collection:{version}:{index}",
            payload={
                "organization_id": str(seeded["org_a"]),
                "document_id": str(seeded["doc_a"]),
                "index_version": version,
            },
        )
        for index in range(count)
    ]


@pytest.mark.asyncio
async def test_apply_purges_eval_points_from_both_collections(db_session: AsyncSession) -> None:
    seeded = await _seed(db_session)
    stale = seeded["stale_version"]
    running = seeded["running_version"]
    eval_client = FakeQdrantClient(
        points=_eval_points(seeded, stale, 2) + _eval_points(seeded, running, 1)
    )
    client = MultiCollectionClient(
        {settings.qdrant_collection: seeded["qdrant"], EVAL: eval_client}
    )
    service = EvalIndexPurgeService(
        qdrant_client=client,
        collection=settings.qdrant_collection,
        batch_size=2,
        evaluation_collection=EVAL,
    )

    report = await service.run(db_session, apply=True)

    rows = _by_key(report)
    org_a = str(seeded["org_a"])
    # Three legacy points in production plus two in the evaluation collection.
    assert rows[(org_a, stale)].point_count == 5
    assert rows[(org_a, stale)].points_deleted == 5
    assert set(client.deleted_from) == {settings.qdrant_collection, EVAL}
    left = {p.payload["index_version"] for p in eval_client.points}
    assert left == {running}  # an in-progress run's points are never purged
    assert set(client.scrolled) == {settings.qdrant_collection, EVAL}


@pytest.mark.asyncio
async def test_missing_eval_collection_is_empty_and_other_errors_raise(
    db_session: AsyncSession,
) -> None:
    seeded = await _seed(db_session)
    client = MultiCollectionClient({settings.qdrant_collection: seeded["qdrant"]})
    report = await EvalIndexPurgeService(
        qdrant_client=client, batch_size=10, evaluation_collection=EVAL
    ).run(db_session, apply=False)
    assert report.versions
    assert EVAL in client.scrolled

    failing = MultiCollectionClient({settings.qdrant_collection: seeded["qdrant"]}, status=500)
    with pytest.raises(UnexpectedResponse):
        await EvalIndexPurgeService(
            qdrant_client=failing, batch_size=10, evaluation_collection=EVAL
        ).run(db_session, apply=False)

    # The production collection is never treated as optional.
    missing_production = MultiCollectionClient({EVAL: FakeQdrantClient()})
    with pytest.raises(UnexpectedResponse):
        await EvalIndexPurgeService(
            qdrant_client=missing_production, batch_size=10, evaluation_collection=EVAL
        ).run(db_session, apply=False)


def test_same_collection_is_scanned_once() -> None:
    service = EvalIndexPurgeService(
        qdrant_client=None, collection="documents", evaluation_collection="documents"
    )
    assert service._collections == ["documents"]


@pytest.mark.asyncio
async def test_script_honours_the_evaluation_collection(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seeded = await _seed(db_session)
    eval_client = FakeQdrantClient(points=_eval_points(seeded, seeded["stale_version"], 2))
    client = MultiCollectionClient(
        {settings.qdrant_collection: seeded["qdrant"], EVAL: eval_client}
    )
    script = _load_script()
    factory = async_sessionmaker(bind=db_session.bind, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(script, "SessionLocal", factory)
    monkeypatch.setattr(script, "create_qdrant_client", lambda config: client)
    monkeypatch.setattr(settings, "qdrant_evaluation_collection", EVAL)

    await script.run(["--apply", "--organization-id", str(seeded["org_a"])])

    assert eval_client.points == []
    assert EVAL in client.deleted_from
    assert "private document text" not in capsys.readouterr().out
