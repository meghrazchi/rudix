"""Batched Neo4j writes and bounded extraction concurrency (R06-10).

No Neo4j: a fake driver runs every ``execute_write`` function against a fake transaction,
counts the write transactions, and keeps a MERGE-keyed store so reruns can be checked
for duplicates (the same approach as ``tests/test_graph_repository_f281.py``, with the
transaction functions actually executed).
"""

from __future__ import annotations

import asyncio
import json
import math
import re
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest

import app.clients.neo4j_client as neo4j_module
from app.core.config import settings
from app.core.metrics_workers import GRAPH_WRITE_BATCHES_TOTAL
from app.domains.ai.providers.factory import default_provider_factory
from app.domains.graph.repositories import entity_batch, fact_batch
from app.domains.graph.repositories.batch_writes import (
    AliasWriteRow,
    EntityWriteRow,
    EvidenceWriteRow,
    RelationWriteRow,
    split_rows,
)
from app.domains.graph.repositories.entity_repository import EntityRepository
from app.domains.graph.repositories.evidence_repository import EvidenceRepository
from app.domains.graph.repositories.relation_repository import RelationRepository
from app.domains.graph.services.bounded_batches import gather_in_order
from app.domains.graph.services.entity_extraction_service import EntityExtractionService
from app.domains.graph.services.graph_service import GraphService
from app.domains.graph.services.relation_extraction_service import RelationExtractionService
from app.workers import document_tasks

# ---------------------------------------------------------------------------
# Fake driver
# ---------------------------------------------------------------------------


def _kind(cypher: str) -> str:
    if cypher == entity_batch.UPSERT_ENTITIES_CYPHER:
        return "entity"
    if cypher == entity_batch.UPSERT_ALIASES_CYPHER:
        return "alias"
    if cypher == fact_batch.LINK_EVIDENCE_CYPHER:
        return "evidence"
    if cypher.lstrip().startswith("UNWIND $rows AS row\nMATCH (a:Entity"):
        return "relation"
    return "other"


def _merge_key(kind: str, org: str, row: dict[str, Any]) -> tuple[Any, ...]:
    if kind == "entity":
        return ("Entity", org, row["entity_id"])
    if kind == "alias":
        return ("EntityAlias", org, row["alias_id"])
    if kind == "evidence":
        return ("EVIDENCE_FOR", org, row["chunk_id"], row["entity_id"])
    return (row["rel_type"], org, row["from_entity_id"], row["to_entity_id"])


@dataclass
class FakeDriver:
    fail_transactions: set[int] = field(default_factory=set)
    transactions: list[list[tuple[str, dict[str, Any]]]] = field(default_factory=list)
    store: dict[tuple[Any, ...], dict[str, Any]] = field(default_factory=dict)

    def session(self, **_: Any) -> FakeSession:
        return FakeSession(self)

    def write_transactions(self, kind: str) -> int:
        return sum(1 for tx in self.transactions if tx and _kind(tx[0][0]) == kind)


class FakeTx:
    def __init__(self) -> None:
        self.runs: list[tuple[str, dict[str, Any]]] = []

    async def run(self, cypher: str, **params: Any) -> Any:
        self.runs.append((cypher, params))
        result = SimpleNamespace()

        async def _none() -> None:
            return None

        async def _empty() -> list[Any]:
            return []

        result.single = _none
        result.data = _empty
        result.consume = _none
        return result


class FakeSession:
    def __init__(self, driver: FakeDriver) -> None:
        self.driver = driver

    async def __aenter__(self) -> FakeSession:
        return self

    async def __aexit__(self, *_: Any) -> bool:
        return False

    async def execute_write(self, fn: Any) -> Any:
        index = len(self.driver.transactions)
        tx = FakeTx()
        self.driver.transactions.append(tx.runs)
        if index in self.driver.fail_transactions:
            raise RuntimeError("neo4j unavailable")
        result = await fn(tx)
        # Commit: apply MERGE semantics to the store.
        for cypher, params in tx.runs:
            kind = _kind(cypher)
            if kind == "other":
                continue
            for row in params["rows"]:
                key = _merge_key(kind, params["organization_id"], row)
                self.driver.store[key] = {"organization_id": params["organization_id"], **row}
        return result

    async def execute_read(self, fn: Any) -> Any:
        return await fn(FakeTx())


@pytest.fixture
def driver(monkeypatch: pytest.MonkeyPatch) -> FakeDriver:
    fake = FakeDriver()
    monkeypatch.setattr(settings, "enterprise_graph_enabled", True)
    monkeypatch.setattr(settings, "neo4j_database", "neo4j")
    monkeypatch.setattr(settings, "graph_write_batch_size", 3)
    monkeypatch.setattr(neo4j_module, "_neo4j_driver", fake)
    return fake


# ---------------------------------------------------------------------------
# Cypher contract
# ---------------------------------------------------------------------------


_NODE_PATTERN = re.compile(r"(?:MERGE|MATCH) \((\w+):(\w+) \{([^}]*)\}\)")


@pytest.mark.parametrize(
    "cypher",
    [
        entity_batch.UPSERT_ENTITIES_CYPHER,
        entity_batch.UPSERT_ALIASES_CYPHER,
        fact_batch.LINK_EVIDENCE_CYPHER,
        fact_batch.relation_cypher("RELATES_TO"),
    ],
)
def test_every_node_and_relationship_is_scoped_to_the_organisation(cypher: str) -> None:
    assert cypher.lstrip().startswith("UNWIND $rows AS row")
    nodes = _NODE_PATTERN.findall(cypher)
    assert nodes, cypher
    for _var, _label, keys in nodes:
        assert "organization_id: $organization_id" in keys
    # Relationships either carry organization_id in their MERGE key or get it set.
    for variable in re.findall(r"MERGE \(\w+\)-\[(\w+):\w+", cypher):
        assert (
            re.search(rf"{variable}\.organization_id\s*=\s*\$organization_id", cypher)
            or "{organization_id: $organization_id" in cypher.split(f"[{variable}:", 1)[1][:80]
        ), variable
    assert "$organization_id" in cypher and "row.organization_id" not in cypher


def test_relation_cypher_rejects_unknown_types() -> None:
    with pytest.raises(ValueError, match="Unknown relationship type"):
        fact_batch.relation_cypher("DROP_ALL")


def test_split_rows() -> None:
    rows = [{"i": i} for i in range(7)]
    assert [len(batch) for batch in split_rows(rows, 3)] == [3, 3, 1]
    assert split_rows([], 3) == []


# ---------------------------------------------------------------------------
# Repository batches
# ---------------------------------------------------------------------------


def _entity_rows(count: int, *, prefix: str = "e") -> list[EntityWriteRow]:
    return [
        EntityWriteRow(
            entity_id=f"{prefix}-{index}",
            entity_type="policy",
            canonical_name=f"Policy {index}",
            normalized_name=f"policy {index}",
            aliases=[f"P{index}"],
            extra={"language": "en"},
        )
        for index in range(count)
    ]


async def test_entity_batches_use_one_transaction_per_batch(
    driver: FakeDriver, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "metrics_enabled", True)
    before = GRAPH_WRITE_BATCHES_TOTAL.labels(kind="entity", outcome="written")._value.get()
    org = str(uuid4())
    written = await EntityRepository().upsert_entities_batch(
        organization_id=org, rows=_entity_rows(7)
    )
    assert written == 3 == driver.write_transactions("entity")
    sizes = [len(tx[0][1]["rows"]) for tx in driver.transactions]
    assert sizes == [3, 3, 1]
    assert all(tx[0][1]["organization_id"] == org for tx in driver.transactions)
    after = GRAPH_WRITE_BATCHES_TOTAL.labels(kind="entity", outcome="written")._value.get()
    assert after - before == 3


async def test_a_failed_batch_is_logged_and_the_rest_are_written(
    driver: FakeDriver, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "metrics_enabled", True)
    before = GRAPH_WRITE_BATCHES_TOTAL.labels(kind="alias", outcome="failed")._value.get()
    driver.fail_transactions = {1}
    rows = [
        AliasWriteRow(
            entity_id=f"e-{i}", alias_id=f"a-{i}", alias_name=f"A{i}", normalized_name=f"a{i}"
        )
        for i in range(7)
    ]
    written = await EntityRepository().upsert_entity_aliases_batch(
        organization_id=uuid4(), rows=rows
    )
    assert written == 2 and len(driver.transactions) == 3
    after = GRAPH_WRITE_BATCHES_TOTAL.labels(kind="alias", outcome="failed")._value.get()
    assert after - before == 1


async def test_session_errors_never_escape(monkeypatch: pytest.MonkeyPatch) -> None:
    class _BrokenDriver:
        def session(self, **_: Any) -> Any:
            raise RuntimeError("connection refused")

    monkeypatch.setattr(settings, "enterprise_graph_enabled", True)
    monkeypatch.setattr(neo4j_module, "_neo4j_driver", _BrokenDriver())
    written = await EvidenceRepository().link_evidence_batch(
        organization_id=uuid4(),
        rows=[
            EvidenceWriteRow(entity_id="e", chunk_id="c", source_document_id="d", citation_text="t")
        ],
    )
    assert written == 0


async def test_empty_batches_open_no_session(driver: FakeDriver) -> None:
    assert await EntityRepository().upsert_entities_batch(organization_id=uuid4(), rows=[]) == 0
    assert driver.transactions == []


async def test_batches_are_noops_without_a_driver(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "enterprise_graph_enabled", True)
    monkeypatch.setattr(neo4j_module, "_neo4j_driver", None)
    assert (
        await EntityRepository().upsert_entities_batch(
            organization_id=uuid4(), rows=_entity_rows(2)
        )
        == 0
    )


async def test_evidence_and_relation_validation_happens_before_any_write(
    driver: FakeDriver,
) -> None:
    org = uuid4()
    good = EvidenceWriteRow(entity_id="e", chunk_id="c", source_document_id="d", citation_text="t")
    bare = EvidenceWriteRow(entity_id="e2", chunk_id="c2", source_document_id="d")
    with pytest.raises(ValueError, match="provenance_required"):
        await EvidenceRepository().link_evidence_batch(organization_id=org, rows=[good, bare])
    relation = RelationWriteRow(
        from_entity_id="a",
        to_entity_id="b",
        rel_type="RELATES_TO",
        relation_id="r",
        citation_text="t",
    )
    for bad in (
        RelationWriteRow(**{**relation.__dict__, "rel_type": "NOPE"}),
        RelationWriteRow(**{**relation.__dict__, "initial_status": "approved"}),
        RelationWriteRow(**{**relation.__dict__, "citation_text": None}),
    ):
        with pytest.raises(ValueError):
            await RelationRepository().create_relations_with_evidence_batch(
                organization_id=org, rows=[relation, bad]
            )
    assert driver.transactions == []


async def test_relation_batches_group_types_inside_one_transaction(driver: FakeDriver) -> None:
    rows = [
        RelationWriteRow(
            from_entity_id=f"a{i}",
            to_entity_id=f"b{i}",
            rel_type="RELATES_TO" if i % 2 else "DEPENDS_ON",
            relation_id=f"r{i}",
            citation_text="evidence",
            confidence=0.7,
        )
        for i in range(3)
    ]
    written = await RelationRepository().create_relations_with_evidence_batch(
        organization_id=uuid4(), rows=rows
    )
    assert written == 1 and len(driver.transactions) == 1
    statements = driver.transactions[0]
    assert len(statements) == 2  # one UNWIND per relationship type
    assert {":DEPENDS_ON {" in c for c, _ in statements} == {True, False}
    assert all(p["rows"][0]["status"] == "unverified" for _, p in statements)


async def test_graph_service_wrappers_are_noops_when_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "enterprise_graph_enabled", False)
    service = GraphService()
    org = uuid4()
    assert await service.upsert_entities_batch(organization_id=org, rows=_entity_rows(1)) == 0
    alias = AliasWriteRow(entity_id="e", alias_id="a", alias_name="A", normalized_name="a")
    assert await service.upsert_entity_aliases_batch(organization_id=org, rows=[alias]) == 0
    evidence = EvidenceWriteRow(
        entity_id="e", chunk_id="c", source_document_id="d", citation_text="t"
    )
    assert await service.link_evidence_batch(organization_id=org, rows=[evidence]) == 0
    relation = RelationWriteRow(
        from_entity_id="a",
        to_entity_id="b",
        rel_type="RELATES_TO",
        relation_id="r",
        citation_text="t",
    )
    assert (
        await service.create_relations_with_evidence_batch(organization_id=org, rows=[relation])
        == 0
    )


async def test_graph_service_wrappers_delegate_when_available(driver: FakeDriver) -> None:
    service = GraphService()
    org = uuid4()
    assert await service.upsert_entities_batch(organization_id=org, rows=_entity_rows(4)) == 2
    assert await service.upsert_entities_batch(organization_id=org, rows=[]) == 0


# ---------------------------------------------------------------------------
# Worker: one transaction per batch per kind, idempotent, tenant-scoped
# ---------------------------------------------------------------------------


def _extraction_fakes(entity_count: int, relation_count: int, org_id: UUID) -> tuple[Any, Any]:
    entity_ids = [uuid4() for _ in range(entity_count)]

    async def _extract_entities(**_: Any) -> Any:
        return SimpleNamespace(
            entities=[
                SimpleNamespace(
                    entity_id=entity_ids[i],
                    type="policy",
                    name=f"Entity {i}",
                    original_name=f"Entity {i}",
                    aliases=[f"E{i}"],
                    language="en",
                    confidence=0.9,
                    evidence_span=f"Entity {i} is mentioned.",
                    source_chunk_index=i % 3,
                )
                for i in range(entity_count)
            ],
            batch_count=1,
            total_chunks=3,
            validation_errors=0,
            llm_errors=0,
        )

    async def _extract_relations(**_: Any) -> Any:
        return SimpleNamespace(
            relations=[
                SimpleNamespace(
                    relation_id=uuid4(),
                    from_entity_id=entity_ids[i],
                    to_entity_id=entity_ids[(i + 1) % entity_count],
                    rel_type="RELATES_TO",
                    confidence=0.8,
                    evidence_span="related",
                    source_chunk_index=i % 3,
                )
                for i in range(relation_count)
            ],
            batch_count=1,
            skipped_unknown_entity=0,
            validation_errors=0,
            llm_errors=0,
        )

    return _extract_entities, _extract_relations


async def _run_document(monkeypatch: pytest.MonkeyPatch, document: Any, fakes: Any) -> Any:
    extract_entities, extract_relations = fakes

    async def _status(*_: Any, **__: Any) -> None:
        return None

    async def _noop(**_: Any) -> None:
        return None

    monkeypatch.setattr(settings, "feature_enable_entity_extraction", True)
    monkeypatch.setattr(settings, "feature_enable_relation_extraction", True)
    monkeypatch.setattr(settings, "feature_enable_entity_resolution", False)
    monkeypatch.setattr(document_tasks, "_update_document_graph_status_async", _status)
    graph = GraphService()
    monkeypatch.setattr(graph, "start_extraction_run", _noop)
    monkeypatch.setattr(graph, "finish_extraction_run", _noop)
    monkeypatch.setattr(document_tasks, "_graph_service", graph)
    monkeypatch.setattr(
        document_tasks._entity_extraction_service, "extract_from_chunks", extract_entities
    )
    monkeypatch.setattr(
        document_tasks._relation_extraction_service, "extract_from_chunks", extract_relations
    )
    return await document_tasks._run_document_graph_extraction_async(
        document,
        request_id="req-batch",
        organization_id=str(document.organization_id),
        user_id=str(document.uploaded_by_user_id),
        pipeline_type="document.process",
        chunk_pairs=[(0, "a"), (1, "b"), (2, "c")],
        chunk_id_by_index=document.chunk_ids,
        page_by_index={0: 1, 1: 1, 2: 2},
    )


def _document() -> Any:
    return SimpleNamespace(
        id=uuid4(),
        organization_id=uuid4(),
        uploaded_by_user_id=uuid4(),
        filename="handbook.pdf",
        language="en",
        graph_extraction_run_id=None,
        # Stable chunk ids for the document, so a rerun writes the same graph facts.
        chunk_ids={0: uuid4(), 1: uuid4(), 2: uuid4()},
    )


async def test_worker_writes_one_transaction_per_batch_not_per_entity(
    driver: FakeDriver, monkeypatch: pytest.MonkeyPatch
) -> None:
    document = _document()
    entities, relations = 7, 5
    result = await _run_document(
        monkeypatch, document, _extraction_fakes(entities, relations, document.organization_id)
    )
    assert result == {"entity_count": entities, "relation_count": relations}
    per_batch = settings.graph_write_batch_size
    assert driver.write_transactions("entity") == math.ceil(entities / per_batch) == 3
    assert driver.write_transactions("alias") == math.ceil(entities / per_batch)
    assert driver.write_transactions("evidence") == math.ceil(entities / per_batch)
    assert driver.write_transactions("relation") == math.ceil(relations / per_batch) == 2
    # Previously: one transaction per entity, alias, evidence link and relation (26).
    assert (
        sum(driver.write_transactions(k) for k in ("entity", "alias", "evidence", "relation")) == 11
    )
    # Entities are committed before the aliases and evidence that MATCH them.
    kinds = [_kind(tx[0][0]) for tx in driver.transactions if tx]
    assert kinds.index("alias") > max(i for i, k in enumerate(kinds) if k == "entity")


async def test_worker_rerun_is_idempotent_and_tenant_scoped(
    driver: FakeDriver, monkeypatch: pytest.MonkeyPatch
) -> None:
    document = _document()
    fakes = _extraction_fakes(4, 3, document.organization_id)
    await _run_document(monkeypatch, document, fakes)
    first = dict(driver.store)
    assert len(first) == 4 + 4 + 4 + 3
    await _run_document(monkeypatch, document, fakes)
    assert driver.store.keys() == first.keys()  # no duplicates on rerun
    org = str(document.organization_id)
    assert all(value["organization_id"] == org for value in driver.store.values())
    for tx in driver.transactions:
        for _cypher, params in tx:
            if "rows" in params:
                assert params["organization_id"] == org


# ---------------------------------------------------------------------------
# Bounded extraction concurrency
# ---------------------------------------------------------------------------


async def test_gather_in_order_respects_the_limit_and_keeps_order() -> None:
    active = 0
    peak = 0

    async def _work(item: int) -> int:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01 * (6 - item))  # later items finish first
        active -= 1
        return item * 10

    assert await gather_in_order(list(range(6)), _work, limit=3) == [0, 10, 20, 30, 40, 50]
    assert peak == 3
    peak = 0
    assert await gather_in_order(list(range(3)), _work, limit=1) == [0, 10, 20]
    assert peak == 1


class _FakeProvider:
    def __init__(self, respond: Any) -> None:
        self.respond = respond
        self.active = 0
        self.peak = 0

    async def complete(self, request: Any) -> Any:
        self.active += 1
        self.peak = max(self.peak, self.active)
        indices = [int(i) for i in re.findall(r"\[CHUNK (\d+)\]", request.prompt)]
        await asyncio.sleep(0.005 * (10 - indices[0]))
        self.active -= 1
        return SimpleNamespace(content=json.dumps(self.respond(indices)))


def _entity_json(indices: list[int]) -> dict[str, Any]:
    if indices[0] == 4:
        return {"entities": [{"type": "nope"}]}  # one invalid batch
    return {
        "entities": [
            {
                "type": "policy",
                "name": f"Entity {indices[0]}",
                "original_name": f"Entity {indices[0]}",
                "aliases": [],
                "language": "en",
                "confidence": 0.9,
                "evidence_span": "span",
                "source_chunk_index": indices[0],
            }
        ]
    }


@pytest.mark.parametrize(("limit", "expected_peak"), [(None, 1), (3, 3)])
async def test_entity_extraction_bounds_concurrency_in_batch_order(
    monkeypatch: pytest.MonkeyPatch, limit: int | None, expected_peak: int
) -> None:
    provider = _FakeProvider(_entity_json)
    monkeypatch.setattr(default_provider_factory, "get_chat_provider", lambda *a, **k: provider)
    monkeypatch.setattr(settings, "entity_extraction_max_concurrent_batches", 1)
    service = EntityExtractionService(batch_size=1, max_retries=0, max_concurrent_batches=limit)
    chunks = [(index, f"chunk {index}") for index in range(6)]

    result = await service.extract_from_chunks(chunks=chunks, organization_id="org-1")

    assert [e.name for e in result.entities] == [f"Entity {i}" for i in (0, 1, 2, 3, 5)]
    assert result.validation_errors == 1 and result.batch_count == 6
    assert provider.peak == expected_peak


async def test_entity_extraction_reads_the_concurrency_setting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _FakeProvider(_entity_json)
    monkeypatch.setattr(default_provider_factory, "get_chat_provider", lambda *a, **k: provider)
    monkeypatch.setattr(settings, "entity_extraction_max_concurrent_batches", 2)
    service = EntityExtractionService(batch_size=1, max_retries=0)
    await service.extract_from_chunks(chunks=[(i, f"c{i}") for i in range(4)], organization_id="o")
    assert provider.peak == 2


def _relation_json(indices: list[int]) -> dict[str, Any]:
    return {
        "relations": [
            {
                "from_entity_name": "Alpha",
                "to_entity_name": "Beta" if indices[0] != 2 else "Unknown",
                "rel_type": "relates_to",
                "confidence": 0.8,
                "evidence_span": f"span {indices[0]}",
                "source_chunk_index": indices[0],
            }
        ]
    }


@pytest.mark.parametrize(
    ("setting", "limit", "expected_peak"), [(1, None, 1), (4, None, 4), (1, 2, 2)]
)
async def test_relation_extraction_bounds_concurrency_in_batch_order(
    monkeypatch: pytest.MonkeyPatch, setting: int, limit: int | None, expected_peak: int
) -> None:
    provider = _FakeProvider(_relation_json)
    monkeypatch.setattr(default_provider_factory, "get_chat_provider", lambda *a, **k: provider)
    monkeypatch.setattr(settings, "relation_extraction_max_concurrent_batches", setting)
    service = RelationExtractionService(batch_size=1, max_retries=0, max_concurrent_batches=limit)
    names = {"alpha": uuid4(), "beta": uuid4()}

    result = await service.extract_from_chunks(
        chunks=[(i, f"chunk {i}") for i in range(5)],
        entity_name_to_id=names,
        entity_names_by_chunk={i: ["Alpha", "Beta"] for i in range(5)},
        organization_id="org-1",
    )

    assert [r.evidence_span for r in result.relations] == [f"span {i}" for i in (0, 1, 3, 4)]
    assert result.skipped_unknown_entity == 1
    assert provider.peak == expected_peak
